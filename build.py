#!/usr/bin/env python3
"""
Build the static GitHub Pages site from live Danish spot prices.

    python3 build.py                 # today + tomorrow, writes docs/index.html
    python3 build.py --date 2026-10-06
    python3 build.py --refresh       # ignore the disk cache

One page per price area in config.json ("areas"), so the correct area can be
identified by comparing against the Home Assistant dashboard.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import kiln_calc
import tariffs
from fetch_prices import (DATASETS, TZ, _price_by_local_hour, fetch_records, today_local)

HERE = os.path.dirname(os.path.abspath(__file__))

# The largest household grid company in each price area, used when the config does
# not name one for that area.
DEFAULT_DSO = {"DK1": "N1", "DK2": "Radius"}


def load_config(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def dkk(value: int | None) -> str:
    return "–" if value is None else f"{value:,} kr.".replace(",", ".")


def dso_for_area(cfg: dict, area: str) -> str | None:
    """Which grid company's nettarif applies to this area (None = no tariffs)."""
    nettarif = cfg.get("nettarif") or {}
    if not nettarif.get("enabled", False):
        return None
    by_area = nettarif.get("selskab_by_area") or {}
    dso = by_area.get(area)
    if not dso and area == cfg.get("area"):
        dso = nettarif.get("selskab")
    dso = dso or DEFAULT_DSO.get(area)
    if dso and dso not in tariffs.DSO_TARIFFS:
        raise SystemExit(f"unknown grid company {dso!r}; known: {sorted(tariffs.DSO_TARIFFS)}")
    return dso


def fetch_two_days(area: str, today: dt.date, cache_dir: str, refresh: bool):
    """One API window per area, sliced into local days. Keeps us inside the rate limit."""
    start = (today - dt.timedelta(days=1)).isoformat()
    end = (today + dt.timedelta(days=3)).isoformat()
    tomorrow = today + dt.timedelta(days=1)

    def day(records, day_value) -> list[tuple[str, float]]:
        hours = _price_by_local_hour(records, day_value, area)
        return [(f"{h:02d}:00", hours[h]) for h in sorted(hours)]

    for spec in DATASETS:                        # DayAheadPrices, then the old dataset
        payload = fetch_records(area, start, end, cache_dir=cache_dir, refresh=refresh,
                                dataset=spec["name"])
        records = payload.get("records") or []
        if day(records, today) or day(records, tomorrow):
            return day(records, today), day(records, tomorrow), spec["name"]
    return [], [], None


def kpi_html(label: str, best: dict | None, coeffs: list[float], pending: bool) -> str:
    if pending:
        return (f'<div class="kpi pending"><div class="k">{label}</div>'
                f'<div class="h">Priser ikke offentliggjort endnu</div>'
                f'<div class="v">offentliggøres kl. 13:00</div></div>')
    if best is None:
        return (f'<div class="kpi pending"><div class="k">{label}</div>'
                f'<div class="h">Ingen data</div><div class="v">–</div></div>')
    kwh = sum(coeffs)
    return (f'<div class="kpi"><div class="k">{label}</div>'
            f'<div class="h">{best["hour"]}</div>'
            f'<div class="v">{dkk(best["value"])} · {kwh:.1f} kWh</div></div>')


def row_html(row: dict) -> str:
    def cell(key: str) -> str:
        c = row[key]
        if c is None:
            return '<td class="na">–</td>'
        cls = f' class="{c["mark"]}"' if c["mark"] else ""
        body = f'<strong>{dkk(c["value"])}</strong>' if c["mark"] else dkk(c["value"])
        return f"<td{cls}>{body}</td>"

    return (f'    <tr><th scope="row">{row["hour"]}</th>'
            + cell("b_today") + cell("g_today") + cell("b_tom") + cell("g_tom")
            + "</tr>")


def area_toggle(areas: list[str], current: str) -> str:
    if len(areas) < 2:
        return ""
    links = []
    for a in areas:
        label = {"DK1": "DK1 · Jylland/Fyn", "DK2": "DK2 · Sjælland"}.get(a, a)
        if a == current:
            links.append(f'<span class="badge"><b>{label} ✓</b></span>')
        else:
            links.append(f'<a class="badge" href="{a.lower()}.html">{label}</a>')
    return '<div class="meta">Prisområde: ' + " ".join(links) + "</div>"


def build_area(area: str, cfg: dict, today: dt.date, args) -> dict:
    hours_today, hours_tomorrow, dataset = fetch_two_days(area, today, args.cache, args.refresh)
    complete_today = len(hours_today) == 24
    complete_tomorrow = len(hours_tomorrow) == 24

    dso = dso_for_area(cfg, area)
    tomorrow = today + dt.timedelta(days=1)
    snapshot = tariffs.load_snapshot()      # official DataHub rates when available

    def price_series(hours: list[tuple[str, float]], day: dt.date) -> list[float]:
        """Spot only, or the all-in price incl. nettarif, Energinet, elafgift and moms."""
        if not hours:
            return []
        if dso:
            return tariffs.all_in_prices(
                [{"hour": h, "price": p} for h, p in hours], day, dso, snapshot)
        return [p for _, p in hours]

    prices_today = price_series(hours_today, today)
    prices_tomorrow = price_series(hours_tomorrow, tomorrow)

    data = kiln_calc.compute(
        prices_today,
        prices_tomorrow,
        complete_tomorrow,
        hours=cfg.get("hours_shown", 24),
        labels_today=[h for h, _ in hours_today],
        labels_tomorrow=[h for h, _ in hours_tomorrow] or None,
    )

    rows = [row_html(r) for r in data["rows"]]

    kpi = "".join([
        kpi_html("I dag · Forglødning", data["best"]["b_today"], kiln_calc.C_BISC, not complete_today),
        kpi_html("I dag · Glasur", data["best"]["g_today"], kiln_calc.C_GLAZE, not complete_today),
        kpi_html("I morgen · Forglødning", data["best"]["b_tom"], kiln_calc.C_BISC, not complete_tomorrow),
        kpi_html("I morgen · Glasur", data["best"]["g_tom"], kiln_calc.C_GLAZE, not complete_tomorrow),
    ])

    alert = ""
    if not complete_today:
        alert = (f'<div class="alert">⚠️ Kun {len(hours_today)} af 24 timer fundet for i dag '
                 f'({today:%d-%m-%Y}) i prisdata for {area}. Tabellen nedenfor er ufuldstændig.</div>')

    if complete_tomorrow:
        note = "✅ Priser for i morgen er offentliggjort. Nye priser offentliggøres dagligt ca. kl. 13:00."
    else:
        note = cfg.get("tomorrow_note", "Priser i morgen opdateres kl 13:00")

    now_local = dt.datetime.now(TZ)
    if dso:
        basis = tariffs.describe(dso, snapshot, day=today) + (
            " Faste abonnementer (netabonnement, systemabonnement og "
            "elselskabets månedsgebyr) er ikke medregnet, fordi de ikke "
            "afhænger af, hvornår ovnen startes.")
    else:
        basis = ("Prisgrundlag: spotpris i DKK/kWh (Nord Pool) uden nettarif, afgifter og moms — "
                 "sæt \"nettarif\": {\"enabled\": true} i config.json for at regne dem med.")

    profile = (f"Programmer: Forglødning {len(kiln_calc.C_BISC)} timer / "
               f"{sum(kiln_calc.C_BISC):.1f} kWh · Glasur {len(kiln_calc.C_GLAZE)} timer / "
               f"{sum(kiln_calc.C_GLAZE):.1f} kWh. Beløbet pr. række er summen af "
               f"timepris × forbrug for hele brændingen — en brænding der starter om aftenen "
               f"prissættes med næste dags priser efter midnat.")

    area_links = cfg.get("areas", [area])
    html = open(os.path.join(HERE, "template.html")).read()
    for token, value in {
        "{{TITLE}}": cfg["title"],
        "{{SUBTITLE}}": cfg.get("subtitle", ""),
        "{{UPDATED}}": now_local.strftime("%d-%m-%Y kl. %H:%M"),
        "{{AREA}}": area,
        "{{AREA_TOGGLE}}": area_toggle(area_links, area),
        "{{ALERT}}": alert,
        "{{TOMORROW_NOTE}}": note,
        "{{KPI}}": kpi,
        "{{ROWS}}": "\n".join(rows),
        "{{PROFILE_NOTE}}": profile,
        "{{BASIS_NOTE}}": basis,
        "{{RAW_LINK}}": "prices.json" if area == cfg["area"] else f"prices-{area.lower()}.json",
    }.items():
        html = html.replace(token, value)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"{area.lower()}.html"), "w") as fh:
        fh.write(html)

    snapshot = {
        "generated_at": now_local.isoformat(timespec="seconds"),
        "area": area,
        "date": today.isoformat(),
        "price_dataset": dataset,
        "nettarif_selskab": dso,
        "spot_hours_today": [{"hour": h, "price": p} for h, p in hours_today],
        "spot_hours_tomorrow": [{"hour": h, "price": p} for h, p in hours_tomorrow],
        "all_in_hours_today": data["hours_today"],
        "all_in_hours_tomorrow": data["hours_tomorrow"],
        "rows": data["rows"],
        "cheapest": data["best"],
        "price_basis": tariffs.composition() if dso else {"note": "spot only"},
    }
    with open(os.path.join(args.out, f"prices-{area.lower()}.json"), "w") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False)

    print(f"[{area}] {len(hours_today)}/24 hours today, {len(hours_tomorrow)}/24 tomorrow "
          f"(dataset {dataset}, nettarif {dso or 'none'})")
    for label, key in (("biscuit today", "b_today"), ("glaze today", "g_today"),
                       ("biscuit tomorrow", "b_tom"), ("glaze tomorrow", "g_tom")):
        best = data["best"][key]
        print(f"   cheapest {label:18s}: " + (f"{best['hour']} -> {best['value']} kr." if best else "n/a"))
    return {"html": html, "snapshot": snapshot}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "docs"))
    ap.add_argument("--cache", default=os.path.join(HERE, ".cache"))
    ap.add_argument("--date", help="reference 'today' (YYYY-MM-DD), default: today in Copenhagen")
    ap.add_argument("--refresh", action="store_true", help="bypass the disk cache")
    args = ap.parse_args()

    cfg = load_config(args.config)
    default_area = cfg["area"]
    areas = cfg.get("areas") or [default_area]
    if default_area not in areas:
        areas.insert(0, default_area)
    today = dt.date.fromisoformat(args.date) if args.date else today_local()

    print(f"building for {today} — areas: {', '.join(areas)}")
    results = {area: build_area(area, cfg, today, args) for area in areas}

    # The default area also answers at the site root.
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "index.html"), "w") as fh:
        fh.write(results[default_area]["html"])
    with open(os.path.join(args.out, "prices.json"), "w") as fh:
        json.dump(results[default_area]["snapshot"], fh, indent=2, ensure_ascii=False)

    print(f"wrote {args.out}/index.html (area {default_area})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
