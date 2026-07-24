# WriteFlow — daily writing accountability

A tiny local system that makes daily writing feel like a game worth not quitting.
No accounts, no apps, no dependencies — one Python script and two JSON files.

## Daily loop

Write, then log it:

```bash
./write game            # open the mini-game — log today's words right on the page
./write done 400        # or log from the terminal; also opens the game screen
./write status          # streak, coins, last-7-days view (terminal)
./write shop            # what your coins can buy
./write redeem coffee   # cash in a treat
./write log             # recent history
```

`write game` starts a tiny localhost server (stdlib only, 127.0.0.1:8799,
naps after 30 idle minutes) and opens the game in your browser: on unlogged
days it shows "TODAY'S QUEST" with an input box and a LOG IT button — type
your word count, press Enter, and the page reloads into an animated
slot-machine loot reveal (confetti on big wins), streak flame, coin
count-up, an XP bar to the next milestone, a 14-day calendar, and the
reward shop with affordable items glowing. `write done` renders the same
screen as a static `dashboard.html` (no input box without the server).

For a global command, add to your `~/.zshrc`:

```bash
alias write="$HOME/Desktop/daily-writing/write"
```

## How the reward system works (and why)

Each mechanic maps to a piece of habit science:

- **Tiny floor (200 words).** The commitment is showing up, not heroics.
  Even 50 words keeps the streak alive (at half word-bonus), because a
  never-zero rule survives bad days and heroic goals don't.
- **Coins favor consistency over binging.** Streak bonus is linear
  (capped at +25/day); word bonus grows on a square root, so writing 4x
  the words earns only ~2x the coins. The math quietly says: come back
  tomorrow instead.
- **Variable rewards (the clever part).** After each check-in you get a
  loot draw — 50% nothing, 32% small, 13% medium, 5% jackpot. Random,
  intermittent rewards are the strongest known driver of repeated
  behavior (variable-ratio reinforcement — the slot-machine effect).
  A pity timer guarantees a win at least every 4th day so dry spells
  never demotivate.
- **Streak freezes fight the what-the-hell effect.** Every 7-day streak
  banks a freeze (max 3) that auto-covers a missed day. One bad day
  doesn't nuke three weeks of work — which is the #1 reason people quit
  streak systems.
- **The shop makes coins real.** Treats you'd enjoy anyway become things
  you *earn*. Edit `rewards.json` to make every item something you
  genuinely want — the system only works if the rewards are honest.
  The `dayoff` item is deliberate: buying rest with earned coins turns
  even skipping into a win.
- **Milestones (days 7/14/30/60/100/365)** give the long arc — the loot
  table handles today, milestones handle the identity shift.

## Files

- `writeflow.py` — all the logic (Python 3.6+, stdlib only)
- `state.json` — your streak, coins, history (auto-created; back this up if you care)
- `rewards.json` — loot table + shop (auto-created; **customize this**)

## Tuning

Open `writeflow.py` and adjust the constants at the top: `MIN_WORDS`
(floor goal), `MAX_FREEZES`, `MILESTONES`. Loot odds live in `draw_loot`.
