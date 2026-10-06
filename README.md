# Priser på Forglødning og Glasurbrænding

A static website (GitHub Pages) that answers: **when is it cheapest to start the kiln?**
It is the Home Assistant markdown card Nick already runs, rendered as a web page that
updates itself — no Home Assistant needed to *view* it. Prices are **all-in**: spot +
nettarif + Energinet + elafgift + moms.

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

## The price build-up

For each hour: **(spotpris + nettarif + Energinet + elafgift) × 1,25 moms**

| Component | 2026 | Varies with |
|---|---|---|
| Spotpris (Nord Pool day-ahead) | market | hour |
| **Nettarif** (grid company, Tarifmodel 3.0) | 11–132 øre/kWh | hour band + season + company |
| Energinet (systemtarif + transmissionstarif) | 14,38 øre/kWh incl. moms | nothing (same nationwide) |
| Elafgift | 1,00 øre/kWh incl. moms (0,8 excl.) | nothing — **cut from 72 øre in 2025 to the EU minimum in 2026** |
| Moms | 25 % | charged on the spot price *and* on the tariffs and the elafgift |

**The nettarif is what makes this worth doing.** Tarifmodel 3.0 splits the day into lavlast
(00–06), højlast (06–17 and 21–24) and spidslast (17–21), with separate summer (Apr–Sep) and
winter (Oct–Mar) rates. At N1 the winter spidslast is **98,84 øre/kWh** against 10,98 øre in
lavlast — about 88 øre/kWh more than the night, on top of the spot price. The site therefore
ranks start hours on the all-in price, not on spot alone.

**Fixed fees are excluded on purpose**: the netabonnement (~422 kr/yr), the systemabonnement
and the supplier's monthly fee do not depend on *when* the kiln is fired, so they cannot change
which start hour is cheapest — they only shift every row by the same amount.

## Data sources

* **Spot**: `api.energidataservice.dk`, dataset **`DayAheadPrices`** (current). The old
  `Elspotprices` dataset was discontinued on 2025-09-30 and is kept as a fallback for older
  dates; the two do not share a schema (`TimeUTC`/`DayAheadPriceDKK` vs `HourUTC`/`SpotPriceDKK`).
  Prices are DKK/**MWh**, divided by 1000, excluding VAT (VAT is applied later).
* **Nettarif**: **the official rates from Energi Data Service's DataHub price list**
  (`DatahubPricelist`, ChargeType `D03`, kundekategori C), keyed by the grid company's GLN.
  `refresh_tariffs.py` fetches them into `tariffs_datahub.json` (committed); each row carries
  its own season in `ValidFrom`/`ValidTo` and one price per local hour (`Price1..24`, kr/kWh
  excl. moms). When no row covers the day, `tariffs.py` falls back to its own published table
  (source noted per company). Configured so far: **N1** (DK1, GLN 5790001089030, code `CD`)
  and **Radius** (DK2, GLN 5790000705689, code `DT_C_01`).

Tomorrow's prices are published around 13:00 Copenhagen time, so the page shows
"Priser ikke offentliggjort endnu" for the tomorrow columns until then.

## Files

| File | Purpose |
|---|---|
| `fetch_prices.py` | API client: dataset fallback, disk cache, 429 back-off, optional `ENERGIDATA_API_KEY` |
| `refresh_tariffs.py` | Fetches the official nettarif rows from DataHub into `tariffs_datahub.json` |
| `tariffs_datahub.json` | Committed snapshot of those rows (validity range + 24 hourly prices) |
| `tariffs.py` | All-in build-up: bands, seasons, grid-company tariffs, Energinet, elafgift, moms |
| `kiln_calc.py` | The calculation, ported 1:1 from the HA card (+ constant kWh profiles) |
| `build.py` | Builds `docs/index.html` (+ one page per price area, + JSON snapshot) |
| `parity_test.py` | Renders the **original card** and this port on identical prices, compares every cell |
| `tariff_test.py` | Band/season assignment, tax+VAT composition, cross-check against published rates |
| `dst_check.py` | Spring-forward (23 h) and autumn-back (25 h) day handling |
| `compare_spot_vs_allin.py` | Shows how much the tariffs add, and whether they move the best start hour |
| `reference_card.jinja` | Verbatim copy of the Home Assistant card — the parity reference |
| `template.html` | Page template (dark/light, responsive) |
| `.github/workflows/build.yml` | Runs the test suites, rebuilds hourly, commits to `docs/` |

## Run it locally

```bash
cd ~/workspace/kiln-prices-site
python3 parity_test.py     # PARITY PASSED    — the site matches the HA card
python3 tariff_test.py     # TARIFFS PASSED   — bands, seasons, tax base
python3 dst_check.py       # DST PASSED       — 23/25-hour days
python3 build.py                            # today in Europe/Copenhagen
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
| `nettarif.enabled` | `true` = all-in prices; `false` = spot only (comparable to the HA card) |
| `nettarif.selskab` | Grid company for the default area, e.g. `N1` |
| `nettarif.selskab_by_area` | Optional per-area override, e.g. `{"DK1": "N1", "DK2": "Radius"}` |
| `hours_shown` | Rows in the table (24) |
| `title` / `subtitle` / `tomorrow_note` | Page text |

**Which grid company do you have?** It follows your address, not your choice — it is on your
electricity bill (or at eloverblik.dk). DK1 includes N1, Norlys Net, TREFOR, Vores Elnet,
Konstant, RAH Net, Nord Energi Net and Dinel; DK2 includes Radius, Cerius and Konstant. Only N1
and Radius are in `tariffs.py` so far; add yours from the company's own price list.

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
- **Keep tariffs in one place.** All rates live in `tariffs.py`; the page text and the JSON
  snapshot are generated from it, so a rate change is a one-line edit plus a rebuild.
- **Tariff values are 2026 and incl. moms.** Grid companies publish them incl. moms (N1's page
  was confirmed with its own "Med moms" toggle); Energinet and elafgift are stored incl. moms
  too, and only the spot price is multiplied by 1.25. `tariff_test.py` guards that arithmetic.
- **Do not make the page fetch the API from the browser.** The anonymous rate limit is
  tiny and would be consumed by visitors; the build-time snapshot avoids it entirely.
- **Refresh the tariffs monthly**: `python3 refresh_tariffs.py --refresh` (the CI job does it on
  the 1st). Rates change on 1 Jan / 1 Apr / 1 Oct, and a stale table would silently price the
  page wrongly. The script **must** filter on `ChargeTypeCode`: a grid company publishes dozens
  of charge codes, and an unfiltered multi-year window is truncated before it reaches the row
  that is valid today.
- **The official rates are the ground truth.** `tariff_test.py` compares the fallback table in
  `tariffs.py` against the DataHub snapshot — if the two ever disagree by more than 0.05 øre,
  the test fails rather than quietly repricing the page.
- **Unit trap:** the API quotes DKK per **MWh**; a factor of 1000 sits between the raw field and
  every kr figure on the page.
- DST is handled by `zoneinfo` conversion, so CET/CEST days both map to 24 local hours; the
  23-hour and 25-hour transition days are covered by `dst_check.py`.
