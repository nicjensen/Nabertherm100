#!/usr/bin/env python3
"""
The kiln calculation, ported 1:1 from the Home Assistant markdown card.

Two firing programmes, each with its own hourly consumption profile (kWh per hour
of the programme). The cost of starting at hour i is  sum(price[i+h] * coeff[h]).

    Biscuit (Forglødning) : 13 hourly steps, total 29.69 kWh
    Glaze   (Glasur)      :  6 hourly steps, total 30.70 kWh

The port is kept honest by parity_test.py, which renders the original Jinja card
and this module against the same price arrays and compares every cell.
"""
from __future__ import annotations

C_BISC = [1.3, 1.5, 1.6, 1.85, 2, 2.2, 2.5, 2.82, 3, 3.1, 3.2, 3.4, 1.22]
C_GLAZE = [2.2, 2.8, 3.5, 7.15, 7.15, 6.2]

BEST, SECOND = "best", "second"


def _window_costs(prices: list[float], coeffs: list[float], limit: int) -> list[int]:
    """Cost in whole DKK for a start at each index 0..limit-1 (only where the window fits)."""
    out: list[int] = []
    for i in range(0, limit):
        if i + len(coeffs) <= len(prices):
            total = 0.0
            for h in range(0, len(coeffs)):
                total += prices[i + h] * coeffs[h]
            out.append(int(round(total)))
    return out


def _marks(costs: list[int]) -> dict[int, str]:
    """Cheapest value -> 'best', second cheapest distinct value -> 'second' (Jinja: unique|sort)."""
    if not costs:
        return {}
    ordered = sorted(set(costs))
    marked: dict[int, str] = {ordered[0]: BEST}
    if len(ordered) > 1:
        marked.setdefault(ordered[1], SECOND)
    return marked


def _series_to_rows(costs: list[int], marks: dict[int, str], hours: int) -> list[dict | None]:
    rows: list[dict | None] = []
    for i in range(hours):
        if i < len(costs):
            rows.append({"value": costs[i], "mark": marks.get(costs[i])})
        else:
            rows.append(None)
    return rows


def first_best_hour(rowlist: list[dict | None]) -> dict | None:
    for i, cell in enumerate(rowlist):
        if cell and cell["mark"] == BEST:
            return {"index": i, "hour": f"{i:02d}:00", "value": cell["value"]}
    return None


def _apply_price_basis(entries: list[dict], tariff: float, vat_percent: float) -> list[dict]:
    """Flat adder + VAT. A flat adder cannot change which window is cheapest."""
    factor = 1.0 + (vat_percent / 100.0)
    return [{"hour": e["hour"], "price": round((e["price"] + tariff) * factor, 6)} for e in entries]


def compute(prices_today: list[float], prices_tom: list[float], tomorrow_valid: bool,
            hours: int = 24,
            tariff_dkk_per_kwh: float = 0.0, vat_percent: float = 0.0) -> dict:
    """Everything the page needs. Mirrors the Jinja card's branching exactly."""
    today = [{"hour": f"{h:02d}:00", "price": p} for h, p in enumerate(prices_today)]
    tomorrow = [{"hour": f"{h:02d}:00", "price": p} for h, p in enumerate(prices_tom)]
    if tariff_dkk_per_kwh or vat_percent:
        today = _apply_price_basis(today, tariff_dkk_per_kwh, vat_percent)
        tomorrow = _apply_price_basis(tomorrow, tariff_dkk_per_kwh, vat_percent)

    p_today = [e["price"] for e in today]
    p_tom = [e["price"] for e in tomorrow]
    has_tomorrow = bool(tomorrow_valid and p_tom)

    # The card builds today's windows from today + tomorrow concatenated, so a firing
    # started late today is priced across midnight with tomorrow's real prices.
    combined = list(p_today) + (list(p_tom) if has_tomorrow else [])

    series = {
        "b_today": _window_costs(combined, C_BISC, len(p_today)),
        "g_today": _window_costs(combined, C_GLAZE, len(p_today)),
        "b_tom": _window_costs(p_tom, C_BISC, max(0, len(p_tom) - len(C_BISC) + 1)) if has_tomorrow else [],
        "g_tom": _window_costs(p_tom, C_GLAZE, max(0, len(p_tom) - len(C_GLAZE) + 1)) if has_tomorrow else [],
    }
    marks = {key: _marks(costs) for key, costs in series.items()}

    rows = []
    for i in range(hours):
        row = {"hour": f"{i:02d}:00"}
        for key in ("b_today", "g_today", "b_tom", "g_tom"):
            if key.endswith("_tom") and not has_tomorrow:
                row[key] = None
            elif i < len(series[key]):
                row[key] = {"value": series[key][i], "mark": marks[key].get(series[key][i])}
            else:
                row[key] = None
        rows.append(row)

    return {
        "rows": rows,
        "series": series,
        "hours_today": today,
        "hours_tomorrow": tomorrow if has_tomorrow else [],
        "tomorrow_valid": has_tomorrow,
        "best": {
            "b_today": first_best_hour(_series_to_rows(series["b_today"], marks["b_today"], hours)),
            "g_today": first_best_hour(_series_to_rows(series["g_today"], marks["g_today"], hours)),
            "b_tom": first_best_hour(_series_to_rows(series["b_tom"], marks["b_tom"], hours)),
            "g_tom": first_best_hour(_series_to_rows(series["g_tom"], marks["g_tom"], hours)),
        },
    }


# ---------------------------------------------------------------------------
#  Card-style markdown renderer — used ONLY by parity_test.py to compare
#  against the original Jinja card, character for character.
# ---------------------------------------------------------------------------
def render_card_markdown(prices_today: list[float], prices_tom: list[float],
                         tomorrow_valid: bool, hours: int = 24) -> list[str]:
    data = compute(prices_today, prices_tom, tomorrow_valid, hours=hours)
    lines = []
    for row in data["rows"]:
        cells = []
        for key in ("b_today", "g_today", "b_tom", "g_tom"):
            cell = row[key]
            if cell is None:
                cells.append("--")
            elif cell["mark"] == BEST:
                cells.append(f"🟢&nbsp;**{cell['value']}&nbsp;kr.**")
            elif cell["mark"] == SECOND:
                cells.append(f"🟡&nbsp;**{cell['value']}&nbsp;kr.**")
            else:
                cells.append(f"{cell['value']}&nbsp;kr.")
        lines.append(f"| **{row['hour']}** | " + " | ".join(cells) + " |")
    return lines
