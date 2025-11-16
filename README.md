# RevivalHub ➜ TRMNL Bridge

This repository surfaces the next RevivalHub screening on a TRMNL OG device (800×480 e‑ink) using a Private Plugin in Polling mode. GitHub Actions builds a tiny JSON file every 15 minutes; your plugin fetches it and renders via Liquid.

- `src/revivalhub_trmnl_sync.py` – Fetch RevivalHub’s JSON dump, select the next screening for a chosen venue, and build the plugin payload.
- `plugin/screen.liquid` – Liquid template tuned for the TRMNL OG (800×480, 4 grayscale). Poster on the left, metadata + compact QR on the right.[^device]
- `.github/workflows/revivalhub_sync.yml` – Scheduled GitHub Action that runs the sync script every 15 minutes (or on demand) and publishes JSON to GitHub Pages.

[^device]: https://shop.usetrmnl.com/collections/devices/products/trmnl  
[^docs]: https://docs.usetrmnl.com/go/private-plugins/create-a-screen?utm_source=openai

## Requirements

- Python 3.11+
- `requests` (installed via `pip install -r requirements.txt`)
- RevivalHub JSON endpoint (public or authenticated)
- TRMNL Private Plugin configured to fetch data via Polling[^dev]

[^dev]: https://usetrmnl.com/blog/developer-edition?utm_source=openai

## Local development

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Run the sync script to inspect the output:
   ```bash
   python src/revivalhub_trmnl_sync.py \
     --revivalhub-url "https://…/data-import.json" \
     --theatre "aero" \
     --timezone "America/Los_Angeles" \
     --lookahead-hours 96 \
     --show-qr \
     --payload-path payload.json \
     --dry-run
   ```
   This writes `payload.json` locally and also prints it to stdout.

The script exits with code 2 if `--fail-on-missing` is set and no matching show is found within the lookahead window.

## GitHub Action Automation

The workflow in `.github/workflows/revivalhub_sync.yml`:

- Runs on a `0 */4 * * *` cron (every 4 hours) plus manual `workflow_dispatch`.
- Sets up Python, installs dependencies, and executes the sync CLI.
- Uploads the JSON payload as a build artifact for troubleshooting.
- Publishes `payload.json` and `plugin_body.json` to GitHub Pages. Point your Private Plugin (Polling) to `plugin_body.json` (it wraps the payload under `{"data": …}` which Liquid reads as `data.*`).[^go]

Configure the following repository **secrets**:

| Secret | Purpose |
| --- | --- |
| `REVIVALHUB_URL` | RevivalHub JSON dump |

Optional repository **variables** (or inline overrides):

| Variable | Default in workflow |
| --- | --- |
| `REVIVALHUB_THEATRE` | `"new beverly"` |
| `REVIVALHUB_TIMEZONE` | `"America/Los_Angeles"` |
| `REVIVALHUB_LOOKAHEAD_HOURS` | `96` |

Adjust the cron cadence to stay within TRMNL’s published webhook limits (12/hour for standard accounts, 30/hour for TRMNL+).[^^limits]

[^^limits]: https://docs.usetrmnl.com/go/private-plugins/create-a-screen?utm_source=openai

### Point your plugin to the published JSON
1. Enable GitHub Pages for this repo (Source: GitHub Actions).
2. After the workflow runs:
   - `https://<user>.github.io/<repo>/payload.json`
   - `https://<user>.github.io/<repo>/plugin_body.json`  ← use this one in Polling
3. In the TRMNL dashboard, set Strategy: Polling, Polling Verb: GET, leave Headers/Body empty, and set Polling URL to `plugin_body.json`. Click Force Refresh.
4. The Liquid (`plugin/screen.liquid`) expects: `data.title`, `data.subtitle`, `data.theatre`, `data.poster_url`, `data.ticket_url`, `data.show_qr`.

[^go]: https://docs.usetrmnl.com/go/

## TRMNL Plugin Template

1. In the TRMNL dashboard, go to **Plugins → Private → New Plugin** and note the generated Plugin UUID.[^private]
2. Open the plugin, switch to the **Screen Templating** tab, click **Edit Markup**, and paste the contents of `plugin/screen.liquid` (or add it as shared markup for reuse).[^shared]
3. Grayscale notes: TRMNL preserves grayscale in raster images only. CSS grays/borders are snapped to B/W. The template tags images with class `image` so they flow through the image pipeline and survive Dark Mode. For gray rules or blocks, use tiny raster assets (e.g., inline SVG/PNG) instead of CSS fills.

[^private]: https://help.usetrmnl.com/en/articles/9510536-private-plugins?utm_source=openai  
[^shared]: https://trmnl.app/blog/private-plugin-shared-markup?utm_source=openai  
[^preview]: https://github.com/schrockwell/trmnl_preview?utm_source=openai

## Extending later
- Rotate venues, customize QR toggling, or pre‑dither 4‑tone posters server‑side for consistent mid‑tones.

