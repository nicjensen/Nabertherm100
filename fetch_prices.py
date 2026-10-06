#!/usr/bin/env python3
"""
Fetch Danish day-ahead spot prices from Energi Data Service (the source the Home
Assistant 'energi_data_service' integration uses).

Two datasets matter, and they do NOT share a schema:
  * DayAheadPrices - current, from 2025-10-01: TimeUTC / TimeDK / DayAheadPriceDKK
  * Elspotprices   - discontinued 2025-09-30:  HourUTC / HourDK / SpotPriceDKK

Prices are quoted in DKK/MWh -> divided by 1000 for DKK/kWh, excluding VAT
(the marketplace price; VAT is applied later together with the tariffs).

The public API is rate limited hard (HTTP 429, "try again in N seconds").
This module therefore keeps a disk cache and backs off rather than hammering it.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

API = "https://api.energidataservice.dk/dataset/"
TZ = ZoneInfo("Europe/Copenhagen")
USER_AGENT = "kiln-price-site/1.0 (+github pages)"

# Tried in order: the current dataset first, the discontinued one as a fallback so
# historical dates can still be back-tested.
DATASETS: list[dict] = [
    {"name": "DayAheadPrices",
     "time": ("TimeUTC", "HourUTC"),
     "price": ("DayAheadPriceDKK", "SpotPriceDKK")},
    {"name": "Elspotprices",
     "time": ("HourUTC", "TimeUTC"),
     "price": ("SpotPriceDKK", "DayAheadPriceDKK")},
]


def _headers() -> dict:
    headers = {"User-Agent": USER_AGENT}
    # Optional: a free key from energidataservice.dk lifts the very tight anonymous
    # rate limit. Export ENERGIDATA_API_KEY (or set it as a repository secret).
    key = os.environ.get("ENERGIDATA_API_KEY", "").strip()
    if key:
        headers["X-Api-Key"] = key
    return headers


def _cache_path(cache_dir: str, dataset: str, area: str, start: str, end: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{dataset}_{area}_{start}_{end}.json")


def _http_json(url: str, tries: int = 4) -> dict:
    last_err = None
    for _ in range(tries):
        req = urllib.request.Request(url, headers=_headers())
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            last_err = f"HTTP {exc.code}: {body[:200]}"
            if exc.code == 429:
                wait = 120
                m = re.search(r"(\d+)\s*second", body)
                if m:
                    wait = min(int(m.group(1)) + 10, 320)
                print(f"    rate limited -> sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(last_err)
        except Exception as exc:  # timeouts, DNS, ...
            last_err = repr(exc)
            time.sleep(15)
    raise RuntimeError(f"giving up on {url}: {last_err}")


def _dataset_spec(name: str) -> dict:
    for spec in DATASETS:
        if spec["name"] == name:
            return spec
    return DATASETS[0]


def fetch_records(area: str, start: str, end: str, cache_dir: str = ".cache",
                  refresh: bool = False, dataset: str = "DayAheadPrices") -> dict:
    """Raw API payload for [start, end) (dates as YYYY-MM-DD, UTC based)."""
    path = _cache_path(cache_dir, dataset, area, start, end)
    if os.path.exists(path) and not refresh:
        with open(path) as fh:
            return json.load(fh)
    # Sort on the dataset's own time column (they differ) and ask for enough rows: at
    # quarter-hour resolution a year-long window is meaningless, and a small limit would
    # silently truncate the series before it reaches today.
    query = urllib.parse.urlencode({
        "offset": 0,
        "start": start,
        "end": end,
        "filter": json.dumps({"PriceArea": [area]}),
        "sort": f"{_dataset_spec(dataset)['time'][0]} ASC",
        "limit": 400,
    })
    payload = _http_json(f"{API}{dataset}?{query}")
    with open(path, "w") as fh:
        json.dump(payload, fh)
    return payload


def _first_present(record: dict, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in record:
            return name
    return None


def time_field(records: list[dict]) -> str | None:
    if not records:
        return None
    for spec in DATASETS:
        found = _first_present(records[0], spec["time"])
        if found:
            return found
    return None


def price_field(records: list[dict]) -> str | None:
    """Which column holds the DKK price in this payload."""
    if not records:
        return None
    for spec in DATASETS:
        found = _first_present(records[0], spec["price"])
        if found:
            return found
    for key in records[0]:
        if key.lower().endswith("dkk"):
            return key
    return None


def _price_by_local_hour(records: list[dict], day: dt.date, area: str) -> dict[int, float]:
    """
    {local hour -> DKK/kWh excl. moms} for one local calendar day.

    DayAheadPrices is a QUARTER-HOURLY dataset: every local hour has four records and the
    hourly price is their MEAN. Sampling a single quarter instead is a real error, not a
    rounding detail — in the ramp hours it differs from the hour average by up to ~45 øre/kWh,
    and it silently disagrees with the Home Assistant integration, which averages the four.
    The discontinued Elspotprices dataset is hourly, where one record is its own mean.
    """
    tfield = time_field(records)
    pfield = price_field(records)
    if not tfield or not pfield:
        return {}
    buckets: dict[int, list[float]] = {}
    for rec in records:
        if rec.get("PriceArea") != area:
            continue
        raw_hour = rec.get(tfield)
        raw_price = rec.get(pfield)
        if raw_hour is None or raw_price is None:
            continue
        try:
            utc = dt.datetime.fromisoformat(str(raw_hour)).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        local = utc.astimezone(TZ)
        if local.date() == day:
            buckets.setdefault(local.hour, []).append(float(raw_price) / 1000.0)  # DKK/MWh
    return {h: round(sum(values) / len(values), 6) for h, values in buckets.items()}


def day_prices(area: str, day: dt.date, cache_dir: str = ".cache",
               refresh: bool = False) -> tuple[list[dict], bool, str | None]:
    """
    Return (entries, complete, dataset) where entries is
    [{'hour': 'HH:00', 'price': kr/kWh excl. moms}, ...] ordered by local hour, and the
    price is the MEAN of that hour's sub-hourly records. complete is True when all 24
    hours are present.
    """
    start = (day - dt.timedelta(days=1)).isoformat()
    end = (day + dt.timedelta(days=2)).isoformat()
    for spec in DATASETS:
        payload = fetch_records(area, start, end, cache_dir=cache_dir, refresh=refresh,
                                dataset=spec["name"])
        hours = _price_by_local_hour(payload.get("records") or [], day, area)
        if hours:
            entries = [{"hour": f"{h:02d}:00", "price": hours[h]} for h in sorted(hours)]
            return entries, len(hours) == 24, spec["name"]
    return [], False, None


def today_local() -> dt.date:
    return dt.datetime.now(TZ).date()
