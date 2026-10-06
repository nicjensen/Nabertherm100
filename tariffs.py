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
# Reported as 6.3 + 5.3 øre excl. moms (elselskaber.dk) or 7.2 + 4.3 øre excl.
# (eltjek24) — the split differs between sources, the total does not.
ENERGINET_ORE_INCL_MOMS = 14.38
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
        "vinter": {"lavlast": 13.32, "hoejlast": 39.85, "spidslast": 119.42},
        "source": "minenergiberegner.dk verified 2026 summer table (incl. moms) + "
                  "elselskaber.dk winter table — CHECK AGAINST YOUR OWN BILL",
    },
}


def band_of_hour(hour: int) -> str:
    for band, hours in BAND_HOURS.items():
        if hour in hours:
            return band
    raise ValueError(f"hour out of range: {hour}")


def season_of(day: dt.date) -> str:
    return "vinter" if day.month in WINTER_MONTHS else "sommer"


def grid_ore_per_kwh(dso: str, day: dt.date, hour: int) -> float:
    """Nettarif + Energinet + elafgift for one hour, øre/kWh incl. moms."""
    profile = DSO_TARIFFS[dso]
    nettarif = profile[season_of(day)][band_of_hour(hour)]
    return nettarif + ENERGINET_ORE_INCL_MOMS + ELAFGIFT_ORE_INCL_MOMS


def all_in_prices(entries: list[dict], day: dt.date, dso: str) -> list[float]:
    """
    Turn a day's spot entries into all-in DKK/kWh incl. moms.

    entries: [{'hour': 'HH:00', 'price': spot DKK/kWh excl. moms}, ...]
    """
    out = []
    for entry in entries:
        hour = int(str(entry["hour"]).split(":")[0])
        spot_incl = float(entry["price"]) * (1.0 + MOMS)
        out.append(round(spot_incl + grid_ore_per_kwh(dso, day, hour) / 100.0, 6))
    return out


def composition() -> dict:
    return {"moms_pct": MOMS * 100,
            "energinet_ore_incl_moms": ENERGINET_ORE_INCL_MOMS,
            "elafgift_ore_incl_moms": ELAFGIFT_ORE_INCL_MOMS}


def describe(dso: str) -> str:
    profile = DSO_TARIFFS[dso]
    parts = []
    for season in ("vinter", "sommer"):
        rates = profile[season]
        parts.append(f"{season}: " + ", ".join(
            f"{BAND_DA[b]} {rates[b]:.2f} øre" for b in ("lavlast", "hoejlast", "spidslast")))
    return (f"Nettarif {profile['label']} — " + " · ".join(parts)
            + f". Energinet (system+transmission) {ENERGINET_ORE_INCL_MOMS:.2f} øre/kWh og "
              f"elafgift {ELAFGIFT_ORE_INCL_MOMS:.2f} øre/kWh er ens hele døgnet. "
              f"Alt er inkl. moms (spotprisen ganges med 1,25). Kilde: {profile['source']}.")
