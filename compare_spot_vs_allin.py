#!/usr/bin/env python3
"""
Compare spot-only vs all-in (nettarif + Energinet + elafgift + moms) for the same day.

Does adding the tariffs change WHICH start hour is cheapest? A flat adder cannot, but
Tarifmodel 3.0 is time-differentiated, so it can.
"""
import datetime as dt
import sys

sys.path.insert(0, '.')
import kiln_calc
import tariffs
from fetch_prices import day_prices

area = sys.argv[1] if len(sys.argv) > 1 else "DK1"
dso = sys.argv[2] if len(sys.argv) > 2 else "N1"
today = dt.date(2026, 10, 6)
tomorrow = today + dt.timedelta(days=1)


def best(series, coeffs, starts):
    """Cheapest start hour and its cost for one programme, over a plain price series."""
    costs = kiln_calc._window_costs(series, coeffs, starts)
    if not costs:
        return None
    low = min(costs)
    return {"hour": f"{costs.index(low):02d}:00", "value": low}


e_today, _, ds = day_prices(area, today)
e_tom, _, _ = day_prices(area, tomorrow)
spot_today = [e["price"] for e in e_today]
spot_tom = [e["price"] for e in e_tom]
all_today = tariffs.all_in_prices(e_today, today, dso)
all_tom = tariffs.all_in_prices(e_tom, tomorrow, dso)
# Today is evaluated against today+tomorrow, exactly like the card (a firing started in
# the evening runs past midnight at tomorrow's prices).
spot_comb, all_comb = spot_today + spot_tom, all_today + all_tom

print(f"{area} / {dso} — {today} (dataset {ds}, {len(spot_today)}/24 h). All-in incl. moms.\n")
print(f"{'programme':12s} {'day':9s} {'spot-only':>18s} {'all-in':>18s}   effect")
for label, coeffs in (("Forglødning", kiln_calc.C_BISC), ("Glasur", kiln_calc.C_GLAZE)):
    for name, spot_series, all_series, starts in (
            ("i dag", spot_comb, all_comb, len(spot_today)),
            ("i morgen", spot_tom, all_tom, max(0, len(spot_tom) - len(coeffs) + 1))):
        b_spot = best(spot_series, coeffs, starts)
        b_all = best(all_series, coeffs, starts)
        if not b_spot or not b_all:
            continue
        moved = "same hour" if b_spot["hour"] == b_all["hour"] else "HOUR MOVED"
        print(f"{label:12s} {name:9s} {b_spot['hour']} = {b_spot['value']:>4} kr. "
              f"{b_all['hour']} = {b_all['value']:>4} kr.   {moved}"
              f" (+{b_all['value'] - b_spot['value']} kr. = tariffs+VAT)")
