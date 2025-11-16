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
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

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
        "--show-qr",
        action="store_true",
        default=False,
        help="Set this flag to request a QR block on the TRMNL template.",
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
        show_qr=args.show_qr,
        fail_on_missing=args.fail_on_missing,
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
    show_qr: bool,
    fail_on_missing: bool,
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

    logging.info(
        "Next screening: %s at %s (%s)",
        screening.title,
        screening.when.isoformat(),
        screening.ticket_url or "no ticket URL",
    )
    return build_trmnl_payload(screening=screening, show_qr=show_qr)


def find_next_screening(
    source: Any,
    theatre: str,
    timezone: str,
    lookahead_hours: int,
) -> Screening | None:
    theatre_lower = theatre.lower()
    venue_index = _build_venue_index(source)  # id -> human-readable name
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

        # Poster URL: try direct URL fields first, then build from RevivalHub slug
        poster_url = _coalesce(entry, ["poster", "poster_url", "image", "artwork"])
        if not poster_url:
            slug = _coalesce(
                entry,
                [
                    "poster-image-path",  # primary key in RevivalHub dump
                    "poster_image_path",
                    "posterImagePath",
                    "posterSlug",
                    "poster_slug",
                ],
            )
            poster_url = _poster_url_from_slug(slug)

        # Ticket URL: prefer single url fields, else first from ticket_urls[]
        ticket_url = _coalesce(entry, ["ticket_url", "tickets", "link", "url"])
        if not ticket_url:
            urls = entry.get("ticket_urls") if isinstance(entry, Mapping) else None
            if isinstance(urls, list) and urls:
                ticket_url = urls[0]

        # Title: prefer explicit titles, then filmTitle, then first film name
        title = _coalesce(entry, ["title", "film", "movie", "name", "filmTitle"])
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
    return candidates[0] if candidates else None


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


def build_trmnl_payload(screening: Screening, show_qr: bool) -> Mapping[str, Any]:
    payload = {
        "title": screening.title,
        "subtitle": screening.format_when_text(),
        "theatre": screening.theatre,
        "poster_url": screening.poster_url,
        "ticket_url": screening.ticket_url,
        "show_qr": bool(show_qr and screening.ticket_url),
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
        "show_qr": False,
        "refreshed_at": now.isoformat(),
    }


def _coalesce(entry: Mapping[str, Any], keys: Iterable[str]) -> Any | None:
    for key in keys:
        if key in entry and entry[key]:
            return entry[key]
    return None


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

