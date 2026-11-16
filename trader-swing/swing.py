#!/usr/bin/env python3
"""Swing scans, their backtest and a position plan for trader-swing. Standard library only.

    python3 swing.py sync                                  # NSE daily files -> trader/cache/bhav (once a day)
    python3 swing.py scan                                  # every setup, latest CLOSED session
    python3 swing.py live                                  # the same setups on today's prices so far (market hours)
    python3 swing.py scan --setups volume_shocker,ema_9_21 --max-price 500
    python3 swing.py backtest --setup volume_shocker       # how that rule did on the cached history
    python3 swing.py backtest --all
    python3 swing.py plan TATAPOWER                        # stop, target, shares, charges -> trader/swing/

Data: NSE's own daily file for every stock (open, high, low, close, volume, turnover, delivery
percentage), cached by trader-data/bhav.py. Prices are unadjusted: a stock with a split or bonus
inside the window is left out, not adjusted.

Setups (daily bars, EQ series, long only; a stock must have traded on every one of the last 60
sessions and average at least --min-turnover-cr a day over 20 sessions):
  volume_shocker  volume at least 3x its 20-session average, close up 3 % or more, close in the
                  top 30 % of the day's range
  ema_9_21        the 9-day EMA crossed above the 21-day EMA today, close above the 50-day EMA
  ema_20_50       the 20-day EMA crossed above the 50-day EMA today
  high_52w        highest close of the last 250 sessions, on volume 1.5x the average or more
  gap_up          opened 2 % or more above yesterday's high and closed above its open
  momentum        up 30 % or more over 60 sessions and within 10 % of its 250-session closing high
                  (a state, not an event: it stays on for days)

Live: `live` adds today's bar so far to the cached history and runs the same rules. Today's price,
day high, day low and volume so far come from Yahoo's spark endpoint, 20 stocks a request (free,
unofficial, can lag a few minutes); today's open is approximated by the first 5-minute close. Two
volume readings: "so far" against a FULL average day (a volume shocker fires only when today has
already traded 3x an average day), and "pace", so far divided by the share of the session gone.
Pace overstates before about 10:30, because the first hour is the busiest: it is shown, and tagged
`volume_pace` (pace 3x+, up 3 %+), but it is not a volume shocker until the volume is really there.
`heavy_volume` means the 3x volume IS there and the stock is up 3 %+, but the price has fallen out of
the top 30 % of the day's range, so the shocker rule does not fire.
A live hit can vanish by the close: the rules were tested on closing prices, not on mid-day ones.

Backtest: for every past session a setup fired, buy at the NEXT session's open, stop at entry minus
--stop-atr (2) x the 14-day ATR, target --target-r (2) x that risk, out at the close after --hold
(10) sessions if neither is hit. A bar that touches both counts as the stop; a gap through the
stop fills at the open. R is the result in units of the risk, after Zerodha delivery charges on a
position sized to --risk rupees (gross R is before them). The BASELINE line is the same exit applied to every liquid stock
on every 5th session, setup or not: a setup is only worth anything if it beats that line.
This is ONE year of ONE market. It overstates what you would get: no slippage, no missed fills, and
you would never take every signal. Past results do not predict the next trade.
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-data"))
import bhav      # noqa: E402
import charges   # noqa: E402

SETUPS = ("volume_shocker", "ema_9_21", "ema_20_50", "high_52w", "gap_up", "momentum")
WORDS = {"volume_shocker": "volume shocker", "ema_9_21": "9/21 EMA cross", "ema_20_50": "20/50 EMA cross",
         "high_52w": "52-week closing high", "gap_up": "gap up", "momentum": "momentum leader"}
LIVE_WORDS = {"heavy_volume": "3x volume but off the day's high", "volume_pace": "volume pace (not yet 3x a day)"}
DEFAULTS = {"swing_capital": 25000, "swing_max_loss_per_trade_inr": 250, "swing_max_position_pct": 40,
            "swing_max_open_positions": 3}
TICK = 0.05
UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
SPARK = "https://%s.finance.yahoo.com/v7/finance/spark?symbols=%s&range=1d&interval=5m"
SPARK_MAX = 20
IST = datetime.timedelta(hours=5, minutes=30)
OPEN_MIN, CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30


class SwingError(Exception):
    pass


# ---------------------------------------------------------------- indicators

def ema(values, n):
    out, k, e = [], 2.0 / (n + 1), None
    for i, v in enumerate(values):
        e = v if e is None else v * k + e * (1 - k)
        out.append(e if i >= n - 1 else None)
    return out


def series(bars):
    """Plain lists for one stock's consecutive bars, plus the indicators the setups need."""
    c = [b["c"] for b in bars]
    v = [b["v"] for b in bars]
    n = len(c)
    tr = [bars[0]["h"] - bars[0]["l"]] + [max(bars[i]["h"] - bars[i]["l"], abs(bars[i]["h"] - c[i - 1]),
                                              abs(bars[i]["l"] - c[i - 1])) for i in range(1, n)]
    atr, avgv, avgt, hi250 = [None] * n, [None] * n, [None] * n, [None] * n
    for i in range(n):
        if i >= 14:
            atr[i] = sum(tr[i - 13:i + 1]) / 14.0
        if i >= 20:
            avgv[i] = sum(v[i - 20:i]) / 20.0                               # the 20 sessions BEFORE today
            avgt[i] = sum(b["turnover_lacs"] for b in bars[i - 20:i]) / 2000.0   # crore a day
        if i >= 200:
            hi250[i] = max(c[max(0, i - 250):i])                           # before today
    return {"c": c, "v": v, "atr": atr, "avgv": avgv, "avgt": avgt, "hi250": hi250,
            "e9": ema(c, 9), "e21": ema(c, 21), "e20": ema(c, 20), "e50": ema(c, 50)}


def fired(bars, s, i):
    """The setups that fire on bar i (uses bars up to i only)."""
    out = []
    b, c, v = bars[i], s["c"], s["v"]
    if i < 60 or not s["avgv"][i]:
        return out
    rng = b["h"] - b["l"]
    if v[i] >= 3 * s["avgv"][i] and c[i] >= c[i - 1] * 1.03 and rng > 0 and (c[i] - b["l"]) / rng >= 0.7:
        out.append("volume_shocker")
    if s["e9"][i - 1] is not None and s["e21"][i - 1] is not None and s["e50"][i] is not None:
        if s["e9"][i - 1] <= s["e21"][i - 1] and s["e9"][i] > s["e21"][i] and c[i] > s["e50"][i]:
            out.append("ema_9_21")
    if s["e50"][i - 1] is not None and s["e20"][i - 1] <= s["e50"][i - 1] and s["e20"][i] > s["e50"][i]:
        out.append("ema_20_50")
    if s["hi250"][i] and c[i] > s["hi250"][i] and v[i] >= 1.5 * s["avgv"][i]:
        out.append("high_52w")
    if b["o"] >= bars[i - 1]["h"] * 1.02 and c[i] > b["o"]:
        out.append("gap_up")
    if c[i] >= c[i - 60] * 1.30 and s["hi250"][i] and c[i] >= 0.9 * max(s["hi250"][i], c[i]):
        out.append("momentum")
    return out


def usable(hist, min_bars=61):
    """{SYM: consecutive bars} for stocks with no gap in their last bars and no split/bonus suspicion."""
    out, skipped = {}, 0
    for sym, s in hist.items():
        if s["ca_suspect"]:
            skipped += 1
            continue
        bars = s["bars"]
        j = len(bars)
        while j > 0 and bars[j - 1] is not None:
            j -= 1
        run = bars[j:]                       # the unbroken run that ends on the last cached session
        if len(run) >= min_bars:
            out[sym] = run
    return out, skipped


# ---------------------------------------------------------------- scan

def scan(stocks, setups, min_turnover_cr, min_price, max_price):
    hits = []
    for sym, bars in stocks.items():
        s = series(bars)
        i = len(bars) - 1
        if s["avgt"][i] is None or s["avgt"][i] < min_turnover_cr:
            continue
        if not min_price <= s["c"][i] <= max_price:
            continue
        f = [x for x in fired(bars, s, i) if x in setups]
        if f:
            b = bars[i]
            hits.append({"symbol": sym, "setups": f, "close": b["c"], "change_pct": round((b["c"] / s["c"][i - 1] - 1) * 100, 2),
                         "volume_x": round(b["v"] / s["avgv"][i], 1), "deliv_pct": b["deliv_pct"],
                         "turnover_cr": round(b["turnover_lacs"] / 100.0, 2), "avg_turnover_cr": round(s["avgt"][i], 2),
                         "atr": round(s["atr"][i], 2)})
    hits.sort(key=lambda h: (-len(h["setups"]), -h["volume_x"]))
    return hits


# ---------------------------------------------------------------- live

def _spark(symbols):
    ys = ",".join(urllib.parse.quote(s + ".NS", safe="") for s in symbols)
    last = "no answer"
    for host in ("query2", "query1"):
        req = urllib.request.Request(SPARK % (host, ys), headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            e.close()
            if e.code == 429:
                time.sleep(5)
        except (urllib.error.URLError, OSError) as e:
            last = "could not connect: %s" % getattr(e, "reason", e)
    raise SwingError("Yahoo did not answer (%s)" % last)


def parse_spark(text):
    """Spark JSON -> {SYM: today's bar so far}. Stocks without a price or volume are left out."""
    out = {}
    try:
        results = json.loads(text)["spark"]["result"] or []
    except (ValueError, KeyError, TypeError):
        raise SwingError("Yahoo's spark answer is not the shape this tool knows")
    for item in results:
        resp = (item.get("response") or [{}])[0] or {}
        m = resp.get("meta") or {}
        sym = str(m.get("symbol") or item.get("symbol") or "").upper()
        sym = sym[:-3] if sym.endswith(".NS") else sym
        closes = [c for c in (((resp.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
        price, vol, t = m.get("regularMarketPrice"), m.get("regularMarketVolume"), m.get("regularMarketTime")
        if not sym or not price or not vol or not t or not closes:
            continue
        out[sym] = {"o": closes[0], "h": m.get("regularMarketDayHigh") or max(closes + [price]),
                    "l": m.get("regularMarketDayLow") or min(closes + [price]), "c": float(price),
                    "prev": m.get("chartPreviousClose") or m.get("previousClose"), "v": int(vol),
                    "turnover_lacs": price * vol / 1e5, "deliv_pct": None, "time": int(t)}
    return out


def session_fraction(now_ist):
    """The share of the 9:15 to 15:30 session that has passed, between 0 and 1."""
    mins = now_ist.hour * 60 + now_ist.minute
    return max(0.0, min(1.0, (mins - OPEN_MIN) / float(CLOSE_MIN - OPEN_MIN)))


def live_scan(stocks, quotes, setups, frac, today, min_turnover_cr, min_price, max_price):
    """Add today's bar so far to each stock's history and run the rules on it."""
    hits, stale = [], 0
    for sym, bars in stocks.items():
        q = quotes.get(sym)
        if not q:
            continue
        if (datetime.datetime.utcfromtimestamp(q["time"]) + IST).date() != today:
            stale += 1                               # no trade today: yesterday's quote is not a live bar
            continue
        s0 = series(bars)
        last = len(bars) - 1
        if s0["avgt"][last] is None or s0["avgt"][last] < min_turnover_cr or not min_price <= q["c"] <= max_price:
            continue
        both = bars + [q]
        s = series(both)
        i = len(both) - 1
        f = [x for x in fired(both, s, i) if x in setups]
        so_far = q["v"] / s["avgv"][i]
        pace = so_far / frac if frac >= 0.04 else None           # not before 9:30
        chg = (q["c"] / bars[-1]["c"] - 1) * 100
        if "volume_shocker" in setups and "volume_shocker" not in f and chg >= 3:
            if so_far >= 3:
                f.append("heavy_volume")             # the volume is there, but the price is off the day's high
            elif pace and pace >= 3:
                f.append("volume_pace")
        if f:
            hits.append({"symbol": sym, "setups": f, "price": q["c"], "change_pct": round(chg, 2),
                         "volume_x_so_far": round(so_far, 2), "volume_pace_x": round(pace, 1) if pace else None,
                         "avg_turnover_cr": round(s0["avgt"][last], 2), "atr": round(s0["atr"][last], 2),
                         "quote_time": (datetime.datetime.utcfromtimestamp(q["time"]) + IST).strftime("%H:%M")})
    hits.sort(key=lambda h: (-len(h["setups"]), -h["volume_x_so_far"]))
    return hits, stale


# ---------------------------------------------------------------- backtest

def one_trade(bars, i, atr, stop_atr, target_r, hold):
    """Enter at bar i+1's open after a signal on bar i. -> (R before charges, entry, exit, days) or None."""
    if i + 1 >= len(bars) or not atr:
        return None
    entry = bars[i + 1]["o"]
    risk = stop_atr * atr
    if entry <= 0 or risk <= 0 or risk >= entry:
        return None
    stop, target = entry - risk, entry + target_r * risk
    last = min(i + hold, len(bars) - 1)
    for j in range(i + 1, last + 1):
        b = bars[j]
        if b["o"] <= stop and j > i + 1:
            return (b["o"] - entry) / risk, entry, b["o"], j - i          # gapped through the stop
        if b["l"] <= stop:
            return -1.0, entry, stop, j - i
        if b["h"] >= target:
            return target_r, entry, target, j - i
    x = bars[last]["c"]
    return (x - entry) / risk, entry, x, last - i


def backtest(stocks, setup, stop_atr, target_r, hold, min_turnover_cr, risk_inr, max_position, sessions):
    trades, base = [], []
    for sym, bars in stocks.items():
        s = series(bars)
        off = sessions - len(bars)          # bar i of this stock is session off + i of the window
        for i in range(60, len(bars) - 1):
            if s["avgt"][i] is None or s["avgt"][i] < min_turnover_cr:
                continue
            is_hit = setup in fired(bars, s, i)
            if not is_hit and i % 5:
                continue
            t = one_trade(bars, i, s["atr"][i], stop_atr, target_r, hold)
            if t is None:
                continue
            r, entry, exit_, days = t
            if i % 5 == 0:
                base.append(r)
            if is_hit:
                risk_ps = stop_atr * s["atr"][i]
                qty = int(min(risk_inr / risk_ps, max_position / entry))
                if qty < 1:
                    continue                       # too dear for this account: you could not have taken it
                cost = charges.round_trip(entry, exit_, qty, delivery=True)["total"]
                trades.append({"symbol": sym, "i": off + i, "r": r, "net_r": r - cost / (qty * risk_ps), "days": days,
                               "net_inr": qty * (exit_ - entry) - cost})
    return trades, base


def summary(trades, key="net_r"):
    if not trades:
        return None
    rs = sorted(t[key] for t in trades)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    streak = worst = 0
    for t in sorted(trades, key=lambda t: t["i"]):
        streak = streak + 1 if t[key] <= 0 else 0
        worst = max(worst, streak)
    return {"trades": len(rs), "win_pct": round(100.0 * len(wins) / len(rs), 1), "avg_r": round(sum(rs) / len(rs), 3),
            "median_r": round(rs[len(rs) // 2], 3), "avg_win_r": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss_r": round(sum(losses) / len(losses), 2) if losses else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "worst_losing_streak": worst}


def halves(trades, sessions):
    """Average gross R of the signals in the first and the second half of the tested sessions, and how many
    different sessions the signals came from (1,000 trades on 40 days are 40 bets, not 1,000)."""
    mid = 60 + (sessions - 60) // 2
    a = [t["r"] for t in trades if t["i"] < mid]
    b = [t["r"] for t in trades if t["i"] >= mid]
    avg = lambda x: round(sum(x) / len(x), 3) if x else None
    return {"first_half_r": avg(a), "second_half_r": avg(b), "signal_days": len({t["i"] for t in trades})}


def verdict(net, gross, base_avg, split=None):
    """net and gross are summary() dicts; base_avg is the baseline's average R before charges."""
    if net["trades"] < 30:
        return "Too few trades (%d) to say anything." % net["trades"]
    edge = gross["avg_r"] - base_avg
    if split and edge > 0.02 and None not in (split["first_half_r"], split["second_half_r"]) and \
            min(split["first_half_r"], split["second_half_r"]) <= base_avg:
        return ("NOT STABLE: %+.3f R before charges overall, but %+.3f R in the first half of the year and %+.3f R in "
                "the second. A rule that only worked in one stretch is luck or a market phase, not an edge."
                % (gross["avg_r"], split["first_half_r"], split["second_half_r"]))
    if edge <= 0.02:
        return ("The rule added nothing: %+.3f R a trade before charges, against %+.3f R for any liquid stock on any day."
                % (gross["avg_r"], base_avg))
    if net["avg_r"] <= 0:
        return ("The rule beat the baseline by %+.3f R before charges, but charges on a position this small turned it "
                "into a loss (%+.3f R)." % (edge, net["avg_r"]))
    return ("Beat the baseline by %+.3f R before charges and kept %+.3f R after them, on this history. "
            "One year is thin evidence, not proof." % (edge, net["avg_r"]))


# ---------------------------------------------------------------- plan

def floor_tick(x):
    return math.floor(x / TICK + 1e-9) * TICK


def plan(sym, bars, cfg, stop_atr, target_r):
    s = series(bars)
    i = len(bars) - 1
    if not s["atr"][i]:
        raise SwingError("%s has too little history for an ATR stop" % sym)
    entry = bars[i]["c"]
    stop = floor_tick(entry - stop_atr * s["atr"][i])
    risk = entry - stop
    target = floor_tick(entry + target_r * risk)
    cap = cfg["swing_capital"] * cfg["swing_max_position_pct"] / 100.0
    by_risk, by_cap = int(cfg["swing_max_loss_per_trade_inr"] / risk), int(cap / entry)
    qty = min(by_risk, by_cap)
    out = {"created_by": "trader-swing", "symbol": sym, "style": "swing", "product": "CNC", "as_of_close": entry,
           "stop": round(stop, 2), "target": round(target, 2), "risk_per_share": round(risk, 2), "atr": round(s["atr"][i], 2),
           "qty": qty, "bound_by": "max loss" if by_risk <= by_cap else "position cap",
           "avg_turnover_cr": round(s["avgt"][i], 2), "setups_today": fired(bars, s, i), "warnings": []}
    if qty < 1:
        out["warnings"].append("no order: one share risks %.2f, more than your %s max loss, or costs more than your %s position cap"
                               % (risk, cfg["swing_max_loss_per_trade_inr"], round(cap)))
        return out
    win = charges.round_trip(entry, target, qty, delivery=True)
    loss = charges.round_trip(entry, stop, qty, delivery=True)
    out.update(cost=round(qty * entry, 2), max_loss=round(-loss["net"], 2), gain_at_target=round(win["net"], 2),
               charges_round_trip=win["total"], reward_risk_after_charges=round(win["net"] / -loss["net"], 2))
    if qty * entry > s["avgt"][i] * 1e7 * 0.01:
        out["warnings"].append("this position is over 1 % of the stock's average daily turnover: it may be hard to sell")
    if s["avgt"][i] < 1:
        out["warnings"].append("thin stock (under 1 crore a day): wide spreads and circuit locks are likely")
    if out["reward_risk_after_charges"] < 1.5:
        out["warnings"].append("after charges the reward:risk is %.2f: charges eat a large part of a position this small"
                               % out["reward_risk_after_charges"])
    return out


def render_plan(p):
    L = ["Swing plan: %s (CNC delivery), from the %s close" % (p["symbol"], p["as_of_close"])]
    if p["qty"] < 1:
        return "\n".join(L + ["  " + w for w in p["warnings"]])
    L += ["  Buy           %d shares near %.2f = Rs %s (size bound by your %s)" % (p["qty"], p["as_of_close"], "{:,.0f}".format(p["cost"]), p["bound_by"]),
          "  Stop          %.2f  (2 x the 14-day ATR of %.2f under the close)" % (p["stop"], p["atr"]),
          "  Target        %.2f" % p["target"],
          "  If stopped    about Rs -%.0f after charges" % p["max_loss"],
          "  At target     about Rs +%.0f after charges (charges Rs %.0f; reward:risk %.2f)" % (
              p["gain_at_target"], p["charges_round_trip"], p["reward_risk_after_charges"])]
    L += ["  WARNING: " + w for w in p["warnings"]]
    L += ["The entry is yesterday's close: tomorrow's open can be far from it. If it opens above the target or",
          "below the stop, the plan is void. In Kite: buy as CNC, then set ONE GTT of type OCO on the holding with",
          "the stop as the lower trigger and the target as the upper one. A stop can fill worse on a gap, and a",
          "stock locked at its lower circuit cannot be sold at all. You place every order yourself. Not financial advice."]
    return "\n".join(L)


# ---------------------------------------------------------------- commands

def _load(a, days):
    dates, hist = bhav.history(days)
    stocks, skipped = usable(hist)
    return dates, stocks, skipped


def _cfg(path):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            cfg.update({k: v for k, v in json.load(fh).items() if k in DEFAULTS})
    return cfg


def cmd_scan(a):
    setups = [s.strip() for s in a.setups.split(",")] if a.setups else list(SETUPS)
    bad = [s for s in setups if s not in SETUPS]
    if bad:
        raise SwingError("unknown setup %s: choose from %s" % (", ".join(bad), ", ".join(SETUPS)))
    dates, stocks, skipped = _load(a, 260)
    hits = scan(stocks, setups, a.min_turnover_cr, a.min_price, a.max_price)
    doc = {"created_by": "trader-swing", "mode": "swing", "as_of": dates[-1].isoformat(), "scanned": len(stocks),
           "skipped_split_or_bonus": skipped, "filters": {"min_turnover_cr": a.min_turnover_cr, "min_price": a.min_price,
                                                         "max_price": a.max_price}, "hits": hits}
    if a.write:
        os.makedirs(os.path.join("trader", "swing"), exist_ok=True)
        with open(os.path.join("trader", "swing", "watchlist.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    if a.json:
        print(json.dumps(doc, indent=2))
        return 0 if hits else 1
    print("Swing scan, session of %s: %d stocks with full history (%d left out for a suspected split or bonus)."
          % (dates[-1], len(stocks), skipped))
    print("%d matched a rule (liquid: %s+ crore a day, price %s to %s)." % (len(hits), a.min_turnover_cr, a.min_price, a.max_price))
    print("%-12s %9s %7s %6s %7s %9s  %s" % ("symbol", "close", "chg %", "vol x", "deliv %", "cr/day", "setups"))
    for h in hits[:a.show]:
        print("%-12s %9.2f %+7.2f %6.1f %7s %9.2f  %s" % (
            h["symbol"], h["close"], h["change_pct"], h["volume_x"],
            ("%.0f" % h["deliv_pct"]) if h["deliv_pct"] is not None else "-", h["avg_turnover_cr"],
            ", ".join(WORDS[s] for s in h["setups"])))
    if len(hits) > a.show:
        print("... and %d more (--show N, or --json)." % (len(hits) - a.show))
    print("A scan lists charts that match a rule, not stocks to buy. Check each rule's record first: swing.py backtest --all.")
    return 0 if hits else 1


def cmd_live(a):
    setups = [s.strip() for s in a.setups.split(",")] if a.setups else list(SETUPS)
    bad = [s for s in setups if s not in SETUPS]
    if bad:
        raise SwingError("unknown setup %s: choose from %s" % (", ".join(bad), ", ".join(SETUPS)))
    now = datetime.datetime.utcnow() + IST
    dates, stocks, skipped = _load(a, 260)
    if dates[-1] >= now.date():
        raise SwingError("today's closing file is already cached: the session is over, use `swing.py scan`")
    if (now.date() - dates[-1]).days > 5:
        raise SwingError("the price files stop at %s: run `swing.py sync` first" % dates[-1])
    liquid = []
    for sym, bars in stocks.items():
        t = sum(b["turnover_lacs"] for b in bars[-20:]) / 2000.0
        if t >= a.min_turnover_cr and a.min_price <= bars[-1]["c"] <= a.max_price * 1.3:
            liquid.append(sym)
    liquid.sort()
    batches = [liquid[i:i + SPARK_MAX] for i in range(0, len(liquid), SPARK_MAX)]
    if not a.json:
        print("Fetching live prices for %d liquid stocks (%d requests)..." % (len(liquid), len(batches)), file=sys.stderr)
    quotes, failed = {}, 0
    for k, batch in enumerate(batches):
        if k:
            time.sleep(a.pause)
        try:
            quotes.update(parse_spark(_spark(batch)))
        except SwingError:
            failed += len(batch)
    if not quotes:
        raise SwingError("no live prices came back from Yahoo: try again in a minute")
    now = datetime.datetime.utcnow() + IST
    frac = session_fraction(now)
    hits, stale = live_scan(stocks, quotes, setups, frac, now.date(), a.min_turnover_cr, a.min_price, a.max_price)
    doc = {"created_by": "trader-swing", "mode": "live", "as_of": now.strftime("%Y-%m-%d %H:%M IST"), "history_to": dates[-1].isoformat(),
           "session_fraction": round(frac, 2), "asked": len(liquid), "quoted": len(quotes), "failed": failed,
           "no_trade_today": stale, "hits": hits}
    if a.write:
        os.makedirs(os.path.join("trader", "swing"), exist_ok=True)
        with open(os.path.join("trader", "swing", "live.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    if a.json:
        print(json.dumps(doc, indent=2))
        return 0 if hits else 1
    if frac <= 0 or frac >= 1:
        print("The market is not open (%s IST). These are the last prices Yahoo has, not live ones." % now.strftime("%H:%M"))
    print("Live scan %s IST, %d %% of the session gone. Prices for %d of %d liquid stocks%s; history to %s."
          % (now.strftime("%H:%M"), round(frac * 100), len(quotes), len(liquid),
             (" (%d failed)" % failed) if failed else "", dates[-1]))
    print("%d match a rule on today's bar SO FAR. A live hit can vanish by the close." % len(hits))
    print("%-12s %9s %7s %8s %7s %8s %6s  %s" % ("symbol", "price", "chg %", "vol/day", "pace x", "cr/day", "as of", "setups"))
    for h in hits[:a.show]:
        print("%-12s %9.2f %+7.2f %8.2f %7s %8.2f %6s  %s" % (
            h["symbol"], h["price"], h["change_pct"], h["volume_x_so_far"],
            ("%.1f" % h["volume_pace_x"]) if h["volume_pace_x"] else "-", h["avg_turnover_cr"], h["quote_time"],
            ", ".join(LIVE_WORDS.get(s) or WORDS[s] for s in h["setups"])))
    if len(hits) > a.show:
        print("... and %d more (--show N, or --json)." % (len(hits) - a.show))
    print("'vol/day' is today's volume so far as a multiple of an average FULL day. 'pace x' divides that by the share of")
    print("the session gone; it overstates in the first hour. Yahoo's quotes are free and can lag a few minutes: check the")
    print("price in Kite. A scan lists charts that match a rule, not stocks to buy; see `swing.py backtest --all`.")
    return 0 if hits else 1


def cmd_backtest(a):
    if not a.all and a.setup not in SETUPS:
        raise SwingError("--setup is one of %s (or --all)" % ", ".join(SETUPS))
    dates, stocks, skipped = _load(a, a.days)
    cfg = _cfg(a.config)
    risk = a.risk or cfg["swing_max_loss_per_trade_inr"]
    max_pos = cfg["swing_capital"] * cfg["swing_max_position_pct"] / 100.0
    rows = []
    for setup in (SETUPS if a.all else (a.setup,)):
        trades, base = backtest(stocks, setup, a.stop_atr, a.target_r, a.hold, a.min_turnover_cr, risk, max_pos, len(dates))
        st, gross = summary(trades), summary(trades, "r")
        base_avg = sum(base) / len(base) if base else 0.0
        split = halves(trades, len(dates))
        rows.append({"setup": setup, "stats": st, "gross": gross, "baseline_avg_r": round(base_avg, 3),
                     "baseline_trades": len(base), "stability": split,
                     "verdict": verdict(st, gross, base_avg, split) if st else "It never fired on a stock this account could buy."})
    doc = {"from": dates[0].isoformat(), "to": dates[-1].isoformat(), "sessions": len(dates), "stocks": len(stocks),
           "rules": {"stop_atr": a.stop_atr, "target_r": a.target_r, "hold": a.hold, "risk_inr": risk,
                     "max_position_inr": max_pos, "min_turnover_cr": a.min_turnover_cr}, "results": rows}
    if a.json:
        print(json.dumps(doc, indent=2))
        return 0
    print("Backtest %s to %s (%d sessions, %d stocks). Buy next open, stop %sx ATR, target %sR, out after %d sessions."
          % (dates[0], dates[-1], len(dates), len(stocks), a.stop_atr, a.target_r, a.hold))
    print("Sized to Rs %s risk and a Rs %s position cap; R is after Zerodha delivery charges." % (risk, "{:,.0f}".format(max_pos)))
    print("%-16s %7s %5s %6s %8s %8s %6s %7s %7s  %s" % ("setup", "trades", "days", "win %", "gross R", "net R", "PF", "streak", "base R", "1st half / 2nd half"))
    for r in rows:
        st = r["stats"]
        if not st:
            print("%-16s %7s" % (r["setup"], 0))
            continue
        sp = r["stability"]
        print("%-16s %7d %5d %6.1f %+8.3f %+8.3f %6s %7d %+7.3f  %s / %s" % (
            r["setup"], st["trades"], sp["signal_days"], r["gross"]["win_pct"], r["gross"]["avg_r"], st["avg_r"],
            st["profit_factor"] if st["profit_factor"] is not None else "-", st["worst_losing_streak"], r["baseline_avg_r"],
            "%+.3f" % sp["first_half_r"] if sp["first_half_r"] is not None else "-",
            "%+.3f" % sp["second_half_r"] if sp["second_half_r"] is not None else "-"))
    for r in rows:
        print("  %s: %s" % (WORDS[r["setup"]], r["verdict"]))
    print("'gross R' is the average result before charges, 'net R' after them, in units of the risk. 'PF' is rupees won")
    print("per rupee lost, after charges. 'streak' is the longest run of losing trades. 'base R' is the same exit on any")
    print("liquid stock on any day, before charges. 'win %' is before charges. 'days' is how many different sessions the")
    print("signals came from. The halves are gross R in the first and second half of the tested sessions.")
    print("One year, one market, no slippage, every signal taken, and only stocks still listed today: real results will be")
    print("worse. A stock locked at its upper circuit cannot be bought at the next open. Not a prediction.")
    return 0


def cmd_plan(a):
    sym = a.symbol.upper()
    dates, stocks, _ = _load(a, 260)
    if sym not in stocks:
        raise SwingError("%s has no unbroken, unadjusted history in the cache (new listing, a gap, or a split/bonus)" % sym)
    p = plan(sym, stocks[sym], _cfg(a.config), a.stop_atr, a.target_r)
    p["as_of"] = dates[-1].isoformat()
    if a.write:
        os.makedirs(os.path.join("trader", "swing"), exist_ok=True)
        with open(os.path.join("trader", "swing", "plan-%s.json" % sym), "w", encoding="utf-8") as fh:
            json.dump(p, fh, indent=2)
    print(json.dumps(p, indent=2) if a.json else render_plan(p))
    return 0 if p["qty"] >= 1 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Swing scans, backtest and plan (trader-swing).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("sync", help="download NSE's daily files")
    p.add_argument("--days", type=int, default=260)
    p = sub.add_parser("scan")
    p.add_argument("--setups")
    p.add_argument("--min-turnover-cr", type=float, default=2.0)
    p.add_argument("--min-price", type=float, default=20.0)
    p.add_argument("--max-price", type=float, default=1e9)
    p.add_argument("--show", type=int, default=25)
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("live", help="the setups on today's prices so far")
    p.add_argument("--setups")
    p.add_argument("--min-turnover-cr", type=float, default=2.0)
    p.add_argument("--min-price", type=float, default=20.0)
    p.add_argument("--max-price", type=float, default=1e9)
    p.add_argument("--show", type=int, default=25)
    p.add_argument("--pause", type=float, default=0.3)
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("backtest")
    p.add_argument("--setup")
    p.add_argument("--all", action="store_true")
    p.add_argument("--days", type=int, default=260)
    p.add_argument("--hold", type=int, default=10)
    p.add_argument("--stop-atr", type=float, default=2.0)
    p.add_argument("--target-r", type=float, default=2.0)
    p.add_argument("--min-turnover-cr", type=float, default=2.0)
    p.add_argument("--risk", type=float)
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("plan")
    p.add_argument("symbol")
    p.add_argument("--stop-atr", type=float, default=2.0)
    p.add_argument("--target-r", type=float, default=2.0)
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--write", action="store_true")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "sync":
            new, n = bhav.sync(a.days, say=lambda m: print(m, file=sys.stderr))
            print("%d new file(s), %d sessions cached." % (new, n))
            return 0
        if a.cmd in ("scan", "live", "backtest", "plan"):
            return {"scan": cmd_scan, "live": cmd_live, "backtest": cmd_backtest, "plan": cmd_plan}[a.cmd](a)
    except (SwingError, bhav.BhavError) as e:
        print("swing.py: %s" % e, file=sys.stderr)
        return 1
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
