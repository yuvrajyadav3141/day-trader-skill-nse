#!/usr/bin/env python3
"""NSE's daily price file for every stock (the "bhavcopy"), cached on disk. Standard library only.

    python3 bhav.py sync --days 260        # download what is missing -> trader/cache/bhav/
    python3 bhav.py status

One official file a trading day holds open, high, low, close, volume, turnover and the DELIVERY
percentage of every NSE security:
  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
No key, no login. A weekend answers 404. A holiday can answer with the previous session's file,
so files are stored under the date INSIDE them and never twice.

Prices are NOT adjusted for splits and bonuses. A one-day fall of more than 35 % with no lower
circuit that deep is almost always a split or a bonus: history() marks the symbol `ca_suspect`
and callers leave it out of signals instead of guessing an adjustment.
"""

import argparse
import csv
import datetime
import io
import os
import sys
import time
import urllib.error
import urllib.request

UA = "day-trader-skills-nse/1.0 (personal research tool)"   # NSE's CDN drops a User-Agent that carries a URL
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_%s.csv"
CACHE = os.path.join("trader", "cache", "bhav")
PAUSE = 0.4
SERIES = ("EQ",)
CA_DROP = 0.35


class BhavError(Exception):
    pass


def _fetch(day):
    req = urllib.request.Request(URL % day.strftime("%d%m%Y"), headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        if code == 404:
            return None
        raise BhavError("NSE answered HTTP %d for the %s price file" % (code, day))
    except (urllib.error.URLError, OSError) as e:
        raise BhavError("could not reach NSE: %s" % getattr(e, "reason", e))


def parse(text):
    """One file -> (date, {SYMBOL: row}) for the EQ series. Row: o h l c prev v turnover_lacs deliv_pct."""
    rows, day = {}, None
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if r.get("SERIES") not in SERIES:
            continue
        try:
            day = day or datetime.datetime.strptime(r["DATE1"], "%d-%b-%Y").date()
            rows[r["SYMBOL"].upper()] = {
                "o": float(r["OPEN_PRICE"]), "h": float(r["HIGH_PRICE"]), "l": float(r["LOW_PRICE"]),
                "c": float(r["CLOSE_PRICE"]), "prev": float(r["PREV_CLOSE"]), "v": int(float(r["TTL_TRD_QNTY"])),
                "turnover_lacs": float(r["TURNOVER_LACS"]),
                "deliv_pct": float(r["DELIV_PER"]) if r.get("DELIV_PER") not in ("", "-", None) else None}
        except (KeyError, ValueError):
            continue
    if day is None or not rows:
        raise BhavError("not an NSE full bhavcopy file")
    return day, rows


def cached_days(cache=CACHE):
    if not os.path.isdir(cache):
        return []
    return sorted(datetime.date.fromisoformat(f[:-4]) for f in os.listdir(cache)
                  if f.endswith(".csv") and len(f) == 14)


def sync(days=260, cache=CACHE, today=None, say=None, sleep=time.sleep):
    """Make sure the last `days` sessions are cached. Returns (new files, sessions cached)."""
    today = today or (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).date()
    os.makedirs(cache, exist_ok=True)
    have = set(cached_days(cache))
    tried_path = os.path.join(cache, "no_file.txt")      # dates NSE has no file for (holidays): not asked again
    tried = set()
    if os.path.exists(tried_path):
        with open(tried_path) as fh:
            tried = {l.strip() for l in fh if l.strip()}
    new, d, guard = 0, today, 0
    while len(have) < days and guard < days * 2 + 30:
        guard += 1
        if d.weekday() < 5 and d not in have and d.isoformat() not in tried:
            text = _fetch(d)
            sleep(PAUSE)
            got = None
            if text:
                try:
                    got, _ = parse(text)
                except BhavError:
                    got = None
            if got and got not in have:
                with open(os.path.join(cache, got.isoformat() + ".csv"), "w", encoding="utf-8") as fh:
                    fh.write(text)
                have.add(got)
                new += 1
                if say:
                    say("  %s (%d cached)" % (got, len(have)))
            if got != d and d != today:                  # today's file appears in the evening: ask again later
                tried.add(d.isoformat())
        d -= datetime.timedelta(days=1)
    with open(tried_path, "w") as fh:
        fh.write("\n".join(sorted(tried)) + "\n")
    return new, len(have)


def history(days=260, cache=CACHE, until=None):
    """-> (dates oldest first, {SYMBOL: {"bars": [row or None per date], "ca_suspect": bool}})."""
    dates = [d for d in cached_days(cache) if until is None or d <= until][-days:]
    if not dates:
        raise BhavError("no price files cached: run bhav.py sync first")
    out = {}
    for i, d in enumerate(dates):
        with open(os.path.join(cache, d.isoformat() + ".csv"), encoding="utf-8") as fh:
            _, rows = parse(fh.read())
        for sym, row in rows.items():
            out.setdefault(sym, {"bars": [None] * len(dates), "ca_suspect": False})["bars"][i] = row
    for s in out.values():
        for b in s["bars"]:
            if b and b["prev"] > 0 and b["o"] < b["prev"] * (1 - CA_DROP):
                s["ca_suspect"] = True
        closes = [b["c"] for b in s["bars"] if b]
        for a, b in zip(closes, closes[1:]):
            if b < a * (1 - CA_DROP):
                s["ca_suspect"] = True
    return dates, out


def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE daily price files, cached.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("sync")
    p.add_argument("--days", type=int, default=260)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "sync":
            new, n = sync(a.days, say=lambda m: print(m, file=sys.stderr))
            ds = cached_days()
            print("%d new file(s). %d sessions cached, %s to %s." % (new, n, ds[0], ds[-1]))
            return 0
        if a.cmd == "status":
            ds = cached_days()
            print("%d sessions cached%s." % (len(ds), (", %s to %s" % (ds[0], ds[-1])) if ds else ""))
            return 0 if ds else 1
    except BhavError as e:
        print("bhav.py: %s" % e, file=sys.stderr)
        return 1
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
