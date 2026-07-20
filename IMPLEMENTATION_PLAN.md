# Vibe-Intraday — Build Plan (Phase 1)

**An NSE intraday (MIS) trading assistant built on HKUDS/Vibe-Trading, using Dhan for data + execution and Gemini for research + oversight.**

Status: Phase 1 (Plan). Created 2026-07-13.

---

## 1. Objective

Stand up a **personal, self-hosted** intraday equities assistant for the Indian market that:

1. Reads **live NSE/BSE data** from a Dhan account (quotes + intraday minute bars).
2. Runs **fast, rule-based signal engines** intraday (the ORB / momentum / mean-reversion strategies already prototyped).
3. Uses **Gemini** for *pre-market research, watchlist construction, and end-of-day review* — **not** per-bar trade decisions.
4. Trades **paper-first** (simulated fills on live data), then graduates to **live MIS orders** behind a hard risk mandate + kill switch, with a small ₹25–50k trial account.
5. Squares off all positions before the broker's MIS auto-close, every day.

Non-goals (explicitly out of scope): **short selling** (long-only system), F&O/options, delivery/swing trading, multi-user or hosted SaaS, HFT, and any LLM-in-the-loop per-bar execution.

---

## 2. Locked architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Rollout | **Paper-first, then live** | Validate mechanics + net-of-cost edge before risking cash. |
| LLM role | **Research + oversight** (Gemini) | Rule engines decide entries/exits (low latency, deterministic, testable). Gemini does morning research, watchlist, EOD journal review. Cheap, robust, low prompt-injection surface. |
| Trial capital | **₹25–50k**, 2–3 liquid stocks | Costs dominate at this size → strategy must be low-frequency and cost-aware; sizing/mandate tuned to this. |
| Direction | **Long-only** (no shorting, anywhere) | Simpler risk; no short margin/borrow rules or upper-circuit short traps. Every trade is buy-then-sell, same day. |
| Notifications | **All trade events → Telegram** | Every entry, exit, and 15:15 square-off (paper *and* live), plus halts/errors, posted to a Telegram channel in real time. Repo already ships a Telegram channel. |
| LLM provider | **Gemini** (`gemini-3.5-flash` default) | Per user. Cheap enough to run pre/post-market. |
| Broker | **Dhan** (`dhanhq` SDK) | Data + execution in one; free trading API; up to 5y minute history. |

---

## 3. The two hard technical problems (must solve for intraday)

### P1 — The India backtest engine hard-codes T+1 (blocks intraday)
`agent/backtest/engines/india_equity.py :: can_execute()` refuses any same-bar-date
sell (delivery T+1 rule), with **no config override**. Intraday round-trips are
therefore silently impossible in the shipped engine.

**Plan:** add an **intraday MIS mode** — either a config flag on `IndiaEquityEngine`
(`intraday=True`) or a subclass `IndiaIntradayEngine` — that:
- disables the same-day-sell block (so a stock bought at 9:30 can be sold at 14:00),
- keeps **long-only** (`allow_short=False`) — no shorting anywhere in the system,
- swaps the cost stack to **MIS economics** (brokerage `min(₹20, 0.03%)`/order, STT
  `0.025%` sell-side only, buy-side stamp `0.003%`, exchange+SEBI+18% GST, no DP charge),
- enforces an **intraday square-off**: force-exits any open long at a configurable
  cutoff (~15:15 IST) — see note.

> **What "15:15 square-off" means.** MIS (intraday) positions use intraday margin and
> cannot be carried overnight — they must be closed the same day. If you don't exit, the
> *broker* auto-squares-off open MIS positions near the close (Dhan equity intraday: ~3:15 PM
> IST; market closes 3:30). Broker auto-close is a market order at whatever price is available
> and may carry a penalty, so the runner proactively flattens by ~15:15 to control the exit.
> Exact cutoff depends on Dhan's current policy/segment — verify before live.

### P2 — The Dhan connector is paper-only by design (blocks live orders)
`agent/src/trading/connectors/dhan/sdk.py` hard-refuses live `place_order`
(`_PAPER_ONLY_ERROR`) because Dhan exposes no runtime paper/live discriminator.

**Plan (deferred to live milestone M2):** add an **explicit operator-declared live
boundary** — a new `dhan-live-trade` profile whose live order path is gated by the
existing **mandate + halt + daily-count + audit** stack in `agent/src/live/`, plus a
separate one-time confirmation. Paper-first means we do **not** touch this until M1 is proven.

---

## 4. Milestones & acceptance targets

### M0 — Environment up (setup)
- Vibe-Trading cloned to a permanent project location; `pip install` + deps resolved.
- `agent/.env` configured with Gemini key; Gemini answers a test research prompt.
- Dhan `dhan-live-sdk-readonly` profile reads account, positions, quotes, and 15m history for `RELIANCE.NS`.
- **Done when:** `connector check` passes and a live 15m quote prints.

### M1 — Paper intraday loop (core deliverable)
- Intraday MIS engine (P1) implemented + unit-tested; strategies backtest on real Dhan 15m bars.
- A market-hours **runner** (9:15–15:30 IST) that: pulls bars each interval → runs the signal engine → simulates MIS fills → tracks positions → **flattens by 15:15**.
- Gemini pre-market job builds the day's watchlist; EOD job writes a trade-journal review.
- **Telegram trade feed** live (see §4.5): every paper entry / exit / 15:15 square-off posted in real time, plus the morning watchlist and EOD review.
- **Done when:** a full simulated session runs unattended on live data, flattens correctly, produces a trade journal, and every trade appeared in Telegram. Target: ≥ 5 clean paper sessions, net-of-MIS-cost P&L tracked.
- **Week-1 parallel bake-off (added per user):** run **4 diverse long-only strategies in parallel**
  (breakout / mean-reversion / trend / momentum), each in its own isolated **₹25k** paper account with a
  **₹10k per-strategy setup kill-switch** (permanent retire on breach; survivors continue). Telegram gets
  an **hourly** rollup + an EOD scoreboard; a weekly `ScoreboardStore` accumulates one record per
  (date × strategy). After ≥ 1 week, rank on **net-of-cost** P&L → iterate or promote a survivor to M2.
  Built in `src/intraday/portfolio.py` + `scoreboard.py`.

### M2 — Live intraday (gated, real ₹25–50k)
- Live Dhan order path (P2) behind mandate (2–3 symbols, per-order + daily-loss caps, max positions), filesystem kill switch, audit ledger.
- Daily 24h **token-refresh** step automated before 9:15.
- SEBI compliance checklist done (static IP whitelisted with Dhan, generic algo ID, < 10 OPS — trivially satisfied).
- Same **Telegram trade feed** as M1, now on live fills, plus mandate/halt/kill-switch alerts.
- **Done when:** one live session places + squares off a single tiny MIS trade within mandate, fully audited, with the fill + square-off posted to Telegram. Only after M1 shows a positive net-of-cost paper edge.

---

### 4.5 — Trade notification flow (Telegram)

Every trade event flows to a Telegram channel, in **both** paper and live modes, from one
central notifier so paper and live behave identically (only the fill source differs):

```
signal engine → order (paper-sim OR live Dhan) → fill recorded
                                                     │
                                                     ▼
                                         trade-event notifier ──→ Telegram channel
```

Events posted (each with symbol, side=BUY/SELL, qty, price, timestamp IST, and running P&L):
- **ENTRY** — a new long is opened.
- **EXIT** — a long is closed by the strategy's exit rule.
- **SQUARE-OFF** — the 15:15 forced flatten closed a still-open long.
- **HALT / ERROR** — kill switch tripped, mandate breach, data outage, or token failure.
- **DAY BOOKENDS** — the morning watchlist (from Gemini) and the EOD journal summary.

Implementation note: reuse the repo's existing `agent/src/channels/telegram.py` +
channel manager; add a thin notifier the runtime calls on every fill/flatten/halt.
Config: `TELEGRAM_BOT_TOKEN` + target chat/channel id in `agent/.env`. This is a
notification sink only — Telegram never places or approves orders (that stays in the mandate gate).

## 5. Anticipated file-level work (detail in Phase 3 `docs/IMPLEMENTATION_PLAN.md`)

- `agent/backtest/engines/india_equity.py` — add intraday mode (P1).
- `agent/backtest/engines/__init__.py` / market hooks — route intraday interval to the new mode.
- `agent/backtest/loaders/india_broker_loader.py` — confirm Dhan 15m/5m history path for backtests.
- `agent/src/trading/connectors/dhan/` — (M2) live-trade profile + boundary (P2).
- `agent/src/live/runtime/` — intraday scheduler + 15:15 flatten wiring for IST session.
- `agent/src/channels/telegram.py` + a thin trade-event notifier — post every entry / exit / square-off / halt to Telegram (§4.5), wired into the runtime's fill path.
- `strategies/` — relocate + tune the prototyped engines as **long-only**; strip the short side out of `orb_intraday`; add MIS cost configs.
- Gemini jobs — pre-market watchlist + EOD review via the scheduled-research runtime.

## 6. Testing & QA (per standard workflow)
- Unit tests for the intraday engine (same-day exit allowed, MIS cost math, 15:15 flatten, long-only enforced / short orders rejected) → `docs/UNIT_TESTS.md`, run before every build → `docs/TEST_REPORT.md`.
- Reuse repo's validation suite (Monte Carlo / bootstrap / walk-forward) on any strategy before it sees live capital.
- QA sessions logged newest-first in `docs/QA.md`.

## 7. Risks & constraints
- **Data cost:** Dhan Data API free only with 25 trades/30d, else ₹499+GST/mo.
- **Token churn:** Dhan access tokens expire every 24h — a daily refresh is mandatory for autonomy.
- **Cost drag at ₹25–50k:** ~₹40–75/round-trip on tiny notional can erase thin edges — the paper phase exists to catch exactly this.
- **Ticker churn:** Yahoo/Dhan symbols change (e.g. `TATAMOTORS.NS` delisted post-demerger) — validate the universe each cycle.
- **SEBI (in force since Apr 1, 2026):** personal self-built algo under 10 OPS is permitted; requires static IP + broker-issued generic algo ID. No sharing/distribution.
- **Live-order safety:** P2 removes a deliberate safety cap — only behind mandate + kill switch + tiny capital.

## 8. Immediate next step
Phase 2 — write `README.md` (architecture + quick start) and `docs/FLOWS.md` (Mermaid diagrams for the intraday loop, data flow, and paper→live gating). Then Phase 3 file-by-file spec, then code.
