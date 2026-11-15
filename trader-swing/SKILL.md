---
name: trader-swing
description: >-
  Swing Scanner for the NSE: multi-day setups on daily bars, each with its own
  backtest. Scans every NSE EQ stock for volume shockers (3x volume with a
  strong close, with delivery percentage), 9/21 and 20/50 EMA crossovers,
  52-week closing highs, gap-ups and momentum leaders, using NSE's official
  daily price files. Backtests any setup on a year of data against a
  buy-anything baseline, after Zerodha charges, with a stability check, and
  says plainly when a rule added nothing. Plans a delivery (CNC) position:
  ATR stop, target, shares sized to your max loss, charges, liquidity
  warnings and the GTT OCO to set in Kite. Use when the user says "volume
  shockers", "EMA crossover", "golden cross", "52 week high", "gap up
  stocks", "swing trade", "positional", "backtest this setup", "does this
  strategy work", "stocks for the week".
argument-hint: "[sync | scan | backtest | plan SYMBOL]"
---

# trader-swing

Swing trades are held for days, bought for delivery (CNC), with no leverage and
no 3:20 PM square-off. This skill finds the setups, tests them, and sizes a
position. It is separate from the intraday chain and has its own limits.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/swing.py" sync                          # NSE daily files -> trader/cache/bhav (first run ~2 min)
python3 "${CLAUDE_SKILL_DIR}/swing.py" scan --write                  # every setup, latest session -> trader/swing/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/swing.py" scan --setups volume_shocker --max-price 500
python3 "${CLAUDE_SKILL_DIR}/swing.py" backtest --all                # every setup's record
python3 "${CLAUDE_SKILL_DIR}/swing.py" backtest --setup gap_up --hold 5 --target-r 1.5
python3 "${CLAUDE_SKILL_DIR}/swing.py" plan DHANBANK --write         # -> trader/swing/plan-DHANBANK.json
```

## The data

NSE publishes one file a trading day with open, high, low, close, volume, turnover
and delivery percentage for every security. `sync` caches them. No key, no login.
Prices are unadjusted: a stock with a suspected split or bonus in the window
(a one-day fall over 35 %) is left out, and the scan says how many. If the NSE
connector is available, confirm with `get_corporate_actions` before trusting a hit.

## The setups

| setup | rule (daily bars, long only) |
| --- | --- |
| `volume_shocker` | volume 3x its 20-session average or more, close up 3 %+, close in the top 30 % of the day's range |
| `ema_9_21` | 9-day EMA crossed above the 21-day today, close above the 50-day EMA |
| `ema_20_50` | 20-day EMA crossed above the 50-day today |
| `high_52w` | highest close of the last 250 sessions, on 1.5x average volume |
| `gap_up` | opened 2 %+ above yesterday's high and closed above its open |
| `momentum` | up 30 %+ over 60 sessions and within 10 % of its 250-session closing high |

Only stocks that traded on each of the last 60 sessions and average 2 crore a day
(`--min-turnover-cr`). The scan shows the volume multiple and the delivery
percentage: a volume spike on 5 % delivery is intraday churn, not buying to hold.

## The backtest, and what it found

Buy at the next session's open after a signal; stop 2x the 14-day ATR below;
target 2R; out at the close after 10 sessions. Results are in R (units of the
risk), before charges (gross) and after Zerodha delivery charges on a position
sized to your max loss (net). The baseline is the same exit on any liquid stock
on any day.

Run on 2025-10-24 to 2026-11-13 (260 sessions, 2,298 stocks), Rs 250 risk, Rs 10,000 position cap:

| setup | trades | win % | gross R | net R | first half / second half | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| volume_shocker | 3,152 | 42.5 | -0.031 | -0.129 | -0.019 / -0.042 | added nothing |
| ema_9_21 | 4,540 | 45.9 | -0.093 | -0.614 | -0.117 / -0.068 | added nothing |
| ema_20_50 | 2,383 | 45.4 | -0.239 | -0.843 | -0.397 / +0.007 | added nothing |
| high_52w | 982 | 41.2 | -0.058 | -0.645 | - / -0.058 | added nothing |
| gap_up | 1,221 | 58.6 | +0.213 | +0.117 | +0.313 / -0.084 | NOT STABLE |
| momentum | 3,911 | 37.4 | -0.157 | -0.254 | - / -0.157 | added nothing |

Baseline: -0.015 R. Read it straight: on this year, taken mechanically, the popular
setups did not beat buying anything, and charges on a small account made each worse.
Gap-up made money only in the first half. This is one year, with no slippage, every
signal taken and only stocks still listed, so real results would be worse. It does
not prove these setups never work; it shows they are not an edge by themselves.

**Always run the backtest for a setup before planning a trade on it, and say its verdict.**
Changing `--hold`, `--stop-atr` and `--target-r` until a number turns green is curve
fitting: if the user tunes them, say so and check that both halves agree.

## The plan

`plan SYMBOL` uses the last close as the reference entry, a stop 2x ATR below
(rounded down to the 0.05 tick) and a 2R target. Shares are the smaller of
`swing_max_loss_per_trade_inr / risk a share` and `swing_max_position_pct` of
`swing_capital`. It prints the loss at the stop and the gain at the target after
charges, and warns when the position is over 1 % of the stock's daily turnover,
when the stock trades under 1 crore a day, or when charges leave reward:risk
under 1.5.

The user then, in Kite: buys as CNC; sets ONE GTT of type OCO on the holding
(lower trigger = stop, upper trigger = target). Tell them: tomorrow's open can be
far from yesterday's close (if it opens beyond the stop or target the plan is
void); a stop fills worse on a gap; a stock locked at its lower circuit cannot be
sold. With the Kite connector, read the circuit limits first.

Keep at most `swing_max_open_positions` (3) open. Check `/trader-news` for a results
date inside the hold: a swing trade is exposed to results, a day trade is not.

## What it never does

Never says buy or sell, never calls a setup a signal that works, never hides a bad
backtest, never places an order, never adjusts prices for corporate actions by guesswork.

## Safety

- Education and tooling, not financial advice.
- No skill in this pack places an order. You place every order yourself in Zerodha Kite.
