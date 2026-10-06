# Priser på Forglødning og Glasurbrænding

A static website (GitHub Pages) that answers: **when is it cheapest to start the kiln?**
It is the Home Assistant markdown card Nick already runs, rendered as a web page that
updates itself — no Home Assistant needed to *view* it.

## What it shows

For every start hour of the day, the total electricity cost of a whole firing:

| Programme | Hourly profile | Total |
|---|---|---|
| **Forglødning** (BISCUIT 950) | 13 hourly steps, `C_BISC` | 29.7 kWh |
| **Glasur** (GLAZE 1050) | 6 hourly steps, `C_GLAZE` | 29.0 kWh |

The cheapest start hour is highlighted green, the second cheapest yellow — exactly the
marking the dashboard card uses. A firing that starts in the evening is priced with
tomorrow's prices after midnight, because the card (and this site) concatenates today with
tomorrow before computing the windows.

## Data source

`https://api.energidataservice.dk/dataset/Elspotprices` — the same Nord Pool spot prices
the HA `energi_data_service` integration reads. `SpotPriceDKK` is DKK/**MWh**, so it is
divided by 1000 here. Prices are **spot only** (no elafgift, no nettarif, no VAT) — that is
what Nick's dashboard shows, and it means these numbers are comparable to the firing log in
`~/wiki/nabertherm/`. A flat adder and a VAT percentage can be configured in `config.json`;
note that a **flat** adder cannot change which hour is cheapest, it only scales the amounts.

Tomorrow's prices are published around 13:00 Copenhagen time, so the page shows
"Priser ikke offentliggjort endnu" for the tomorrow columns until then.

## Files

| File | Purpose |
|---|---|
| `fetch_prices.py` | API client: disk cache, 429 back-off, optional `ENERGIDATA_API_KEY` |
| `kiln_calc.py` | The calculation, ported 1:1 from the HA card (+ constant kWh profiles) |
| `build.py` | Builds `docs/index.html` (+ one page per price area, + JSON snapshot) |
| `parity_test.py` | Renders the **original card** and this port on identical prices, compares every cell |
| `reference_card.jinja` | Verbatim copy of the Home Assistant card — the parity reference |
| `template.html` | Page template (dark/light, responsive) |
| `.github/workflows/build.yml` | Hourly rebuild + commit to `docs/` |

## Run it locally

```bash
cd ~/workspace/kiln-prices-site
python3 parity_test.py                      # must print PARITY PASSED
python3 build.py                            # uses today in Europe/Copenhagen
python3 build.py --date 2025-01-15          # or any date (demo/back-test)
python3 -m http.server -d docs 8099         # then open http://localhost:8099
```

The public API is rate limited very aggressively without a key (HTTP 429, "try again in
N seconds"); the client waits and retries, so a cold build can take a few minutes. A free
API key from <https://www.energidataservice.dk/> removes that: export it as
`ENERGIDATA_API_KEY` locally or add it as an Actions secret of the same name.

## Configuration (`config.json`)

| Key | Meaning |
|---|---|
| `area` | Price area used for the site root: `DK1` (Jylland/Fyn) or `DK2` (Sjælland) |
| `areas` | Every area to build a page for; each page links to the others |
| `tariff_dkk_per_kwh` | Flat adder, e.g. `0.761` for elafgift. Default `0` = spot only |
| `vat_percent` | e.g. `25`. Default `0` |
| `hours_shown` | Rows in the table (24) |
| `title` / `subtitle` / `tomorrow_note` | Page text |

## Deploy to GitHub Pages

1. **Create the repo** — public is simplest (Pages is free there):
   `nicjensen/kiln-prices` (any name will do).
2. **Push this folder** to `main` (it is already a git repo with one commit).
3. **Turn Pages on** once: *Settings → Pages → Source: Deploy from a branch →
   Branch: `main`, folder: `/docs` → Save*.
   (Or set it in one API call — see below.)
4. The workflow then runs hourly, rebuilds `docs/`, and commits if the numbers changed.
   The site lands at `https://nicjensen.github.io/kiln-prices/`.

One-time Pages setup via API, if you would rather not click:

```bash
TOKEN=$(cat ~/.hermes/.github_token)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/nicjensen/kiln-prices/pages \
     -d '{"source":{"branch":"main","path":"/docs"}}'
```

Note: a **fine-grained** PAT must be granted *Pages: write* (and repo creation) for the
call above to work; the nightly-backup token may only have access to `hermes-backup`.
If it is refused, create the repo and enable Pages in the browser instead — the workflow
itself needs nothing beyond the default `GITHUB_TOKEN` (`contents: write`).

## Notes for future edits

- **Keep the parity test passing.** `kiln_calc.py` is a port of a Jinja template; if the
  card on the dashboard is ever changed (coefficients, thresholds, column order), update
  `reference_card.jinja` from the dashboard and re-run `parity_test.py` before trusting
  the site.
- **Do not make the page fetch the API from the browser.** The anonymous rate limit is
  tiny and would be consumed by visitors; the build-time snapshot avoids it entirely.
- DST is handled by `zoneinfo` conversion, so CET/CEST days both map to 24 local hours.
