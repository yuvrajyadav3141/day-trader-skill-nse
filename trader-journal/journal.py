#!/usr/bin/env python3
"""Trade journal for trader-journal: what your own trades actually did, after charges. Standard library only.

    python3 journal.py report                       # every closed trade so far
    python3 journal.py report --since 2026-11-01 --json
    python3 journal.py add --symbol DHANBANK --qty 58 --buy 40.25 --sell 43.10 \\
        --bought 2026-11-16 --sold 2026-11-24 --setup volume_shocker        # a trade made outside the pack

Where trades come from:
  trader/state/broker.json   the fills trader-broker logged (`ticket.py placed --filled-*`, `ticket.py fill`).
                             Buys and sells of a symbol are paired first in, first out.
  trader/journal.json        trades you add by hand with `add` (swing trades, anything placed outside the pack).
A buy and sell on the same date is costed as intraday (MIS); otherwise as delivery (CNC). Charges are
Zerodha's published rates (trader-data/charges.py), not your contract note: the note is the truth.

The report: trades, win rate, average win and loss, net result after charges, what charges took,
expectancy a trade, the longest losing run, and the same split by setup and by style. Shares
still held are listed as open and are not counted.
It reports the past. It does not say what the next trade will do.
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-data"))
import charges  # noqa: E402


class JournalError(Exception):
    pass


def _read(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise JournalError("%s is not valid JSON: %s" % (path, e))


def pair_fills(fills):
    """Broker-log fills -> (closed trades, open lots). First in, first out per symbol."""
    lots, closed = {}, []
    for f in sorted(fills, key=lambda f: (f.get("date", ""), f.get("at", ""))):
        sym, qty, price, day = f["symbol"].upper(), float(f["qty"]), float(f["price"]), f.get("date", "")
        if f["side"] == "buy":
            lots.setdefault(sym, []).append({"qty": qty, "price": price, "date": day})
            continue
        left = qty
        for lot in lots.get(sym, []):
            if left <= 1e-9:
                break
            take = min(left, lot["qty"])
            if take <= 1e-9:
                continue
            closed.append({"symbol": sym, "qty": take, "buy": lot["price"], "sell": price, "bought": lot["date"],
                           "sold": day, "setup": f.get("setup") or "", "source": "broker log"})
            lot["qty"] -= take
            left -= take
        lots[sym] = [l for l in lots.get(sym, []) if l["qty"] > 1e-9]
    open_lots = [dict(l, symbol=s) for s, ls in lots.items() for l in ls]
    return closed, open_lots


def cost(t):
    """Add style, charges, gross and net to one closed trade."""
    delivery = t["bought"] != t["sold"]
    c = charges.round_trip(t["buy"], t["sell"], int(round(t["qty"])) or 1, delivery)
    t = dict(t, style="swing" if delivery else "intraday", gross=c["gross"], charges=c["total"], net=c["net"])
    return t


def stats(trades):
    if not trades:
        return None
    nets = [t["net"] for t in trades]
    wins, losses = [n for n in nets if n > 0], [n for n in nets if n <= 0]
    run = worst = 0
    for t in sorted(trades, key=lambda t: (t["sold"], t["bought"])):
        run = run + 1 if t["net"] <= 0 else 0
        worst = max(worst, run)
    return {"trades": len(nets), "win_pct": round(100.0 * len(wins) / len(nets), 1),
            "net": round(sum(nets), 2), "gross": round(sum(t["gross"] for t in trades), 2),
            "charges": round(sum(t["charges"] for t in trades), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "expectancy": round(sum(nets) / len(nets), 2), "biggest_loss": round(min(nets), 2),
            "longest_losing_run": worst}


def build(broker_path, journal_path, since=None):
    state = _read(broker_path, {"orders": []})
    fills = [r for r in state.get("orders", []) if r.get("status") == "filled"]
    closed, open_lots = pair_fills(fills)
    closed += [dict(t, source="added by hand") for t in _read(journal_path, {"trades": []}).get("trades", [])]
    closed = [cost(t) for t in closed if not since or t["sold"] >= since]
    groups = {}
    for key in ("style", "setup"):
        for t in closed:
            groups.setdefault(key, {}).setdefault(t[key] or "(no setup noted)", []).append(t)
    return {"all": stats(closed), "by_style": {k: stats(v) for k, v in groups.get("style", {}).items()},
            "by_setup": {k: stats(v) for k, v in groups.get("setup", {}).items()},
            "open": open_lots, "trades": sorted(closed, key=lambda t: t["sold"])}


def _line(name, s):
    return "  %-22s %4d trades  win %5.1f%%  net %+10.2f  (charges %8.2f)  avg win %s  avg loss %s  per trade %+.2f" % (
        name, s["trades"], s["win_pct"], s["net"], s["charges"],
        "%+.2f" % s["avg_win"] if s["avg_win"] is not None else "-",
        "%+.2f" % s["avg_loss"] if s["avg_loss"] is not None else "-", s["expectancy"])


def render(doc):
    a = doc["all"]
    if not a:
        return "No closed trades yet." + ("  %d position(s) still open." % len(doc["open"]) if doc["open"] else "")
    L = ["Journal: %d closed trades. Net after charges Rs %+.2f (before charges %+.2f; charges took %.2f)."
         % (a["trades"], a["net"], a["gross"], a["charges"]),
         "Won %.1f%% of them. Average win %s, average loss %s, biggest loss %+.2f, longest losing run %d."
         % (a["win_pct"], "%+.2f" % a["avg_win"] if a["avg_win"] is not None else "-",
            "%+.2f" % a["avg_loss"] if a["avg_loss"] is not None else "-", a["biggest_loss"], a["longest_losing_run"]),
         "By style:"]
    L += [_line(k, s) for k, s in sorted(doc["by_style"].items())]
    L.append("By setup:")
    L += [_line(k, s) for k, s in sorted(doc["by_setup"].items(), key=lambda kv: kv[1]["net"])]
    if a["gross"] > 0 and a["net"] <= 0:
        L.append("You were right more than wrong before charges, and charges turned it into a loss: trade less, or bigger moves.")
    if a["avg_win"] is not None and a["avg_loss"] is not None and a["avg_win"] < -a["avg_loss"]:
        L.append("Your average loss is bigger than your average win, so you need to win well over half the time to break even.")
    if a["trades"] < 30:
        L.append("%d trades is too few to judge a method. Win rates swing wildly on small samples." % a["trades"])
    if doc["open"]:
        L.append("Still open (not counted): " + ", ".join("%s %g @ %.2f" % (o["symbol"], o["qty"], o["price"]) for o in doc["open"]))
    L.append("Charges are estimated from Zerodha's published rates; your contract notes are the truth. Not financial advice.")
    return "\n".join(L)


def cmd_add(a):
    for d in (a.bought, a.sold):
        try:
            datetime.date.fromisoformat(d)
        except ValueError:
            raise JournalError("dates look like 2026-11-16, not %r" % d)
    if a.qty <= 0 or a.buy <= 0 or a.sell <= 0 or a.sold < a.bought:
        raise JournalError("qty, buy and sell must be above 0, and --sold cannot be before --bought")
    doc = _read(a.journal, {"trades": []})
    doc["trades"].append({"symbol": a.symbol.upper(), "qty": a.qty, "buy": a.buy, "sell": a.sell, "bought": a.bought,
                          "sold": a.sold, "setup": a.setup or "", "note": a.note or ""})
    d = os.path.dirname(a.journal)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(a.journal, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    t = cost(doc["trades"][-1])
    print("Added %s: %s, net Rs %+.2f after Rs %.2f charges." % (t["symbol"], t["style"], t["net"], t["charges"]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Your closed trades, after charges (trader-journal).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("report")
    p.add_argument("--since", help="YYYY-MM-DD: only trades closed on or after this date")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("add")
    p.add_argument("--symbol", required=True)
    p.add_argument("--qty", type=float, required=True)
    p.add_argument("--buy", type=float, required=True)
    p.add_argument("--sell", type=float, required=True)
    p.add_argument("--bought", required=True)
    p.add_argument("--sold", required=True)
    p.add_argument("--setup")
    p.add_argument("--note")
    for q in sub.choices.values():
        q.add_argument("--broker", default="trader/state/broker.json")
        q.add_argument("--journal", default="trader/journal.json")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "add":
            return cmd_add(a)
        if a.cmd == "report":
            doc = build(a.broker, a.journal, a.since)
            print(json.dumps(doc, indent=2) if a.json else render(doc))
            return 0 if doc["all"] else 1
    except JournalError as e:
        print("journal.py: %s" % e, file=sys.stderr)
        return 1
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
