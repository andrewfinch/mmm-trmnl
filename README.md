# RevivalHub ➜ TRMNL Bridge

This repository packages everything you need to surface the next RevivalHub screening on a TRMNL OG device:

- `src/revivalhub_trmnl_sync.py` – Fetch RevivalHub’s JSON dump, select the next screening for a chosen venue, build the plugin payload, and push it to TRMNL via the Plugin Data or Display API.
- `plugin/screen.liquid` – Liquid + CSS template tuned for the 7.5" TRMNL OG e‑ink screen (800×480, 4 grayscale). Shows poster art, venue, film title, formatted showtime, and an optional QR code.[^device]
- `.github/workflows/revivalhub_sync.yml` – Scheduled GitHub Action that runs the sync script every 15 minutes (or on demand) using repository secrets/variables.
- `docs/trmnl_revival_brief.md` – Architecture notes, constraints, and deployment considerations distilled from the TRMNL developer docs.[^docs]

[^device]: https://shop.usetrmnl.com/collections/devices/products/trmnl  
[^docs]: https://docs.usetrmnl.com/go/private-plugins/create-a-screen?utm_source=openai

## Requirements

- Python 3.11+
- `requests` (installed via `pip install -r requirements.txt`)
- RevivalHub JSON endpoint (public or authenticated)
- TRMNL Developer Edition account with API key + either a plugin ID or display/scene IDs[^dev]

[^dev]: https://usetrmnl.com/blog/developer-edition?utm_source=openai

## Environment configuration

1. Copy the sample file and fill in your credentials:
   ```bash
   cp env.example .env
   # edit .env with REVIVALHUB_URL, REVIVALHUB_THEATRE, TRMNL keys, etc.
   ```
2. Values in `.env` automatically populate the CLI (you can still override any flag explicitly).
3. Set `REVIVALHUB_THEATRE` to a substring that matches the venue label in the RevivalHub dump (e.g., `aero` to catch “Aero Theatre” listings).  
4. Use the theatre’s local timezone (Aero Theatre → `America/Los_Angeles`) so formatted showtimes reflect the venue, not wherever the script runs.
5. Toggle the QR module with `REVIVALHUB_SHOW_QR=1` (or omit it / set `0` to hide the block).

## Local Development

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Run the sync script with dry-run enabled to inspect the output:
   ```bash
   python src/revivalhub_trmnl_sync.py --dry-run --payload-path payload.json
   ```
3. Remove `--dry-run`; if the TRMNL fields are not already present in `.env`, pass one of:
   - `--trmnl-mode plugin --trmnl-plugin-id <PLUGIN_ID>`
   - `--trmnl-mode display --trmnl-display-id <DISPLAY_ID> --trmnl-scene-id <SCENE_ID>`

The script will exit with code 2 if `--fail-on-missing` is set and no matching show is found within the lookahead window.

## GitHub Action Automation

The workflow in `.github/workflows/revivalhub_sync.yml`:

- Runs on a `*/15 * * * *` cron plus manual `workflow_dispatch`.
- Sets up Python, installs dependencies, and executes the sync CLI.
- Uploads the JSON payload as a build artifact for troubleshooting.

Configure the following repository **secrets**:

| Secret | Purpose |
| --- | --- |
| `REVIVALHUB_URL` | RevivalHub JSON dump |
| `TRMNL_API_KEY` | API key from TRMNL dashboard |
| `TRMNL_PLUGIN_ID` or `TRMNL_DISPLAY_ID`/`TRMNL_SCENE_ID` | Delivery target |

Optional repository **variables** (or inline overrides):

| Variable | Default in workflow |
| --- | --- |
| `REVIVALHUB_THEATRE` | `"new beverly"` |
| `REVIVALHUB_TIMEZONE` | `"America/Los_Angeles"` |
| `REVIVALHUB_LOOKAHEAD_HOURS` | `96` |

Adjust the cron cadence to stay within TRMNL’s published webhook limits (12/hour for standard accounts, 30/hour for TRMNL+).[^^limits]

[^^limits]: https://docs.usetrmnl.com/go/private-plugins/create-a-screen?utm_source=openai

## TRMNL Plugin Template

1. In the TRMNL dashboard, go to **Plugins → Private → New Plugin** and note the generated Plugin UUID.[^private]
2. Open the plugin, switch to the **Screen Templating** tab, click **Edit Markup**, and paste the contents of `plugin/screen.liquid` (or add it as shared markup for reuse).[^shared]
3. Use TRMNL’s local preview tooling (`trmnlp`) to validate typography and grayscale rendering before deploying to hardware.[^preview]
4. Map plugin settings (`theatre_id`, `show_qr`, etc.) to the payload fields expected by the template.

[^private]: https://help.usetrmnl.com/en/articles/9510536-private-plugins?utm_source=openai  
[^shared]: https://trmnl.app/blog/private-plugin-shared-markup?utm_source=openai  
[^preview]: https://github.com/schrockwell/trmnl_preview?utm_source=openai

## Extending the System

- Rotate through multiple venues by storing an array of theatre slugs and iterating each run.
- Cache poster art or generate grayscale crops server-side for faster refreshes.
- Package the plugin as a TRMNL Recipe to share with other users once stable.[^recipes]

[^recipes]: https://help.usetrmnl.com/en/articles/10122094-plugin-recipes?utm_source=openai

