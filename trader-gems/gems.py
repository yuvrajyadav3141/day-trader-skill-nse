#!/usr/bin/env python3
"""Small-company fundamentals screen for trader-gems. Standard library only.

    python3 gems.py fetch                          # annual numbers for every stock in trader/universe.txt (slow, once)
    python3 gems.py fetch --symbols KIOCL 20MICRONS
    python3 gems.py screen                         # the default screen, from what is cached
    python3 gems.py screen --max-mcap-cr 500 --max-debt-equity 0 --min-roe 15
    python3 gems.py show 20MICRONS                 # one company's numbers, year by year

What it reads: Yahoo Finance's fundamentals time series for SYMBOL.NS (annual balance sheet,
cash flow and income statement, up to four years; unofficial, free, no key). One request a
company, cached in trader/cache/fund/ for 14 days, so `fetch` for the whole NSE EQ list takes
one to two hours the first time (not timed precisely) and can be stopped and resumed.

The default screen (every number is adjustable):
  size          market value between 50 and 2,000 crore
  debt          total debt at most 10 % of shareholders' equity ("nearly debt free")
  cash flow     cash from operations positive in at least 3 of the last 4 years
  profit        a profit in the latest year
  growth        latest revenue above the earliest year's
Shown with each company: return on equity, price to earnings, price to book, net cash, and the
LAND on its books (Yahoo's "land and improvements") in crore and as a share of market value.

Read this before trusting a row:
  - Land is at BOOK COST, often decades old. It says a company owns land, not what the land is
    worth, and not whether it is free to sell. The annual report's property note says more.
  - "Debt free" on the last balance sheet date is not debt free today.
  - The screen cannot see promoter holding, pledged shares, auditor remarks, related-party deals
    or lawsuits. Those decide whether a cheap small company is a find or a trap. SKILL.md lists
    what to read before any money goes in.
  - Yahoo's numbers for small Indian companies have errors and gaps. A company with a missing
    field is left out and counted, not guessed.
  - Small stocks are thinly traded: the last column is the average rupees traded a day (from the
    NSE price files, if `swing.py sync` has been run). Under 1 crore, getting out can take days.
A screen is a list of companies that pass a filter. It is not a list of stocks to buy.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-data"))
import bhav  # noqa: E402

UA = "day-trader-skills-nse/1.0 (personal research tool)"
HOSTS = ("query2", "query1")
URL = ("https://%s.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
       "?type=%s&period1=%d&period2=%d&merge=false")
ANNUAL = ("TotalRevenue", "NetIncome", "OperatingIncome", "InterestExpense", "TotalDebt", "StockholdersEquity",
          "CashAndCashEquivalents", "OperatingCashFlow", "FreeCashFlow", "LandAndImprovements", "NetPPE", "TotalAssets")
CACHE = os.path.join("trader", "cache", "fund")
CACHE_DAYS = 14
CRORE = 1e7
PAUSE = 0.5


class GemsError(Exception):
    pass


# ---------------------------------------------------------------- fetch and cache

def _get(sym):
    now = int(time.time())
    types = ",".join(["annual" + t for t in ANNUAL] + ["trailingMarketCap"])
    last = "no answer"
    for host in HOSTS:
        url = URL % (host, urllib.parse.quote(sym + ".NS", safe=""), types, now - 6 * 366 * 86400, now + 86400)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            e.close()
            if e.code == 429:
                time.sleep(20)
        except (urllib.error.URLError, OSError) as e:
            last = "could not connect: %s" % getattr(e, "reason", e)
    raise GemsError("Yahoo did not answer for %s (%s)" % (sym, last))


def parse(text, sym):
    """-> {"symbol", "currency", "mcap", "years": {date: {field: value}}} in the reporting currency."""
    try:
        results = json.loads(text)["timeseries"]["result"] or []
    except (ValueError, KeyError, TypeError):
        raise GemsError("Yahoo returned something unexpected for %s" % sym)
    years, cur, mcap = {}, set(), None
    for res in results:
        for key, rows in res.items():
            if key in ("meta", "timestamp") or not isinstance(rows, list):
                continue
            for row in rows:
                raw = ((row or {}).get("reportedValue") or {}).get("raw")
                if raw is None:
                    continue
                if key == "trailingMarketCap":
                    mcap = float(raw)                      # rows are oldest first: the last one stays
                elif key.startswith("annual") and row.get("periodType") == "12M":
                    years.setdefault(row["asOfDate"], {})[key[6:]] = float(raw)
                    cur.add(row.get("currencyCode") or "INR")
    return {"symbol": sym, "currency": ",".join(sorted(cur)) or None, "mcap": mcap, "years": years}


def cache_path(sym, cache=CACHE):
    return os.path.join(cache, sym.replace("&", "_and_") + ".json")


def load(sym, cache=CACHE, max_age_days=None):
    p = cache_path(sym, cache)
    if not os.path.exists(p):
        return None
    if max_age_days is not None and time.time() - os.path.getmtime(p) > max_age_days * 86400:
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def fetch(symbols, cache=CACHE, say=None, sleep=time.sleep):
    os.makedirs(cache, exist_ok=True)
    done = failed = skipped = 0
    for sym in symbols:
        if load(sym, cache, CACHE_DAYS) is not None:
            skipped += 1
            continue
        try:
            doc = parse(_get(sym), sym)
            done += 1
        except GemsError as e:
            doc = {"symbol": sym, "error": str(e), "years": {}}
            failed += 1
        with open(cache_path(sym, cache), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        if say and (done + failed) % 25 == 0:
            say("  %d fetched, %d failed, %d already cached" % (done, failed, skipped))
        sleep(PAUSE)
    return done, failed, skipped


# ---------------------------------------------------------------- the numbers

def metrics(doc):
    """The screen's numbers for one company, or (None, reason)."""
    if doc.get("error") or not doc.get("years"):
        return None, "no data"
    if doc.get("currency") != "INR":
        return None, "reports in %s, not rupees" % doc.get("currency")
    need = ("TotalRevenue", "NetIncome", "StockholdersEquity")
    ys = sorted(y for y in doc["years"] if "TotalRevenue" in doc["years"][y])   # a year with one stray row is not a year
    if not ys or doc.get("mcap") is None or any(k not in doc["years"][ys[-1]] for k in need):
        return None, "a needed field is missing"
    last, first = doc["years"][ys[-1]], doc["years"][ys[0]]
    eq = last["StockholdersEquity"]
    debt = last.get("TotalDebt", 0.0)            # Yahoo omits the row when a company has no borrowings
    cash = last.get("CashAndCashEquivalents")
    ocf = [doc["years"][y].get("OperatingCashFlow") for y in ys]
    land = last.get("LandAndImprovements")
    opi, intr = last.get("OperatingIncome"), last.get("InterestExpense")
    m = {"symbol": doc["symbol"], "year_end": ys[-1], "years": len(ys), "mcap_cr": doc["mcap"] / CRORE,
         "revenue_cr": last["TotalRevenue"] / CRORE, "profit_cr": last["NetIncome"] / CRORE,
         "debt_cr": debt / CRORE, "equity_cr": eq / CRORE,
         "debt_equity": debt / eq if eq > 0 else None,
         "net_cash_cr": (cash - debt) / CRORE if cash is not None else None,
         "ocf_positive_years": sum(1 for x in ocf if x is not None and x > 0), "ocf_years": sum(1 for x in ocf if x is not None),
         "revenue_growth_pct": (last["TotalRevenue"] / first["TotalRevenue"] - 1) * 100 if len(ys) > 1 and first.get("TotalRevenue", 0) > 0 else None,
         "roe_pct": last["NetIncome"] / eq * 100 if eq > 0 else None,
         "pe": doc["mcap"] / last["NetIncome"] if last["NetIncome"] > 0 else None,
         "pb": doc["mcap"] / eq if eq > 0 else None,
         "interest_cover": opi / intr if opi is not None and intr and intr > 0 else None,
         "land_cr": land / CRORE if land is not None else None,
         "land_pct_of_mcap": land / doc["mcap"] * 100 if land is not None and doc["mcap"] > 0 else None}
    return m, None


def passes(m, a):
    if not a.min_mcap_cr <= m["mcap_cr"] <= a.max_mcap_cr:
        return "size"
    if m["debt_equity"] is None or m["debt_equity"] > a.max_debt_equity:
        return "debt"
    if m["ocf_years"] < 3 or m["ocf_positive_years"] < min(a.min_ocf_years, m["ocf_years"]):
        return "cash flow"
    if m["profit_cr"] <= 0:
        return "no profit"
    if m["revenue_growth_pct"] is None or m["revenue_growth_pct"] <= 0:
        return "no growth"
    if a.min_roe is not None and (m["roe_pct"] is None or m["roe_pct"] < a.min_roe):
        return "return on equity"
    if a.min_land_pct is not None and (m["land_pct_of_mcap"] is None or m["land_pct_of_mcap"] < a.min_land_pct):
        return "land"
    return None


def turnover():
    """{SYM: average crore traded a day over 20 sessions} from the NSE price files, or {}."""
    try:
        _, hist = bhav.history(20)
    except bhav.BhavError:
        return {}
    out = {}
    for sym, s in hist.items():
        vals = [b["turnover_lacs"] for b in s["bars"] if b]
        if vals:
            out[sym] = sum(vals) / len(vals) / 100.0
    return out


def screener_query(a):
    q = ["Market Capitalization > %g" % a.min_mcap_cr, "Market Capitalization < %g" % a.max_mcap_cr,
         "Debt to equity < %g" % max(a.max_debt_equity, 0.01), "Net profit > 0", "Cash from operations last year > 0",
         "Sales growth 3Years > 0"]
    if a.min_roe is not None:
        q.append("Return on equity > %g" % a.min_roe)
    return " AND ".join(q)


def _n(x, nd=1):
    return "-" if x is None else ("{:,.%df}" % nd).format(x)


# ---------------------------------------------------------------- commands

def universe(a):
    if getattr(a, "symbols", None):
        return [s.upper() for s in a.symbols]
    if not os.path.exists(a.universe):
        raise GemsError("no %s: run trader-scanner's `scan.py universe` first, or pass --symbols" % a.universe)
    with open(a.universe, encoding="utf-8") as fh:
        return [line.split("|")[0].strip().upper() for line in fh if line.strip()]


def cmd_fetch(a):
    syms = universe(a)
    if a.limit:
        syms = syms[:a.limit]
    print("Fetching annual numbers for %d companies (cached ones are skipped)..." % len(syms), file=sys.stderr)
    done, failed, skipped = fetch(syms, say=lambda m: print(m, file=sys.stderr))
    print("%d fetched, %d failed, %d were already cached (under %d days old)." % (done, failed, skipped, CACHE_DAYS))
    return 0


def cmd_screen(a):
    syms = universe(a)
    rows, why, missing = [], {}, 0
    for sym in syms:
        doc = load(sym)
        if doc is None:
            missing += 1
            continue
        m, reason = metrics(doc)
        if m is None:
            why[reason] = why.get(reason, 0) + 1
            continue
        fail = passes(m, a)
        if fail:
            why[fail] = why.get(fail, 0) + 1
        else:
            rows.append(m)
    liq = turnover()
    for m in rows:
        m["avg_turnover_cr"] = round(liq[m["symbol"]], 2) if m["symbol"] in liq else None
    rows.sort(key=lambda m: -(m["roe_pct"] or 0))
    doc = {"created_by": "trader-gems", "universe": len(syms), "not_fetched": missing, "dropped": why, "passed": len(rows),
           "screener_query": screener_query(a), "companies": rows}
    if a.write:
        os.makedirs("trader", exist_ok=True)
        with open(os.path.join("trader", "gems.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    if a.json:
        print(json.dumps(doc, indent=2))
        return 0 if rows else 1
    print("Screened %d companies; %d not fetched yet. %d passed." % (len(syms) - missing, missing, len(rows)))
    print("Dropped: " + ", ".join("%d %s" % (v, k) for k, v in sorted(why.items(), key=lambda kv: -kv[1])) + ".")
    print("%-12s %8s %8s %7s %6s %6s %5s %8s %8s %7s %7s" % (
        "symbol", "mcap cr", "sales cr", "D/E", "ROE %", "P/E", "P/B", "netcash", "land cr", "land %", "cr/day"))
    for m in rows[:a.show]:
        print("%-12s %8s %8s %7s %6s %6s %5s %8s %8s %7s %7s" % (
            m["symbol"], _n(m["mcap_cr"], 0), _n(m["revenue_cr"], 0), _n(m["debt_equity"], 2), _n(m["roe_pct"]),
            _n(m["pe"]), _n(m["pb"]), _n(m["net_cash_cr"], 0), _n(m["land_cr"]), _n(m["land_pct_of_mcap"]),
            _n(m["avg_turnover_cr"], 2)))
    if len(rows) > a.show:
        print("... and %d more (--show N, or --json)." % (len(rows) - a.show))
    odd = [m["symbol"] for m in rows[:a.show] if m["profit_cr"] > 0.5 * m["revenue_cr"]]
    if odd:
        print("ONE-OFF LIKELY: profit is over half of sales at %s. That is usually a one-time gain (an asset sale, a"
              % ", ".join(odd))
        print("write-back), so their return on equity and P/E are not real. Read the filing.")
    print("Sorted by return on equity. Land is at book cost. 'cr/day' is the average traded a day; '-' means no price files.")
    print("Cross-check in your own Screener.in account with this query:")
    print("  " + doc["screener_query"])
    print("A screen is a list that passed a filter, not a list to buy. Read the filings first (see SKILL.md).")
    return 0 if rows else 1


def cmd_show(a):
    sym = a.symbol.upper()
    doc = load(sym)
    if doc is None:
        fetch([sym])
        doc = load(sym)
    if doc.get("error") or not doc.get("years"):
        raise GemsError("no annual data for %s: %s" % (sym, doc.get("error") or "Yahoo has none"))
    ys = sorted(doc["years"])
    unit = "INR crore" if doc.get("currency") == "INR" else "%s, in units of 10 million (NOT rupees)" % doc.get("currency")
    print("%s, annual, %s (Yahoo Finance, unofficial). Market value: %s." % (sym, unit, _n(doc["mcap"] / CRORE, 0) if doc.get("mcap") else "-"))
    print("%-26s" % "year end" + "".join("%13s" % y for y in ys))
    for k in ANNUAL:
        print("%-26s" % k + "".join("%13s" % _n(doc["years"][y][k] / CRORE) if k in doc["years"][y] else "%13s" % "-" for y in ys))
    m, reason = metrics(doc)
    if m:
        print("Debt/equity %s, return on equity %s %%, P/E %s, P/B %s, interest cover %s, cash from operations positive in %d of %d years."
              % (_n(m["debt_equity"], 2), _n(m["roe_pct"]), _n(m["pe"]), _n(m["pb"]), _n(m["interest_cover"]),
                 m["ocf_positive_years"], m["ocf_years"]))
    else:
        print("Ratios not computed: %s." % reason)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Small-company fundamentals screen (trader-gems).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("fetch")
    p.add_argument("--symbols", nargs="+")
    p.add_argument("--universe", default="trader/universe.txt")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("screen")
    p.add_argument("--symbols", nargs="+")
    p.add_argument("--universe", default="trader/universe.txt")
    p.add_argument("--min-mcap-cr", type=float, default=50)
    p.add_argument("--max-mcap-cr", type=float, default=2000)
    p.add_argument("--max-debt-equity", type=float, default=0.1)
    p.add_argument("--min-ocf-years", type=int, default=3)
    p.add_argument("--min-roe", type=float)
    p.add_argument("--min-land-pct", type=float, help="land on the books as a percent of market value, at least")
    p.add_argument("--show", type=int, default=30)
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show")
    p.add_argument("symbol")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("fetch", "screen", "show"):
            return {"fetch": cmd_fetch, "screen": cmd_screen, "show": cmd_show}[a.cmd](a)
    except GemsError as e:
        print("gems.py: %s" % e, file=sys.stderr)
        return 1
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
