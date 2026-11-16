---
name: trader-gems
description: >-
  Small-company fundamentals screen for the NSE, with a research checklist.
  Screens NSE EQ stocks on market value (50 to 2,000 crore by default), debt
  to equity (nearly debt free), cash from operations, profit and revenue
  growth, and shows return on equity, P/E, P/B, net cash, the land on the
  books (at book cost, in crore and as a share of market value) and how much
  the stock trades a day. Then walks the checks no screen can do: promoter
  holding and pledges, auditor remarks, related-party deals, the property
  note in the annual report. Use when the user says "hidden gems", "micro
  cap", "small cap", "debt free companies", "companies with land", "cash
  rich", "undervalued", "multibagger", "fundamentally strong", "screen
  stocks", "find good small companies".
argument-hint: "[fetch | screen | show SYMBOL]"
---

# trader-gems

A screen narrows 2,400 companies to a few dozen that pass a filter. That is all.
Most cheap small companies are cheap for a reason the filter cannot see, so the
second half of this skill is reading, not screening.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/gems.py" fetch                       # once: every company in trader/universe.txt (one to two hours the first time, resumable)
python3 "${CLAUDE_SKILL_DIR}/gems.py" screen --write              # the default screen -> trader/gems.json
python3 "${CLAUDE_SKILL_DIR}/gems.py" screen --max-mcap-cr 500 --max-debt-equity 0 --min-roe 15
python3 "${CLAUDE_SKILL_DIR}/gems.py" screen --min-land-pct 20    # land on the books worth 20 %+ of market value
python3 "${CLAUDE_SKILL_DIR}/gems.py" show 20MICRONS              # four years, line by line
```

**Run `fetch` first, in the same folder you trade from.** The numbers are cached in that folder's
`trader/cache/fund/`; in a new folder `screen` has nothing to read and says so. `screen` works on a partly
fetched cache and prints PARTIAL.

Needs `trader/universe.txt` (`scan.py universe`). The traded-a-day column needs `swing.py sync`.

## Data, and why not Screener.in

Annual numbers come from Yahoo Finance's fundamentals time series, cached 14 days.
Screener.in has better data, but its terms allow only personal, transitory viewing
and forbid copying, and its robots file disallows its query pages, so this tool
does not read it. Instead `screen` prints a ready-made Screener query: the user
pastes it into their own Screener account to cross-check the list.

## The default screen

| filter | default | flag |
| --- | --- | --- |
| market value | 50 to 2,000 crore | `--min-mcap-cr`, `--max-mcap-cr` |
| debt / equity | at most 0.1 | `--max-debt-equity` |
| cash from operations | positive in 3 of the last 4 years | `--min-ocf-years` |
| profit | positive in the latest year | |
| revenue | latest above the earliest year | |
| optional | return on equity, land as % of market value | `--min-roe`, `--min-land-pct` |

Companies with a missing field, or that report in another currency, are dropped
and counted, never guessed.

## A real run (2026-11-15)

All 2,391 NSE EQ companies fetched, none failed. The default screen passed 143 and dropped 1,295 on
size, 768 on debt, 108 on cash flow, 55 on growth, 12 on profit, and 10 for missing or non-rupee data.
The top row by return on equity was a company with Rs 7 crore of sales, a P/E of 0.6 and Rs 3 lakh
traded a day: a one-off gain in a stock nobody can sell. The tool now flags rows like it (ONE-OFF
LIKELY), and it is the reason the list is where the reading starts, not where it ends.

## What the numbers do not mean

- **Land** is Yahoo's "land and improvements" at BOOK COST, often decades old. It
  shows a company owns land, not what it is worth, whether it is mortgaged, or
  whether it can be sold. Never state a market value for it.
- **Debt free** is as of the last balance-sheet date.
- **Low P/E** on one good year is not cheap.
- **Thin trading:** under 1 crore a day, a small order can move the price and
  selling can take days. Lower-circuit locks are common.

## The research checklist (do these before saying anything is interesting)

For the company the user picks, find and READ, and report each with its source or say "not found":

1. **Promoter holding and pledges.** The latest shareholding pattern (NSE filings). Falling promoter
   holding or pledged shares is the most common trap.
2. **The annual report's auditor's report and CARO annexure.** Any qualification, emphasis of matter,
   or auditor resignation.
3. **Related-party transactions and loans to group companies** (notes to accounts).
4. **The property note** (property, plant and equipment; investment property): where the land is,
   freehold or leasehold, any charge on it. This is the "land ownership" check; the screen only flags candidates.
5. **Contingent liabilities and tax disputes.**
6. **Cash flow against profit** over four years (`gems.py show`): profit without cash is a warning.
7. **Results** via `/trader-news` and `/trader-analyst`: the last quarters and any upcoming board meeting.
8. **Who else holds it and recent deals** via `/trader-deals`.
9. **Trading:** average traded value, circuit band (Kite connector `market mode=quote`), and
   corporate actions (NSE connector `get_corporate_actions`).

Use `news.py --save URL` to download a filing and read it. If a document cannot be
opened, say so; do not summarise it from memory.

## Steps

1. `gems.py screen`. Say how many were screened, how many passed, and why the rest dropped.
2. The user picks one or two. Never pick for them.
3. `gems.py show SYMBOL`, then the checklist.
4. Report what was found for and against, with sources, and what could not be checked.
   No verdict. If they want to size a position, `/trader-swing plan SYMBOL`.

## What it never does

Never calls a stock a hidden gem, undervalued or a multibagger; never estimates land's market value;
never says buy; never places an order.

## Safety

- Education and tooling, not financial advice. Small companies carry more risk of fraud, illiquidity and total loss.
- No skill in this pack places an order. You place every order yourself in Zerodha Kite.
