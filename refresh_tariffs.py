#!/usr/bin/env python3
"""
Refresh the official grid-tariff snapshot from Energi Data Service's DataHub price list.

Writes tariffs_datahub.json: for every grid company in tariffs.DSO_REGISTRY, all nettarif
rows (ChargeType D03, resolution PT1H) with their validity range and their 24 hourly
prices. The rows encode the seasons through ValidFrom/ValidTo, so the site can simply ask
"which row covers this day?" instead of assuming band and season rules.

Values are kr/kWh EXCL. moms, exactly as published (tariffs.py converts to øre incl. moms).

Run manually when tariffs change (typically 1 January and 1 April/October):

    python3 refresh_tariffs.py            # uses the disk cache if present
    python3 refresh_tariffs.py --refresh  # always hits the API
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse

sys.path.insert(0, ".")
import tariffs
from fetch_prices import _http_json

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.energidataservice.dk/dataset/DatahubPricelist"


def fetch_rows(gln: str, code: str, cache_dir: str, refresh: bool) -> list[dict]:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"datahub_{gln}_{code}.json")
    if os.path.exists(path) and not refresh:
        with open(path) as fh:
            return json.load(fh)
    today = dt.date.today()
    # Filtering on ChargeTypeCode is essential: a grid company publishes dozens of charge
    # codes, and without this filter a 2-year window is truncated before reaching the row
    # that is actually valid today.
    query = urllib.parse.urlencode({
        "offset": 0,
        "start": (today - dt.timedelta(days=730)).isoformat(),
        "end": (today + dt.timedelta(days=730)).isoformat(),
        "filter": json.dumps({"GLN_Number": [gln], "ChargeType": ["D03"],
                              "ChargeTypeCode": [code]}),
        "sort": "ValidFrom ASC",
        "limit": 200,
    })
    payload = _http_json(f"{API}?{query}")
    rows = payload.get("records") or []
    with open(path, "w") as fh:
        json.dump(rows, fh)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(HERE, ".cache"))
    ap.add_argument("--out", default=os.path.join(HERE, "tariffs_datahub.json"))
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    snapshot: dict = {
        "source": "api.energidataservice.dk/dataset/DatahubPricelist",
        "note": ("ChargeType D03 (nettarif), kundekategori C. Prices are kr/kWh EXCL. moms, "
                 "as published; Price1..24 = hours 00-23 local Danish time."),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "companies": {},
    }

    for dso, ident in tariffs.DSO_REGISTRY.items():
        rows = fetch_rows(ident["gln"], ident["charge_code"], args.cache, args.refresh)
        keep = []
        for r in rows:
            code = r.get("ChargeTypeCode")
            prices = [r.get(f"Price{i}") for i in range(1, 25)]
            if code != ident["charge_code"]:
                continue
            if any(p is None for p in prices):
                continue
            keep.append({
                "charge_type_code": code,
                "note": r.get("Note"),
                "vat_class": r.get("VATClass"),
                "resolution": r.get("ResolutionDuration"),
                "valid_from": (r.get("ValidFrom") or "")[:10],
                "valid_to": (r.get("ValidTo") or "")[:10],
                "prices_kr_per_kwh_excl_moms": prices,
            })
        keep.sort(key=lambda r: r["valid_from"])
        snapshot["companies"][dso] = {
            "gln": ident["gln"],
            "charge_type_code": ident["charge_code"],
            "label": tariffs.DSO_TARIFFS.get(dso, {}).get("label", dso),
            "rows": keep,
        }
        print(f"{dso} (GLN {ident['gln']}, code {ident['charge_code']}): {len(keep)} nettarif rows")

    with open(args.out, "w") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
