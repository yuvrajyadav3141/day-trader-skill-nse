---
name: trader-journal
description: >-
  Trade Journal. Shows what your own trades actually did after charges: win
  rate, average win and loss, net result, what Zerodha's charges took,
  expectancy a trade, the longest losing run, split by setup and by style
  (intraday or swing). Reads the fills trader-broker logged and any trade
  you add by hand, and estimates charges for one round trip. Use when the
  user says "how am I doing", "my win rate", "review my trades", "journal",
  "log this trade", "what did I make", "weekly review", "how much did
  charges cost", "is this working".
argument-hint: "[report | add]"
---

# trader-journal

The backtest says what a rule did on paper. The journal says what you did with
real money. After twenty or thirty trades it is the only evidence that matters.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/journal.py" report
python3 "${CLAUDE_SKILL_DIR}/journal.py" report --since 2026-11-01 --json
python3 "${CLAUDE_SKILL_DIR}/journal.py" add --symbol DHANBANK --qty 58 --buy 40.25 --sell 43.10 \
    --bought 2026-11-16 --sold 2026-11-24 --setup volume_shocker
python3 "${CLAUDE_SKILL_DIR}/../trader-data/charges.py" --buy 1311.90 --sell 1323.00 --qty 15      # one round trip's charges
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/state/broker.json` | fills logged by trader-broker, paired first in, first out per symbol |
| `trader/journal.json` | trades added by hand with `add` (swing trades, anything placed outside the pack) |

A buy and sell on the same date is costed as intraday (MIS), otherwise delivery
(CNC), at Zerodha's published rates as of 2026-11-15 (`trader-data/charges.py`).
The contract note is the truth; these are estimates. Shares still held are listed
as open and not counted.

## Reading the report

- **Net after charges** is the number that matters. On a small account charges are
  large: a Rs 20,000 intraday round trip costs about Rs 21, so a Rs 250 risk loses
  about 8 % of itself to charges before the trade moves.
- **Average win against average loss.** If the average loss is bigger, you need to
  win well over half the time just to break even. The report says so.
- **Under 30 trades** proves nothing either way. Say so.
- **By setup:** stop trading a setup that loses over a fair sample; do not add size to
  one that won five times.
- **Longest losing run:** compare it with the backtest's. A run of eight losses at 1 %
  each is an 8 % drawdown; the user should know that can happen before it does.

## Steps

1. `journal.py report` (weekly is enough). Read the totals, then the weakest line.
2. Compare with the limits in `trader/config.json`: was any loss bigger than
   `max_loss_per_trade_inr`? That is a discipline finding, not a market one.
3. Suggest at most ONE change (fewer trades, a wider target, dropping a setup). Never suggest bigger size to catch up.
4. For a swing trade or anything placed outside the pack, `journal.py add` when it closes.

## What it never does

Never predicts, never says a method "works" on a small sample, never suggests raising risk to recover
losses or to hit a target, never places an order.

## Safety

- Education and tooling, not financial advice.
- No skill in this pack places an order. You place every order yourself in Zerodha Kite.
