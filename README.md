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

**A passed optimum is not advertised.** The four "cheapest" cards at the top are checked in
*your browser*, not at build time — the page is a snapshot rebuilt once a day, so a card can be
hours stale by the time it is opened. Once a card's start hour is behind the current
Copenhagen time it is dropped (`kpi_past: "hide"`), or re-pointed to the cheapest start still
available today (`kpi_past: "remaining"`). A start hour counts as available through the end of
that clock hour, the check re-runs every minute so a page left open stays honest, and if the
page is a day old the cards are hidden outright. **The table below always shows the whole day,
passed hours included** — that is the record; the cards are only the recommendation.

## When it updates

Tomorrow's prices are published around 13:00 local time and nothing else in the data changes
during the day, so the workflow runs **once a day, at 13:15 local** (two cron entries, so DST
cannot shift it) plus on every push — the first push builds the page with both days. Then **the
browser moves the day at midnight**, so nothing has to be rebuilt for it: the "i morgen" columns
slide into "i dag" (their numbers were computed by exactly the same server-side code, so the
rollover relabels and reorders, it never recalculates), the cards swap places, and "i morgen"
goes back to dashes until the next afternoon publication. Because the rollover lives in the
page, a skipped GitHub run cannot leave the site calling yesterday "i dag".

Two states are called out rather than guessed at: if the page was built before the afternoon
publication (so it has nothing to promote), or if it is more than a day old, it says so in a
note and hides the cards. The page always prints its own build time, so staleness stays visible.

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
  **The dataset is quarter-hourly** — four records per local hour, and the hourly price is the
  **mean** of the four (which is what hourly settlement and the HA integration use). Sampling a
  single quarter instead drifts by up to ~45 øre/kWh in the ramp hours: it is a real error, not
  a rounding detail, and it was the one thing that made this page disagree with the dashboard.
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
| `area` | Price area used for the site root: `DK1` (Jylland/Fyn) or `DK2` (Sjælland). Currently `DK2` |
| `areas` | Every area to build a page for; each page links to the others (currently just `DK2`) |
| `nettarif.enabled` | `true` = all-in prices; `false` = spot only (comparable to the HA card) |
| `nettarif.selskab` | Grid company for the default area. Currently `Radius` (DK2) |
| `nettarif.selskab_by_area` | Optional per-area override, e.g. `{"DK1": "N1", "DK2": "Radius"}` |
| `hours_shown` | Rows in the table (24) |
| `kpi_past` | `hide` (default) = drop a "today" card once its start hour has passed · `remaining` = re-point it to the cheapest start still available today |
| `title` / `subtitle` / `tomorrow_note` | Page text |

**Which grid company do you have?** It follows your address, not your choice — it is on your
electricity bill (or at eloverblik.dk). DK1 includes N1, Norlys Net, TREFOR, Vores Elnet,
Konstant, RAH Net, Nord Energi Net and Dinel; DK2 includes Radius, Cerius and Konstant. Only N1
and Radius are in `tariffs.py` so far; add yours from the company's own price list.

## Deploy to GitHub Pages

1. **Create the repo** — public is simplest (Pages is free there):
   `nicjensen/Nabertherm100` (any name will do).
2. **Push this folder** to `main` (any account or token with access to that one repo).
3. **Turn Pages on** once: *Settings → Pages → Source: Deploy from a branch →
   Branch: `main`, folder: `/docs` → Save*.
   (Or set it in one API call — see below.)
4. The workflow then runs once a day (13:15 local) and on every push, rebuilds `docs/`, and
   commits when anything changed. The site lands at `https://nicjensen.github.io/Nabertherm100/`.

One-time Pages setup via API, if you would rather not click:

```bash
TOKEN=$GITHUB_TOKEN    # a fine-grained PAT with Pages: write, scoped to this repo only
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/nicjensen/Nabertherm100/pages \
     -d '{"source":{"branch":"main","path":"/docs"}}'
```

The workflow itself needs **no personal access token**. It commits with the default
`GITHUB_TOKEN` (`contents: write`), which GitHub scopes to this one repository, and it runs on
schedule/push/dispatch only — never on a fork's pull request, so a stranger's PR cannot execute
anything in this context. The single optional secret is `ENERGIDATA_API_KEY`, a free price-API
key rather than an account credential. Nothing in this repository can read or write any other
repository, and publishing it grants nobody access to the account.

## Notes for future edits

- **Keep the parity test passing.** `kiln_calc.py` is a port of a Jinja template; if the
  card on the dashboard is ever changed (coefficients, thresholds, column order), update
  `reference_card.jinja` from the dashboard and re-run `parity_test.py` before trusting
  the site.
- **Validate against the live sensor, not only against the card.** The card's whole-kroner
  cells hide a systematic error; the integration's own numbers do not. Read them from
  `sensor.energi_data_service`: the attributes carry `region_code` (the price area),
  `net_operator` (the grid company), the per-hour `today`/`tomorrow` prices, and the exact
  `tariffs`/`additional_tariffs` it applied. With that, the site can be checked term by term —
  and those two attributes are also how you learn the area and DSO instead of assuming them.
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
