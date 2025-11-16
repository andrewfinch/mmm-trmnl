from __future__ import annotations
import datetime as dt, functools, json, pathlib, re, requests
from PIL import Image, ImageDraw, ImageFont
import qrcode
from qrcode import QRCode, constants
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
try:
    from qrcode.image.styles.eyedrawers import RoundedEyeDrawer  # type: ignore
except ImportError:
    RoundedEyeDrawer = None  # older qrcode versions
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styles.moduledrawers import CircleModuleDrawer

# ─── constants ────────────────────────────────────────────────────
DUMP_URL = (
    "https://storage.googleapis.com/"
    "revival-hub-ab2a8.firebasestorage.app/airtable-uploads/data-import.json"
)
IMG_BASE = (
    "https://storage.googleapis.com/"
    "revival-hub-ab2a8.firebasestorage.app/screening-posters/resized"
)

CACHE        = pathlib.Path("/tmp/mmm_bridge"); CACHE.mkdir(exist_ok=True)
JSON_FP      = CACHE / "dump.json"
POSTER_CACHE = CACHE / "posters"; POSTER_CACHE.mkdir(exist_ok=True)

ASSETS   = pathlib.Path(__file__).parent / "assets"
FONT_HEAD = ImageFont.truetype(str(ASSETS / "Marquee-ExtraLight.ttf"), 56)
FONT_BODY = ImageFont.truetype(str(ASSETS / "Marquee-ExtraLight.ttf"), 38)
W, H     = 800, 1280   # image dimensions

# ─── RevivalHub dump helpers ──────────────────────────────────────
def _download_dump() -> None:
    r = requests.get(DUMP_URL, timeout=30)
    r.raise_for_status()
    JSON_FP.write_bytes(r.content)

def _maybe_refresh() -> None:
    if not JSON_FP.exists():
        _download_dump()
        return
    age = dt.datetime.utcnow() - dt.datetime.utcfromtimestamp(JSON_FP.stat().st_mtime)
    if age > dt.timedelta(minutes=10):
        _download_dump()

@functools.lru_cache(maxsize=1)
def screenings() -> list[dict]:
    _maybe_refresh()
    return json.loads(JSON_FP.read_text())["screenings"]

# cache venue id→name lookup
@functools.lru_cache(maxsize=1)
def venue_names() -> dict[str,str]:
    _maybe_refresh()
    venues = json.loads(JSON_FP.read_text()).get("venues", [])
    return {v["id"]: v["name"] for v in venues}

def next_show(venue_id: str, horizon_days: int = 30) -> dict | None:
    now   = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    limit = now + dt.timedelta(days=horizon_days)
    best: tuple[dt.datetime, dict] | None = None

    for rec in screenings():
        if (rec.get("venue") or rec.get("venueId")) != venue_id:
            continue
        for iso in rec.get("screening_times", []):
            ts = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if now <= ts <= limit and (best is None or ts < best[0]):
                best = (ts, rec)

    if best is None:
        return None

    ts, rec = best
    rec = rec.copy()
    rec["showtime_dt"] = ts        # keep dt object for later
    # attach human-readable venue name if available
    vid = venue_id
    rec["venue_name"] = venue_names().get(vid, "")
    return rec

# ─── small utilities ──────────────────────────────────────────────
def _poster_path(slug: str | None) -> pathlib.Path:
    if not slug:
        slug = ""  # force fallback below
    slug = re.sub(r"\.\w+$", "", slug)           # drop extension if present
    url  = f"{IMG_BASE}/{slug}_400x600.jpg" if slug else ""
    fp   = POSTER_CACHE / f"{slug or 'blank'}.jpg"
    if slug and not fp.exists():
        try:
            r = requests.get(url, timeout=20)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                fp.write_bytes(r.content)
        except Exception:
            pass
    # validate that the cached file is a real image
    if fp.exists():
        try:
            Image.open(fp).verify()  # will raise if corrupt/non-image
            return fp
        except Exception:
            fp.unlink(missing_ok=True)
    fallback = ASSETS / "poster_fallback.jpg"
    if fallback.exists():
        return fallback
    # Generate plain black placeholder if fallback image missing
    ph = POSTER_CACHE / "fallback_generated.jpg"
    if not ph.exists():
        Image.new("RGB", (W, int(W*3/2)), "black").save(ph, "JPEG")
    return ph

def when_text(ts_utc: dt.datetime) -> str:
    local = ts_utc.astimezone()                  # use system TZ
    now   = dt.datetime.now(local.tzinfo)
    delta = (local.date() - now.date()).days
    tstr  = local.strftime("%-I:%M %p")
    if delta == 0:
        return ("Tonight " if local.hour >= 18 else "Today ") + tstr
    if delta == 1 and local.hour < 3:
        return f"Tonight {tstr}"
    if delta == 1:
        return f"Tomorrow {tstr}"
    if 1 < delta < 7:
        return f"{local.strftime('%A')} {tstr}"
    return local.strftime('%b %-d ') + tstr

def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int,int]:
    """Return (w,h) of rendered text compatible with Pillow ≥10."""
    if hasattr(draw, "textbbox"):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    return draw.textsize(text, font=font)

# ─── screen builders ──────────────────────────────────────────────
def build_poster_screen(show: dict, out_fp: pathlib.Path) -> pathlib.Path:
    canvas = Image.new("RGB", (W, H), "black")

    # poster
    poster_src = _poster_path(show.get("poster-image-path"))
    poster = Image.open(poster_src)
    poster = poster.resize((W, int(poster.height * W / poster.width)), Image.LANCZOS)
    canvas.paste(poster, (0, (H - poster.height) // 2))

    # bottom time bar
    bar_h = 90
    draw  = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle([0, H - bar_h, W, H], fill=(0, 0, 0, 180))

    txt = when_text(show["showtime_dt"])
    tw, th = _text_size(draw, txt, FONT_HEAD)
    draw.text(((W - tw) // 2, H - bar_h + (bar_h - th) // 2),
              txt, font=FONT_HEAD, fill="white")

    canvas.save(out_fp, "JPEG", quality=90)
    return out_fp

def build_info_screen(show: dict, out_fp: pathlib.Path) -> pathlib.Path:
    venue_id = show.get("venue") or show.get("venueId") or ""
    bg_path = ASSETS / f"{venue_id}.png"
    if not bg_path.exists():
        bg_path = ASSETS / "info_bg.png"
    if bg_path.exists():
        canvas = Image.open(bg_path).convert("RGB")
    else:
        canvas = Image.new("RGB", (W, H), "black")
    draw   = ImageDraw.Draw(canvas)

    y = 60

    def center(text: str, font):
        nonlocal y
        w, _ = _text_size(draw, text, font)
        draw.text(((W - w) // 2, y), text, font=font, fill="white")
        y += font.size + 20

    venue_name = (show.get("venue_name") or "").upper()
    if venue_name:
        center(venue_name, FONT_BODY)

    films = show.get("films") or [{"name": show.get("filmTitle", "")}]
    for film in films[:2]:
        center((film.get("name", "")).upper(), FONT_HEAD)
        info = f'{film.get("year", "")} – {film.get("directors", "")}'
        if info.strip(" –"):
            center(info, FONT_BODY)

    fmt = (show.get("formats") or [""])[0]
    if fmt:
        center(fmt, FONT_BODY)

    center(when_text(show["showtime_dt"]), FONT_HEAD)

    # QR code with styled rounded dots and corner squares
    url = (show.get("ticket_urls") or [""])[0]
    if url:
        # larger modules + higher error-correction improve legibility once pasted
        qr = QRCode(error_correction=constants.ERROR_CORRECT_Q, box_size=10, border=1)
        qr.add_data(url)
        qr.make(fit=True)

        kwargs = dict(
            image_factory=StyledPilImage,
            module_drawer=CircleModuleDrawer(),                   # dots
            color_mask=SolidFillColorMask(
                back_color=(0, 0, 0, 0),           # transparent bg
                front_color=(68, 68, 68, 255)      # dark grey dots / eyes
            ),
        )
        if RoundedEyeDrawer:
            kwargs["eye_drawer"] = RoundedEyeDrawer(radius_ratio=0.35)

        qr_img = (  # type: ignore[arg-type]
            qr.make_image(**kwargs)
              .convert("RGBA")                       # keep alpha for transparent bg
              .resize((280, 280), Image.NEAREST)     # keep circles crisp
        )

        # paste with transparency preserved
        pad = 40
        canvas.paste(qr_img, (W - qr_img.width - pad, H - qr_img.height - pad), qr_img)

    canvas.save(out_fp, "JPEG", quality=90)
    return out_fp