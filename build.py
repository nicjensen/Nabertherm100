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
from fetch_prices import TZ, _price_by_local_hour, fetch_records, today_local

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def dkk(value: int | None) -> str:
    return "–" if value is None else f"{value:,} kr.".replace(",", ".")


def fetch_two_days(area: str, today: dt.date, cache_dir: str, refresh: bool):
    """One API window per area, sliced into local days. Keeps us inside the rate limit."""
    start = (today - dt.timedelta(days=1)).isoformat()
    end = (today + dt.timedelta(days=3)).isoformat()
    payload = fetch_records(area, start, end, cache_dir=cache_dir, refresh=refresh)
    records = payload.get("records") or []

    def day(day_value: dt.date) -> list[tuple[str, float]]:
        hours = _price_by_local_hour(records, day_value, area)
        return [(f"{h:02d}:00", hours[h]) for h in sorted(hours)]

    return day(today), day(today + dt.timedelta(days=1))


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


def row_html(row: dict, spot: tuple[str, float] | None) -> str:
    def cell(key: str) -> str:
        c = row[key]
        if c is None:
            return '<td class="na">–</td>'
        cls = f' class="{c["mark"]}"' if c["mark"] else ""
        body = f'<strong>{dkk(c["value"])}</strong>' if c["mark"] else dkk(c["value"])
        return f"<td{cls}>{body}</td>"

    spot_cell = (f'<td class="spot">{spot[1]:.2f}</td>'.replace(".", ",")
                 if spot else '<td class="na">–</td>')
    return (f'    <tr><th scope="row">{row["hour"]}</th>{spot_cell}'
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
    hours_today, hours_tomorrow = fetch_two_days(area, today, args.cache, args.refresh)
    complete_today = len(hours_today) == 24
    complete_tomorrow = len(hours_tomorrow) == 24

    data = kiln_calc.compute(
        [p for _, p in hours_today],
        [p for _, p in hours_tomorrow],
        complete_tomorrow,
        hours=cfg.get("hours_shown", 24),
        tariff_dkk_per_kwh=cfg.get("tariff_dkk_per_kwh", 0.0),
        vat_percent=cfg.get("vat_percent", 0.0),
    )

    spot_map = dict(hours_today)
    rows = [row_html(r, (r["hour"], spot_map[r["hour"]]) if r["hour"] in spot_map else None)
            for r in data["rows"]]

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
    basis_bits = [f"spotpris i DKK/kWh (Nord Pool, {area})"]
    if cfg.get("tariff_dkk_per_kwh"):
        basis_bits.append(f"tillæg {cfg['tariff_dkk_per_kwh']:.3f} kr./kWh")
    if cfg.get("vat_percent"):
        basis_bits.append(f"moms {cfg['vat_percent']:.0f} %")
    basis = ("Prisgrundlag: " + " + ".join(basis_bits) + ". "
             "Elafgift og nettarif er ikke medtaget, med mindre der er sat tillæg i config.json.")

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
        "spot_hours_today": data["hours_today"],
        "spot_hours_tomorrow": data["hours_tomorrow"],
        "rows": data["rows"],
        "cheapest": data["best"],
        "price_basis": {"tariff_dkk_per_kwh": cfg.get("tariff_dkk_per_kwh", 0.0),
                        "vat_percent": cfg.get("vat_percent", 0.0)},
    }
    with open(os.path.join(args.out, f"prices-{area.lower()}.json"), "w") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False)

    print(f"[{area}] {len(hours_today)}/24 hours today, {len(hours_tomorrow)}/24 tomorrow")
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
