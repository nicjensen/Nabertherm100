"""Confirm local-hour mapping across CET/CEST and the DST boundaries."""
import datetime as dt, sys
sys.path.insert(0, '.')
from fetch_prices import day_prices

for label, d in [("summer / CEST", dt.date(2025, 6, 15)),
                 ("spring-forward day (23 local hours)", dt.date(2025, 3, 30)),
                 ("autumn-back day (25 local hours)", dt.date(2025, 10, 26))]:
    entries, complete = day_prices("DK1", d)
    first = entries[0] if entries else None
    last = entries[-1] if entries else None
    print(f"{label:38s} {d}  hours={len(entries):2d} complete={complete}  "
          f"first={first}  last={last}", flush=True)
