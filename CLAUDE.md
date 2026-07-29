# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

WriteFlow: a single-file, dependency-free daily writing tracker with a
variable-reward game economy (streaks, coins, loot draws, a shop). Everything
lives in `writeflow.py` (stdlib only, no build step, no package manager, no
tests).

## Commands

```bash
./write done 400        # log today's words (CLI), then opens the dashboard
./write game             # start/wake the live localhost game server + open it
./write status            # streak/coins/week view in the terminal
./write shop              # list shop items
./write redeem <id>       # spend coins
./write log                # last 10 sessions
```

`./write` is a thin launcher (`write:1-3`) that always invokes
`/usr/bin/python3` explicitly, not whatever `python3` resolves to on PATH —
keep it that way when editing the launcher.

There is no lint/build/test tooling in this repo — verify changes by running
the commands above directly and inspecting `state.json` / the rendered
dashboard.

## Architecture

Everything is in `writeflow.py`:

- **State & data files** (`STATE_FILE` = `state.json`, `REWARDS_FILE` =
  `rewards.json`) are loaded via `load()`, which auto-creates them from
  `DEFAULT_STATE` / `DEFAULT_REWARDS` if missing. Both files are gitignored
  except `rewards.json`, which is meant to be user-customized.
- **`perform_checkin()`** is the single source of truth for logging a
  session — it's called both by the CLI (`cmd_done`) and by the live game
  server's `POST /done` handler, so streak/coin/loot logic never diverges
  between the two entry points. A same-day re-check-in just adds words to
  the existing entry without granting new coins/loot (once-per-day economy).
- **Two ways to view progress**: a static render (`render_dashboard` →
  writes `dashboard.html` and opens it with `open`/`webbrowser`) for `write
  done`, versus a **live server** (`cmd_serve`, stdlib `HTTPServer` on
  `127.0.0.1:8799`) for `write game`, which additionally serves a
  same-page "TODAY'S QUEST" input box that POSTs to `/done` and reloads.
  The server self-terminates after `IDLE_LIMIT` (30 min) of inactivity via a
  watchdog thread; `cmd_game` detects an existing server with `server_alive()`
  (`GET /ping`) before spawning a new detached one.
- **Rendering**: `dashboard_data()` computes the JSON blob (streak, coins,
  14-day calendar, next milestone %, shop affordability) that both the
  static and live paths inject into `TEMPLATE` (a single big HTML/CSS/JS
  string embedded in `writeflow.py`) via `build_html()`'s `__DATA__`
  placeholder. There's no separate frontend build — editing the game UI
  means editing the `TEMPLATE` string in place.
- **Game economy** (tunable constants at the top of the file — `MIN_WORDS`,
  `MAX_FREEZES`, `MILESTONES`): `advance_streak()` handles streak
  continuation/breaking and consumes streak freezes for gaps; coin payout in
  `perform_checkin` is `base + min(streak,25) + sqrt(words)` (halved word
  bonus under `MIN_WORDS`) so consistency beats binge-writing; `draw_loot()`
  is a variable-ratio reward draw (50/32/13/5 odds across none/small/
  medium/jackpot) with a pity timer forcing a win after 3 dry draws.
