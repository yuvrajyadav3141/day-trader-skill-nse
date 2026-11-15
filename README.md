# The Day Trader skill, for the NSE

15 Claude skills for trading on the NSE: intraday and swing scans with honest backtests, a small-company fundamentals screen, results research, risk limits, charges and a journal. You place the orders.

This is a port of [jakeschincariol/day-trader-skill](https://github.com/jakeschincariol/day-trader-skill) (MIT, US stocks) to India: IST clock, NSE holidays, NSE symbols, rupees and the 0.05 tick. The original is the work of its author; the port changes the market, not the method.

Free, MIT, no signup. The tools are plain Python (3.8 or newer, nothing to pip install) that read public data: Yahoo Finance charts for NSE symbols (or Zerodha Kite Connect, optional), NSE's own RSS feeds and CSV files.

## What changed from the US version

| | US original | This port |
| --- | --- | --- |
| Clock | New York, DST, NYSE holidays, 9:30 to 16:00 | IST (UTC+5:30, no DST), 16 NSE holidays for 2026, 9:15 to 15:30 |
| Opening range | 9:30, 9:35, 9:40 bars | 9:15, 9:20, 9:25 bars |
| Entry window / flat by | 09:45 to 15:30 / 15:55 | 09:30 to 15:00 / 15:10 (Zerodha squares off MIS around 3:20 PM) |
| Universe | Nasdaq Trader lists | NSE `EQUITY_L.csv`, EQ series (about 2,390 stocks) |
| Prices | Yahoo | Yahoo `SYMBOL.NS`, or Kite Connect for single-symbol charts (`trader-data/`) |
| Orders | Alpaca or IBKR connector, with a typed "yes" | **You place every order yourself in Kite**; `/trader-broker` prints the form and keeps the log |
| News | Yahoo headlines and SEC 8-Ks | NSE RSS: quarterly results, board meetings, announcements |
| Earnings analyst | SEC XBRL | Yahoo fundamentals time series, in crore |
| Pelosi tracker | House Clerk disclosures | `/trader-deals`: NSE bulk and block deals |
| Money | dollars, cents | rupees, 5-paisa tick; config keys end `_inr` |

## Install

You need Python 3.8 or newer (check with `python3 --version`) and [Claude Code](https://claude.com/claude-code) or the Claude desktop app. Nothing to pip install. Tested on macOS only; Linux should work, Windows is untested.

**1. Install the skills, either way**

*A. As a plugin, straight from GitHub (no clone):* in Claude Code run

```
/plugin marketplace add yuvrajyadav3141/day-trader-skill-nse
/plugin install day-trader-skills-nse@day-trader-skills-nse
```

In the desktop app `/plugin` opens a window instead: add `yuvrajyadav3141/day-trader-skill-nse` there as a marketplace, then install `day-trader-skills-nse`. Plugin skills are namespaced, e.g. `/day-trader-skills-nse:trader-scanner`.

*B. Copy the folders (gives plain names like `/trader-scanner`):*

```bash
git clone https://github.com/yuvrajyadav3141/day-trader-skill-nse.git
cd day-trader-skill-nse
mkdir -p ~/.claude/skills
cp -R trader trader-* ~/.claude/skills/
```

Copy `trader-data` too: the `trader-*` pattern includes it, and the tools import it. Start a new Claude session afterwards. To update later, `git pull` and run the same `cp -R` again.

*No Claude Code?* Paste any one `SKILL.md` at the top of a chat and it works as a mode. You lose the Python tools, but the method stays.

**2. Set your rules**

In the folder where you will trade (any folder; the tools write a `trader/` folder there):

```bash
mkdir -p trader
cp ~/.claude/skills/trader-budget/config.example.json trader/config.json
```

Edit `trader/config.json`: `budget`, `max_loss_per_trade_inr` and `max_daily_loss_inr` first. The example is for a Rs 25,000 account: 25,000, 250 and 500, with a separate `swing_*` set for delivery trades. Everything else (entry window 09:30 to 15:00, flat by 15:10, `"product": "MIS"`) can stay.

**3. Run it**

Ask Claude, or run the tools directly:

```bash
python3 ~/.claude/skills/trader-scanner/scan.py universe     # once: the NSE EQ list
python3 ~/.claude/skills/trader-scanner/scan.py daily        # before the open
python3 ~/.claude/skills/trader-scanner/scan.py orb          # after 9:35 AM IST
python3 ~/.claude/skills/trader-swing/swing.py sync          # a year of NSE daily files, about 2 minutes
python3 ~/.claude/skills/trader-swing/swing.py scan          # multi-day setups
python3 ~/.claude/skills/trader-swing/swing.py backtest --all
python3 ~/.claude/skills/trader-gems/gems.py fetch           # one to two hours, once; then: gems.py screen
```

Then the order of the pack is: scanner, news, entry, exit, timemachine, budget, risk, broker. Each step reads what the one before wrote into `trader/`.

**4. Optional: Zerodha Kite Connect for prices**

The default is free Yahoo data and needs no account. If you have a Kite Connect plan with historical data:

```bash
export TRADER_DATA_SOURCE=kite
export KITE_API_KEY=your_key
export KITE_ACCESS_TOKEN=today_token     # Zerodha expires it every morning
```

You run Zerodha's login yourself; the tools never see your password or TOTP and never log in for you. See `trader-data/README.md`. The Kite path is untested against the live API: compare one `entry.py check` with Yahoo before relying on it.

**Troubleshooting**

- *NSE feed returns 403 or times out:* NSE's CDN refuses some clients. The tools say so and stop; they do not try to look like a browser. Try again later, or use `--offline` with saved files.
- *"holiday list unknown":* the built-in NSE holiday list covers 2026 only. Check nseindia.com, and see Contributing below.
- *Yahoo is slow or rate-limiting:* wait a minute; the tools retry once.

## Start here

Type `/trader`. It asks what you want to do and walks the right skills in order: morning routine, an intraday
trade, a swing trade, small-company research, results, managing an open trade, or a weekly review.

## What the backtest says (read this first)

`/trader-swing backtest --all` on a year of NSE data (2025-10-24 to 2026-11-13, 2,298 stocks), buying the next open
after a signal, stop 2x ATR, target 2R, out after 10 sessions, on a Rs 25,000 account:

| setup | trades | win % | before charges | after charges | first half / second half |
| --- | --- | --- | --- | --- | --- |
| volume shocker | 3,152 | 42.5 | -0.031 R | -0.129 R | -0.019 / -0.042 |
| 9/21 EMA cross | 4,540 | 45.9 | -0.093 R | -0.614 R | -0.117 / -0.068 |
| 20/50 EMA cross | 2,383 | 45.4 | -0.239 R | -0.843 R | -0.397 / +0.007 |
| 52-week closing high | 982 | 41.2 | -0.058 R | -0.645 R | - / -0.058 |
| gap up | 1,221 | 58.6 | +0.213 R | +0.117 R | +0.313 / -0.084 |
| momentum leader | 3,911 | 37.4 | -0.157 R | -0.254 R | - / -0.157 |

R is the result in units of the money risked. Buying any liquid stock on any day with the same exit: -0.015 R.
**Five of the six popular setups did no better than that, and the sixth only worked in the first half of the year.**
Charges on a small account made every one worse. This is one year with no slippage, so real results would be worse
still. The pack does not contain a winning signal. What it gives you is small, fixed losses, honest odds before a
trade, proper research, and a record of what you actually did.

## The fifteen

| command | job |
| --- | --- |
| `/trader` | The guided front door: one step at a time, both tracks. |
| **Find** | |
| `/trader-scanner` | Intraday: opening-range breakouts, flags, oversold bounces across the NSE EQ list. |
| `/trader-swing` | Multi-day: volume shockers, EMA crossovers, 52-week highs, gap-ups, momentum, each with a backtest; plans a CNC position. |
| `/trader-gems` | Small companies: low debt, cash flow, growth, land on the books; then a reading checklist. |
| `/trader-deals` | Bulk and block deals, with the clients who made them. |
| **Research** | |
| `/trader-news` | Quarterly results, board meetings and announcements from NSE's feeds; downloads the filing to read. |
| `/trader-analyst` | Last quarters' revenue, profit, EPS and margins side by side. |
| **Plan an intraday trade** | |
| `/trader-entry` | Watches a setup bar by bar and says when it triggers. |
| `/trader-exit` | Sets the stop and target (on the 0.05 tick) before you enter. |
| `/trader-timemachine` | Replays the rest of the session 10,000 times plus every past day the setup fired. |
| `/trader-budget` | Sizes the position to your max loss, and shows the result after Zerodha charges. |
| `/trader-risk` | Checks the trade against your limits. PASS or BLOCK, with the reason. |
| **Place and manage** | |
| `/trader-broker` | Prints the Kite order form and logs your fills. You place the order. |
| `/trader-alerts` | Rings on the stop, the target, the 9:15 open and flat-by 15:10. |
| **Review** | |
| `/trader-journal` | Your closed trades after charges: win rate, average win and loss, by setup. |

## Connectors

If Claude has the Zerodha Kite and NSE connectors in the session, the skills use them for live quotes, circuit
limits, 5-minute candles, volume history and corporate actions, and fall back to free Yahoo data without them.
They are read-only here: no skill places, modifies or cancels an order through a connector.

## One trade, run live on 2026-11-06

RELIANCE, Friday 2026-11-06, Yahoo data, replayed at 10:30 AM IST:

1. `/trader-entry`: opening range 1295.60 to 1306.00; the 9:45 bar closed at 1311.90, above it: **TRIGGERED, 9:50 AM**.
2. `/trader-exit`: stop 1300.80 (range midpoint), target 1323.00 (1R), risk 11.10 a share, flat by 15:10.
3. `/trader-timemachine`: 10,000 replays on RELIANCE's last 58 full sessions: target first 27.4 %, stop first 38.9 %, 33.7 % still open at 3:10 PM. On those sessions the same rule fired 28 times: 13 target, 10 stop, 5 neither. Verdict: leans toward the stop.
4. `/trader-budget` (run then with a ₹1,00,000 budget and ₹500 max loss per trade): 45 shares, ₹59,035.50, max loss ₹499.50.
5. `/trader-risk`: PASS at 10:30; BLOCK at 09:20 (before 09:30), at 15:05 (after 15:00) and on 2026-11-10 (Diwali-Balipratipada, NSE closed).
6. `/trader-broker`: the Kite form, READY. You place the buy, then the SL-M stop and the LIMIT target, and log them.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Offline. The fixtures are saved NSE feeds (2026-11-06), Yahoo fundamentals for TCS and RELIANCE, and a made-up session for the trade chain.
**The US version's 300-odd tests were written around its US fixtures (TSLA bars, SEC filings, House PTRs) and were not ported:**
they are in the git history's first commit. The new suite covers the NSE changes and the trade chain, not every engine
path the old one did. The Time Machine's engine, for example, was checked by a live run, not by its old tests.

## Fine print

**Not financial advice.** This is software that reads public data and does arithmetic. It cannot see the future.
Most people who day trade lose money. You can lose money. Talk to a SEBI-registered adviser if you need advice.

**You place every order.** Nothing in this pack can place an order. `/trader-risk` can say PASS, and `/trader-broker`
prints the form; the click in Kite is yours.

**A stop is a plan, not a guarantee.** Kite has no bracket order, so the stop (SL-M) and the target (LIMIT) are
two separate orders that do not cancel each other: cancel the other one when one fills. In a fast market or across
a gap a stop can fill well past its trigger.

**The data is free and unofficial.** Yahoo's chart endpoint can lag, change or rate-limit you, and has no price for the last
two five-minute bars on most NSE days. NSE's RSS feeds hold only recent filings, and the feeds name companies, not symbols.
Check anything that matters in Kite before you act on it.

**Not modelled:** the Diwali Muhurat session, 2027 holidays (not published when this was written; the tools say
"unknown" instead of guessing), slippage, MIS leverage (the budget
counts full price), F&O, and SEBI insider-trading (PIT) disclosures.

**The fundamentals screen is a filter, not research.** Land is at book cost, debt is as of the last balance sheet,
Yahoo's numbers for small companies have errors, and the screen cannot see promoter pledges or auditor remarks.
Screener.in is not read by the tools: its terms allow personal viewing only.

**Taxes.** Intraday equity gains are taxed as speculative business income in India. Nothing here is tax advice.

## Contributing

Issues and pull requests are welcome, especially: the 2027 NSE holiday list when it is published (it lives in `NSE_HOLIDAYS` in each script, and `tests/test_nse.py` checks that they agree), a live test of the Kite path, and ports of the old engine tests. Run `python3 -m unittest discover -s tests` before sending anything. Keep the standard-library-only rule.

## Files

```
trader-*/SKILL.md      the skill (what Claude reads)
trader-*/*.py          the tool (what Claude runs)
trader/SKILL.md        the guided front door
trader-data/           shared code: NSE daily files, Zerodha charges, optional Kite Connect source
tests/                 offline tests and fixtures
```

MIT, as the original. See LICENSE.
