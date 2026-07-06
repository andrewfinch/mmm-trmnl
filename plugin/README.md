# TRMNL Revival Plugin Template

This directory contains the Liquid template (`screen.liquid`) that the TRMNL private plugin uses to render a single-screen "mini marquee" layout featuring:

- Poster artwork centered up top (or a black marquee-style title card when no poster is available)
- A showtime strip below it ("Tonight • 7:00 PM", "Tomorrow • 7:30 PM", or "Wednesday • Jul 8 • 7:00 PM" for shows further out)
- A QR code pinned to the right edge pointing to the ticket checkout URL (rendered only when `ticket_url` is present)

## Usage

1. Create a new **Private Plugin** inside the TRMNL dashboard.
2. Paste the contents of `screen.liquid` into the plugin's screen editor (or upload as shared markup if you plan to reuse it across scenes).
3. Make sure your plugin's data payload provides the following keys:
   - `title` – Movie title
   - `theatre` – Venue label
   - `poster_url` – Remote JPG/PNG path (dithered by the framework; 16 gray levels on 4-bit panels)
   - `ticket_url` – Checkout URL (optional; the QR block renders whenever this is present)
   - `showtime_epoch` – UTC epoch of the screening
   - `day_start_epoch` / `day_end_epoch` – UTC epochs of venue-local midnight bounding the show date; the template compares these against TRMNL's render-time clock to label the show Tonight/Today/Tomorrow without any timezone math in Liquid
   - `show_day` / `show_date` / `show_time` – Venue-local display parts (`Sat`, `Jul 4`, `3:00 PM`)
   - `is_evening` – `true` for showtimes at or after 5:00 PM local (drives the "Tonight" label)
   - `subtitle` – Legacy preformatted showtime (`Fri • Jan 17 • 7:30 PM`); only used as a fallback when `showtime_epoch` is absent
4. Preview using TRMNL’s local tooling (`trmnlp`) or directly on a device before going live.

The template targets the TRMNL framework (v3+, currently pinned to 3.1.1) on an 800×480 landscape OG panel with bleed margin removed. The deployed version in the TRMNL markup editor additionally embeds a custom "Marquee" display font as a woff2 data URI; this reference copy omits the font blob but is otherwise kept in sync with the deployed `markup_full`.

