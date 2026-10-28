"""
LIAR'S DICE — a saloon dice game in the style of Red Dead Redemption (2010)
==========================================================================
Rules follow Liar's Dice as played in RDR1:
  * 2–4 players, each with one cup and five six-sided dice. No wild dice.
  * The opener bids "X dice showing Y". Play passes clockwise (to the left).
  * On your turn you may RAISE the bid, call BLUFF, or call SPOT ON.
      - Raise   : more dice of any face, or the same number of dice with a higher face.
      - Bluff   : if the table holds fewer than bid -> the bidder loses a die,
                  otherwise -> the caller loses a die.
      - Spot On : if the table holds exactly the bid -> EVERY other player loses a die,
                  otherwise -> the caller loses a die.
  * Lost dice never come back. Out of dice = out of the game. Last player with dice wins the pot.
  * The next round's opening bid passes counter-clockwise from the previous opener.
  * Single-player ante: $20 per player.

Run:
    pip install -r requirements.txt
    streamlit run main.py
"""

import html
import math
import random
import time

import streamlit as st

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
ANTE = 20
START_MONEY = 200
DICE_PER_PLAYER = 5
NPC_NAMES = [
    "Diego", "Abraham", "Old Pete", "Rosa", "Silas", "Mateo",
    "Clem", "Jonah", "Ezequiel", "Hattie", "Wade", "Lupe",
]
AVATARS = ["🤠", "🧔", "👴", "👒", "🎩", "👨"]
LOCATIONS = {
    "Thieves' Landing": "A river den of smugglers, drunks and cardsharps — West Elizabeth",
    "Casa Madrugada": "A dusty hacienda south of the border — Nuevo Paraíso",
    "Escalera": "The Governor's fortress town — Nuevo Paraíso",
}
SPEEDS = {"Slow": 2.0, "Normal": 1.25, "Fast": 0.6}

NUM_WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty",
]
FACE_ONE = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
FACE_MANY = {1: "ones", 2: "twos", 3: "threes", 4: "fours", 5: "fives", 6: "sixes"}

PIPS = {
    1: [(50, 50)],
    2: [(27, 27), (73, 73)],
    3: [(27, 27), (50, 50), (73, 73)],
    4: [(27, 27), (73, 27), (27, 73), (73, 73)],
    5: [(27, 27), (73, 27), (50, 50), (27, 73), (73, 73)],
    6: [(27, 24), (73, 24), (27, 50), (73, 50), (27, 76), (73, 76)],
}

# Table talk — original lines written in an Old West saloon voice.
LINES = {
    "open": [
        "Let's see what the bones have to say.",
        "Cups down, gentlemen. Let's dance.",
        "Got a good feelin' about this one.",
        "Easy now. Nobody's gettin' shot over dice... tonight.",
        "I'll start us off gentle.",
        "My granddaddy taught me this game. Then he lost the farm at it.",
    ],
    "raise": [
        "I'll see that and raise ya.",
        "You don't scare me, friend.",
        "Bold talk. I'll go bolder.",
        "That all you got?",
        "Hmph. Easy money.",
        "I've seen better bluffs from a preacher.",
        "Keep 'em comin'.",
        "Higher. Much higher.",
    ],
    "bold": [
        "Don't look at me like that.",
        "I know what I'm doin'... mostly.",
        "Fortune favors the reckless.",
        "Go on, call me a liar. I dare ya.",
    ],
    "bluff": [
        "Liar! Lift that cup.",
        "Horse feathers. Show 'em.",
        "You're bluffin', and we both know it.",
        "That's a tall tale, friend. Let's see 'em.",
        "Not a chance in hell. Cups up!",
        "I call. Show your hand, snake.",
    ],
    "spot": [
        "Spot on. I'd bet my boots on it.",
        "That's exactly right, I reckon.",
        "Dead on the money. Show 'em.",
        "Spot on — and I ain't never wrong.",
    ],
    "gloat": [
        "Read you like a dime novel.",
        "Ha! Never doubt me.",
        "Pay up, friend.",
        "Like takin' candy from a baby.",
        "Told ya. The bones don't lie — folks do.",
        "Another round? Your funeral.",
    ],
    "lose": [
        "Well, I'll be...",
        "Beginner's luck, that's all.",
        "Dang it all.",
        "Lucky guess. Won't happen twice.",
        "These dice are crooked, I tell ya.",
        "Bartender! Whiskey. Now.",
    ],
    "out": [
        "I'm cleaned out. Good game, gents.",
        "That's me done. Drinks are on you.",
        "Bah. I'm goin' to the bar.",
        "Next time, stranger. Next time.",
    ],
    "win": [
        "Drinks are on me... well, maybe one.",
        "The bones love me tonight.",
        "Pleasure doin' business.",
        "Come back when you've got more money and less sense.",
    ],
}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def p_at_least(n: int, k: int, p: float = 1 / 6) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def p_exact(n: int, k: int, p: float = 1 / 6) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * p**k * (1 - p) ** (n - k)


def bid_beats(new, cur) -> bool:
    if cur is None:
        return True
    return new[0] > cur[0] or (new[0] == cur[0] and new[1] > cur[1])


def bid_words(q, f) -> str:
    word = NUM_WORDS[q] if q < len(NUM_WORDS) else str(q)
    return f"{word.capitalize()} {FACE_ONE[f] if q == 1 else FACE_MANY[f]}"


# ----------------------------------------------------------------------------
# Game engine
# ----------------------------------------------------------------------------
class Game:
    def __init__(self, seats, location="Thieves' Landing", ante=ANTE, seed=None):
        self.rng = random.Random(seed)
        self.chat_rng = random.Random(None if seed is None else seed + 7919)
        self.location = location
        self.ante = ante
        self.players = []
        for k, s in enumerate(seats):
            self.players.append(
                dict(
                    name=s["name"],
                    human=s["human"],
                    money=s.get("money", START_MONEY),
                    avatar=s.get("avatar", AVATARS[k % len(AVATARS)]),
                    dice=[],
                    count=DICE_PER_PLAYER,
                )
            )
        self.pot = 0
        self.round_no = 0
        self.phase = "bidding"  # bidding | reveal | gameover
        self.current_bid = None
        self.bidder = None
        self.turn = None
        self.history = []  # (player, qty, face) this round
        self.say = {}  # seat -> {"line": str|None, "text": str}
        self.reveal = None
        self.winner = None
        self.feed = []  # table talk: dicts {who, text, line, kind}
        self.bid_seq = 0
        self.unlocked = None
        self.banked = False
        self._collect_antes()
        self.opener = self.rng.randrange(len(self.players))
        self._event(f"{self.players[self.opener]['name']} is picked to open the bidding.")
        self.start_round()

    # --- utilities -----------------------------------------------------------
    def alive(self):
        return [i for i, p in enumerate(self.players) if p["count"] > 0]

    def total_dice(self):
        return sum(p["count"] for p in self.players)

    def next_alive(self, i, step=1):
        n = len(self.players)
        for k in range(1, n + 1):
            j = (i + step * k) % n
            if self.players[j]["count"] > 0:
                return j
        return i

    def is_legal(self, q, f):
        return 1 <= f <= 6 and 1 <= q <= self.total_dice() and bid_beats((q, f), self.current_bid)

    def default_raise(self):
        """Suggested next bid for the UI (None if the bid cannot be raised)."""
        total = self.total_dice()
        if self.current_bid is None:
            return (1, 1)
        q, f = self.current_bid
        if q + 1 <= total:
            return (q + 1, f)
        if f < 6:
            return (q, f + 1)
        return None

    def _event(self, text):
        self.feed.append(dict(who=None, text=text, line=None, kind="event"))

    def _quip(self, i, kind, chance=1.0):
        if self.players[i]["human"] or self.chat_rng.random() > chance:
            return None
        return self.chat_rng.choice(LINES[kind])

    def _collect_antes(self):
        for p in self.players:
            if p["money"] < self.ante:
                p["money"] += START_MONEY
                self._event(f"{p['name']} borrows ${START_MONEY} from the barkeep.")
            p["money"] -= self.ante
            self.pot += self.ante
        self._event(f"Everyone antes up ${self.ante}. The pot stands at ${self.pot}.")

    # --- round flow -----------------------------------------------------------
    def start_round(self):
        self.round_no += 1
        for p in self.players:
            p["dice"] = sorted(self.rng.randint(1, 6) for _ in range(p["count"])) if p["count"] > 0 else []
        self.current_bid = None
        self.bidder = None
        self.history = []
        self.say = {}
        self.reveal = None
        self.turn = self.opener
        self.phase = "bidding"
        self.bid_seq += 1
        self.unlocked = None
        self._event(f"Round {self.round_no} — cups slam down. {self.total_dice()} dice on the table.")

    def place_bid(self, i, q, f, line=None):
        assert self.phase == "bidding" and i == self.turn, "Not this player's turn"
        assert self.is_legal(q, f), f"Illegal bid: {q}x{f}"
        self.current_bid = (q, f)
        self.bidder = i
        self.history.append((i, q, f))
        self.bid_seq += 1
        self.say[i] = dict(line=line, text=f"{bid_words(q, f)}.")
        self.feed.append(dict(who=i, text=f"{bid_words(q, f)}.", line=line, kind="bid"))
        self.turn = self.next_alive(i, 1)

    def call(self, i, kind):
        assert self.phase == "bidding" and i == self.turn and self.current_bid is not None
        assert kind in ("bluff", "spot")
        q, f = self.current_bid
        snapshot = {j: list(self.players[j]["dice"]) for j in self.alive()}
        actual = sum(d == f for dice in snapshot.values() for d in dice)
        b = self.bidder
        if kind == "bluff":
            correct = actual < q
            losers = [b] if correct else [i]
        else:
            correct = actual == q
            losers = [j for j in snapshot if j != i] if correct else [i]
        eliminated = []
        for j in losers:
            self.players[j]["count"] -= 1
            if self.players[j]["count"] == 0:
                eliminated.append(j)

        nm = self.players
        call_line = self._quip(i, kind)
        call_text = "Liar!" if kind == "bluff" else "Spot on!"
        self.feed.append(dict(who=i, text=call_text, line=call_line, kind="call"))

        # Reactions around the table
        react = {}
        winners = [j for j in snapshot if j not in losers]
        for j in winners:
            if j in (i, b):
                line = self._quip(j, "gloat", 0.85)
                if line:
                    react[j] = line
        for j in losers:
            line = self._quip(j, "lose", 0.8 if len(losers) == 1 else 0.45)
            if line:
                react[j] = line
        for j in eliminated:
            line = self._quip(j, "out")
            if line:
                react[j] = line

        loser_names = ", ".join(nm[j]["name"] for j in losers)
        self._event(f"Cups up: {NUM_WORDS[actual] if actual < len(NUM_WORDS) else actual} "
                    f"{FACE_ONE[f] if actual == 1 else FACE_MANY[f]} on the table. "
                    f"{loser_names} lose{'s' if len(losers) == 1 else ''} a die.")
        for j in eliminated:
            self._event(f"{nm[j]['name']} is out of dice and leaves the table.")

        alive = self.alive()
        self.bid_seq += 1
        self.reveal = dict(
            kind=kind, caller=i, bidder=b, bid=(q, f), actual=actual, losers=losers,
            eliminated=eliminated, snapshot=snapshot, correct=correct,
            history=list(self.history), call_line=call_line, react=react,
        )
        if len(alive) == 1:
            self.winner = alive[0]
            self.players[self.winner]["money"] += self.pot
            self.phase = "gameover"
            line = self._quip(self.winner, "win")
            if line:
                react[self.winner] = line
            self._event(f"{nm[self.winner]['name']} takes the pot — ${self.pot}.")
        else:
            self.opener = self.next_alive(self.opener, -1)
            self.reveal["next_opener"] = self.opener
            self.phase = "reveal"
        for j, line in react.items():
            self.feed.append(dict(who=j, text="", line=line, kind="say"))

    # --- AI modelled on the RDR1 NPCs -----------------------------------------
    def ai_decide(self, i):
        rng = self.rng
        p = self.players[i]
        dice = p["dice"]
        total = self.total_dice()
        unknown = total - len(dice)
        cnt = [0] * 7
        for d in dice:
            cnt[d] += 1
        n_alive = len(self.alive())
        cur = self.current_bid

        # Opening bid
        if cur is None:
            if len(dice) == 1:  # NPCs always name their last die honestly
                return ("bid", rng.choice([1, 1, 2]) if total >= 2 else 1, dice[0])
            best = max(range(1, 7), key=lambda f: (cnt[f], -f))
            exp = unknown / 6
            r = rng.random()
            if r < 0.5:
                extra = 0
            elif r < 0.85:
                extra = int(exp * 0.5)
            else:
                extra = int(round(exp)) + (1 if rng.random() < 0.3 else 0)
            return ("bid", max(1, min(total, cnt[best] + extra)), best)

        cq, cf = cur
        have = cnt[cf]
        need = cq - have
        p_true = p_at_least(unknown, need)
        p_spot = p_exact(unknown, need) if need >= 0 else 0.0

        cands = []
        for f in range(1, 7):
            q = cq if f > cf else cq + 1
            if q <= total:
                cands.append((p_at_least(unknown, q - cnt[f]), cnt[f], q, f))
        if len(dice) == 1:
            own = [c for c in cands if c[3] == dice[0]]
            if own:
                cands = own
        best = max(cands) if cands else None

        # NPC habit: holding none of that face -> almost always shouts bluff
        if have == 0 and cq >= 2 and rng.random() < 0.8:
            return ("bluff",)
        # Spot on: never in a 1-on-1 duel, rare at a crowded table
        if n_alive > 2 and need >= 0 and p_spot >= 0.3 and rng.random() < 0.12:
            return ("spot",)
        if best is None:
            return ("bluff",)

        trusts_low_bid = cq < 4 and have >= 1
        if trusts_low_bid or p_true >= 0.5:
            if best[0] < 0.2 and not trusts_low_bid:
                return ("bluff",)
            q, f = best[2], best[3]
            if rng.random() < 0.08:  # the occasional reckless jump
                q = min(total, q + rng.choice([1, 2]))
                return ("bid", q, f, "bold")
            return ("bid", q, f)
        if best[0] > 0.6 and rng.random() < 0.3:
            return ("bid", best[2], best[3])
        return ("bluff",)

    def ai_act(self, i):
        action = self.ai_decide(i)
        if action[0] == "bid":
            q, f = action[1], action[2]
            mood = action[3] if len(action) > 3 else ("open" if self.current_bid is None else "raise")
            if not self.is_legal(q, f):  # safety net
                dr = self.default_raise()
                if dr is None:
                    self.call(i, "bluff")
                    return
                q, f = dr
            self.place_bid(i, q, f, line=self._quip(i, mood, 0.55))
        else:
            self.call(i, action[0])


# ----------------------------------------------------------------------------
# Graphics (pure SVG/CSS — no external assets)
# ----------------------------------------------------------------------------
def die_svg(face, size=40, state="normal"):
    if state == "hidden":
        body = (
            "<rect x='5' y='5' width='90' height='90' rx='18' fill='#2b170b' stroke='#c9a227' stroke-width='5'/>"
            "<circle cx='50' cy='50' r='11' fill='#c9a227' opacity='.55'/>"
        )
    else:
        fill, stroke, pip, sw = "#f6efdc", "#5a3b1c", "#2a160a", 4
        if state == "hl":
            fill, stroke, pip, sw = "#f7cf4f", "#8e1f17", "#3b0d06", 7
        body = (
            f"<rect x='5' y='5' width='90' height='90' rx='18' fill='{fill}' stroke='{stroke}' stroke-width='{sw}'/>"
            "<rect x='13' y='11' width='74' height='26' rx='12' fill='#ffffff' opacity='.22'/>"
        )
        for (x, y) in PIPS[face]:
            body += f"<circle cx='{x}' cy='{y}' r='9' fill='{pip}'/>"
    label = "hidden die" if state == "hidden" else f"die {face}"
    return (
        f"<svg class='die die-{state}' width='{size}' height='{size}' viewBox='0 0 100 100' "
        f"xmlns='http://www.w3.org/2000/svg' aria-label='{label}'>{body}</svg>"
    )


CUP_SVG = (
    "<svg class='cup' width='46' height='42' viewBox='0 0 100 90' xmlns='http://www.w3.org/2000/svg'>"
    "<path d='M20 12 H80 L72 86 H28 Z' fill='#5b3417' stroke='#1e0f06' stroke-width='4'/>"
    "<rect x='13' y='5' width='74' height='12' rx='5' fill='#7d4c25' stroke='#1e0f06' stroke-width='3'/>"
    "<path d='M29 36 H71' stroke='#c9a227' stroke-width='3' opacity='.75'/>"
    "<path d='M31 64 H69' stroke='#c9a227' stroke-width='3' opacity='.75'/>"
    "</svg>"
)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Rye&family=Special+Elite&display=swap');
:root{--parch:#f1e3c2;--paper:#fffaf0;--gold:#d4a73a;--blood:#8e1f17;--ink:#2a160a;--leather:#6b4423;}

/* ---------- page ---------- */
.stApp{
  background:
    radial-gradient(ellipse at 50% 0%, rgba(255,190,110,.16), transparent 55%),
    radial-gradient(ellipse at 50% 120%, rgba(0,0,0,.65), transparent 60%),
    repeating-linear-gradient(90deg,#2b1a10 0 26px,#321f13 26px 52px,#27170d 52px 80px);
  color:var(--parch);
}
header[data-testid="stHeader"]{background:transparent;}
[data-testid="stToolbar"],[data-testid="stSidebarCollapsedControl"],#MainMenu,footer{display:none !important;}
.block-container{padding-top:1.2rem;padding-bottom:3rem;max-width:900px;}
.stApp p,.stApp li,.stApp label{font-family:'Special Elite','Courier New',monospace;}
/* keep Streamlit's icon font intact (fixes the "arrow_right" text) */
[data-testid="stIconMaterial"]{font-family:'Material Symbols Rounded' !important;}
[data-testid="stWidgetLabel"] p{color:var(--parch);font-size:.9rem;}

/* ---------- form widgets: same look in light & dark browser themes ---------- */
.stApp [data-baseweb="input"],.stApp [data-baseweb="base-input"],
.stApp [data-baseweb="select"]>div{background:var(--paper) !important;border-color:var(--leather) !important;}
.stApp input{background:var(--paper) !important;color:var(--ink) !important;-webkit-text-fill-color:var(--ink) !important;
  font-family:'Special Elite','Courier New',monospace !important;font-size:1rem !important;}
[data-testid="stSelectbox"] [data-baseweb="select"] div{color:var(--ink) !important;font-family:'Special Elite',monospace;}
[data-testid="stSelectbox"] svg{fill:var(--ink) !important;color:var(--ink) !important;}
[data-baseweb="popover"] ul,[data-baseweb="popover"] [role="listbox"]{background:var(--paper) !important;}
[data-baseweb="popover"] li,[data-baseweb="popover"] [role="option"],[data-baseweb="popover"] li *{color:var(--ink) !important;font-family:'Special Elite',monospace;}
[data-testid="stNumberInputStepDown"],[data-testid="stNumberInputStepUp"]{background:var(--leather) !important;color:#f6e7c1 !important;}
[data-testid="stNumberInputStepDown"] svg,[data-testid="stNumberInputStepUp"] svg{fill:#f6e7c1 !important;color:#f6e7c1 !important;}

button[kind="segmented_control"],button[kind="segmented_controlActive"]{
  border:2px solid var(--leather) !important;min-height:42px;font-family:'Special Elite',monospace;}
button[kind="segmented_control"]{background:var(--paper) !important;}
button[kind="segmented_control"] p{color:var(--ink) !important;font-weight:bold;}
button[kind="segmented_control"]:hover{background:#f3dfae !important;}
button[kind="segmented_controlActive"]{background:var(--blood) !important;}
button[kind="segmented_controlActive"] p{color:#fff3d6 !important;font-weight:bold;}

/* ---------- title ---------- */
.ld-title{font-family:'Rye',serif;font-size:clamp(2.1rem,8vw,3.6rem);text-align:center;color:var(--gold);
  text-shadow:0 3px 0 #3a1b0b,0 0 18px rgba(212,167,58,.35);letter-spacing:3px;margin:0;line-height:1.1;}
.ld-sub{text-align:center;opacity:.92;margin:.25rem 0 1rem;font-size:.92rem;font-family:'Special Elite',monospace;}
.ld-sub b{color:var(--gold);font-family:'Rye',serif;font-weight:normal;}

/* ---------- table & seats ---------- */
.ld-table{background:radial-gradient(ellipse at center,#86532b 0%,#633a1d 55%,#3f2210 100%);
  border:7px solid #241208;border-radius:30px;padding:14px 12px 16px;
  box-shadow:inset 0 0 45px rgba(0,0,0,.65),0 12px 30px rgba(0,0,0,.6),0 0 0 2px rgba(212,167,58,.25);}
.ld-seats{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}
.seat{flex:1 1 180px;max-width:215px;background:rgba(18,9,3,.62);border:2px solid rgba(212,167,58,.3);
  border-radius:16px;padding:10px 8px;text-align:center;transition:all .25s;font-family:'Special Elite',monospace;}
.seat.active{border-color:var(--gold);box-shadow:0 0 0 3px rgba(212,167,58,.22),0 0 22px rgba(212,167,58,.5);}
.seat.out{opacity:.42;filter:grayscale(.9);}
.seat-name{font-family:'Rye',serif;color:var(--parch);font-size:1.02rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.seat-meta{font-size:.78rem;opacity:.85;margin-top:3px;}
.seat-dice{display:flex;flex-wrap:wrap;gap:3px;justify-content:center;margin-top:5px;min-height:24px;}
.tags{min-height:18px;}
.tag{display:inline-block;font-size:.64rem;padding:1px 7px;border-radius:999px;margin:2px 2px 0;letter-spacing:.3px;}
.tag-you{background:var(--gold);color:var(--ink);}
.tag-open{background:rgba(255,255,255,.14);color:var(--parch);}
.tag-top{background:#3c5a2a;color:#e9f3d9;}
.tag-loss{background:var(--blood);color:#fff;}
.tag-out{background:#111;color:#bbb;}
.bubble{position:relative;display:block;background:var(--parch);color:var(--ink);border-radius:12px;
  padding:6px 9px;margin:9px 2px 0;font-size:.85rem;line-height:1.25;box-shadow:0 2px 0 var(--leather);text-align:center;}
.bubble:before{content:"";position:absolute;top:-7px;left:50%;margin-left:-7px;border:7px solid transparent;
  border-top:0;border-bottom-color:var(--parch);}
.bubble .q{font-style:italic;display:block;}
.bubble .b{font-family:'Rye',serif;display:block;margin-top:2px;color:var(--blood);}
.bubble.turn{background:var(--gold);}
.bubble.turn:before{border-bottom-color:var(--gold);}
.dots span{animation:blink 1.2s infinite;font-size:1.2rem;}
.dots span:nth-child(2){animation-delay:.2s}.dots span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,100%{opacity:.15}50%{opacity:1}}

.ld-center{text-align:center;margin-top:14px;font-family:'Special Elite',monospace;}
.bidplaque{display:inline-flex;align-items:center;gap:10px;background:linear-gradient(#f5e9cb,#dcc699);
  color:var(--ink);border:3px solid var(--leather);border-radius:14px;padding:6px 18px;font-family:'Rye',serif;
  font-size:1.9rem;box-shadow:0 4px 0 #2a160a;}
.bidwords{font-family:'Rye',serif;color:var(--gold);font-size:1.05rem;margin-top:6px;}
.bidby{font-size:.85rem;opacity:.9;}
.nobid{font-family:'Rye',serif;color:var(--gold);font-size:1.15rem;}
.chips{display:flex;justify-content:center;gap:6px;flex-wrap:wrap;margin-top:10px;}
.chip{background:rgba(0,0,0,.38);border:1px solid rgba(212,167,58,.45);border-radius:999px;padding:3px 11px;font-size:.78rem;}

/* ---------- your cup ---------- */
.hand{margin:16px 0 4px;background:rgba(18,9,3,.62);border:2px solid var(--gold);border-radius:18px;padding:12px;text-align:center;}
.hand-title{font-family:'Rye',serif;color:var(--gold);font-size:1.1rem;margin-bottom:8px;}
.hand-dice{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;}
.hand-sum{margin-top:8px;font-size:.85rem;opacity:.9;font-family:'Special Elite',monospace;}

/* ---------- parchment panels ---------- */
.st-key-bidpanel,.st-key-setup,.st-key-cover,.st-key-result{
  background:linear-gradient(#f5ead0,#e2cd9d);border:3px solid var(--leather);border-radius:18px;
  padding:14px 14px 10px;box-shadow:0 6px 0 #2a160a,0 12px 26px rgba(0,0,0,.5);margin-top:10px;}
.st-key-bidpanel [data-testid="stWidgetLabel"] p,.st-key-setup [data-testid="stWidgetLabel"] p{color:var(--ink) !important;}
.panel-title{font-family:'Rye',serif;font-size:1.4rem;color:var(--blood);text-align:center;margin-bottom:4px;}
.panel-note{text-align:center;font-size:.88rem;color:var(--ink);font-family:'Special Elite',monospace;}
.panel-note b{font-family:'Rye',serif;font-weight:normal;}
.preview{display:flex;align-items:center;justify-content:center;gap:8px;font-family:'Rye',serif;font-size:1.25rem;color:var(--ink);margin:4px 0 8px;flex-wrap:wrap;}
.warn{text-align:center;color:var(--blood);font-size:.85rem;font-family:'Special Elite',monospace;}
.verdict{font-family:'Rye',serif;font-size:clamp(1.7rem,6vw,2.4rem);text-align:center;color:var(--blood);margin:0;line-height:1.15;}
.verdict.win{color:#2f4a1f;}
.verdict-line{text-align:center;color:var(--ink);font-size:.98rem;margin:5px 0;font-family:'Special Elite',monospace;}
.verdict-line .inl{display:inline-flex;align-items:center;gap:5px;vertical-align:middle;}
.big{font-family:'Rye',serif;font-size:1.25rem;}

/* ---------- table talk ---------- */
.talk{margin-top:14px;background:rgba(18,9,3,.6);border:1px solid rgba(212,167,58,.35);border-radius:16px;padding:10px 12px;font-family:'Special Elite',monospace;}
.talk-title{font-family:'Rye',serif;color:var(--gold);font-size:1rem;margin-bottom:6px;}
.talk-row{padding:5px 0;border-top:1px dashed rgba(212,167,58,.2);font-size:.88rem;line-height:1.35;}
.talk-row:first-of-type{border-top:0;}
.talk-row .who{font-family:'Rye',serif;color:var(--gold);}
.talk-row .q{font-style:italic;color:#fff1cf;}
.talk-row .bid{color:#f3b7a5;font-family:'Rye',serif;}
.talk-row.event{opacity:.7;font-size:.8rem;}

/* ---------- buttons ---------- */
.stButton button{font-family:'Rye',serif !important;width:100%;min-height:50px;border-radius:12px;
  border:2px solid #1e0f06;background:linear-gradient(#7a4f2a,#5b3417);color:#f6e7c1;
  box-shadow:0 4px 0 #1e0f06;transition:transform .08s,filter .15s;}
.stButton button p{font-family:'Rye',serif !important;color:#f6e7c1 !important;font-size:1.05rem;}
.stButton button[kind="primary"]{background:linear-gradient(#b0301f,#7a1a12);}
.stButton button:hover{filter:brightness(1.15);border-color:var(--gold);}
.stButton button:active{transform:translateY(3px);box-shadow:0 1px 0 #1e0f06;}
.stButton button:disabled{filter:grayscale(.8) brightness(.8);opacity:.55;}

/* expanders */
[data-testid="stExpander"] details{background:rgba(20,10,4,.6);border:1px solid rgba(212,167,58,.35);border-radius:14px;}
[data-testid="stExpander"] summary p{color:var(--gold);font-family:'Rye',serif;}
[data-testid="stExpander"] summary svg,[data-testid="stExpander"] summary [data-testid="stIconMaterial"]{color:var(--gold);}
[data-testid="stExpanderDetails"] li,[data-testid="stExpanderDetails"] p{color:var(--parch);}

/* rows that must stay side-by-side even on phones */
.st-key-actions [data-testid="stHorizontalBlock"],[class*="st-key-seatrow"] [data-testid="stHorizontalBlock"],
.st-key-endbtns [data-testid="stHorizontalBlock"]{flex-wrap:nowrap !important;gap:.5rem !important;}
.st-key-actions [data-testid="stColumn"],[class*="st-key-seatrow"] [data-testid="stColumn"],
.st-key-endbtns [data-testid="stColumn"]{min-width:0 !important;}

/* ---------- phones ---------- */
@media (max-width:640px){
  .block-container{padding-left:.55rem;padding-right:.55rem;padding-top:.6rem;}
  .ld-sub{font-size:.8rem;}
  .ld-table{padding:10px 7px 12px;border-width:5px;border-radius:22px;}
  .ld-seats{gap:7px;}
  .seat{flex:1 1 calc(50% - 7px);max-width:none;padding:8px 5px;}
  .seat-name{font-size:.9rem;}
  .seat .cup{width:36px;height:32px;}
  .seat .die{width:19px;height:19px;}
  .bubble{font-size:.76rem;padding:5px 6px;}
  .hand .die{width:50px;height:50px;}
  .bidplaque{font-size:1.45rem;padding:4px 14px;}
  .bidplaque .die{width:38px;height:38px;}
  .stButton button{min-height:48px;padding:0 .3rem;}
  .stButton button p{font-size:.9rem;}
  .st-key-bidpanel,.st-key-setup,.st-key-cover,.st-key-result{padding:12px 10px 8px;}
  button[kind="segmented_control"],button[kind="segmented_controlActive"]{padding-left:.55rem;padding-right:.55rem;}
}
</style>
"""


def H(s: str):
    # "$" is escaped so Streamlit never treats it as LaTeX math ($...$)
    st.markdown(s.replace("$", "&#36;"), unsafe_allow_html=True)


def md(s: str):
    st.markdown(s.replace("$", "\\$"))


def esc(s) -> str:
    return html.escape(str(s))


def bid_inline(q, f, size=24):
    return f"<span class='inl'>{q} × {die_svg(f, size)}</span>"


# ----------------------------------------------------------------------------
# UI components
# ----------------------------------------------------------------------------
def humans_of(g):
    return [i for i, p in enumerate(g.players) if p["human"]]


def hero_index(g):
    """The human whose dice may be shown on screen right now."""
    hs = humans_of(g)
    if len(hs) == 1:
        return hs[0]
    if len(hs) > 1 and g.phase == "bidding" and g.players[g.turn]["human"]:
        if g.unlocked == (g.round_no, len(g.history), g.turn):
            return g.turn
    return None


def render_header(location=None):
    H("<div class='ld-title'>LIAR'S DICE</div>")
    if location:
        H(f"<div class='ld-sub'><b>{esc(location)}</b> · {esc(LOCATIONS.get(location, ''))}</div>")
    else:
        H("<div class='ld-sub'>Bluff, bid, and pray your cup ain't empty.</div>")


def bubble_html(line=None, text=None, turn=False):
    inner = ""
    if line:
        inner += f"<span class='q'>“{esc(line)}”</span>"
    if text:
        inner += f"<span class='b'>{esc(text)}</span>"
    return f"<div class='bubble{' turn' if turn else ''}'>{inner}</div>" if inner else ""


def seat_html(g, i, hero):
    p = g.players[i]
    revealing = g.phase in ("reveal", "gameover") and g.reveal is not None
    snap = g.reveal["snapshot"] if revealing else {}
    cls = ["seat"]
    if (g.phase == "bidding" and i == g.turn) or (g.phase == "gameover" and i == g.winner):
        cls.append("active")
    if p["count"] == 0 and i not in snap:
        cls.append("out")

    tags = ""
    if p["human"]:
        tags += "<span class='tag tag-you'>YOU</span>" if len(humans_of(g)) == 1 else "<span class='tag tag-you'>HUMAN</span>"
    if g.phase == "bidding" and i == g.opener:
        tags += "<span class='tag tag-open'>opener</span>"
    if g.phase == "bidding" and i == g.bidder:
        tags += "<span class='tag tag-top'>high bid</span>"
    if revealing and i in g.reveal["losers"]:
        tags += "<span class='tag tag-loss'>−1 die</span>"
    if p["count"] == 0:
        tags += "<span class='tag tag-out'>OUT</span>"
    if g.phase == "gameover" and i == g.winner:
        tags += "<span class='tag tag-top'>WINNER</span>"

    if revealing and i in snap:
        f = g.reveal["bid"][1]
        dice = "".join(die_svg(d, 24, "hl" if d == f else "normal") for d in snap[i])
    elif i == hero and p["count"] > 0:
        cf = g.current_bid[1] if g.current_bid else None
        dice = "".join(die_svg(d, 24, "hl" if d == cf else "normal") for d in p["dice"])
    else:
        dice = "".join(die_svg(1, 22, "hidden") for _ in range(p["count"]))

    bubble = ""
    if g.phase == "bidding":
        if i == g.turn:
            if p["human"]:
                bubble = bubble_html(text="Your move", turn=True)
            else:
                bubble = "<div class='bubble turn dots'>thinking<span>.</span><span>.</span><span>.</span></div>"
        elif i in g.say:
            bubble = bubble_html(g.say[i]["line"], g.say[i]["text"])
    elif revealing:
        r = g.reveal
        react = r["react"].get(i)
        if i == r["caller"]:
            bubble = bubble_html(react or r["call_line"], "Liar!" if r["kind"] == "bluff" else "Spot on!", turn=True)
        elif react:
            bubble = bubble_html(react)
        elif i == r["bidder"]:
            bubble = bubble_html(None, f"{bid_words(*r['bid'])}.")

    return (
        f"<div class='{' '.join(cls)}'>"
        f"<div class='seat-name'>{p['avatar']} {esc(p['name'])}</div>"
        f"<div class='tags'>{tags}</div>"
        f"<div>{CUP_SVG}</div>"
        f"<div class='seat-dice'>{dice}</div>"
        f"<div class='seat-meta'>{p['count']} dice · ${p['money']}</div>"
        f"{bubble}</div>"
    )


def render_table(g, hero):
    seats = "".join(seat_html(g, i, hero) for i in range(len(g.players)))
    if g.phase == "bidding" and g.current_bid:
        q, f = g.current_bid
        center = (
            f"<div class='bidplaque'>{q} × {die_svg(f, 46)}</div>"
            f"<div class='bidwords'>“{bid_words(q, f)}”</div>"
            f"<div class='bidby'>high bid by {esc(g.players[g.bidder]['name'])}</div>"
        )
    elif g.phase == "bidding":
        center = f"<div class='nobid'>No bid yet — {esc(g.players[g.opener]['name'])} opens</div>"
    else:
        q, f = g.reveal["bid"]
        center = (
            f"<div class='bidplaque'>{q} × {die_svg(f, 46)}</div>"
            f"<div class='bidwords'>Table shows {g.reveal['actual']}</div>"
        )
    chips = (
        f"<span class='chip'>Round {g.round_no}</span>"
        f"<span class='chip'>{g.total_dice()} dice on the table</span>"
        f"<span class='chip'>Pot ${g.pot}</span>"
        f"<span class='chip'>Play passes clockwise</span>"
    )
    H(
        f"<div class='ld-table'><div class='ld-seats'>{seats}</div>"
        f"<div class='ld-center'>{center}<div class='chips'>{chips}</div></div></div>"
    )


def render_hand(g, hero):
    if hero is None or g.phase != "bidding":
        return
    p = g.players[hero]
    if p["count"] == 0:
        H("<div class='hand'><div class='hand-title'>You're out of dice — watching the rest from the bar…</div></div>")
        return
    cf = g.current_bid[1] if g.current_bid else None
    dice = "".join(die_svg(d, 60, "hl" if d == cf else "normal") for d in p["dice"])
    counts = {}
    for d in p["dice"]:
        counts[d] = counts.get(d, 0) + 1
    summary = " · ".join(
        f"{c} × {FACE_ONE[f] if c == 1 else FACE_MANY[f]}"
        for f, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    )
    title = "Under your cup" if len(humans_of(g)) == 1 else f"Under {esc(p['name'])}'s cup"
    H(
        f"<div class='hand'><div class='hand-title'>{title}</div>"
        f"<div class='hand-dice'>{dice}</div><div class='hand-sum'>{summary}</div></div>"
    )


def render_cover(g, i):
    with st.container(key="cover"):
        H(
            f"<div class='panel-title'>Pass the device to {esc(g.players[i]['name'])}</div>"
            "<div class='panel-note'>Everybody else — eyes off the cup.</div>"
        )
        if st.button(f"I'm {g.players[i]['name']} — lift my cup", type="primary",
                     key=f"unlock_{g.round_no}_{len(g.history)}_{i}"):
            g.unlocked = (g.round_no, len(g.history), i)
            st.rerun()


def render_controls(g, i, show_odds):
    p = g.players[i]
    cur = g.current_bid
    total = g.total_dice()
    single = len(humans_of(g)) == 1
    action = None
    with st.container(key="bidpanel"):
        H(f"<div class='panel-title'>{'Your move' if single else esc(p['name']) + '’s move'}</div>")
        if cur:
            q0, f0 = cur
            H(
                f"<div class='panel-note'>{esc(g.players[g.bidder]['name'])} says "
                f"<b>“{bid_words(q0, f0)}”</b> · {total} dice on the table</div>"
            )
            if show_odds:
                have = p["dice"].count(f0)
                pr = p_at_least(total - len(p["dice"]), q0 - have)
                H(f"<div class='panel-note'>Odds that bid is true: <b>{pr * 100:.0f}%</b> "
                  f"(you hold {have})</div>")
        else:
            H(f"<div class='panel-note'>You open this round. {total} dice on the table.</div>")

        default = g.default_raise()
        if cur is None:  # open with your strongest face
            best = max(range(1, 7), key=lambda f: (p["dice"].count(f), -f))
            default = (max(1, p["dice"].count(best)), best)
        qty, face, valid = None, None, False
        if default:
            c1, c2 = st.columns([1, 2.2])
            with c1:
                qty = st.number_input("How many dice", min_value=1, max_value=total, value=default[0], step=1,
                                      key=f"q_{g.bid_seq}")
            with c2:
                face = st.segmented_control("Showing face", options=[1, 2, 3, 4, 5, 6],
                                            format_func=lambda x: str(x), default=default[1],
                                            key=f"f_{g.bid_seq}")
            if face is None:
                face = default[1]
            qty = int(qty)
            valid = g.is_legal(qty, face)
            H(f"<div class='preview'>You'll say: {qty} × {die_svg(face, 34)} "
              f"<span>“{bid_words(qty, face)}”</span></div>")
            if show_odds and valid:
                have = p["dice"].count(face)
                pr = p_at_least(total - len(p["dice"]), qty - have)
                H(f"<div class='panel-note'>Odds your bid is true: <b>{pr * 100:.0f}%</b></div>")
            if not valid:
                q0, f0 = cur
                H(f"<div class='warn'>Must beat “{bid_words(q0, f0)}”: bid more dice, "
                  f"or the same count with a higher face.</div>")
        else:
            H("<div class='warn'>The bid can't go any higher — call Bluff or Spot On.</div>")

        with st.container(key="actions"):
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("Bid", type="primary", disabled=not valid, key=f"raise_{g.bid_seq}"):
                    action = ("bid", qty, face)
            with b2:
                if st.button("Liar!", disabled=cur is None, key=f"bluff_{g.bid_seq}"):
                    action = ("bluff",)
            with b3:
                if st.button("Spot On", disabled=cur is None, key=f"spot_{g.bid_seq}"):
                    action = ("spot",)

    if action:
        if action[0] == "bid":
            g.place_bid(i, action[1], action[2])
        else:
            g.call(i, action[0])
        st.rerun()


def render_result(g):
    r = g.reveal
    if r is None:
        return
    pl = g.players
    q, f = r["bid"]
    caller, bidder = esc(pl[r["caller"]]["name"]), esc(pl[r["bidder"]]["name"])
    if r["kind"] == "bluff":
        title = "LIAR!"
        verdict = (f"{bidder} was bluffing!" if r["correct"]
                   else f"{bidder} told the truth — {caller} called it wrong!")
    else:
        title = "SPOT ON!"
        verdict = ("Dead on the money! Everyone else loses a die." if r["correct"]
                   else f"Missed! {caller} loses a die.")
    with st.container(key="result"):
        H(f"<p class='verdict'>{title}</p>")
        H(f"<div class='verdict-line'>{caller} challenged {bidder}'s bid: "
          f"<b>“{bid_words(q, f)}”</b></div>")
        H(f"<div class='verdict-line big'>The table shows <span class='inl'>{r['actual']} × {die_svg(f, 28)}</span></div>")
        H(f"<div class='verdict-line'><b>{verdict}</b></div>")
        for j in r["eliminated"]:
            H(f"<div class='verdict-line'>{esc(pl[j]['name'])} is out of dice.</div>")

        if g.phase == "reveal":
            H(f"<div class='verdict-line'>Next round opens with <b>{esc(pl[r['next_opener']]['name'])}</b>.</div>")
            if st.button("Next round", type="primary", key=f"next_{g.round_no}"):
                g.start_round()
                st.rerun()
        else:
            w = pl[g.winner]
            H(f"<p class='verdict win'>{esc(w['name'])} takes the ${g.pot} pot!</p>")
            with st.container(key="endbtns"):
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Play again", type="primary", key="again"):
                        seats = [dict(name=p["name"], human=p["human"], money=p["money"], avatar=p["avatar"])
                                 for p in g.players]
                        st.session_state.game = Game(seats, g.location)
                        st.rerun()
                with c2:
                    if st.button("Change table", key="menu"):
                        st.session_state.game = None
                        st.rerun()


def render_talk(g, n=7):
    rows = []
    for e in g.feed[-n:][::-1]:
        if e["kind"] == "event":
            rows.append(f"<div class='talk-row event'>— {esc(e['text'])}</div>")
            continue
        who = g.players[e["who"]]
        quote = f" <span class='q'>“{esc(e['line'])}”</span>" if e["line"] else ""
        said = f" <span class='bid'>{esc(e['text'])}</span>" if e["text"] else ""
        rows.append(f"<div class='talk-row'><span class='who'>{who['avatar']} {esc(who['name'])}:</span>{quote}{said}</div>")
    H(f"<div class='talk'><div class='talk-title'>Table talk</div>{''.join(rows)}</div>")


def render_full_log(g):
    with st.expander("Full table log"):
        for e in reversed(g.feed[-60:]):
            if e["kind"] == "event":
                md(f"- *{e['text']}*")
            else:
                name = g.players[e["who"]]["name"]
                quote = f" “{e['line']}”" if e["line"] else ""
                md(f"- **{name}:**{quote} {e['text']}")


def render_rules():
    with st.expander("How to play (Red Dead Redemption rules)"):
        md(
            """
- Every player has **one cup and five dice**. Everyone shakes and slams their cup upside down; only you see what's under yours.
- The opener names a bid like **"Three fours"** — meaning there are *at least* three dice showing 4 across the **whole table**, everyone's dice included. **No wild dice.**
- Play passes **clockwise (to the left)**. On your turn you can:
  1. **Bid higher** — more dice of any face (*Four twos* beats *Three fours*), or the same count with a higher face (*Three fives* beats *Three fours*).
  2. **Call Liar (bluff)** — all cups are lifted. If there are **fewer** dice than bid, the bidder loses a die. Otherwise the caller loses a die.
  3. **Call Spot On** — all cups are lifted. If the count is **exactly** right, *every other player* loses a die. If not, the caller loses a die.
- Lost dice never come back. No dice left means you're out; **the last player holding dice takes the pot.**
- The next round's opening bid passes **counter-clockwise** from the previous opener.
- Ante: **$20** a head.

**Saloon wisdom:** bid what's actually under your cup, start low, and remember the regulars hardly ever call Spot On. When a man's down to his last die, the face he names first is almost always the truth.
"""
        )


def render_settings(g):
    with st.expander("Table settings"):
        st.segmented_control("AI speed", list(SPEEDS), default="Normal", key="speed")
        st.segmented_control("Odds helper (not in the original game)", ["Off", "On"], default="Off", key="odds")
        if g is not None and st.button("Leave the table", key="leave"):
            st.session_state.game = None
            st.rerun()


def render_setup():
    ss = st.session_state
    if "default_names" not in ss:
        ss.default_names = ["Marston"] + random.sample(NPC_NAMES, 3)
    with st.container(key="setup"):
        H("<div class='panel-title'>Pick a table</div>")
        loc = st.selectbox("Saloon", list(LOCATIONS), key="loc")
        H(f"<div class='panel-note'>{esc(LOCATIONS[loc])} · ${ANTE} ante</div>")
        n = st.segmented_control("Players at the table", [2, 3, 4], default=2, key="n_players") or 2
        seats = []
        for i in range(n):
            with st.container(key=f"seatrow_{i}"):
                c1, c2 = st.columns([1.4, 1])
                with c1:
                    name = st.text_input(f"Seat {i + 1}", value=ss.default_names[i], key=f"name_{i}", max_chars=14)
                with c2:
                    kind = st.segmented_control("Player", ["Human", "AI"], default="Human" if i == 0 else "AI",
                                                key=f"kind_{i}") or ("Human" if i == 0 else "AI")
            seats.append(dict(name=(name or f"Player {i + 1}").strip() or f"Player {i + 1}",
                              human=kind == "Human", avatar=AVATARS[i % len(AVATARS)]))
        H("<div class='panel-note'>More than one <b>Human</b> = hotseat mode: pass the device around, "
          "cups stay hidden between turns.</div>")
        if ss.bank:
            wallet = " · ".join(f"{esc(k)} ${v}" for k, v in ss.bank.items())
            H(f"<div class='panel-note' style='margin-top:6px'>Purse: {wallet}</div>")
        names = [s["name"] for s in seats]
        dup = len(set(names)) != len(names)
        if dup:
            H("<div class='warn'>Every player needs a different name.</div>")
        if st.button(f"Take a seat & ante ${ANTE}", type="primary", disabled=dup, key="start"):
            for s in seats:
                s["money"] = ss.bank.get(s["name"], START_MONEY)
            ss.game = Game(seats, loc)
            st.rerun()


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Liar's Dice — Saloon", page_icon="🎲", layout="centered",
                       initial_sidebar_state="collapsed")
    H(CSS)
    ss = st.session_state
    ss.setdefault("bank", {})
    ss.setdefault("game", None)

    g = ss.game
    if g is None:
        render_header()
        render_setup()
        render_rules()
        return

    render_header(g.location)
    if g.phase == "gameover" and not g.banked:
        for p in g.players:
            ss.bank[p["name"]] = p["money"]
        g.banked = True

    show_odds = ss.get("odds") == "On"
    hero = hero_index(g)
    if g.phase in ("reveal", "gameover"):
        render_result(g)
    render_table(g, hero)

    if g.phase == "bidding":
        if g.players[g.turn]["human"]:
            if len(humans_of(g)) > 1 and hero != g.turn:
                render_cover(g, g.turn)
            else:
                render_hand(g, hero)
                render_controls(g, g.turn, show_odds)
        else:
            render_hand(g, hero)

    render_talk(g)
    render_settings(g)
    render_rules()
    render_full_log(g)

    # AI driver: acts on its own with a short pause, like a real table
    delay = SPEEDS.get(ss.get("speed") or "Normal", 1.25)
    humans_alive = [i for i in humans_of(g) if g.players[i]["count"] > 0]
    if g.phase == "bidding" and not g.players[g.turn]["human"]:
        time.sleep(delay if humans_alive else delay * 0.5)
        g.ai_act(g.turn)
        st.rerun()
    elif g.phase == "reveal" and not humans_alive:
        time.sleep(delay * 1.8)
        g.start_round()
        st.rerun()


if __name__ == "__main__":
    main()
