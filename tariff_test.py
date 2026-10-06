#!/usr/bin/env python3
"""
Checks for the all-in price build-up (tariffs + taxes + VAT).

The band rates themselves come from the grid companies; what is tested here is that
they are applied to the right hours, in the right season, on top of the right tax
and VAT base — and that the published incl.-moms figures round-trip against the
excl.-moms figures the grid company also publishes.
"""
from __future__ import annotations

import datetime as dt
import sys

import kiln_calc
import tariffs

FAILED: list[str] = []


def case(name: str, got, want, tol: float | None = None) -> None:
    if tol is None:
        ok = got == want
    else:
        ok = abs(got - want) <= tol
    shown = f"{got!r}" if tol is None else f"{got!r} (want {want!r} ±{tol})"
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {shown}")
    if not ok:
        FAILED.append(name)


def main() -> int:
    print("band assignment (Tarifmodel 3.0, kategori C)")
    bands = [tariffs.band_of_hour(h) for h in range(24)]
    case("00-05 lavlast", bands[0:6], ["lavlast"] * 6)
    case("06-16 højlast", bands[6:17], ["hoejlast"] * 11)
    case("17-20 spidslast", bands[17:21], ["spidslast"] * 4)
    case("21-23 højlast", bands[21:24], ["hoejlast"] * 3)

    print("season boundaries (vinter = okt-mar)")
    for day, want in ((dt.date(2025, 9, 30), "sommer"), (dt.date(2025, 10, 1), "vinter"),
                      (dt.date(2026, 3, 31), "vinter"), (dt.date(2026, 4, 1), "sommer"),
                      (dt.date(2026, 1, 15), "vinter")):
        case(f"{day} -> {want}", tariffs.season_of(day), want)

    print("composition: spot incl. moms + nettarif + Energinet + elafgift")
    winter = dt.date(2026, 1, 15)
    # 0.50 kr/kWh spot -> 0.625 incl. moms; N1 winter spidslast 98.84 + 14.38 + 1.00 øre
    entries = [{"hour": "18:00", "price": 0.50}]
    want = 0.625 + (98.84 + 14.38 + 1.0) / 100.0
    case("N1 winter spidslast 18:00", tariffs.all_in_prices(entries, winter, "N1")[0], want, 1e-9)

    print("cross-check against N1's own published figures")
    # n1.dk publishes lavlast as 10,98 øre incl. moms and 8,79 øre excl. moms.
    nettarif_incl = tariffs.DSO_TARIFFS["N1"]["vinter"]["lavlast"]
    case("10,98 incl. moms / 1,25 = 8,784 excl. (n1.dk shows 8,79)",
         round(nettarif_incl / (1 + tariffs.MOMS), 2), 8.78, 0.01)

    print("the band spread actually reaches the price")
    flat = [{"hour": f"{h:02d}:00", "price": 0.50} for h in range(24)]
    winter_prices = tariffs.all_in_prices(flat, winter, "N1")
    summer = dt.date(2026, 7, 15)
    summer_prices = tariffs.all_in_prices(flat, summer, "N1")
    case("winter 18:00 - winter 03:00 = (98,84-10,98)/100",
         round(winter_prices[18] - winter_prices[3], 6), round((98.84 - 10.98) / 100, 6), 1e-9)
    case("winter 18:00 - summer 18:00 = (98,84-42,83)/100",
         round(winter_prices[18] - summer_prices[18], 6), round((98.84 - 42.83) / 100, 6), 1e-9)
    case("summer 18:00 - summer 03:00 = (42,83-10,98)/100",
         round(summer_prices[18] - summer_prices[3], 6), round((42.83 - 10.98) / 100, 6), 1e-9)

    print("fixed subscriptions are excluded (they cannot change the best start hour)")
    case("no fixed fee in the hourly price", tariffs.all_in_prices([{"hour": "03:00", "price": 0.0}], winter, "N1")[0],
         round((10.98 + 14.38 + 1.0) / 100, 6), 1e-9)

    print("effect: does the tariff change which start hour wins?")
    # A realistic winter day: cheap night, expensive evening peak.
    winter_spot = [0.35, 0.32, 0.30, 0.31, 0.38, 0.55, 0.80, 1.05, 1.20, 1.10, 1.02, 0.98,
                   0.95, 0.92, 1.00, 1.25, 1.60, 1.95, 1.80, 1.50, 1.20, 0.95, 0.70, 0.50]
    entries_today = [{"hour": f"{h:02d}:00", "price": p} for h, p in enumerate(winter_spot)]
    all_in = tariffs.all_in_prices(entries_today, winter, "N1")
    spot_only = kiln_calc.compute(winter_spot, [], False)["best"]["b_today"]
    with_tariff = kiln_calc.compute(all_in, [], False)["best"]["b_today"]
    print(f"       spot-only cheapest Forglødning start: {spot_only}")
    print(f"       all-in    cheapest Forglødning start: {with_tariff}")
    case("all-in cost is strictly higher than spot-only",
         all_in[0] > winter_spot[0], True)
    case("the evening peak is the most expensive hour on the day",
         max(all_in) == all_in[18] or max(all_in) == all_in[17], True)

    print("\nTARIFFS", "PASSED" if not FAILED else f"FAILED ({len(FAILED)})")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
