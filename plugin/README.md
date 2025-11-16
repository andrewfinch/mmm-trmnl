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
   - `subtitle` – Preformatted showtime (e.g., `Fri • Jan 17 • 7:30 PM`)
   - `theatre` – Venue label
   - `poster_url` – Remote JPG/PNG path
   - `ticket_url` – Checkout URL (optional)
   - `show_qr` – Boolean flag that enables the QR block when `ticket_url` exists
4. Preview using TRMNL’s local tooling (`trmnlp`) or directly on a device before going live.

You can further customize typography, spacing, or QR behavior by editing the CSS near the top of the template. Keep the grayscale palette and generous quiet zones so the design remains legible on the OG 7.5" e‑ink display.

