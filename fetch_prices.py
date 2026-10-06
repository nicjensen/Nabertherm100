#!/usr/bin/env python3
"""
Fetch Danish day-ahead spot prices from Energi Data Service (the same source the
Home Assistant 'energi_data_service' integration uses).

SpotPriceDKK is quoted in DKK/MWh -> divided by 1000 to get DKK/kWh.

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

API = "https://api.energidataservice.dk/dataset/Elspotprices"
TZ = ZoneInfo("Europe/Copenhagen")
USER_AGENT = "kiln-price-site/1.0 (+github pages)"


def _headers() -> dict:
    headers = {"User-Agent": USER_AGENT}
    # Optional: a free key from energidataservice.dk lifts the very tight anonymous
    # rate limit. Export ENERGIDATA_API_KEY (or set it as a repository secret).
    key = os.environ.get("ENERGIDATA_API_KEY", "").strip()
    if key:
        headers["X-Api-Key"] = key
    return headers


def _cache_path(cache_dir: str, area: str, start: str, end: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{area}_{start}_{end}.json")


def _http_json(url: str, tries: int = 4) -> dict:
    last_err = None
    for _ in range(tries):
        req = urllib.request.Request(url, headers=_headers())
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            last_err = f"HTTP {exc.code}: {body[:160]}"
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


def fetch_records(area: str, start: str, end: str, cache_dir: str = ".cache",
                  refresh: bool = False) -> dict:
    """Raw API payload for [start, end) (dates as YYYY-MM-DD, UTC based)."""
    path = _cache_path(cache_dir, area, start, end)
    if os.path.exists(path) and not refresh:
        with open(path) as fh:
            return json.load(fh)
    query = urllib.parse.urlencode({
        "offset": 0,
        "start": start,
        "end": end,
        "filter": json.dumps({"PriceArea": [area]}),
        "sort": "HourUTC ASC",
        "limit": 200,
    })
    payload = _http_json(f"{API}?{query}")
    with open(path, "w") as fh:
        json.dump(payload, fh)
    return payload


def _price_by_local_hour(records: list[dict], day: dt.date, area: str) -> dict[int, float]:
    """{local hour -> DKK/kWh} for one local calendar day."""
    out: dict[int, float] = {}
    for rec in records:
        if rec.get("PriceArea") != area:
            continue
        raw_hour = rec.get("HourUTC")
        raw_price = rec.get("SpotPriceDKK")
        if raw_hour is None or raw_price is None:
            continue
        try:
            utc = dt.datetime.fromisoformat(str(raw_hour)).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        local = utc.astimezone(TZ)
        if local.date() == day:
            out[local.hour] = round(float(raw_price) / 1000.0, 6)  # DKK/MWh -> DKK/kWh
    return out


def day_prices(area: str, day: dt.date, cache_dir: str = ".cache",
               refresh: bool = False) -> tuple[list[dict], bool]:
    """
    Return (entries, complete) where entries is [{'hour': 'HH:00', 'price': kr/kWh}, ...]
    ordered by local hour, and complete is True when all 24 hours are present.
    Fetches a UTC window one day wider on each side so DST shifts cannot clip a day.
    """
    start = (day - dt.timedelta(days=1)).isoformat()
    end = (day + dt.timedelta(days=2)).isoformat()
    payload = fetch_records(area, start, end, cache_dir=cache_dir, refresh=refresh)
    hours = _price_by_local_hour(payload.get("records") or [], day, area)
    entries = [{"hour": f"{h:02d}:00", "price": hours[h]} for h in sorted(hours)]
    return entries, len(hours) == 24


def today_local() -> dt.date:
    return dt.datetime.now(TZ).date()
