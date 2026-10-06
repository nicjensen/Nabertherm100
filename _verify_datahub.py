#!/usr/bin/env python3
"""
Verify the tariff rates in tariffs.py against Energi Data Service's official
DataHub price list (dataset DatahubPricelist, ChargeType D03 = nettarif).

The dataset publishes Price1..Price24 = one price per local hour of the day, and
seasons/periods as separate rows with ValidFrom/ValidTo. Comparing a fetched hour-0
price against the grid company's own published figure also settles whether DataHub
quotes prices incl. or excl. moms.
"""
import datetime as dt
import json
import sys
import urllib.parse

sys.path.insert(0, '.')
import tariffs
from fetch_prices import _http_json

BASE = "https://api.energidataservice.dk/dataset/DatahubPricelist"
TODAY = dt.date(2026, 10, 6)
TARGETS = [("N1", "5790001089030"), ("Radius", "5790000705689")]


def rows_for(gln: str) -> list[dict]:
    query = urllib.parse.urlencode({
        "offset": 0,
        "start": "2015-01-01",
        "end": (TODAY + dt.timedelta(days=1)).isoformat(),
        "filter": json.dumps({"GLN_Number": [gln], "ChargeType": ["D03"]}),
        "sort": "ValidFrom DESC",
        "limit": 60,
    })
    payload = _http_json(f"{BASE}?{query}")
    return payload.get("records") or []


def main() -> int:
    for name, gln in TARGETS:
        print("=" * 78)
        print(f"{name}  GLN {gln}")
        try:
            rows = rows_for(gln)
        except Exception as exc:
            print("  query failed:", exc)
            continue
        print(f"  rows returned: {len(rows)}")
        current = []
        for r in rows:
            vf = (r.get("ValidFrom") or "")[:10]
            vt = (r.get("ValidTo") or "")[:10]
            try:
                active = dt.date.fromisoformat(vf) <= TODAY < dt.date.fromisoformat(vt)
            except ValueError:
                active = False
            if active:
                current.append(r)
        print(f"  rows active on {TODAY}: {len(current)}")
        for r in current:
            prices = [r.get(f"Price{i}") for i in range(1, 25)]
            print(f"   code={r.get('ChargeTypeCode')!r} note={r.get('Note')!r} "
                  f"VATClass={r.get('VATClass')!r} resolution={r.get('ResolutionDuration')!r}")
            print(f"      valid {r.get('ValidFrom')} .. {r.get('ValidTo')}")
            print(f"      Price1..24: {prices}")
            distinctive = sorted({p for p in prices if p is not None})
            print(f"      distinct values (kr/kWh): {distinctive}")

        # My table, converted both ways for comparison.
        profile = tariffs.DSO_TARIFFS[name]
        for season in ("vinter", "sommer"):
            incl = profile[season]
            excl = {b: round(incl[b] / (1 + tariffs.MOMS) / 100, 5) for b in incl}
            print(f"   tariffs.py {season}: øre incl. moms {incl}")
            print(f"                 -> kr/kWh excl. moms {excl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
