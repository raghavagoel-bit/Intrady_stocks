# Vibe-Intraday — Flows

Mermaid diagrams for every major flow. Update these whenever a flow changes.

- [1. Account linking (credentials)](#1-account-linking--credentials)
- [2. Daily intraday trading loop](#2-daily-intraday-trading-loop)
- [3. Order path: paper vs live gate](#3-order-path--paper-vs-live-gate)
- [4. Trade → Telegram notification flow](#4-trade--telegram-notification-flow)
- [5. Data fetch + fallback](#5-data-fetch--fallback)
- [6. Paper runtime tick (as-built, `src/intraday`)](#6-paper-runtime-tick-as-built)
- [7. Week-1 parallel bake-off (`src/intraday/portfolio`)](#7-week-1-parallel-bake-off)

---

## 1. Account linking / credentials

Three independent credentials, one hub process. No cross-account OAuth.

```mermaid
flowchart LR
    D["Dhan account\n(API enabled)"] -->|client_id + 24h token| DJ["~/.vibe-trading/dhan.json"]
    G["Google AI Studio"] -->|GEMINI_API_KEY| E["agent/.env"]
    T["Telegram bot (@BotFather)"] -->|bot token + chat id| AJ["~/.vibe-trading/agent.json"]

    DJ --> A(("Vibe-Intraday agent"))
    E --> A
    AJ --> A

    A -->|reads data / places orders| D
    A -->|research + EOD review| G
    A -->|trade events| T
```

---

## 2. Daily intraday trading loop

Runs unattended during market hours (IST). Same shape for paper and live; only the
order step differs (see flow 3).

```mermaid
flowchart TD
    START([Pre-market ~09:00 IST]) --> REFRESH["Refresh Dhan token (24h expiry)"]
    REFRESH --> RESEARCH["Gemini: build day's watchlist\n(research + oversight)"]
    RESEARCH --> WAIT{Market open?\n09:15–15:30}

    WAIT -->|before 09:15| WAIT
    WAIT -->|open| BAR["Every interval (15m):\nfetch bars from Dhan"]

    BAR --> SIG["Run long-only signal engine\n→ entry / exit / hold"]
    SIG --> CUTOFF{Time ≥ 15:15?}

    CUTOFF -->|no| ORDER["Place order\n(paper-sim OR live)"]
    CUTOFF -->|yes| FLAT["SQUARE-OFF:\nforce-exit all open longs"]

    ORDER --> NOTIFY["Notify Telegram\n(entry/exit)"]
    FLAT --> NOTIFY2["Notify Telegram\n(square-off)"]

    NOTIFY --> WAIT
    NOTIFY2 --> EOD["After 15:30:\nGemini EOD journal review"]
    EOD --> DONE([Flat overnight — nothing carried])
```

---

## 3. Order path — paper vs live gate

Paper-first: the same signal drives a simulated fill now, and a mandate-gated live order
only after Milestone M2. Long-only means the gate also rejects any non-buy/sell-to-close.

```mermaid
flowchart TD
    SIGNAL["Signal: enter/exit long"] --> MODE{Mode?}

    MODE -->|Paper M1| SIM["Simulate fill on live Dhan price\n+ MIS cost model"]
    SIM --> REC["Record paper position + P&L"]

    MODE -->|Live M2| LONGCHK{Long-only?\nbuy or sell-to-close}
    LONGCHK -->|no| REJECT["Reject (short blocked)"]
    LONGCHK -->|yes| MANDATE{Mandate gate:\nsymbol ∈ universe?\nsize ≤ cap?\ndaily loss ≤ cap?\nnot halted?}

    MANDATE -->|deny| REJECT
    MANDATE -->|allow| DHAN["Dhan place_order (MIS)"]
    DHAN --> AUDIT["Audit ledger + daily counter"]
    AUDIT --> REC

    REC --> TG["→ Telegram notifier (flow 4)"]
    REJECT --> TG
```

---

## 4. Trade → Telegram notification flow

One central notifier for both paper and live, so the Telegram feed is identical in both
modes. Sink only — never places or approves orders.

```mermaid
flowchart LR
    subgraph Events
        EN["ENTRY"]
        EX["EXIT"]
        SQ["15:15 SQUARE-OFF"]
        HA["HALT / ERROR"]
        BK["Watchlist / EOD summary"]
    end

    EN --> N["Trade-event notifier"]
    EX --> N
    SQ --> N
    HA --> N
    BK --> N

    N -->|"symbol, side, qty, price,\nIST time, running P&L"| CH["channels/telegram.py"]
    CH --> USER([Your Telegram channel])
```

---

## 5. Data fetch + fallback

Intraday bars come from Dhan (your live account). The repo's fallback chain for
`india_equity` is `yahoo → yfinance → india_broker → local`; for intraday we prefer the
broker (Dhan) source because Yahoo 15m history is capped at ~60 days.

```mermaid
flowchart LR
    REQ["Request 15m bars for RELIANCE.NS"] --> DHAN{Dhan configured?}
    DHAN -->|yes| DH["india_broker loader\n(Dhan, up to 5y minute history)"]
    DHAN -->|no / gap| YF["yahoo / yfinance\n(~60d of 15m only)"]
    DH --> OHLCV["OHLCV frame → signal engine"]
    YF --> OHLCV
```

> Note: flows 3 (live path), and the token-refresh + scheduler in flow 2, are **designed
> here but not built** — implementation is Phase 3+. Diagrams will be revised if the design
> changes during build.

---

## 6. Paper runtime tick (as-built)

The M1 paper loop as implemented in `src/intraday/runner.py::run_tick(now)`. Fail-closed order,
fully injectable (replay bars + frozen clock make it unit-testable with no live services).

```mermaid
flowchart TD
    T["run_tick(now)"] --> H{halted?}
    H -- yes --> STOP["no-op"]
    H -- no --> SQ{now ≥ 15:15 IST?}
    SQ -- yes --> FF["force-flatten ALL open positions\n(sell longs, COVER shorts —\n3L invariant 2, idempotent;\nno last price → avg_price fallback)"] --> N
    SQ -- no --> OPEN{session open?\n09:15–15:30, weekday}
    OPEN -- no --> STOP
    OPEN -- yes --> SIG["build data_map (recent bars)\n→ SignalEngine.generate()\n→ desired ∈ {−1,0,1} per symbol\n(−1 coerced to 0 unless allow_short)"]
    SIG -- engine raises --> HALT["halt(reason) → HALT notify"]
    SIG --> EX["exits first: open direction ≠ desired\n→ PaperBroker.close_position\n(sell / cover; flips close-then-open)"]
    EX --> EN["entries: desired 1 → buy · desired −1 → short\n(hybrid only), cap across BOTH directions"]
    EN --> N["TradeNotifier → Telegram sink / log sink"]
```

Bookends (outside the tick): `gemini_jobs.premarket_watchlist` before open and
`gemini_jobs.eod_review` after close post the day's watchlist + journal to the same feed.
Paper fills at the observed bar's **close**; the strategy's own flat-by-15:00 rule still
applies, with 15:15 as the authoritative backstop. Live orders remain out of scope (M2).

---

## 7. Week-1 parallel bake-off

`src/intraday/portfolio.py` — the 4 strategies run side by side on one shared bar feed, each in an
isolated ₹25k paper account, ranked at week's end on net-of-cost P&L.

```mermaid
flowchart TD
    BARS["shared bar feed (15m)\nCachedBarSource: ONE Dhan fetch\nper symbol per tick"] --> P["Portfolio.run_tick(now)"]
    P --> A["orb · pullback · ema_trend\n· momentum_rsi · ₹25k each"]
    P --> N["10 new archetypes (3G, since 2026-07-16):\ngap_go · gap_fade · vwap_hold · range_break\n· macd_cross · boll_bounce · boll_break\n· atr_trail · rel_strength · three_thrust · ₹25k each"]
    A & N --> KS{"per-strategy loss ≥ ₹10k?"}
    KS -- yes --> RET["square off + RETIRE that strategy\n(survivors keep trading) → HALT notify"]
    KS -- no --> CONT["keep trading"]
    P --> HR{"IST hour changed?"}
    HR -- yes --> HS["hourly rollup → Telegram"]
    P --> EOD["finalize(): EOD scoreboard → Telegram\n+ persist to weekly ScoreboardStore"]
```

> **Since 3M (2026-07-16):** the `llm_trader` **Gemini** slot was removed from the roster on cost grounds; Gemini is research/oversight only (pre-market watchlist + EOD review).
> **Since 3R (2026-07-17):** the LLM slot is revived on **local Ollama** — two long-only candidate slots, `llm_local_a` (llama3.1:8b) and `llm_local_b` (qwen3:8b), share `builtin:llm_trader` via per-slot roster `params` (`provider`/`model`). Zero marginal cost, no quota, no WAN. BUG-005 lessons built in: slot-tagged journal/logs; after 3 consecutive failed calls the slot goes **degraded = flat** (never frozen on stale decisions), a success resets it. The scoreboard picks between the two candidates.
> **Since 3P (2026-07-17):** the EOD scoreboard leads with a topline `Σ net · fees · trades · P of M profitable`. (3P's hourly per-slot diet — idle-collapse, movers-first, 8-fill cap, `⇅ legs` — was sized for ~42 slots and is **superseded by B4-2** below.)
> **Since B4-2 (2026-07-19, for the 64-slot roster):** both reports **collapse each long/`_ls` pair to one line** so the A/B delta reads directly. Hourly = one row per pair `long · ls · sht · Δ(=ls−long) · f · h`, **all pairs** shown movers-first (by max |leg net|); EOD = one pair row ranked by best leg. Halted pairs are **always shown** (both legs, ✖ on the retired leg); unpaired `llm_local_a/b` get their own line (a halted one flagged ✖). A hard **≤3-chunk cap** (`scoreboard._cap_report` over `notifier.split_for_telegram`) truncates with `… +N more pairs (log)`. This cut the hourly from 4→1 chunk and the EOD from 2→1 chunk at 64 slots. Full per-fill detail always survives in the log tape.

Per-trade ENTRY/EXIT go to each strategy's **log tape** (not Telegram) to keep the feed quiet; the
feed carries only the hourly rollup, the EOD scoreboard, and kill-switch HALTs. The ₹10k cutoff is
**per strategy** and **permanent** for the run (a disqualified setup is out for good), not an aggregate
or daily limit. Over the week the scoreboard accumulates one record per (date × strategy); the
weekly table decides which setup (if any) graduates to an M2 live test.

## 8. One trading day via the launcher (as-run since 2026-07-15)

`src/intraday/bakeoff.py` (started by `start_bakeoff.bat` each morning) wires the whole day:

```mermaid
flowchart TD
    BAT["start_bakeoff.bat\n(morning double-click)"] --> V{"creds + security_ids\n+ roster valid?"}
    V -- no --> X["exit 2 with reason"]
    V -- yes --> WL["Gemini pre-market watchlist\n→ Telegram (if before 09:15)"]
    WL --> WAIT["wait_for_open\n(30s polls; weekend/after-close → exit 0)"]
    WAIT --> RUN["Portfolio.run_session\n(tick every 15m on live Dhan bars,\ncreds threaded from agent/.env — DC-003)"]
    RUN --> RC{"3N: canary probe —\ndata feed up?"}
    RC -- no --> WAITRC["ride out the drop:\nbackoff 5s→30s, re-probe up to\nreconnect_budget_seconds (5 min)"]
    WAITRC --> RC
    RC -- "yes / budget lapsed" --> TICK["run_tick — a lapsed budget\ndegrades to empty-frame hold\n(only that bar lost)"]
    TICK --> FLAT["force-flatten ≥ 15:15"]
    FLAT --> SB["EOD scoreboard → Telegram\n+ weekly ScoreboardStore"]
    SB --> REV["Gemini EOD journal review\n→ Telegram (aggregated per-strategy\nlines when fills > 40 — 3O)"]
    REV --> LOG["utf-8 day log:\nagent/logs/bakeoff-YYYYMMDD.log"]
```

One invocation = one trading day (the Dhan token expires every 24h, so a fresh morning start is
the natural unit — refresh the token in `agent/.env` first).

**Bookend reliability (3O, BUG-006):** both Gemini bookends now retry **transient** failures
(timeout / transport / 5xx / 429) up to 3 attempts (2s/8s); if retries are exhausted, the prompt
runs through **local Ollama** (`ollama_url`/`ollama_model` config) and posts with a `[local]`
prefix — the static `"(no watchlist)"`/`"(no review)"` placeholder is the last resort only. A
quota-429 (daily free-tier reset ≈ 12:30 IST = midnight Pacific) therefore degrades to a local
model's text instead of silence.

---

## 9. 3L long-vs-hybrid A/B (live from 2026-07-16)

Every long-only rule slot gets a `_ls` twin sharing the **same** `signal_engine.py` source, built
with `allow_short=True`. Since 3R (2026-07-17) the process runs **42 slots**: the 20 + 20 rule
pairs below plus the two long-only local-LLM candidates (`llm_local_a`/`llm_local_b`, flow 7 —
outside this A/B). Any pair delta over shared days ≈ the value of the short side alone (per-leg
decomposition exposes slot interference).

```mermaid
flowchart TD
    CFG["config/intraday.json — roster 64\n(31 rule long + 31 _ls same run_dir\n+ 2 llm_local long slots)"] --> PRE["bakeoff.validate_roster preflight:\nbuild EVERY slot before the first tick\n(_ls ctor rejects allow_short → TypeError;\nbad llm params → TypeError\n= fail fast, never silently wrong)"]
    PRE -- any slot fails --> GATE["LAUNCH GATE: exit 2 →\nrun config/intraday.long21.json\n(20 long-only), the rest slips a day"]
    PRE -- all build --> P["Portfolio.run_tick — each slot\nwrapped in try/except: one slot's\nexception halts THAT slot only\n(the other 63 finish the day)"]
    P --> L["<name>: SignalEngine()\nlong-only, −1 coerced to 0"]
    P --> HY["<name>_ls: SignalEngine(allow_short=True)\nsame tuned params — may emit −1"]
    L & HY --> SB["scoreboard (B4-2): ONE row per pair\nlong ₹ · ls ₹ · sht ₹ · Δ(=ls−long)\n(long_pnl = Σ sell realized,\nshort_pnl = Σ cover realized)"]
    SB --> AB["A/B read (≥2 weeks, shared days only):\npair delta = hybrid − long\n≈ short-side value ± interference"]
```

Shorts are **paper-only** (user decision 2026-07-15): the M2 live gate in flow 3 still rejects
non-long orders — promoting any short-capable setup to live needs its own explicit decision.
Short mechanics: 1x reserve (notional + entry commission), STT on the short leg / stamp on the
cover, one direction per symbol per account, 15:15 force-cover is a hard invariant (flow 6).
