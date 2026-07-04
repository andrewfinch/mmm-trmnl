# TRMNL Revival Plugin Template

This directory contains the Liquid template (`screen.liquid`) that the TRMNL private plugin uses to render a single-screen layout featuring:

- Poster artwork (or a neutral placeholder)
- Theatre name + film title
- Formatted showtime string
- Optional QR code pointing to the ticket checkout URL

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

The template uses only TRMNL framework (v3+) classes — no custom CSS. It adapts automatically: landscape renders poster-left / meta-right, portrait renders poster-on-top with a title/time + QR strip below (`portrait:` variants), and `lg:` variants scale typography and the QR for larger panels like the TRMNL X.

