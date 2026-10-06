#!/usr/bin/env python3
"""
The all-in Danish electricity price for a given hour.

Build-up of what a household actually pays per kWh:

    (spotpris + nettarif + Energinet-tariffer + elafgift) x (1 + moms)

* **Spotpris** — Nord Pool day-ahead, fetched excl. moms by fetch_prices.py.
* **Nettarif** — your local grid company, Tarifmodel 3.0: three time bands
  (lavlast 00-06, højlast 06-17 and 21-24, spidslast 17-21) with separate summer
  (Apr-Sep) and winter (Oct-Mar) rates. This is the term that makes firing at
  17-21 on a winter evening expensive.
* **Energinet** — systemtarif + transmissionstarif, the same everywhere in Denmark.
* **Elafgift** — state tax. Since 1 Jan 2026 it is only 0.8 øre/kWh excl. moms
  (EU minimum), down from 72 øre in 2025, so it is now a rounding error.
* **Moms** — 25 %, charged on the spot price AND on the tariffs and the elafgift.

Fixed subscriptions (netabonnement, systemabonnement, the supplier's monthly fee)
are deliberately NOT included: they do not depend on WHEN the kiln is fired, so
they cannot change which start hour is cheapest.
"""
from __future__ import annotations

import datetime as dt
import json
import os

MOMS = 0.25

# Tarifmodel 3.0, kundekategori C (private boliger og mindre erhverv).
# Same band times every day of the week; only the season changes the rates.
BAND_HOURS = {
    "lavlast": (0, 1, 2, 3, 4, 5),
    "hoejlast": (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 21, 22, 23),
    "spidslast": (17, 18, 19, 20),
}
BAND_DA = {"lavlast": "Lavlast 00-06", "hoejlast": "Højlast 06-17 + 21-24",
           "spidslast": "Spidslast 17-21"}
WINTER_MONTHS = (10, 11, 12, 1, 2, 3)

# Energinet 2026: systemtarif + transmissionstarif, øre/kWh incl. moms.
# The HA integration carries these as two separate add-ons — transmissions_nettarif 5.4 øre
# and systemtarif 9.0 øre — i.e. 14.4 øre/kWh incl. moms. Published figures are quoted excl.
# moms as 6.3 + 5.3 øre (elselskaber.dk) or 7.2 + 4.3 øre (eltjek24); the split differs
# between sources, the total (~11.5 excl. = 14.4 incl.) does not.
ENERGINET_ORE_INCL_MOMS = 14.4
ELAFGIFT_ORE_INCL_MOMS = 1.0     # 0.8 øre excl. moms since 2026-01-01

# Grid company tariffs, øre/kWh INCL. MOMS (as the grid companies publish them).
DSO_TARIFFS: dict[str, dict] = {
    "N1": {
        "area": "DK1",
        "label": "N1 — store dele af Midt-, Syd- og Østjylland",
        "sommer": {"lavlast": 10.98, "hoejlast": 16.47, "spidslast": 42.83},
        "vinter": {"lavlast": 10.98, "hoejlast": 32.95, "spidslast": 98.84},
        "source": "n1.dk/priser-og-vilkar (C-kunde, gældende fra 1. jan. 2026); the page's "
                  "incl.-moms figures were confirmed with its own 'Med moms' toggle",
    },
    "Radius": {
        "area": "DK2",
        "label": "Radius Elnet — København, Nordsjælland, dele af Midtsjælland",
        "sommer": {"lavlast": 13.27, "hoejlast": 19.91, "spidslast": 51.76},
        "vinter": {"lavlast": 13.27, "hoejlast": 39.82, "spidslast": 119.45},
        "source": "vinter: DataHub nettarif C (code DT_C_01, gældende 2026-10-01..2027-04-01) "
                  "= 10,6175 / 31,8524 / 95,5573 øre excl. moms; sommer: verified 2026 summer "
                  "table (minenergiberegner.dk + elselskaber.dk)",
    },
}


# Official DataHub identity per grid company: the Global Location Number and the charge
# code of the household nettarif (kundekategori C). refresh_tariffs.py uses this to fetch
# the official hourly rates, and tariff_test.py uses it to guard the table above.
DSO_REGISTRY = {
    "N1": {"gln": "5790001089030", "charge_code": "CD", "area": "DK1"},
    "Radius": {"gln": "5790000705689", "charge_code": "DT_C_01", "area": "DK2"},
}

DATAHUB_SNAPSHOT = "tariffs_datahub.json"


def load_snapshot(path: str | None = None) -> dict:
    """The committed snapshot written by refresh_tariffs.py ({} when it is absent)."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DATAHUB_SNAPSHOT)
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return json.load(fh)


def official_nettarif(dso: str, day: dt.date, snapshot: dict | None = None) -> list[float] | None:
    """
    The 24 hourly nettarif values (kr/kWh excl. moms) that are valid on `day`, straight
    from the DataHub price list — the rows carry the seasons in their validity range, so
    no season rule is needed. None when no row covers that day.
    """
    snap = snapshot if snapshot is not None else load_snapshot()
    company = (snap.get("companies") or {}).get(dso)
    if not company:
        return None
    for row in company.get("rows", []):
        try:
            start = dt.date.fromisoformat(row["valid_from"])
            end = dt.date.fromisoformat(row["valid_to"])
        except (KeyError, ValueError, TypeError):
            continue
        if start <= day < end:
            return row.get("prices_kr_per_kwh_excl_moms")
    return None


def band_of_hour(hour: int) -> str:
    for band, hours in BAND_HOURS.items():
        if hour in hours:
            return band
    raise ValueError(f"hour out of range: {hour}")


def season_of(day: dt.date) -> str:
    return "vinter" if day.month in WINTER_MONTHS else "sommer"


def grid_ore_per_kwh(dso: str, day: dt.date, hour: int, snapshot: dict | None = None) -> float:
    """Nettarif + Energinet + elafgift for one hour, øre/kWh incl. moms."""
    official = official_nettarif(dso, day, snapshot)
    if official:
        nettarif = official[hour] * 100 * (1 + MOMS)      # kr/kWh excl. -> øre incl. moms
    else:
        profile = DSO_TARIFFS[dso]                        # fallback: published table
        nettarif = profile[season_of(day)][band_of_hour(hour)]
    return nettarif + ENERGINET_ORE_INCL_MOMS + ELAFGIFT_ORE_INCL_MOMS


def all_in_prices(entries: list[dict], day: dt.date, dso: str,
                  snapshot: dict | None = None) -> list[float]:
    """
    Turn a day's spot entries into all-in DKK/kWh incl. moms.

    entries: [{'hour': 'HH:00', 'price': spot DKK/kWh excl. moms}, ...]
    """
    out = []
    for entry in entries:
        hour = int(str(entry["hour"]).split(":")[0])
        spot_incl = float(entry["price"]) * (1.0 + MOMS)
        out.append(round(spot_incl + grid_ore_per_kwh(dso, day, hour, snapshot) / 100.0, 6))
    return out


def composition() -> dict:
    return {"moms_pct": MOMS * 100,
            "energinet_ore_incl_moms": ENERGINET_ORE_INCL_MOMS,
            "elafgift_ore_incl_moms": ELAFGIFT_ORE_INCL_MOMS}


def _runs(vector: list[float]) -> list[tuple[int, int, float]]:
    """
    Contiguous runs of equal values: (start hour, end hour exclusive, value).

    The bands are NOT contiguous — højlast is 06-17 plus 21-24 — so a run-based
    description is the only honest way to render the official vector.
    """
    runs: list[tuple[int, int, float]] = []
    start = 0
    for hour in range(1, 25):
        if hour == 24 or vector[hour] != vector[start]:
            runs.append((start, hour, vector[start]))
            start = hour
    return runs


def describe(dso: str, snapshot: dict | None = None, day: dt.date | None = None) -> str:
    profile = DSO_TARIFFS[dso]
    day = day or dt.date.today()
    official = official_nettarif(dso, day, snapshot)
    if official:
        snap = snapshot if snapshot is not None else load_snapshot()
        company = snap["companies"][dso]
        row = next((r for r in company["rows"]
                    if r["valid_from"] <= day.isoformat() < r["valid_to"]), {})
        rates = [f"{BAND_DA.get(band_of_hour(start), 'Time').split(' ')[0]} "
                 f"kl. {start:02d}-{end:02d} {value * 100 * (1 + MOMS):.2f} øre"
                 for start, end, value in _runs(official)]
        return (f"Nettarif {profile['label']}: " + " · ".join(rates)
                + f" (officiel sats fra Energi Data Service DataHub, kode "
                  f"{row.get('charge_type_code', '?')}, gældende "
                  f"{row.get('valid_from', '?')} til {row.get('valid_to', '?')}). "
                + f"Energinet (system+transmission) {ENERGINET_ORE_INCL_MOMS:.2f} øre/kWh og "
                  f"elafgift {ELAFGIFT_ORE_INCL_MOMS:.2f} øre/kWh er ens hele døgnet. "
                  f"Alt er inkl. moms (spotprisen ganges med 1,25).")
    parts = []
    for season in ("vinter", "sommer"):
        rates = profile[season]
        parts.append(f"{season}: " + ", ".join(
            f"{BAND_DA[b]} {rates[b]:.2f} øre" for b in ("lavlast", "hoejlast", "spidslast")))
    return (f"Nettarif {profile['label']} — " + " · ".join(parts)
            + f". Energinet (system+transmission) {ENERGINET_ORE_INCL_MOMS:.2f} øre/kWh og "
              f"elafgift {ELAFGIFT_ORE_INCL_MOMS:.2f} øre/kWh er ens hele døgnet. "
              f"Alt er inkl. moms (spotprisen ganges med 1,25). Kilde: {profile['source']}.")
