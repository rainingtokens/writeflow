#!/usr/bin/python3
"""WriteFlow — daily writing accountability with a variable-reward economy.

Usage:
  writeflow.py done <words>     log today's writing session (opens the game screen)
  writeflow.py game             open the mini-game (live: log words right on the page)
  writeflow.py status           streak, coins, week view (terminal)
  writeflow.py shop             see what your coins can buy
  writeflow.py redeem <id>      spend coins on a treat
  writeflow.py log              recent session history
"""
import json
import math
import os
import random
import subprocess
import sys
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:  # Python < 3.7
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT, "state.json")
REWARDS_FILE = os.path.join(ROOT, "rewards.json")
DASH_FILE = os.path.join(ROOT, "dashboard.html")
PORT = 8799            # live game server (stdlib only, localhost only)
IDLE_LIMIT = 1800      # server naps after 30 idle minutes

# The floor goal is deliberately tiny: the habit is showing up, not word count.
MIN_WORDS = 200
MAX_FREEZES = 3

MILESTONES = {
    7: "One week! Unlock: a small treat of your choice, on the house.",
    14: "Two weeks! Unlock: a lazy morning — write whenever you like today.",
    30: "One month! Unlock: buy yourself that book / notebook / pen.",
    60: "Two months! Unlock: a proper night out. You're a writer now.",
    100: "100 DAYS. Unlock: something you've wanted for months. Go get it.",
    365: "A full year. Unlock: anything. You earned it 365 times over.",
}

DEFAULT_REWARDS = {
    "loot": {
        "small": [
            "A fancy coffee tomorrow",
            "15 minutes of guilt-free scrolling",
            "One song played embarrassingly loud",
            "Dessert after dinner tonight",
        ],
        "medium": [
            "One episode of whatever you're watching",
            "Order in instead of cooking",
            "An hour of gaming / reading for pure pleasure",
        ],
        "jackpot": [
            "Movie night — full ritual, snacks included",
            "Buy that thing sitting in your cart",
            "A completely free evening: no writing, no guilt",
        ],
    },
    "shop": [
        {"id": "coffee", "name": "Fancy coffee run", "cost": 40},
        {"id": "takeout", "name": "Takeout night", "cost": 90},
        {"id": "book", "name": "New book, no justification needed", "cost": 150},
        {"id": "dayoff", "name": "Guilt-free skip day (streak preserved)", "cost": 250},
        {"id": "splurge", "name": "The big splurge (you know the one)", "cost": 600},
    ],
}

DEFAULT_STATE = {
    "streak": 0,
    "best_streak": 0,
    "coins": 0,
    "freezes": 1,          # start with one grace day banked
    "dry_draws": 0,        # pity counter for the loot table
    "last_checkin": None,  # ISO date string
    "history": [],         # [{date, words, coins, tier, loot}]
    "redeemed": [],        # [{date, id, name, cost}]
}


def load(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    with open(path, "w") as f:
        json.dump(default, f, indent=2)
    return json.loads(json.dumps(default))


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def parse_date(s):
    if not s:
        return None
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def advance_streak(state, today):
    """Update the streak for a new check-in, consuming freezes for missed days."""
    last = parse_date(state["last_checkin"])
    if last is None or last == today:
        if last is None:
            state["streak"] = 1
        return None
    gap = (today - last).days
    if gap == 1:
        state["streak"] += 1
        return None
    missed = gap - 1
    if state["freezes"] >= missed:
        state["freezes"] -= missed
        state["streak"] += 1
        return f"❄️ {missed} missed day(s) covered by streak freezes ({state['freezes']} left). Streak survives!"
    state["streak"] = 1
    return f"💔 Streak broken after {missed} missed day(s). Best so far: {state['best_streak']}. Day 1 starts now."


def draw_loot(state, rewards):
    """Variable-ratio reward draw with a pity timer: never more than 3 dry draws."""
    roll = random.random()
    if state["dry_draws"] >= 3:
        roll = 0.5 + random.random() * 0.5  # guaranteed at least a small win
    if roll < 0.50:
        state["dry_draws"] += 1
        return None, None
    state["dry_draws"] = 0
    if roll < 0.82:
        tier = "small"
    elif roll < 0.95:
        tier = "medium"
    else:
        tier = "jackpot"
    return tier, random.choice(rewards["loot"][tier])


# ---------------------------------------------------------------- dashboard

def dashboard_data(state, rewards, result=None):
    today = date.today()
    done_dates = {h["date"] for h in state["history"]}
    days = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        days.append({"l": d.strftime("%a")[0], "done": d.isoformat() in done_dates,
                     "today": d == today})
    nxt = next((m for m in sorted(MILESTONES) if m > state["streak"]), None)
    next_milestone = None
    if nxt:
        prev = max([m for m in MILESTONES if m <= state["streak"]] + [0])
        pct = int(100 * (state["streak"] - prev) / (nxt - prev))
        next_milestone = {"day": nxt, "togo": nxt - state["streak"], "pct": pct}
    shop = [{"id": i["id"], "name": i["name"], "cost": i["cost"],
             "affordable": state["coins"] >= i["cost"]} for i in rewards["shop"]]
    return {
        "streak": state["streak"], "best": state["best_streak"],
        "coins": state["coins"], "freezes": state["freezes"],
        "dry_draws": state["dry_draws"], "min_words": MIN_WORDS,
        "today_logged": state["last_checkin"] == today.isoformat(),
        "today": result, "next_milestone": next_milestone,
        "days": days, "shop": shop,
    }


def build_html(state, rewards, result=None):
    data = dashboard_data(state, rewards, result)
    return TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))


def render_dashboard(state, rewards, result=None):
    with open(DASH_FILE, "w", encoding="utf-8") as f:
        f.write(build_html(state, rewards, result))
    return DASH_FILE


def open_dashboard(path):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            import webbrowser
            webbrowser.open(path if path.startswith("http") else "file://" + path)
        return True
    except Exception:
        return False


def today_result_from_history(state):
    today_s = date.today().isoformat()
    h = next((h for h in state["history"] if h["date"] == today_s), None)
    if not h:
        return None
    tier = h.get("tier") or ("small" if h.get("loot") else None)
    milestone = MILESTONES.get(state["streak"])
    return {"words": h["words"], "earned": h["coins"], "tier": tier,
            "loot": h.get("loot"), "streak_msg": None, "milestone": milestone}


def perform_checkin(state, rewards, words):
    """Shared check-in core for the CLI and the live game server. Saves state."""
    today = date.today()
    today_s = today.isoformat()

    existing = next((h for h in state["history"] if h["date"] == today_s), None)
    if existing:
        existing["words"] += words
        save_state(state)
        return {"duplicate": True, "total": existing["words"], "added": words}

    streak_msg = advance_streak(state, today)
    state["last_checkin"] = today_s
    state["best_streak"] = max(state["best_streak"], state["streak"])

    # Coins: showing up beats binging. Streak pays more than word count,
    # and word count pays on a square root, so 4x the words ≈ 2x the coins.
    base = 10
    streak_bonus = min(state["streak"], 25)
    word_bonus = int(math.sqrt(max(words, 0)))
    if words < MIN_WORDS:
        word_bonus = word_bonus // 2
    earned = base + streak_bonus + word_bonus
    state["coins"] += earned

    tier, loot = draw_loot(state, rewards)
    state["history"].append({"date": today_s, "words": words, "coins": earned,
                             "tier": tier, "loot": loot})

    new_freeze = False
    if state["streak"] > 0 and state["streak"] % 7 == 0 and state["freezes"] < MAX_FREEZES:
        state["freezes"] += 1
        new_freeze = True

    save_state(state)
    return {"duplicate": False, "words": words, "earned": earned, "tier": tier,
            "loot": loot, "streak_msg": streak_msg, "new_freeze": new_freeze,
            "milestone": MILESTONES.get(state["streak"])}


# ---------------------------------------------------------------- commands

def cmd_done(words):
    state = load(STATE_FILE, DEFAULT_STATE)
    rewards = load(REWARDS_FILE, DEFAULT_REWARDS)
    r = perform_checkin(state, rewards, words)

    if r["duplicate"]:
        print(f"✏️  Added {r['added']} words to today (total {r['total']}). "
              "Coins and loot are once per day — see you tomorrow.")
        open_dashboard(render_dashboard(state, rewards, today_result_from_history(state)))
        return

    print(f"✅ Day {state['streak']} logged: {words} words, +{r['earned']} coins "
          f"(wallet: {state['coins']})")
    if words < MIN_WORDS:
        print(f"   Under the {MIN_WORDS}-word floor — still counts, half word-bonus. "
              "Showing up is the win.")
    if r["streak_msg"]:
        print("   " + r["streak_msg"])
    if r["new_freeze"]:
        print(f"   ❄️  7-day streak bonus: +1 streak freeze (you have {state['freezes']}).")
    if r["tier"]:
        labels = {"small": "🎁 Small win", "medium": "🎉 Nice pull", "jackpot": "💎 JACKPOT"}
        print(f"   {labels[r['tier']]}: {r['loot']}")
    else:
        print("   🎲 No loot today — odds improve tomorrow. (Guaranteed win within 3 dry days.)")
    if r["milestone"]:
        print(f"\n   🏆 MILESTONE — {r['milestone']}")

    if open_dashboard(render_dashboard(state, rewards, r)):
        print("   🎮 Game screen opened.")


def server_alive():
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/ping" % PORT, timeout=0.5) as resp:
            return resp.read() == b"writeflow"
    except Exception:
        return False


def cmd_serve():
    """Foreground live-game server; spawned detached by cmd_game."""
    import threading
    import time
    import urllib.parse
    from http.server import BaseHTTPRequestHandler, HTTPServer

    last_hit = {"t": time.time()}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            last_hit["t"] = time.time()
            if self.path == "/ping":
                body = b"writeflow"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
            else:
                state = load(STATE_FILE, DEFAULT_STATE)
                rewards = load(REWARDS_FILE, DEFAULT_REWARDS)
                html = build_html(state, rewards, today_result_from_history(state))
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            last_hit["t"] = time.time()
            if self.path != "/done":
                self.send_response(404)
                self.end_headers()
                return
            n = int(self.headers.get("Content-Length") or 0)
            q = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))
            try:
                words = int(q.get("words", ["0"])[0] or 0)
            except ValueError:
                words = 0
            state = load(STATE_FILE, DEFAULT_STATE)
            rewards = load(REWARDS_FILE, DEFAULT_REWARDS)
            perform_checkin(state, rewards, words)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", PORT), Handler)

    def watchdog():
        while True:
            time.sleep(30)
            if time.time() - last_hit["t"] > IDLE_LIMIT:
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    server.serve_forever()


def cmd_game():
    import time
    url = "http://127.0.0.1:%d/" % PORT
    if not server_alive():
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "serve"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(20):
            if server_alive():
                break
            time.sleep(0.15)
    if server_alive():
        open_dashboard(url)
        print(f"🎮 Game running at {url} — log today's words right on the page. "
              f"(Server naps after {IDLE_LIMIT // 60} idle minutes; run `write game` to wake it.)")
    else:
        state = load(STATE_FILE, DEFAULT_STATE)
        rewards = load(REWARDS_FILE, DEFAULT_REWARDS)
        path = render_dashboard(state, rewards, today_result_from_history(state))
        open_dashboard(path)
        print(f"🎮 Live server unavailable — opened static dashboard: {path}")


def week_grid(state):
    done_dates = {h["date"] for h in state["history"]}
    cells = []
    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        cells.append(d.strftime("%a")[0] + ("✓" if d.isoformat() in done_dates else "·"))
    return "  ".join(cells)


def cmd_status():
    state = load(STATE_FILE, DEFAULT_STATE)
    today_done = state["last_checkin"] == date.today().isoformat()
    print(f"🔥 Streak: {state['streak']} day(s)   (best: {state['best_streak']})")
    print(f"🪙 Coins:  {state['coins']}   ❄️ Freezes: {state['freezes']}")
    print(f"📅 Last 7 days:  {week_grid(state)}")
    print("📝 Today: " + ("done — go live your life." if today_done
                          else f"not yet. Floor is {MIN_WORDS} words. Even 50 keeps the streak."))
    nxt = next((m for m in sorted(MILESTONES) if m > state["streak"]), None)
    if nxt:
        print(f"🏆 Next milestone: day {nxt} ({nxt - state['streak']} to go)")


def cmd_shop():
    state = load(STATE_FILE, DEFAULT_STATE)
    rewards = load(REWARDS_FILE, DEFAULT_REWARDS)
    print(f"🪙 Wallet: {state['coins']} coins\n")
    for item in rewards["shop"]:
        mark = "✅" if state["coins"] >= item["cost"] else "🔒"
        print(f"  {mark} [{item['id']:>8}] {item['cost']:>4} — {item['name']}")
    print("\nRedeem with: writeflow.py redeem <id>   (edit rewards.json to customize)")


def cmd_redeem(item_id):
    state = load(STATE_FILE, DEFAULT_STATE)
    rewards = load(REWARDS_FILE, DEFAULT_REWARDS)
    item = next((i for i in rewards["shop"] if i["id"] == item_id), None)
    if not item:
        print(f"No item '{item_id}'. Run: writeflow.py shop")
        return
    if state["coins"] < item["cost"]:
        print(f"Not enough coins: {item['name']} costs {item['cost']}, "
              f"you have {state['coins']}. Keep writing.")
        return
    state["coins"] -= item["cost"]
    state["redeemed"].append({"date": date.today().isoformat(), **item})
    if item_id == "dayoff" and state["freezes"] < MAX_FREEZES:
        state["freezes"] += 1
        print("❄️  Skip day banked as a streak freeze — use it whenever.")
    save_state(state)
    print(f"🎉 Redeemed: {item['name']} (-{item['cost']} coins, {state['coins']} left). "
          "Actually do the treat — that's the whole point.")


def cmd_log():
    state = load(STATE_FILE, DEFAULT_STATE)
    if not state["history"]:
        print("No sessions yet. Log your first: writeflow.py done <words>")
        return
    for h in state["history"][-10:]:
        loot = f"  🎁 {h['loot']}" if h.get("loot") else ""
        print(f"  {h['date']}  {h['words']:>5} words  +{h['coins']} coins{loot}")


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WriteFlow</title>
<style>
:root{
  --bg0:#0b0e1a; --card:#161b36; --edge:#2b3263; --ink:#e8ecff; --dim:#8a93c4;
  --gold:#ffd24a; --fire:#ff7a3d; --ice:#7fd8ff; --green:#4ade80; --purple:#b78cff;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(1100px 600px at 50% -10%, #242c5c, var(--bg0)) fixed;
  color:var(--ink);font-family:Menlo,Consolas,"Courier New",monospace;
  min-height:100vh;padding:30px 18px 70px}
.wrap{max-width:780px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:20px}
h1{font-size:20px;letter-spacing:7px;color:var(--gold);text-shadow:0 0 18px rgba(255,210,74,.4)}
.sub{color:var(--dim);font-size:11px;letter-spacing:2px}
.row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--edge);border-radius:12px;
  padding:16px 14px;text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.35)}
.big{font-size:34px;font-weight:bold;line-height:1.1}
.lbl{color:var(--dim);font-size:10px;letter-spacing:2px;margin-top:6px;text-transform:uppercase}
.flame{display:inline-block;animation:flick 1.6s ease-in-out infinite}
@keyframes flick{0%,100%{transform:scale(1)}50%{transform:scale(1.15) rotate(-3deg)}}
.streak .big{color:var(--fire)} .coins .big{color:var(--gold)}
.freeze .big{color:var(--ice);font-size:26px;padding-top:6px}
.note{color:var(--ice);font-size:11px;margin:2px 0 14px;text-align:center}
.panel{background:var(--card);border:1px solid var(--edge);border-radius:12px;
  padding:18px;margin-bottom:14px;box-shadow:0 6px 24px rgba(0,0,0,.35)}
.ptitle{font-size:11px;letter-spacing:3px;color:var(--dim);text-transform:uppercase;margin-bottom:12px}
.slots{display:flex;gap:12px;justify-content:center;margin:6px 0 14px}
.reel{width:84px;height:84px;background:#0d1128;border:2px solid var(--edge);border-radius:12px;
  display:flex;align-items:center;justify-content:center;font-size:44px;
  box-shadow:inset 0 6px 18px rgba(0,0,0,.6)}
.reel.land{border-color:var(--gold);box-shadow:0 0 16px rgba(255,210,74,.35),inset 0 6px 18px rgba(0,0,0,.6);
  animation:pop .3s ease}
@keyframes pop{50%{transform:scale(1.12)}}
.banner{text-align:center;min-height:44px}
.bt{font-size:15px;letter-spacing:2px;font-weight:bold}
.bt.small{color:var(--green)} .bt.medium{color:var(--purple)}
.bt.jackpot{color:var(--gold);text-shadow:0 0 14px rgba(255,210,74,.6);
  display:inline-block;animation:flick 1s infinite}
.bt.none{color:var(--dim)}
.bl{color:var(--ink);font-size:13px;margin-top:6px}
.earn{text-align:center;color:var(--gold);font-size:12px;margin-top:10px}
.mile{margin-top:12px;padding:12px;border:1px dashed var(--gold);border-radius:10px;
  color:var(--gold);font-size:12px;text-align:center}
.quest{text-align:center;padding:8px 0 4px}
.quest .qt{font-size:16px;letter-spacing:3px;color:var(--gold);margin-bottom:10px}
.quest .qd{color:var(--ink);font-size:13px;line-height:1.6}
.cmd{display:inline-block;margin-top:12px;background:#0d1128;border:1px solid var(--edge);
  border-radius:8px;padding:8px 14px;color:var(--green);font-size:13px}
.qform{margin-top:14px}
.qinput{background:#0d1128;border:1px solid var(--edge);border-radius:8px;padding:10px 12px;
  color:var(--ink);font-family:inherit;font-size:14px;width:150px;text-align:center;outline:none}
.qinput:focus{border-color:var(--gold);box-shadow:0 0 10px rgba(255,210,74,.25)}
.qbtn{background:linear-gradient(90deg,var(--fire),var(--gold));border:none;border-radius:8px;
  padding:11px 20px;font-family:inherit;font-size:12px;font-weight:bold;letter-spacing:2px;
  color:#1a1035;cursor:pointer;margin-left:8px}
.qbtn:hover{filter:brightness(1.12)}
.qbtn:active{transform:scale(.96)}
.xpbar{height:14px;background:#0d1128;border:1px solid var(--edge);border-radius:8px;overflow:hidden}
.xpfill{height:100%;width:0;background:linear-gradient(90deg,var(--fire),var(--gold));
  border-radius:8px;transition:width 1.2s cubic-bezier(.2,.8,.2,1)}
.xplbl{display:flex;justify-content:space-between;color:var(--dim);font-size:10px;
  letter-spacing:1px;margin-top:6px}
.cal{display:flex;gap:6px;justify-content:center;flex-wrap:wrap}
.cell{width:34px;height:34px;border-radius:8px;background:#0d1128;border:1px solid var(--edge);
  display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--dim)}
.cell.done{background:rgba(74,222,128,.16);border-color:var(--green);color:var(--green)}
.cell.today{outline:2px solid var(--gold)}
.shopgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.item{background:#0d1128;border:1px solid var(--edge);border-radius:10px;padding:12px;opacity:.55}
.item.ok{opacity:1;border-color:var(--gold);box-shadow:0 0 12px rgba(255,210,74,.18)}
.iname{font-size:12px;line-height:1.4;min-height:34px}
.icost{color:var(--gold);font-size:12px;margin-top:6px}
.ibuy{color:var(--green);font-size:11px;margin-top:6px}
.cf{position:fixed;top:-14px;width:8px;height:14px;border-radius:2px;z-index:99;
  animation:fall linear forwards}
@keyframes fall{to{transform:translateY(112vh) rotate(760deg)}}
.hidden{display:none}
footer{text-align:center;color:var(--dim);font-size:10px;letter-spacing:2px;margin-top:24px}
</style>
</head>
<body>
<div class="wrap">
  <header><h1>✒️ WRITEFLOW</h1><div class="sub" id="best"></div></header>

  <div class="row">
    <div class="card streak"><div class="big"><span class="flame">🔥</span> <span id="streak">0</span></div><div class="lbl">day streak</div></div>
    <div class="card coins"><div class="big">🪙 <span id="coins">0</span></div><div class="lbl">coins</div></div>
    <div class="card freeze"><div class="big" id="freezes">–</div><div class="lbl">streak freezes</div></div>
  </div>
  <div class="note" id="streakmsg"></div>

  <div class="panel hidden" id="slotpanel">
    <div class="ptitle">Daily loot draw</div>
    <div class="slots"><div class="reel" id="r0">❔</div><div class="reel" id="r1">❔</div><div class="reel" id="r2">❔</div></div>
    <div class="banner" id="banner"></div>
    <div class="earn" id="earn"></div>
    <div class="mile hidden" id="mile"></div>
  </div>

  <div class="panel hidden" id="questpanel">
    <div class="quest">
      <div class="qt">⚔️ TODAY'S QUEST</div>
      <div class="qd" id="questtext"></div>
      <div class="qform hidden" id="qform">
        <input class="qinput" id="qwords" type="number" min="0" placeholder="words written">
        <button class="qbtn" id="qbtn">LOG IT</button>
      </div>
      <div class="cmd hidden" id="qcmd">write done &lt;words&gt;</div>
    </div>
  </div>

  <div class="panel">
    <div class="ptitle">Milestone progress</div>
    <div class="xpbar"><div class="xpfill" id="xpfill"></div></div>
    <div class="xplbl"><span id="xpfrom"></span><span id="xpto"></span></div>
  </div>

  <div class="panel">
    <div class="ptitle">Last 14 days</div>
    <div class="cal" id="cal"></div>
  </div>

  <div class="panel">
    <div class="ptitle">Reward shop — glowing = affordable</div>
    <div class="shopgrid" id="shop"></div>
  </div>

  <footer>WRITE · LOG · WIN · REPEAT</footer>
</div>

<script>
const D = __DATA__;
const $ = function(id){ return document.getElementById(id); };

function countUp(el, target, ms){
  var t0 = null;
  function step(t){
    if(!t0) t0 = t;
    var p = Math.min((t - t0)/ms, 1);
    el.textContent = Math.round(target * (1 - Math.pow(1-p,3)));
    if(p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

$("streak").textContent = D.streak;
countUp($("coins"), D.coins, 900);
$("freezes").textContent = D.freezes > 0 ? "\\u2744\\ufe0f".repeat(D.freezes) : "\\u2013";
$("best").textContent = "BEST STREAK: " + D.best;

if(D.today && D.today.streak_msg){ $("streakmsg").textContent = D.today.streak_msg; }

if(D.next_milestone){
  $("xpfrom").textContent = "DAY " + D.streak;
  $("xpto").textContent = "DAY " + D.next_milestone.day + " \\u00b7 " + D.next_milestone.togo + " TO GO";
  setTimeout(function(){ $("xpfill").style.width = Math.max(D.next_milestone.pct, 3) + "%"; }, 350);
}else{
  $("xpfrom").textContent = "ALL MILESTONES CLEARED";
  $("xpfill").style.width = "100%";
}

D.days.forEach(function(d){
  var c = document.createElement("div");
  c.className = "cell" + (d.done ? " done" : "") + (d.today ? " today" : "");
  c.textContent = d.l;
  $("cal").appendChild(c);
});

D.shop.forEach(function(it){
  var c = document.createElement("div");
  c.className = "item" + (it.affordable ? " ok" : "");
  c.innerHTML = "<div class='iname'>" + it.name + "</div>" +
    "<div class='icost'>\\ud83e\\ude99 " + it.cost + "</div>" +
    (it.affordable ? "<div class='ibuy'>write redeem " + it.id + "</div>" : "");
  $("shop").appendChild(c);
});

var SYM = ["\\ud83d\\udcdc","\\u2712\\ufe0f","\\ud83e\\ude99","\\ud83d\\udd25","\\ud83d\\udcda","\\u2615","\\ud83c\\udf19"];
var GIFT = "\\ud83c\\udf81", GEM = "\\ud83d\\udc8e";
function rs(){ return SYM[Math.floor(Math.random()*SYM.length)]; }
function targets(tier){
  if(tier === "jackpot") return [GEM, GEM, GEM];
  if(tier === "medium")  return [GIFT, GIFT, GIFT];
  if(tier === "small")   return [GIFT, GIFT, rs()];
  var a = rs(), b = rs(), c = rs();
  while(b === a) b = rs();
  while(c === b) c = rs();
  return [a,b,c];
}

function confetti(n){
  var colors = ["#ffd24a","#ff7a3d","#7fd8ff","#b78cff","#4ade80"];
  for(var i=0;i<n;i++){
    var p = document.createElement("div");
    p.className = "cf";
    p.style.left = (Math.random()*100) + "vw";
    p.style.background = colors[i % colors.length];
    p.style.animationDelay = (Math.random()*0.8) + "s";
    p.style.animationDuration = (2 + Math.random()*2) + "s";
    document.body.appendChild(p);
    (function(el){ setTimeout(function(){ el.remove(); }, 5200); })(p);
  }
}

function reveal(res){
  var b = $("banner");
  if(res.tier){
    var names = {small:"\\ud83c\\udf81 SMALL WIN", medium:"\\ud83c\\udf89 NICE PULL", jackpot:"\\ud83d\\udc8e JACKPOT"};
    b.innerHTML = "<span class='bt " + res.tier + "'>" + names[res.tier] + "</span>" +
      "<div class='bl'>" + res.loot + "</div>";
    if(res.tier === "jackpot") confetti(130);
    else if(res.tier === "medium") confetti(55);
  }else{
    var togo = Math.max(3 - D.dry_draws, 0) + 1;
    b.innerHTML = "<span class='bt none'>\\ud83c\\udfb2 NO LOOT TODAY</span>" +
      "<div class='bl'>Guaranteed win within " + togo + " draw" + (togo>1?"s":"") + " \\u2014 come back tomorrow.</div>";
  }
  $("earn").textContent = "+" + res.earned + " coins \\u00b7 " + res.words + " words logged";
  if(res.milestone){
    $("mile").textContent = "\\ud83c\\udfc6 MILESTONE \\u2014 " + res.milestone;
    $("mile").classList.remove("hidden");
    confetti(90);
  }
}

if(D.today_logged && D.today){
  $("slotpanel").classList.remove("hidden");
  var tg = targets(D.today.tier);
  [$("r0"), $("r1"), $("r2")].forEach(function(r, i){
    var iv = setInterval(function(){ r.textContent = rs(); }, 60);
    setTimeout(function(){
      clearInterval(iv);
      r.textContent = tg[i];
      r.classList.add("land");
      if(i === 2) reveal(D.today);
    }, 900 + i*600);
  });
}else{
  $("questpanel").classList.remove("hidden");
  $("questtext").innerHTML = "Write <b>" + D.min_words + " words</b> to clear today's quest.<br>" +
    "Even 50 keeps the \\ud83d\\udd25 " + D.streak + "-day streak alive. Then log it:";
  if(location.protocol.indexOf("http") === 0){
    $("qform").classList.remove("hidden");
    var send = function(){
      var w = parseInt($("qwords").value || "0", 10) || 0;
      $("qbtn").disabled = true;
      fetch("/done", {method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: "words=" + w
      }).then(function(){ location.reload(); });
    };
    $("qbtn").addEventListener("click", send);
    $("qwords").addEventListener("keydown", function(e){ if(e.key === "Enter") send(); });
    $("qwords").focus();
  }else{
    $("qcmd").classList.remove("hidden");
  }
}
</script>
</body>
</html>
"""


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip())
        return
    cmd = args[0]
    if cmd == "done":
        try:
            words = int(args[1]) if len(args) > 1 else 0
        except ValueError:
            print("Usage: writeflow.py done <words>")
            return
        cmd_done(words)
    elif cmd in ("game", "dash", "play"):
        cmd_game()
    elif cmd == "serve":
        cmd_serve()
    elif cmd == "status":
        cmd_status()
    elif cmd == "shop":
        cmd_shop()
    elif cmd == "redeem":
        if len(args) < 2:
            print("Usage: writeflow.py redeem <id>")
            return
        cmd_redeem(args[1])
    elif cmd == "log":
        cmd_log()
    else:
        print(__doc__.strip())


if __name__ == "__main__":
    main()
