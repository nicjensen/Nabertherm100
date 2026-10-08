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
import hashlib
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


def payload_signature(payload: dict) -> str:
    """A fingerprint of the price payload — everything except the timestamp."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve_stamp(out_dir: str, area: str, payload: dict, now_local: dt.datetime):
    """The timestamp to stamp on this build, plus whether it was carried over.

    New prices must stamp a new time; an unchanged payload must keep the previous one, so that
    running the build more often than the prices change rewrites nothing and commits nothing.
    """
    path = os.path.join(out_dir, f"prices-{area.lower()}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            previous = json.load(fh)
        previous_stamp = dt.datetime.fromisoformat(previous.pop("generated_at"))
    except (OSError, ValueError, KeyError, TypeError):
        return now_local.replace(microsecond=0), False      # no usable previous build
    if payload_signature(previous) == payload_signature(payload):
        return previous_stamp, True
    return now_local.replace(microsecond=0), False


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


def hero_tile(key: str, prog: str, best_today: dict | None, best_tom: dict | None) -> str:
    """One recommendation tile, carrying both days: today's optimum and tomorrow's (a dash until
    the afternoon publication fills it in). The browser re-renders both rows from the embedded
    data once an optimum's hour has passed or the day rolls over."""
    def row(label: str, day: str, best: dict | None) -> str:
        if best is None:
            inner = '<span class="v dash">–</span><span class="h"></span>'
        else:
            inner = (f'<span class="v">{best["value"]:.0f}<span>kr</span></span>'
                     f'<span class="h">kl. {best["hour"]}</span>')
        return f'<div class="drow" data-day="{day}"><span class="d">{label}</span>{inner}</div>'

    return (f'<div class="hero-tile" data-key="{key}" data-prog="{prog}">'
            f'<p class="n">{prog}</p>'
            + row("I dag", "today", best_today)
            + row("I morgen", "tomorrow", best_tom)
            + "</div>")


def row_html(row: dict) -> str:
    def cell(key: str) -> str:
        c = row[key]
        # day/programme ride along so the browser can shift a whole column on the day rollover
        day = "today" if key.endswith("today") else "tomorrow"
        prog = "biscuit" if key.startswith("b") else "glaze"
        attrs = f'data-day="{day}" data-prog="{prog}"'
        if c is None:
            return f'<td class="v dash" {attrs}>–</td>'
        mark = f' {c["mark"]}' if c["mark"] else ""
        return f'<td class="v{mark}" {attrs}>{c["value"]:.0f}</td>'

    return (f'    <tr data-hour="{row["hour"]}"><th scope="row">{row["hour"]}</th>'
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

    hero = "".join([
        hero_tile("b", "Forglødning", data["best"]["b_today"], data["best"]["b_tom"]),
        hero_tile("g", "Glasur", data["best"]["g_today"], data["best"]["g_tom"]),
    ])

    # Everything the browser needs to decide whether a "today" optimum has already passed,
    # and (in "remaining" mode) which start hours are still available.
    def _series(key: str) -> list[list[int]]:
        return [[int(r["hour"][:2]), r[key]["value"]]
                for r in data["rows"] if r[key] is not None]

    def _cheap(*keys: str) -> dict:
        out = {}
        for key in keys:
            best = (data["best"] or {}).get(key)
            out[key] = {"hour": best["hour"], "value": best["value"]} if best else None
        return out

    kpi_json = {
        "date": today.isoformat(),
        "past": cfg.get("kpi_past", "hide"),
        # tomorrow's series is stored under the *today* keys, so a client-side rollover is a
        # plain swap of the two objects rather than a remapping of keys
        "today": {"b_today": _series("b_today"), "g_today": _series("g_today")},
        "tomorrow": {"b_today": _series("b_tom"), "g_today": _series("g_tom")},
        # the tiles are re-rendered in the browser, so it needs both days' optima and the sizes
        "cheapest": _cheap("b_today", "g_today", "b_tom", "g_tom"),
        "kwh": {"b": round(sum(kiln_calc.C_BISC), 1), "g": round(sum(kiln_calc.C_GLAZE), 1)},
    }

    alert = ""
    if not complete_today:
        alert = (f'<div class="alert">⚠️ Kun {len(hours_today)} af 24 timer fundet for i dag '
                 f'({today:%d-%m-%Y}) i prisdata for {area}. Tabellen nedenfor er ufuldstændig.</div>')

    if complete_tomorrow:
        note = "✅ Priser for i morgen er offentliggjort. Nye priser offentliggøres dagligt ca. kl. 13:00."
    else:
        note = cfg.get("tomorrow_note", "Priser i morgen opdateres kl 13:00")

    now_local = dt.datetime.now(TZ)

    # Everything that changes when new prices arrive — the timestamp is deliberately absent.
    # Two runs over the same prices must produce byte-identical files, or a schedule that runs
    # more often than the prices change would commit a new timestamp every single time.
    payload = {
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
    stamp, reused = resolve_stamp(args.out, area, payload, now_local)
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

    tom_pill = ('<span class="pill ok">offentliggjort</span>' if complete_tomorrow
                else '<span class="pill">kl. 13:00</span>')
    tom_note = ("Morgendagens 24 timer står i tabellen med –, og de fyldes ud, så snart "
                "priserne offentliggøres ca. kl. 13:00.")

    area_links = cfg.get("areas", [area])
    html = open(os.path.join(HERE, "template.html")).read()
    for token, value in {
        "{{TITLE}}": cfg["title"],
        "{{SUBTITLE}}": cfg.get("subtitle", ""),
        "{{UPDATED}}": stamp.strftime("%d-%m-%Y kl. %H:%M"),
        "{{AREA}}": area,
        "{{DSO_NAME}}": (dso + " Elnet") if dso else "spotpris uden nettarif",
        "{{AREA_TOGGLE}}": area_toggle(area_links, area),
        "{{ALERT}}": alert,
        "{{KPI}}": hero,
        "{{ROWS}}": "\n".join(rows),
        "{{TODAY_DATE}}": today.strftime("%d-%m-%Y"),
        "{{TOMORROW_DATE}}": tomorrow.strftime("%d-%m-%Y"),
        "{{TOM_PILL}}": tom_pill,
        "{{TOM_NOTE}}": tom_note,
        "{{TOM_NOTE_HIDDEN}}": "" if not complete_tomorrow else " hidden",
        "{{PROFILE_NOTE}}": profile,
        "{{BASIS_NOTE}}": basis,
        "{{BUILD_DATE}}": today.isoformat(),
        "{{KPI_JSON}}": json.dumps(kpi_json, ensure_ascii=False).replace("</", "<\\/"),
    }.items():
        html = html.replace(token, value)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"{area.lower()}.html"), "w") as fh:
        fh.write(html)

    snapshot = {"generated_at": stamp.isoformat(timespec="seconds"), **payload}
    with open(os.path.join(args.out, f"prices-{area.lower()}.json"), "w") as fh:
        json.dump(snapshot, fh, indent=2, ensure_ascii=False)

    print(f"[{area}] {len(hours_today)}/24 hours today, {len(hours_tomorrow)}/24 tomorrow "
          f"(dataset {dataset}, nettarif {dso or 'none'})")
    print(f"   timestamp {'carried over (prices unchanged)' if reused else 'set to now'}: "
          f"{stamp.strftime('%d-%m-%Y %H:%M')}")
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
