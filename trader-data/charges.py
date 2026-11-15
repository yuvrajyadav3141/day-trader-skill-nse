#!/usr/bin/env python3
"""What a round trip costs at Zerodha, NSE equity. Standard library only.

    python3 charges.py --buy 1311.90 --sell 1323.00 --qty 45              # intraday (MIS)
    python3 charges.py --buy 184.00 --sell 200.00 --qty 20 --delivery     # delivery (CNC)

Rates from zerodha.com/charges (read 2026-11-15). They change: check that page.
  intraday  brokerage 0.03 % or Rs 20 an order, whichever is lower; STT 0.025 % on the sell
            side; stamp 0.003 % on the buy side
  delivery  brokerage zero; STT 0.1 % on buy and sell; stamp 0.015 % on the buy side;
            DP charge Rs 15.34 per stock on the day you sell
  both      NSE transaction charge 0.00307 %; SEBI Rs 10 a crore; GST 18 % on
            (brokerage + SEBI + transaction charge)
Not included: the Rs 50 + GST Zerodha charges when IT squares off an MIS position for you,
and income tax.
"""

import argparse
import sys

RATES_AS_OF = "2026-11-15"
TXN_NSE = 0.0000307
SEBI = 10.0 / 1e7
GST = 0.18
DP_SELL = 15.34


def round_trip(buy, sell, qty, delivery=False):
    """Charges for buying qty at `buy` and selling them at `sell`. Returns a dict in rupees."""
    bv, sv = buy * qty, sell * qty
    turnover = bv + sv
    if delivery:
        brokerage = 0.0
        stt = round(0.001 * turnover)
        stamp = 0.00015 * bv
        dp = DP_SELL
    else:
        brokerage = min(20.0, 0.0003 * bv) + min(20.0, 0.0003 * sv)
        stt = round(0.00025 * sv)
        stamp = 0.00003 * bv
        dp = 0.0
    txn = TXN_NSE * turnover
    sebi = SEBI * turnover
    gst = GST * (brokerage + txn + sebi)
    total = brokerage + stt + txn + sebi + gst + stamp + dp
    gross = sv - bv
    return {"brokerage": round(brokerage, 2), "stt": float(stt), "transaction": round(txn, 2), "sebi": round(sebi, 2),
            "gst": round(gst, 2), "stamp": round(stamp, 2), "dp": dp, "total": round(total, 2),
            "gross": round(gross, 2), "net": round(gross - total, 2),
            "breakeven_per_share": round(total / qty, 2) if qty else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Zerodha NSE equity charges for one round trip.")
    ap.add_argument("--buy", type=float, required=True)
    ap.add_argument("--sell", type=float, required=True)
    ap.add_argument("--qty", type=int, required=True)
    ap.add_argument("--delivery", action="store_true", help="CNC delivery instead of MIS intraday")
    a = ap.parse_args(argv)
    if a.buy <= 0 or a.sell <= 0 or a.qty <= 0:
        print("charges.py: buy, sell and qty must be above 0", file=sys.stderr)
        return 1
    c = round_trip(a.buy, a.sell, a.qty, a.delivery)
    print("%s, %d shares, buy %.2f, sell %.2f (rates as of %s)" % (
        "Delivery (CNC)" if a.delivery else "Intraday (MIS)", a.qty, a.buy, a.sell, RATES_AS_OF))
    for k in ("brokerage", "stt", "transaction", "sebi", "gst", "stamp", "dp"):
        print("  %-12s %10.2f" % (k, c[k]))
    print("  %-12s %10.2f" % ("TOTAL", c["total"]))
    print("Gross %+.2f, net of charges %+.2f. The price must move %.2f a share just to cover charges."
          % (c["gross"], c["net"], c["breakeven_per_share"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
