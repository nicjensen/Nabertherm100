#!/usr/bin/env python3
"""
PARITY TEST — proves the ported calculation matches the original Home Assistant card.

Renders reference_card.jinja (a verbatim copy of Nick's markdown card) with a stubbed
state_attr(), renders kiln_calc.render_card_markdown() on the SAME price arrays, and
compares every cell of every row. If they ever diverge, the site is showing different
numbers than the dashboard and this fails.
"""
from __future__ import annotations

import json
import os
import random
import sys

from jinja2 import Environment

import kiln_calc

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(HERE, "reference_card.jinja")


def _ha_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def render_reference(prices_today, prices_tom, tomorrow_valid) -> list[str]:
    """Render the real HA card with stubbed sensor attributes; return its table rows."""
    env = Environment(trim_blocks=False, lstrip_blocks=False)
    env.filters["bool"] = _ha_bool
    attrs = {
        "raw_today": [{"price": p} for p in prices_today],
        "raw_tomorrow": [{"price": p} for p in prices_tom] if prices_tom is not None else None,
        "tomorrow_valid": tomorrow_valid,
    }
    env.globals["state_attr"] = lambda entity, name: attrs.get(name)
    with open(REFERENCE) as fh:
        template = env.from_string(fh.read())
    out = template.render()

    rows = []
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "**" not in stripped or ":" not in stripped:
            continue
        parts = [c.strip() for c in stripped.strip("|").split("|")]
        if len(parts) != 5:
            continue
        if not parts[0].startswith("**"):
            continue
        rows.append(parts)
    return rows


def cells_of(lines: list[str]) -> list[list[str]]:
    return [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]


def check(name: str, prices_today, prices_tom, tomorrow_valid) -> bool:
    ref = render_reference(prices_today, prices_tom, tomorrow_valid)
    mine = cells_of(kiln_calc.render_card_markdown(prices_today, prices_tom, tomorrow_valid))
    ref = [r for r in ref]
    if len(ref) != len(mine):
        print(f"  FAIL {name}: row count {len(ref)} vs {len(mine)}")
        return False
    for i, (a, b) in enumerate(zip(ref, mine)):
        if [c.replace(" ", "") for c in a] != [c.replace(" ", "") for c in b]:
            print(f"  FAIL {name}: row {i} ({a[0]})")
            print(f"        card: {a}")
            print(f"        port: {b}")
            return False
    print(f"  ok   {name}: {len(mine)} rows identical")
    return True


def main() -> int:
    if not os.path.exists(REFERENCE):
        print("reference_card.jinja missing — run _copy_reference.py first")
        return 2
    rng = random.Random(20261006)

    scenarios = [
        ("random day + valid tomorrow", [round(rng.uniform(-0.1, 1.9), 3) for _ in range(24)],
         [round(rng.uniform(-0.1, 1.9), 3) for _ in range(24)], True),
        ("random day, tomorrow not published", [round(rng.uniform(0.0, 2.5), 3) for _ in range(24)],
         [round(rng.uniform(0.0, 2.5), 3) for _ in range(24)], False),
        ("short today array (20 h)", [round(rng.uniform(0.2, 1.5), 3) for _ in range(20)],
         [round(rng.uniform(0.2, 1.5), 3) for _ in range(24)], True),
        ("all hours identical (ties)", [0.75] * 24, [0.75] * 24, True),
        ("many ties (two price levels)", [0.4 if i % 2 else 1.1 for i in range(24)],
         [0.4 if i % 3 else 1.1 for i in range(24)], True),
        ("negative prices", [round(rng.uniform(-0.6, 0.3), 3) for _ in range(24)],
         [round(rng.uniform(-0.6, 0.3), 3) for _ in range(24)], True),
        ("empty tomorrow list, flag true", [round(rng.uniform(0.1, 1.0), 3) for _ in range(24)], [], True),
    ]

    cache = os.path.join(HERE, ".cache")
    real = sorted(f for f in os.listdir(cache)) if os.path.isdir(cache) else []
    if real:
        with open(os.path.join(cache, real[0])) as fh:
            payload = json.load(fh)
        import datetime as dt
        from fetch_prices import _price_by_local_hour, TZ
        from zoneinfo import ZoneInfo
        records = payload.get("records") or []
        if records:
            days = sorted({dt.datetime.fromisoformat(r["HourUTC"]).replace(
                tzinfo=dt.timezone.utc).astimezone(TZ).date() for r in records})
            if len(days) >= 2:
                d0, d1 = days[1], days[2] if len(days) > 2 else days[1]
                p0 = [(_price_by_local_hour(records, d0, payload.get("records")[0]["PriceArea"])).get(h)
                      for h in range(24)]
                p1 = [(_price_by_local_hour(records, d1, payload.get("records")[0]["PriceArea"])).get(h)
                      for h in range(24)]
                if all(v is not None for v in p0) and all(v is not None for v in p1):
                    scenarios.append((f"real API data {d0}", p0, p1, True))

    ok = True
    for name, p_today, p_tom, valid in scenarios:
        ok &= check(name, p_today, p_tom, valid)
    print("\nPARITY", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
