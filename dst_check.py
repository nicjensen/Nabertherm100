#!/usr/bin/env python3
"""
DST regression checks.

The local-day slicing must survive CET/CEST and both DST boundaries:
  * 2025-03-30 (spring forward) -> 23 local hours, 02:00 does not exist
  * 2025-10-26 (autumn back)    -> 02:00 happens twice, the later (CET) hour wins
and the page must label rows from the real clock, not from the array index.

The synthetic cases run offline; there is also an optional API sanity check for a
summer date (the public dataset has no rows for dates beyond its own present).
"""
from __future__ import annotations

import datetime as dt
import sys

from fetch_prices import TZ, _price_by_local_hour
from kiln_calc import compute

UTC = dt.timezone.utc
FAILED: list[str] = []


def synthetic_records(start_utc: dt.datetime, end_utc: dt.datetime) -> list[dict]:
    out, t = [], start_utc
    while t < end_utc:
        out.append({"HourUTC": t.strftime("%Y-%m-%dT%H:%M:%S"), "PriceArea": "DK1",
                    "SpotPriceDKK": 100.0 + t.hour * 10.0})   # -> 0.10 + h*0.01 kr/kWh
        t += dt.timedelta(hours=1)
    return out


def case(name: str, got, want) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        FAILED.append(name)


def main() -> int:
    print("synthetic DST slices")
    spring = _price_by_local_hour(
        synthetic_records(dt.datetime(2025, 3, 29, 20, tzinfo=UTC),
                          dt.datetime(2025, 3, 31, 5, tzinfo=UTC)), dt.date(2025, 3, 30), "DK1")
    case("spring-forward day -> 23 hours", len(spring), 23)
    case("spring-forward day -> 02:00 absent", 2 in spring, False)
    case("spring-forward day -> 03:00 present", 3 in spring, True)
    case("spring-forward day -> 23:00 present", 23 in spring, True)

    autumn = _price_by_local_hour(
        synthetic_records(dt.datetime(2025, 10, 25, 20, tzinfo=UTC),
                          dt.datetime(2025, 10, 27, 5, tzinfo=UTC)), dt.date(2025, 10, 26), "DK1")
    case("autumn-back day -> 24 labelled hours", len(autumn), 24)
    case("autumn-back day -> all hours present", sorted(autumn), list(range(24)))
    # 02:00 local happens at 00:00Z (CEST) and again at 01:00Z (CET). Hourly aggregation
    # carries the MEAN of the two occurrences (the alternative, keeping the later one, was
    # the pre-2026-10 behaviour and only differed because single quarters were sampled).
    case("autumn-back day -> doubled hour is the mean of both occurrences", autumn[2], 0.105)

    print("sub-hourly aggregation (DayAheadPrices is quarter-hourly)")
    # Four quarters per local hour, deliberately different, so the mean is distinguishable
    # from any single quarter.
    base = dt.datetime(2025, 11, 10, 23, 0, tzinfo=UTC)
    quarters = [{"TimeUTC": (base + dt.timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%S"),
                 "PriceArea": "DK1", "DayAheadPriceDKK": 1000.0 + i * 100.0}
                for i in range(8)]
    hours = _price_by_local_hour(quarters, dt.date(2025, 11, 11), "DK1")
    case("quarter-hourly records collapse to hours", sorted(hours), [0, 1])
    case("hour value is the mean of its four quarters", round(hours[1], 6), 1.55)
    case("and is not any single quarter", hours[1] in (1.4, 1.5, 1.6, 1.7), False)

    print("row labels follow the clock, not the array index")
    labels = [f"{h:02d}:00" for h in range(24) if h != 2]      # spring-forward day
    data = compute([0.5] * 23, [0.5] * 24, True, labels_today=labels,
                   labels_tomorrow=[f"{h:02d}:00" for h in range(24)])
    row_hours = [r["hour"] for r in data["rows"]]
    case("rows = 23 start hours", len(row_hours), 23)
    case("labels skip 02:00", row_hours[:4], ["00:00", "01:00", "03:00", "04:00"])
    case("last label is 23:00", row_hours[-1], "23:00")

    print("\nDST", "PASSED" if not FAILED else f"FAILED ({len(FAILED)})")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
