---
name: trader
description: >-
  Start here. The guided front door to the NSE trading pack: asks what you
  want to do (morning routine, find an intraday trade, find a swing trade,
  research a small company, check results, manage an open trade, review your
  record) and walks the right skills in the right order, one step at a time,
  in plain words. Knows the two tracks (intraday MIS and swing CNC), your
  limits in trader/config.json, and when to use the Kite and NSE connectors
  for live data. Use when the user says "trader", "start", "what should I do
  today", "morning routine", "walk me through a trade", "help me trade",
  "where do I begin", or names no specific skill.
argument-hint: "[morning | intraday | swing | gems | results | manage | review]"
---

# trader

One command for the whole pack. Ask the user which of the seven routes below they
want (or take it from their words), then run that route step by step. After each
step say what it found in two or three plain sentences and what comes next. Stop
whenever a step says stop.

Every tool is at `~/.claude/skills/<skill>/<tool>.py` (or the plugin's folder) and
is run from the user's trading folder, where everything lands in `trader/`.

## Before anything else: three facts to say once

1. **No rule here has shown a reliable edge.** `swing.py backtest --all` on a year
   of NSE data (to 2026-11-13) found five of six popular setups no better than
   buying any stock on any day, and the sixth unstable. The pack's value is small
   losses, honest odds and a record of what you did, not a winning signal.
2. **You place every order yourself.** Nothing here places, changes or cancels an order.
3. **Most people who day trade lose money.** If the user states a profit target
   ("double it", "8x in three months"), say plainly that no method does that
   reliably and that chasing it means oversized bets. Do not size up to meet a target.

## First run only

```bash
mkdir -p trader && cp <skills>/trader-budget/config.example.json trader/config.json
python3 <skills>/trader-scanner/scan.py universe        # the NSE EQ list
python3 <skills>/trader-swing/swing.py sync             # a year of NSE daily files, about 2 minutes
```

The example config is for a Rs 25,000 account: Rs 250 max loss a trade (1 %),
Rs 500 a day, 2 intraday trades a day, 3 swing positions at most. Ask the user
for their real numbers and edit the file. If money is added monthly, raise
`budget` and `swing_capital` when it arrives, not before.

## The seven routes

| route | when | steps |
| --- | --- | --- |
| **morning** | before 9:15 | `swing.py sync` (yesterday's file) -> `/trader-news` for holdings and watchlist (results due today?) -> `/trader-scanner daily` -> `/trader-swing scan` -> `/trader-deals` |
| **intraday** | 9:35 to 15:00 | `/trader-scanner orb` -> user picks one -> `/trader-news` -> `/trader-entry` -> `/trader-exit` -> `/trader-timemachine` -> `/trader-budget` -> `/trader-risk` -> `/trader-broker` -> `/trader-alerts` |
| **swing** | after the close, or before the open | `/trader-swing scan` -> `backtest` for the setup that fired -> user picks one -> `/trader-news` and `/trader-analyst` -> `/trader-swing plan` -> user places CNC buy and a GTT OCO -> `/trader-journal add` when closed |
| **gems** | any time | `/trader-gems screen` -> user picks one -> `gems.py show` -> the research checklist in trader-gems -> if still interested, `/trader-swing plan` for size |
| **results** | when a company reports | `/trader-news` -> save and read the filing -> `/trader-analyst` -> price and volume reaction |
| **manage** | a trade is open | `/trader-alerts check` -> stop or target hit: record the fill with `/trader-broker` -> at 15:10 for intraday: `ticket.py flatten` |
| **review** | weekly | `/trader-journal report` -> compare with the backtest and the limits -> one thing to change |

## Using the connectors (when they are connected)

Claude may have a Zerodha Kite connector and NSE data connectors in this session.
The Python tools cannot see them; Claude can. Use them like this:

- **Live price, circuit limits, depth:** Kite `market` with `mode=quote` and
  `instruments=["NSE:SYMBOL"]`. Before any entry, read `upper_circuit_limit` and
  `lower_circuit_limit`: a stock near a circuit can lock and trap the position.
  Write the price into `trader/prices.json` as `{"as_of": "...Z", "prices": {"SYMBOL": 123.45}}`
  so `/trader-risk` measures the trade from the real price.
- **Intraday candles:** Kite `market` with `mode=historical`, `interval=5minute`
  (find the `instrument_token` with `mode=search`). Official, and it has the last bars Yahoo lacks.
- **Volume history and corporate actions:** the NSE connector's `get_volume_analysis`
  and `get_corporate_actions`. Always check corporate actions for a stock a scan
  flagged: a split or bonus makes old prices look like a crash or a breakout.
- **Holdings and positions:** Kite `portfolio`, read only, to check quantities before a flatten ticket.
- **Never** call Kite `orders`, `gtt` or `alerts` to place, modify or cancel anything, even if asked.
  Say: "I can't place trades. Here is the exact form; you place it in Kite."
- If a connector is missing or errors, say so and fall back to the tools' Yahoo data.

## Rules

- One step at a time. Never run the whole chain and present a finished "trade idea".
- Never pick the stock for the user and never say buy, sell or hold. Lists are lists.
- Say the odds the tools print, including when they are bad.
- If `/trader-risk` says BLOCK, the route ends.
- Not financial advice. For advice, a SEBI-registered adviser.

## Safety

- Education and tooling, not financial advice.
- No skill in this pack places an order. You place every order yourself in Zerodha Kite.
