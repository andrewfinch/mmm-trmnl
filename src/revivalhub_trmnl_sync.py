#!/usr/bin/env python3
"""Build a minimal JSON payload for a TRMNL Private Plugin (Polling).

Fetch RevivalHub's JSON dump, select the next screening for a venue, and emit a
compact payload consumed by the Liquid template. No TRMNL API calls are made;
GitHub Actions publishes the JSON to GitHub Pages for the plugin to poll.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence
from urllib.parse import urlparse

import requests

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[misc,assignment]


# Public, resized poster base used by RevivalHub uploads
POSTER_IMG_BASE = (
    "https://storage.googleapis.com/"
    "revival-hub-ab2a8.firebasestorage.app/screening-posters/resized"
)
# RevivalHub poster paths are TMDB poster hashes, so posters missing from the
# RevivalHub bucket (it only mirrors a subset) can be served from TMDB's CDN.
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w500"

# Ticket-URL slug tokens that describe the presentation, not the film title.
SLUG_NOISE_TOKENS = {
    "in", "on", "at", "and", "with",
    "70mm", "35mm", "16mm", "8mm", "4k", "imax", "3d", "dcp", "digital",
    "restoration", "restored", "print", "presents", "presented", "premiere",
    "screening", "matinee", "double", "feature", "anniversary", "edition",
}
POSTER_DIRECT_KEYS = ["poster", "poster_url", "image", "artwork", "image_url"]
POSTER_SLUG_KEYS = [
    "poster-image-path",
    "poster_image_path",
    "posterImagePath",
    "posterPath",
    "poster_path",
    "posterSlug",
    "poster_slug",
]
FILM_TITLE_KEYS = ["title", "film", "movie", "name", "filmTitle"]
TMDB_ID_KEYS = ["tmdb_id", "tmdbId", "tmdbID"]


@dataclasses.dataclass
class Screening:
    """Normalized representation of a single screening."""

    theatre: str
    title: str
    when: dt.datetime
    timezone: str
    poster_url: str | None = None
    ticket_url: str | None = None
    raw: Mapping[str, Any] | None = None

    @property
    def when_local(self) -> dt.datetime:
        tzinfo = _tzinfo(self.timezone)
        return self.when.astimezone(tzinfo) if tzinfo else self.when

    def format_when_text(self) -> str:
        local = self.when_local
        day_str = str(local.day)
        time_str = _format_time(local)
        # Render weekday and month via strftime so %a/%b are expanded
        prefix = local.strftime("%a • %b")
        return f"{prefix} {day_str} • {time_str}"


def _format_time(value: dt.datetime) -> str:
    """Return a platform-safe 12h timestamp without leading zeros."""
    time_token = value.strftime("%I:%M %p")
    # Strip leading zero while retaining '12'.
    if time_token.startswith("0"):
        time_token = time_token[1:]
    return time_token


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revivalhub-url",
        required=True,
        help="JSON endpoint that exposes RevivalHub screening data.",
    )
    parser.add_argument(
        "--theatre",
        required=True,
        help="Slug or name of the theatre to track (case-insensitive substring).",
    )
    parser.add_argument(
        "--lookahead-hours",
        type=int,
        default=96,
        help="Only consider shows starting within this many hours from now.",
    )
    parser.add_argument(
        "--timezone",
        default="America/Los_Angeles",
        help="IANA timezone used for formatting showtimes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payload to stdout (always writes --payload-path when provided).",
    )
    parser.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit with code 2 when no matching screening is found.",
    )
    parser.add_argument(
        "--payload-path",
        help="Optional path to write the computed payload as JSON.",
    )
    parser.add_argument(
        "--skip-poster-check",
        action="store_true",
        help="Skip HTTP verification (and TMDB fallback) of the poster URL.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    logging.debug("Arguments: %s", args)

    payload = fetch_payload(
        revivalhub_url=args.revivalhub_url,
        theatre=args.theatre,
        timezone=args.timezone,
        lookahead_hours=args.lookahead_hours,
        fail_on_missing=args.fail_on_missing,
        verify_poster=not args.skip_poster_check,
    )

    if args.payload_path:
        Path(args.payload_path).write_text(json.dumps(payload, indent=2))
        logging.info("Wrote payload to %s", args.payload_path)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    # Not dry-run: we already wrote the file if --payload-path was provided.
    return 0


def fetch_payload(
    revivalhub_url: str,
    theatre: str,
    timezone: str,
    lookahead_hours: int,
    fail_on_missing: bool,
    verify_poster: bool = True,
) -> Mapping[str, Any]:
    logging.info("Fetching RevivalHub data from %s", revivalhub_url)
    response = requests.get(revivalhub_url, timeout=30)
    response.raise_for_status()
    source = response.json()

    screening = find_next_screening(
        source=source,
        theatre=theatre,
        timezone=timezone,
        lookahead_hours=lookahead_hours,
    )

    if not screening:
        message = f"No screening found for theatre '{theatre}'"
        if fail_on_missing:
            raise SystemExit(message)
        logging.warning("%s; generating placeholder payload.", message)
        return build_placeholder_payload(theatre=theatre, timezone=timezone)

    if verify_poster:
        screening.poster_url = _verify_poster_url(screening.poster_url)

    logging.info(
        "Next screening: %s at %s (%s)",
        screening.title,
        screening.when.isoformat(),
        screening.ticket_url or "no ticket URL",
    )
    return build_trmnl_payload(screening=screening)


def find_next_screening(
    source: Any,
    theatre: str,
    timezone: str,
    lookahead_hours: int,
) -> Screening | None:
    theatre_lower = theatre.lower()
    venue_index = _build_venue_index(source)  # id -> human-readable name
    film_catalog = _collect_films(source)
    film_index = _build_film_index(film_catalog)
    theatre_is_id = theatre in venue_index
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now + dt.timedelta(hours=lookahead_hours)

    candidates: list[Screening] = []
    for entry in iter_screenings(source):
        # Resolve venue id -> label when possible
        venue_id = _coalesce(entry, ["venueId", "venue_id", "venueID", "venue"])
        venue_label = None
        if isinstance(venue_id, str) and venue_id in venue_index:
            venue_label = venue_index[venue_id]
        if not venue_label:
            venue_label = _coalesce(
                entry,
                ["venue_name", "theatre_name", "theatre", "theater", "cinema", "location"],
            )

        # Match either by exact ID or by human label substring
        matches = False
        if theatre_is_id and venue_id == theatre:
            matches = True
        elif venue_label and theatre_lower in str(venue_label).lower():
            matches = True
        if not matches:
            continue

        showtime_raw = _coalesce(
            entry, ["showtime", "show_time", "when", "datetime", "start_at"]
        )
        if not showtime_raw:
            showtimes = entry.get("showtimes") if isinstance(entry, Mapping) else None
            if isinstance(showtimes, list) and showtimes:
                showtime_raw = showtimes[0]
        if not showtime_raw:
            screening_times = (
                entry.get("screening_times") if isinstance(entry, Mapping) else None
            )
            if isinstance(screening_times, list) and screening_times:
                showtime_raw = screening_times[0]
        when = parse_datetime(showtime_raw, timezone)
        if not when:
            logging.debug("Skipping entry with unparseable time: %s", entry)
            continue
        if when < now or when > cutoff:
            continue

        poster_url = _poster_url_for_entry(entry, film_index)

        # Ticket URL: prefer single url fields, else first from ticket_urls[]
        ticket_url = _coalesce(entry, ["ticket_url", "tickets", "link", "url"])
        if not ticket_url:
            urls = entry.get("ticket_urls") if isinstance(entry, Mapping) else None
            if isinstance(urls, list) and urls:
                ticket_url = urls[0]

        # Title: prefer explicit titles, then filmTitle, then first film name
        title = _coalesce(entry, FILM_TITLE_KEYS)
        if not title:
            films = entry.get("films") if isinstance(entry, Mapping) else None
            if isinstance(films, list) and films:
                first = films[0]
                if isinstance(first, Mapping):
                    title = first.get("name") or first.get("title")
        title = title or "Untitled"

        screening = Screening(
            theatre=venue_label or str(venue_id or ""),
            title=title,
            when=when,
            timezone=timezone,
            poster_url=poster_url,
            ticket_url=ticket_url,
            raw=entry,
        )
        candidates.append(screening)

    candidates.sort(key=lambda s: s.when)
    if not candidates:
        return None
    return _correct_film_from_ticket_slug(candidates[0], film_catalog)


def iter_screenings(source: Any) -> Iterable[MutableMapping[str, Any]]:
    """Yield flattened screening dictionaries from a loose RevivalHub payload."""
    if isinstance(source, Mapping):
        if "screenings" in source and isinstance(source["screenings"], list):
            parent = {k: v for k, v in source.items() if k != "screenings"}
            for child in source["screenings"]:
                merged: MutableMapping[str, Any]
                if isinstance(child, Mapping):
                    merged = {**parent, **child}
                    yield from iter_screenings(merged)
                else:
                    merged = dict(parent)
                    merged["showtimes"] = child
                    yield from iter_screenings(merged)
            return

        keys = set(source.keys())
        if ("title" in keys or "film" in keys or "films" in keys) and (
            "showtime" in keys or "showtimes" in keys or "when" in keys or "screening_times" in keys
        ):
            yield dict(source)
            return
        for value in source.values():
            yield from iter_screenings(value)
    elif isinstance(source, list):
        for item in source:
            yield from iter_screenings(item)


def parse_datetime(raw: Any, timezone: str) -> dt.datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return dt.datetime.fromtimestamp(raw, tz=dt.timezone.utc)
    if isinstance(raw, str):
        raw = raw.strip()
        # Normalize trailing Z to +00:00 for fromisoformat/strptime compatibility
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = dt.datetime.strptime(raw, fmt)
                if not parsed.tzinfo:
                    parsed = parsed.replace(tzinfo=_tzinfo(timezone))
                return parsed.astimezone(dt.timezone.utc)
            except ValueError:
                continue
        # Fallback to fromisoformat if available.
        try:
            parsed = dt.datetime.fromisoformat(raw)
            if not parsed.tzinfo:
                parsed = parsed.replace(tzinfo=_tzinfo(timezone))
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            return None
    return None


def build_trmnl_payload(screening: Screening) -> Mapping[str, Any]:
    local = screening.when_local
    tzinfo = local.tzinfo
    # Venue-local calendar-day boundaries, DST-safe (computed on local dates,
    # not by adding 86400s — a local day can be 23h or 25h across a DST shift).
    day_start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = dt.datetime.combine(
        day_start_local.date() + dt.timedelta(days=1), dt.time(0, 0), tzinfo=tzinfo
    )
    payload = {
        "title": screening.title,
        "theatre": screening.theatre,
        "poster_url": screening.poster_url,
        "ticket_url": screening.ticket_url,
        # Machine-readable showtime. The Liquid template compares these epochs
        # against TRMNL's render-time clock (trmnl.system.timestamp_utc), so
        # Tonight/Today/Tomorrow labels never depend on server timezone math.
        "showtime_epoch": int(screening.when.timestamp()),
        "showtime_iso": local.isoformat(),
        "show_day": local.strftime("%a"),
        "show_date": f"{local.strftime('%b')} {local.day}",
        "show_time": _format_time(local),
        "is_evening": local.hour >= 17,
        "day_start_epoch": int(day_start_local.timestamp()),
        "day_end_epoch": int(day_end_local.timestamp()),
        # Legacy preformatted string, kept so older template revisions render.
        "subtitle": screening.format_when_text(),
        "refreshed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return payload


def build_placeholder_payload(theatre: str, timezone: str) -> Mapping[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    tz = _tzinfo(timezone)
    local = now.astimezone(tz) if tz else now
    return {
        "title": "No screening scheduled",
        "subtitle": local.strftime("Updated %b %d • %I:%M %p"),
        "theatre": theatre,
        "poster_url": None,
        "ticket_url": None,
        "refreshed_at": now.isoformat(),
    }


def _coalesce(entry: Mapping[str, Any], keys: Iterable[str]) -> Any | None:
    for key in keys:
        if key in entry and entry[key]:
            return entry[key]
    return None


def _poster_url_for_entry(
    entry: Mapping[str, Any], film_index: Mapping[str, Mapping[str, Any]]
) -> str | None:
    """Return the best poster URL for a screening entry."""
    poster_url = _poster_url_from_record(entry)
    if poster_url:
        return poster_url

    films = entry.get("films")
    if not isinstance(films, list):
        return None

    for film in films:
        if not isinstance(film, Mapping):
            continue
        poster_url = _poster_url_from_record(film)
        if poster_url:
            return poster_url
        for key in _film_index_keys(film):
            indexed = film_index.get(key)
            if indexed:
                poster_url = _poster_url_from_record(indexed)
                if poster_url:
                    return poster_url
    return None


def _poster_url_from_record(record: Mapping[str, Any]) -> str | None:
    direct = _coalesce(record, POSTER_DIRECT_KEYS)
    poster_url = _poster_url_from_value(direct)
    if poster_url:
        return poster_url

    slug = _coalesce(record, POSTER_SLUG_KEYS)
    return _poster_url_from_value(slug)


def _poster_url_from_value(value: Any) -> str | None:
    if not value:
        return None
    value_str = str(value).strip()
    if value_str.startswith(("http://", "https://")):
        return value_str
    return _poster_url_from_slug(value_str)


def _collect_films(source: Any) -> list[Mapping[str, Any]]:
    """Collect every film record reachable under a 'films' list."""
    found: list[Mapping[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, Mapping):
            films = obj.get("films")
            if isinstance(films, list):
                found.extend(f for f in films if isinstance(f, Mapping))
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(source)
    return found


def _build_film_index(films: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Index film records by TMDB id and title."""
    index: dict[str, Mapping[str, Any]] = {}

    def has_poster(record: Mapping[str, Any]) -> bool:
        return bool(_coalesce(record, POSTER_DIRECT_KEYS) or _coalesce(record, POSTER_SLUG_KEYS))

    for record in films:
        for key in _film_index_keys(record):
            existing = index.get(key)
            if existing is None or (has_poster(record) and not has_poster(existing)):
                index[key] = record

    return index


def _normalize_tokens(text: Any) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if t]


def _ticket_slug_tokens(ticket_url: Any) -> list[str]:
    """Tokens of the last path segment of a ticket URL, e.g.
    '.../now-showing/babylon-in-70mm-07-08-2026/' -> ['babylon','in','70mm',...]."""
    if not ticket_url:
        return []
    try:
        path = urlparse(str(ticket_url)).path
    except ValueError:
        return []
    segments = [s for s in path.split("/") if s]
    if not segments:
        return []
    return _normalize_tokens(segments[-1])


def _contains_sublist(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    needle = list(needle)
    n = len(needle)
    if n == 0:
        return False
    return any(list(haystack[i : i + n]) == needle for i in range(len(haystack) - n + 1))


def _entry_film_hints(entry: Any) -> Mapping[str, Any]:
    """Directors/year from the screening's own film record; used to pick among
    same-titled catalog films when the film link is corrected."""
    if not isinstance(entry, Mapping):
        return {}
    films = entry.get("films")
    if isinstance(films, list):
        for film in films:
            if isinstance(film, Mapping):
                return {"directors": film.get("directors"), "year": film.get("year")}
    return {}


def _release_year(film: Mapping[str, Any]) -> int | None:
    raw = film.get("releaseDate") or film.get("year")
    if not raw:
        return None
    match = re.search(r"\d{4}", str(raw))
    return int(match.group()) if match else None


def _correct_film_from_ticket_slug(
    screening: Screening, films: Sequence[Mapping[str, Any]]
) -> Screening:
    """Fix screenings whose film link contradicts their ticket URL.

    RevivalHub occasionally links a screening to the wrong same-titled film
    (e.g. an Aero 'Babylon in 70mm' show linked to a 2022 Korean film named
    'Boogie Nights'). The ticket URL slug names what is actually playing, so
    when the linked title is absent from the slug, re-resolve the film from
    the catalog by slug match, using the entry's directors/year as tie-breaks.
    """
    slug_tokens = _ticket_slug_tokens(screening.ticket_url)
    if not slug_tokens:
        return screening
    title_tokens = _normalize_tokens(screening.title)
    if title_tokens and _contains_sublist(slug_tokens, title_tokens):
        return screening

    content_tokens = [
        t for t in slug_tokens if t not in SLUG_NOISE_TOKENS and not t.isdigit()
    ]
    if not content_tokens:
        return screening

    hints = _entry_film_hints(screening.raw)
    hint_directors = _normalize_tokens(hints.get("directors") or "")
    hint_year = hints.get("year")

    best: Mapping[str, Any] | None = None
    best_score: tuple[int, ...] | None = None
    for film in films:
        cand_title = _coalesce(film, FILM_TITLE_KEYS)
        cand_tokens = _normalize_tokens(cand_title) if cand_title else []
        if not cand_tokens or not _contains_sublist(slug_tokens, cand_tokens):
            continue
        if len(cand_tokens) * 2 <= len(content_tokens):
            # Must cover the majority of the slug's content tokens, else a
            # series page slug like 'filmforum-50-program-16' would hand the
            # screening to any film that shares a word with it (e.g. 'Program').
            continue
        cand_directors = _normalize_tokens(film.get("directors") or "")
        release_year = _release_year(film)
        score = (
            len(cand_tokens),
            1 if hint_directors and cand_directors == hint_directors else 0,
            1 if hint_year and release_year and abs(int(hint_year) - release_year) <= 1 else 0,
            1 if _poster_url_from_record(film) else 0,
            release_year or 0,
        )
        if best_score is None or score > best_score:
            best, best_score = film, score

    if best is None:
        logging.warning(
            "Ticket slug %s does not mention linked film '%s'; no catalog match, keeping feed data.",
            "-".join(slug_tokens),
            screening.title,
        )
        return screening

    new_title = str(_coalesce(best, FILM_TITLE_KEYS))
    logging.warning(
        "Feed links film '%s' but ticket slug says '%s'; using catalog film instead.",
        screening.title,
        new_title,
    )
    return dataclasses.replace(
        screening, title=new_title, poster_url=_poster_url_from_record(best)
    )


def _tmdb_fallback_url(poster_url: str) -> str | None:
    """TMDB CDN equivalent of a RevivalHub resized-bucket poster URL."""
    match = re.match(
        re.escape(POSTER_IMG_BASE) + r"/(?P<root>[^/]+?)(?:_\d+x\d+)?\.jpg$",
        poster_url,
    )
    if not match:
        return None
    return f"{TMDB_IMG_BASE}/{match.group('root')}.jpg"


def _verify_poster_url(poster_url: str | None) -> str | None:
    """Return the first poster candidate that actually serves an image.

    RevivalHub's bucket only mirrors a subset of posters; a missing object
    returns 403 and TRMNL then renders alt text instead of artwork. Fall back
    to the TMDB CDN (poster paths are TMDB hashes) before omitting the poster.
    """
    if not poster_url:
        return None
    candidates = [poster_url]
    fallback = _tmdb_fallback_url(poster_url)
    if fallback:
        candidates.append(fallback)
    for candidate in candidates:
        try:
            response = requests.head(candidate, timeout=15, allow_redirects=True)
        except requests.RequestException as exc:
            logging.warning("Poster check failed for %s: %s", candidate, exc)
            continue
        if response.status_code == 200:
            if candidate != poster_url:
                logging.info("Poster missing from RevivalHub bucket; using %s", candidate)
            return candidate
        logging.warning("Poster URL %s returned HTTP %s", candidate, response.status_code)
    logging.warning("No working poster URL found; omitting poster.")
    return None


def _film_index_keys(film: Mapping[str, Any]) -> Iterable[str]:
    tmdb_id = _coalesce(film, TMDB_ID_KEYS)
    if tmdb_id:
        yield f"tmdb:{tmdb_id}"

    title = _coalesce(film, FILM_TITLE_KEYS)
    if title:
        normalized = " ".join(str(title).lower().split())
        if normalized:
            yield f"title:{normalized}"


def _tzinfo(timezone: str) -> dt.tzinfo:
    if ZoneInfo:
        try:
            return ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            logging.warning("Unknown timezone '%s'; falling back to UTC.", timezone)
    return dt.timezone.utc


def _build_venue_index(source: Any) -> dict[str, str]:
    """Return a mapping of venue id -> human-readable name if present."""
    index: dict[str, str] = {}

    def walk(obj: Any) -> None:
        if isinstance(obj, Mapping):
            venues = obj.get("venues")
            if isinstance(venues, list):
                for v in venues:
                    if isinstance(v, Mapping):
                        vid = v.get("id") or v.get("venueId") or v.get("key")
                        name = v.get("name") or v.get("label") or v.get("title")
                        if isinstance(vid, str) and isinstance(name, str):
                            index.setdefault(vid, name)
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(source)
    return index


def _poster_url_from_slug(slug: Any) -> str | None:
    """Build a public poster URL from a RevivalHub slug or path-like value.

    RevivalHub stores poster paths like 'abc123.jpg' and serves resized variants
    at '{POSTER_IMG_BASE}/{slug_no_ext}_400x600.jpg'.
    """
    if not slug:
        return None
    try:
        slug_str = str(slug).strip().strip("/")
        # Drop any extension and leading folders
        base_name = slug_str.split("/")[-1]
        root = os.path.splitext(base_name)[0]
        if not root:
            return None
        return f"{POSTER_IMG_BASE}/{root}_400x600.jpg"
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
