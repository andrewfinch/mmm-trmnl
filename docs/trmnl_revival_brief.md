# TRMNL Revival Plugin Implementation Notes

## 1. Platform Constraints Snapshot

- **Hardware envelope** – TRMNL OG uses a 7.5" e‑ink panel (4 grayscale) with an effective 800 × 480 canvas, so poster crops, typography, and QR sizing all need to respect monochrome contrast and limited DPI.[^1]
- **Templating stack** – Private plugins render through TRMNL’s Screen Templating pipeline (Liquid + HTML/CSS/JS) with support for shared markup blocks, letting us compose reusable layout fragments for posters, metadata, and QR captions.[^2][^3]
- **Data ingress** – The Create‑a‑Screen/Webhook flow accepts small JSON payloads on a schedule; TRMNL stresses keeping updates within their size/rate guardrails, which fits our single-screen dataset.[^4]
- **Developer tooling** – Enabling the Developer Edition unlocks advanced logging/debug aids on-device, smoothing validation of custom plugins before broader rollout.[^5]

## 2. RevivalHub Data & Sync Service

- **Ingest + cache** – Reuse the existing `example script.py` heuristics to fetch RevivalHub’s JSON dump, normalize showtimes to device locale, and pre-scale poster URLs (store alongside ticket checkout deep links). Keep the cached snapshot lightweight (<2 KB per device) so it can be pushed directly to TRMNL’s webhook endpoint.[^4]
- **Payload schema** – Emit a payload with `title`, `subtitle` (formatted time string), `poster_url`, `ticket_url`, `show_qr`, and `refreshed_at`. This mirrors the fields our Liquid template expects and lets TRMNL’s system render the scene without additional fetches.
- **Transport options**  
  - *GitHub Action cron* – Schedule a job (e.g., every 15 min) that runs the sync CLI, hydrates the JSON, and POSTs to the Display/Plugin Data API with the device/scene identifier stored as secrets. This satisfies “maintenance free” delivery.  
  - *BYOS/BYOD microservice* – For users needing faster refresh or multi-venue coverage, host the same sync logic behind a minimal HTTPS endpoint that TRMNL can poll, aligning with their DIY guidance.[^4]
- **Observability** – Log payload hashes + HTTP responses so we can diff changes between runs and honor TRMNL’s hourly rate envelope (standard vs. TRMNL+ tiers).

## 3. Screen Template & Assets

- **Layout pass** – Divide the 800 × 480 canvas into: poster column (approx. 60% width, full height), info stack (title + showtime) on the right, and an optional QR footer block. Maintain ≥24 px padding to avoid ghosting on the bezel edges.[^1]
- **Poster handling** – Use CSS `object-fit: cover` with grayscale filter fallback so mismatched poster ratios fill the allotted area without warping; apply a thin border to distinguish from the white background when the artwork is mostly light.
- **Typography** – Choose two weights (e.g., `TRMNL Sans`/system fallback) and clamp sizes for e‑ink readability (title 42–48 px, time 26–32 px). Provide uppercase tracking for short titles to reduce shimmering on refresh.
- **QR module** – Render conditionally via TRMNL’s QR helper or embed a pre-generated SVG. Include a short caption (e.g., “Buy Tickets”) and ensure the code sits on pure white with ≥15 px quiet zone for reliable scans.
- **Shared partials + preview** – Break template pieces into shared Liquid snippets (poster, metadata, QR) to reuse later and speed up iterations leveraging TRMNL’s Shared Markup feature plus the `trmnlp` local preview server for rapid visual QA.[^3][^6]

## 4. Configuration, Deployment & Distribution

- **User settings model** – Define plugin settings for `theatre_id` (dropdown or slug), `lookahead_hours`, and `show_qr` boolean so each installation can tailor its data. TRMNL’s private plugin settings flow surfaces these fields in the dashboard and stores values for the data sync to read.[^7]
- **Secrets + rollout** – Document how to: (1) upload the plugin bundle, (2) capture API tokens/device IDs, (3) configure GitHub Action secrets, and (4) verify first render using Developer Edition diagnostics.[^5][^7]
- **Sharing path** – Package the plugin as a Recipe once stable so other TRMNL owners can install with prefilled defaults, while still pointing them to fork the GitHub Action for their own API keys.[^7]
- **Operational notes** – Recommend refresh intervals aligned with TRMNL’s published limits, highlight battery considerations (e.g., reducing updates overnight), and describe fallbacks if RevivalHub data is stale (poster placeholder + “No show scheduled” copy).

[^1]: https://shop.usetrmnl.com/products/trmnl?utm_source=openai  
[^2]: https://trmnl.app/developers?utm_source=openai  
[^3]: https://trmnl.app/blog/private-plugin-shared-markup?utm_source=openai  
[^4]: https://docs.usetrmnl.com/go/private-plugins/create-a-screen?utm_source=openai  
[^5]: https://usetrmnl.com/blog/developer-edition?utm_source=openai  
[^6]: https://github.com/schrockwell/trmnl_preview?utm_source=openai  
[^7]: https://help.usetrmnl.com/en/articles/9510536-private-plugins?utm_source=openai

