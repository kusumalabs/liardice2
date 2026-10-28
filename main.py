"""
LIAR'S DICE — versi web bergaya saloon Red Dead Redemption (2010)
=================================================================
Aturan mengikuti Liar's Dice di RDR1:
  * 2–4 pemain, masing-masing 1 cangkir + 5 dadu enam sisi. Tidak ada dadu "wild".
  * Pembuka menawar "X buah angka Y". Giliran berputar searah jarum jam (ke kiri).
  * Pada gilirannya pemain boleh: NAIKKAN tawaran, panggil BLUFF, atau panggil SPOT ON.
      - Naikkan: jumlah dadu lebih banyak (angka apa pun), atau jumlah sama dengan angka lebih tinggi.
      - Bluff : jika jumlah sebenarnya < tawaran -> penawar kehilangan 1 dadu,
                selain itu -> pemanggil bluff kehilangan 1 dadu.
      - Spot On: jika jumlah sebenarnya == tawaran -> SEMUA pemain lain kehilangan 1 dadu,
                 selain itu -> pemanggil spot on kehilangan 1 dadu.
  * Dadu yang hilang tidak kembali. Pemain tanpa dadu tersingkir; yang terakhir tersisa menang pot.
  * Pembuka ronde berikutnya berpindah berlawanan arah jarum jam dari pembuka ronde sebelumnya.
  * Ante single player: $20 per pemain.

Jalankan:
    pip install -r requirements.txt
    streamlit run main.py
"""

import html
import math
import random
import time

import streamlit as st

# ----------------------------------------------------------------------------
# Konstanta
# ----------------------------------------------------------------------------
ANTE = 20
START_MONEY = 200
DICE_PER_PLAYER = 5
FACE_GLYPH = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
NPC_NAMES = [
    "Diego", "Abraham", "Old Pete", "Rosa", "Silas", "Mateo",
    "Clem", "Jonah", "Ezequiel", "Hattie", "Wade", "Lupe",
]
AVATARS = ["🤠", "🧔", "👴", "👒", "🎩", "🧢"]
LOCATIONS = {
    "Thieves' Landing": "Sarang penjudi & penyelundup di tepi sungai — West Elizabeth",
    "Casa Madrugada": "Hacienda berdebu di perbatasan — Nuevo Paraíso",
    "Escalera": "Kota benteng sang Gubernur — Nuevo Paraíso",
}
SPEEDS = {"Lambat": 2.0, "Normal": 1.25, "Cepat": 0.6}

PIPS = {
    1: [(50, 50)],
    2: [(27, 27), (73, 73)],
    3: [(27, 27), (50, 50), (73, 73)],
    4: [(27, 27), (73, 27), (27, 73), (73, 73)],
    5: [(27, 27), (73, 27), (50, 50), (27, 73), (73, 73)],
    6: [(27, 24), (73, 24), (27, 50), (73, 50), (27, 76), (73, 76)],
}


# ----------------------------------------------------------------------------
# Peluang
# ----------------------------------------------------------------------------
def p_at_least(n: int, k: int, p: float = 1 / 6) -> float:
    """P(X >= k) untuk X ~ Binomial(n, p)."""
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


# ----------------------------------------------------------------------------
# Mesin permainan
# ----------------------------------------------------------------------------
class Game:
    def __init__(self, seats, location="Thieves' Landing", ante=ANTE, seed=None):
        self.rng = random.Random(seed)
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
        self.history = []  # (player, qty, face) ronde ini
        self.reveal = None
        self.winner = None
        self.log = []
        self.bid_seq = 0
        self.unlocked = None
        self.banked = False
        self._collect_antes()
        self.opener = self.rng.randrange(len(self.players))
        self.log.append(f"🎲 {self.players[self.opener]['name']} terpilih membuka tawaran pertama.")
        self.start_round()

    # --- utilitas -----------------------------------------------------------
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
        """Saran tawaran default untuk UI (None jika tidak bisa menaikkan lagi)."""
        total = self.total_dice()
        if self.current_bid is None:
            return (1, 1)
        q, f = self.current_bid
        if q + 1 <= total:
            return (q + 1, f)
        if f < 6:
            return (q, f + 1)
        return None

    def _collect_antes(self):
        for p in self.players:
            if p["money"] < self.ante:
                p["money"] += START_MONEY
                self.log.append(f"💵 {p['name']} meminjam ${START_MONEY} dari bartender.")
            p["money"] -= self.ante
            self.pot += self.ante
        self.log.append(f"🪙 Semua pemain membayar ante ${self.ante}. Pot: ${self.pot}.")

    # --- alur ronde -----------------------------------------------------------
    def start_round(self):
        self.round_no += 1
        for p in self.players:
            p["dice"] = sorted(self.rng.randint(1, 6) for _ in range(p["count"])) if p["count"] > 0 else []
        self.current_bid = None
        self.bidder = None
        self.history = []
        self.reveal = None
        self.turn = self.opener
        self.phase = "bidding"
        self.bid_seq += 1
        self.unlocked = None
        self.log.append(f"— Ronde {self.round_no}: cangkir dikocok & dibanting. {self.total_dice()} dadu di meja.")

    def place_bid(self, i, q, f):
        assert self.phase == "bidding" and i == self.turn, "Bukan giliran pemain ini"
        assert self.is_legal(q, f), f"Tawaran tidak sah: {q}x{f}"
        self.current_bid = (q, f)
        self.bidder = i
        self.history.append((i, q, f))
        self.bid_seq += 1
        self.log.append(f"{self.players[i]['name']}: {q} × {FACE_GLYPH[f]} ({f})")
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
        self.reveal = dict(
            kind=kind, caller=i, bidder=b, bid=(q, f), actual=actual,
            losers=losers, eliminated=eliminated, snapshot=snapshot, correct=correct,
            history=list(self.history),
        )
        nm = self.players
        label = "BLUFF" if kind == "bluff" else "SPOT ON"
        self.log.append(
            f"🗣️ {nm[i]['name']} memanggil {label} → ada {actual} × {FACE_GLYPH[f]}. "
            f"Kehilangan dadu: {', '.join(nm[j]['name'] for j in losers)}."
        )
        for j in eliminated:
            self.log.append(f"💀 {nm[j]['name']} tersingkir.")
        alive = self.alive()
        self.bid_seq += 1
        if len(alive) == 1:
            self.winner = alive[0]
            self.players[self.winner]["money"] += self.pot
            self.phase = "gameover"
            self.log.append(f"🏆 {nm[self.winner]['name']} memenangkan pot ${self.pot}!")
        else:
            self.opener = self.next_alive(self.opener, -1)
            self.reveal["next_opener"] = self.opener
            self.phase = "reveal"

    # --- AI bergaya NPC RDR1 -------------------------------------------------
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

        # Membuka tawaran
        if cur is None:
            if len(dice) == 1:  # NPC selalu jujur soal angka dadu terakhirnya
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

        # Kebiasaan NPC: tak punya angka itu sama sekali -> hampir selalu teriak bluff
        if have == 0 and cq >= 2 and rng.random() < 0.8:
            return ("bluff",)
        # Spot on: tidak pernah saat duel 1 lawan 1, sangat jarang di meja ramai
        if n_alive > 2 and need >= 0 and p_spot >= 0.3 and rng.random() < 0.12:
            return ("spot",)
        if best is None:
            return ("bluff",)

        trusts_low_bid = cq < 4 and have >= 1
        if trusts_low_bid or p_true >= 0.5:
            if best[0] < 0.2 and not trusts_low_bid:
                return ("bluff",)
            q, f = best[2], best[3]
            if rng.random() < 0.08:  # sesekali melompat terlalu tinggi (bluff nekat)
                q = min(total, q + rng.choice([1, 2]))
            return ("bid", q, f)
        if best[0] > 0.6 and rng.random() < 0.3:
            return ("bid", best[2], best[3])
        return ("bluff",)

    def ai_act(self, i):
        action = self.ai_decide(i)
        if action[0] == "bid":
            q, f = action[1], action[2]
            if not self.is_legal(q, f):  # pengaman
                dr = self.default_raise()
                if dr is None:
                    self.call(i, "bluff")
                    return
                q, f = dr
            self.place_bid(i, q, f)
        else:
            self.call(i, action[0])


# ----------------------------------------------------------------------------
# Grafis (SVG/CSS — tanpa aset eksternal)
# ----------------------------------------------------------------------------
def die_svg(face, size=40, state="normal"):
    if state == "hidden":
        body = (
            "<rect x='5' y='5' width='90' height='90' rx='18' fill='#2b170b' stroke='#c9a227' stroke-width='4'/>"
            "<text x='50' y='66' text-anchor='middle' font-size='46' fill='#c9a227' font-family='Rye,serif'>?</text>"
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
    return (
        f"<svg class='die die-{state}' width='{size}' height='{size}' viewBox='0 0 100 100' "
        f"xmlns='http://www.w3.org/2000/svg'>{body}</svg>"
    )


CUP_SVG = (
    "<svg class='cup' width='54' height='48' viewBox='0 0 100 90' xmlns='http://www.w3.org/2000/svg'>"
    "<path d='M20 12 H80 L72 86 H28 Z' fill='#5b3417' stroke='#1e0f06' stroke-width='4'/>"
    "<rect x='13' y='5' width='74' height='12' rx='5' fill='#7d4c25' stroke='#1e0f06' stroke-width='3'/>"
    "<path d='M29 36 H71' stroke='#c9a227' stroke-width='3' opacity='.75'/>"
    "<path d='M31 64 H69' stroke='#c9a227' stroke-width='3' opacity='.75'/>"
    "</svg>"
)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Rye&family=Special+Elite&display=swap');
:root{--parch:#f1e3c2;--gold:#d4a73a;--blood:#8e1f17;--ink:#2a160a;}
.stApp{
  background:
    radial-gradient(ellipse at 50% 0%, rgba(255,190,110,.16), transparent 55%),
    radial-gradient(ellipse at 50% 120%, rgba(0,0,0,.65), transparent 60%),
    repeating-linear-gradient(90deg,#2b1a10 0 26px,#321f13 26px 52px,#27170d 52px 80px);
  color:var(--parch);
  font-family:'Special Elite','Courier New',monospace;
}
header[data-testid="stHeader"]{background:transparent;}
[data-testid="stToolbar"],#MainMenu,footer{display:none !important;}
.block-container{padding-top:1.2rem;padding-bottom:3rem;max-width:880px;}
.stApp p,.stApp li,.stApp label,.stApp span{font-family:'Special Elite','Courier New',monospace;}
[data-testid="stWidgetLabel"] p{color:var(--parch);}
[data-testid="stExpander"] details{background:rgba(20,10,4,.55);border:1px solid rgba(212,167,58,.35);border-radius:14px;}
[data-testid="stExpander"] summary p{color:var(--gold);font-family:'Rye',serif;}
[data-testid="stExpander"] p,[data-testid="stExpander"] li{color:var(--parch);}

.ld-title{font-family:'Rye',serif;font-size:clamp(2.1rem,8vw,3.6rem);text-align:center;color:var(--gold);
  text-shadow:0 3px 0 #3a1b0b,0 0 18px rgba(212,167,58,.35);letter-spacing:3px;margin:0;line-height:1.1;}
.ld-sub{text-align:center;opacity:.9;margin:.2rem 0 1rem;font-size:.95rem;}
.ld-sub b{color:var(--gold);font-family:'Rye',serif;font-weight:normal;}

.ld-table{background:radial-gradient(ellipse at center,#86532b 0%,#633a1d 55%,#3f2210 100%);
  border:7px solid #241208;border-radius:30px;padding:14px 12px 16px;
  box-shadow:inset 0 0 45px rgba(0,0,0,.65),0 12px 30px rgba(0,0,0,.6),0 0 0 2px rgba(212,167,58,.25);}
.ld-seats{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}
.seat{flex:1 1 170px;max-width:210px;background:rgba(18,9,3,.6);border:2px solid rgba(212,167,58,.3);
  border-radius:16px;padding:10px 8px;text-align:center;position:relative;transition:all .25s;}
.seat.active{border-color:var(--gold);box-shadow:0 0 0 3px rgba(212,167,58,.22),0 0 22px rgba(212,167,58,.5);transform:translateY(-2px);}
.seat.out{opacity:.42;filter:grayscale(.9);}
.seat-name{font-family:'Rye',serif;color:var(--parch);font-size:1.02rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.seat-meta{font-size:.78rem;opacity:.85;margin-top:2px;}
.seat-dice{display:flex;flex-wrap:wrap;gap:3px;justify-content:center;margin-top:6px;min-height:26px;}
.tag{display:inline-block;font-size:.66rem;padding:1px 7px;border-radius:999px;margin:2px 2px 0;font-family:'Special Elite',monospace;}
.tag-you{background:var(--gold);color:var(--ink);}
.tag-open{background:rgba(255,255,255,.12);color:var(--parch);}
.tag-top{background:#3c5a2a;color:#e9f3d9;}
.tag-loss{background:var(--blood);color:#fff;}
.tag-out{background:#111;color:#bbb;}
.bubble{display:inline-flex;align-items:center;gap:5px;background:var(--parch);color:var(--ink);
  border-radius:12px;padding:3px 9px;margin-top:7px;font-weight:bold;font-size:.95rem;box-shadow:0 2px 0 #6b4423;}
.bubble.turn{background:var(--gold);}
.dots span{animation:blink 1.2s infinite;font-size:1.2rem;}
.dots span:nth-child(2){animation-delay:.2s}.dots span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,100%{opacity:.15}50%{opacity:1}}

.ld-center{text-align:center;margin-top:14px;}
.bidplaque{display:inline-flex;align-items:center;gap:10px;background:linear-gradient(#f5e9cb,#dcc699);
  color:var(--ink);border:3px solid #6b4423;border-radius:14px;padding:6px 18px;font-family:'Rye',serif;
  font-size:1.9rem;box-shadow:0 4px 0 #2a160a;}
.bidby{font-size:.9rem;margin-top:6px;}
.nobid{font-family:'Rye',serif;color:var(--gold);font-size:1.15rem;}
.chips{display:flex;justify-content:center;gap:6px;flex-wrap:wrap;margin-top:10px;}
.chip{background:rgba(0,0,0,.38);border:1px solid rgba(212,167,58,.45);border-radius:999px;padding:3px 11px;font-size:.8rem;}
.trail{display:flex;flex-wrap:wrap;gap:4px;justify-content:center;margin-top:8px;font-size:.75rem;opacity:.9;}
.trail .step{background:rgba(0,0,0,.3);border-radius:8px;padding:1px 7px;display:inline-flex;align-items:center;gap:3px;}

.hand{margin:16px 0 10px;background:rgba(18,9,3,.6);border:2px solid var(--gold);border-radius:18px;padding:12px;text-align:center;}
.hand-title{font-family:'Rye',serif;color:var(--gold);font-size:1.1rem;margin-bottom:8px;}
.hand-dice{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;}
.hand-sum{margin-top:8px;font-size:.85rem;opacity:.9;}

.st-key-bidpanel,.st-key-setup,.st-key-cover,.st-key-result{
  background:linear-gradient(#f5ead0,#e2cd9d);border:3px solid #6b4423;border-radius:18px;
  padding:14px 14px 8px;box-shadow:0 6px 0 #2a160a,0 12px 26px rgba(0,0,0,.5);margin-top:8px;}
.st-key-bidpanel p,.st-key-bidpanel label,.st-key-bidpanel span,
.st-key-setup p,.st-key-setup label,.st-key-setup span,
.st-key-cover p,.st-key-cover span,.st-key-result p,.st-key-result span{color:var(--ink) !important;}
.panel-title{font-family:'Rye',serif;font-size:1.35rem;color:var(--blood);text-align:center;margin-bottom:4px;}
.panel-note{text-align:center;font-size:.88rem;color:var(--ink);}
.preview{display:flex;align-items:center;justify-content:center;gap:8px;font-family:'Rye',serif;font-size:1.3rem;color:var(--ink);margin:2px 0 6px;}
.warn{text-align:center;color:var(--blood);font-size:.85rem;}
.verdict{font-family:'Rye',serif;font-size:clamp(1.6rem,6vw,2.3rem);text-align:center;color:var(--blood);margin:0;}
.verdict-line{text-align:center;color:var(--ink);font-size:.98rem;margin:4px 0;}
.verdict-line .inline-die{vertical-align:middle;}
.big{font-family:'Rye',serif;font-size:1.25rem;}

.stButton>button{font-family:'Rye',serif !important;width:100%;min-height:50px;border-radius:12px;
  border:2px solid #1e0f06;background:linear-gradient(#7a4f2a,#5b3417);color:#f6e7c1;font-size:1.05rem;
  box-shadow:0 4px 0 #1e0f06;transition:transform .08s,filter .15s;}
.stButton>button p{font-family:'Rye',serif !important;color:#f6e7c1 !important;font-size:1.05rem;}
.stButton>button[kind="primary"]{background:linear-gradient(#b0301f,#7a1a12);}
.stButton>button:hover{filter:brightness(1.15);border-color:var(--gold);color:#fff;}
.stButton>button:active{transform:translateY(3px);box-shadow:0 1px 0 #1e0f06;}
.stButton>button:disabled{filter:grayscale(.8) brightness(.8);opacity:.55;}
[data-testid="stSidebar"]{background:linear-gradient(#f5ead0,#e2cd9d);}
[data-testid="stSidebar"] *{color:var(--ink);}

@media (max-width:640px){
  .block-container{padding-left:.6rem;padding-right:.6rem;}
  .seat{flex:1 1 calc(50% - 10px);max-width:none;padding:8px 6px;}
  .seat .die{width:20px;height:20px;}
  .hand .die{width:50px;height:50px;}
  .bidplaque{font-size:1.5rem;padding:5px 14px;}
  .ld-table{padding:10px 8px 12px;border-width:5px;border-radius:22px;}
}
</style>
"""


def H(s: str):
    # "$" di-escape agar Streamlit tidak membacanya sebagai rumus LaTeX ($...$)
    st.markdown(s.replace("$", "&#36;"), unsafe_allow_html=True)


def md(s: str):
    st.markdown(s.replace("$", "\\$"))


def esc(s) -> str:
    return html.escape(str(s))


def bid_html(q, f, size=26):
    return f"<span style='display:inline-flex;align-items:center;gap:4px'>{q} × {die_svg(f, size)}</span>"


# ----------------------------------------------------------------------------
# Komponen UI
# ----------------------------------------------------------------------------
def humans_of(g):
    return [i for i, p in enumerate(g.players) if p["human"]]


def hero_index(g):
    """Pemain manusia yang dadunya boleh ditampilkan di layar saat ini."""
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
        H("<div class='ld-sub'>Gertak, tebak, dan jangan sampai cangkirmu kosong.</div>")


def seat_html(g, i, hero):
    p = g.players[i]
    revealing = g.phase in ("reveal", "gameover") and g.reveal is not None
    snap = g.reveal["snapshot"] if revealing else {}
    cls = ["seat"]
    if g.phase == "bidding" and i == g.turn:
        cls.append("active")
    if p["count"] == 0 and i not in snap:
        cls.append("out")
    if g.phase == "gameover" and i == g.winner:
        cls.append("active")

    tags = ""
    single_human = len(humans_of(g)) == 1
    if p["human"]:
        tags += "<span class='tag tag-you'>KAMU</span>" if single_human else "<span class='tag tag-you'>MANUSIA</span>"
    if g.phase == "bidding" and i == g.opener:
        tags += "<span class='tag tag-open'>pembuka</span>"
    if g.phase == "bidding" and i == g.bidder:
        tags += "<span class='tag tag-top'>tawaran tertinggi</span>"
    if revealing and i in g.reveal["losers"]:
        tags += "<span class='tag tag-loss'>−1 dadu</span>"
    if p["count"] == 0:
        tags += "<span class='tag tag-out'>TERSINGKIR</span>"
    if g.phase == "gameover" and i == g.winner:
        tags += "<span class='tag tag-top'>🏆 PEMENANG</span>"

    # dadu
    if revealing and i in snap:
        f = g.reveal["bid"][1]
        dice = "".join(die_svg(d, 26, "hl" if d == f else "normal") for d in snap[i])
    elif i == hero and p["count"] > 0:
        cf = g.current_bid[1] if g.current_bid else None
        dice = "".join(die_svg(d, 24, "hl" if d == cf else "normal") for d in p["dice"])
    else:
        dice = "".join(die_svg(1, 22, "hidden") for _ in range(p["count"]))

    # gelembung ucapan
    bubble = ""
    if g.phase == "bidding":
        if i == g.turn:
            if p["human"]:
                bubble = "<div class='bubble turn'>Giliranmu!</div>"
            else:
                bubble = "<div class='bubble turn dots'>🤔<span>.</span><span>.</span><span>.</span></div>"
        else:
            mine = [h for h in g.history if h[0] == i]
            if mine:
                _, q, f = mine[-1]
                bubble = f"<div class='bubble'>{bid_html(q, f, 20)}</div>"
    elif revealing:
        r = g.reveal
        if i == r["caller"]:
            bubble = f"<div class='bubble turn'>{'Bluff!' if r['kind'] == 'bluff' else 'Spot on!'}</div>"
        elif i == r["bidder"]:
            q, f = r["bid"]
            bubble = f"<div class='bubble'>{bid_html(q, f, 20)}</div>"

    return (
        f"<div class='{' '.join(cls)}'>"
        f"<div class='seat-name'>{p['avatar']} {esc(p['name'])}</div>"
        f"<div>{tags}</div>"
        f"<div>{CUP_SVG}</div>"
        f"<div class='seat-dice'>{dice}</div>"
        f"<div class='seat-meta'>🎲 {p['count']} dadu · ${p['money']}</div>"
        f"{bubble}</div>"
    )


def render_table(g, hero):
    seats = "".join(seat_html(g, i, hero) for i in range(len(g.players)))
    if g.current_bid and g.phase == "bidding":
        q, f = g.current_bid
        center = (
            f"<div class='bidplaque'>{q} × {die_svg(f, 46)}</div>"
            f"<div class='bidby'>tawaran {esc(g.players[g.bidder]['name'])}</div>"
        )
    elif g.phase == "bidding":
        center = f"<div class='nobid'>Belum ada tawaran — {esc(g.players[g.opener]['name'])} membuka</div>"
    else:
        q, f = g.reveal["bid"]
        center = f"<div class='bidplaque'>{q} × {die_svg(f, 46)}</div><div class='bidby'>tawaran terakhir</div>"
    trail = ""
    hist = g.history if g.phase == "bidding" else (g.reveal or {}).get("history", [])
    if hist:
        steps = "".join(
            f"<span class='step'>{esc(g.players[j]['name'])}: {q}×{die_svg(f, 14)}</span>" for j, q, f in hist[-8:]
        )
        trail = f"<div class='trail'>{steps}</div>"
    chips = (
        f"<span class='chip'>Ronde {g.round_no}</span>"
        f"<span class='chip'>🎲 {g.total_dice()} dadu di meja</span>"
        f"<span class='chip'>💰 Pot ${g.pot}</span>"
        f"<span class='chip'>⟳ searah jarum jam</span>"
    )
    H(
        f"<div class='ld-table'><div class='ld-seats'>{seats}</div>"
        f"<div class='ld-center'>{center}{trail}<div class='chips'>{chips}</div></div></div>"
    )


def render_hand(g, hero):
    if hero is None or g.phase != "bidding":
        return
    p = g.players[hero]
    if p["count"] == 0:
        H("<div class='hand'><div class='hand-title'>Kamu sudah tersingkir — menonton sisa permainan…</div></div>")
        return
    cf = g.current_bid[1] if g.current_bid else None
    dice = "".join(die_svg(d, 60, "hl" if d == cf else "normal") for d in p["dice"])
    counts = {}
    for d in p["dice"]:
        counts[d] = counts.get(d, 0) + 1
    summary = " · ".join(f"{c}× {FACE_GLYPH[f]}" for f, c in sorted(counts.items(), key=lambda x: (-x[1], x[0])))
    H(
        f"<div class='hand'><div class='hand-title'>🥃 Isi cangkir {esc(p['name'])}</div>"
        f"<div class='hand-dice'>{dice}</div><div class='hand-sum'>{summary}</div></div>"
    )


def render_cover(g, i):
    with st.container(key="cover"):
        H(
            f"<div class='panel-title'>🙈 Serahkan ke {esc(g.players[i]['name'])}</div>"
            "<div class='panel-note'>Pemain lain jangan mengintip cangkir!</div>"
        )
        if st.button(f"Saya {g.players[i]['name']} — buka cangkir", type="primary",
                     key=f"unlock_{g.round_no}_{len(g.history)}_{i}"):
            g.unlocked = (g.round_no, len(g.history), i)
            st.rerun()


def render_controls(g, i, show_hint):
    p = g.players[i]
    cur = g.current_bid
    total = g.total_dice()
    action = None
    with st.container(key="bidpanel"):
        H(f"<div class='panel-title'>🎯 Giliran {esc(p['name'])}</div>")
        if cur:
            q0, f0 = cur
            H(
                f"<div class='panel-note'>Tawaran saat ini: <b>{bid_html(q0, f0, 22)}</b> "
                f"oleh {esc(g.players[g.bidder]['name'])} · {total} dadu di meja</div>"
            )
            if show_hint:
                have = p["dice"].count(f0)
                pr = p_at_least(total - len(p["dice"]), q0 - have)
                H(f"<div class='panel-note'>🔎 Peluang tawaran itu benar: <b>{pr * 100:.0f}%</b> "
                  f"(kamu punya {have}× {FACE_GLYPH[f0]})</div>")
        else:
            H(f"<div class='panel-note'>Kamu membuka ronde ini. Ada {total} dadu di meja.</div>")

        default = g.default_raise()
        qty, face, valid = None, None, False
        if default:
            c1, c2 = st.columns([1, 2])
            with c1:
                qty = st.number_input("Jumlah dadu", min_value=1, max_value=total, value=default[0], step=1,
                                      key=f"q_{g.bid_seq}")
            with c2:
                face = st.segmented_control("Angka dadu", options=[1, 2, 3, 4, 5, 6],
                                            format_func=lambda x: f"{FACE_GLYPH[x]} {x}",
                                            default=default[1], key=f"f_{g.bid_seq}")
            if face is None:
                face = default[1]
            qty = int(qty)
            valid = g.is_legal(qty, face)
            H(f"<div class='preview'>Tawaranmu: {qty} × {die_svg(face, 34)}</div>")
            if show_hint and valid:
                have = p["dice"].count(face)
                pr = p_at_least(total - len(p["dice"]), qty - have)
                H(f"<div class='panel-note'>🔎 Peluang tawaranmu benar: <b>{pr * 100:.0f}%</b></div>")
            if not valid:
                q0, f0 = cur
                H(f"<div class='warn'>Harus lebih tinggi dari {q0} × {FACE_GLYPH[f0]}: "
                  f"tambah jumlahnya, atau jumlah sama dengan angka lebih besar.</div>")
        else:
            H("<div class='warn'>Tawaran sudah maksimal — pilih Bluff atau Spot On.</div>")

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("🎲 Tawar", type="primary", disabled=not valid, key=f"raise_{g.bid_seq}"):
                action = ("bid", qty, face)
        with b2:
            if st.button("🤥 Bluff!", disabled=cur is None, key=f"bluff_{g.bid_seq}"):
                action = ("bluff",)
        with b3:
            if st.button("🎯 Spot On", disabled=cur is None, key=f"spot_{g.bid_seq}"):
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
    caller, bidder = pl[r["caller"]]["name"], pl[r["bidder"]]["name"]
    if r["kind"] == "bluff":
        title = "🤥 BLUFF!"
        verdict = (f"{esc(bidder)} ketahuan menggertak!" if r["correct"]
                   else f"Tawaran {esc(bidder)} benar — {esc(caller)} salah tuduh!")
    else:
        title = "🎯 SPOT ON!"
        verdict = ("Tepat sekali! Semua pemain lain kehilangan 1 dadu." if r["correct"]
                   else f"Meleset! {esc(caller)} kehilangan 1 dadu.")
    with st.container(key="result"):
        H(f"<p class='verdict'>{title}</p>")
        H(f"<div class='verdict-line'>{esc(caller)} menantang tawaran {esc(bidder)}: "
          f"<b>{bid_html(q, f, 22)}</b></div>")
        H(f"<div class='verdict-line big'>Di meja ada {r['actual']} × {die_svg(f, 28)}</div>")
        H(f"<div class='verdict-line'><b>{verdict}</b></div>")
        losers = ", ".join(esc(pl[j]["name"]) for j in r["losers"])
        H(f"<div class='verdict-line'>Kehilangan dadu: {losers}</div>")
        for j in r["eliminated"]:
            H(f"<div class='verdict-line'>💀 {esc(pl[j]['name'])} tersingkir dari meja.</div>")

        if g.phase == "reveal":
            H(f"<div class='verdict-line'>Ronde berikutnya dibuka oleh <b>{esc(pl[r['next_opener']]['name'])}</b>.</div>")
            if st.button("Ronde berikutnya ▶", type="primary", key=f"next_{g.round_no}"):
                g.start_round()
                st.rerun()
        else:
            w = pl[g.winner]
            H(f"<p class='verdict' style='color:#3c5a2a'>🏆 {esc(w['name'])} menang ${g.pot}!</p>")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🔁 Main lagi", type="primary", key="again"):
                    seats = [dict(name=p["name"], human=p["human"], money=p["money"], avatar=p["avatar"])
                             for p in g.players]
                    st.session_state.game = Game(seats, g.location)
                    st.rerun()
            with c2:
                if st.button("🚪 Ganti meja", key="menu"):
                    st.session_state.game = None
                    st.rerun()


def render_log(g):
    with st.expander("📜 Catatan meja"):
        for line in reversed(g.log[-30:]):
            md(f"- {line}")


def render_rules():
    with st.expander("📖 Aturan Liar's Dice (Red Dead Redemption)"):
        md(
            """
- Setiap pemain punya **1 cangkir dan 5 dadu**. Semua mengocok lalu membanting cangkir terbalik; hanya kamu yang tahu isi cangkirmu.
- Pembuka menyebut tawaran, misalnya **"3 buah angka 4"**, artinya *di seluruh meja* (termasuk dadu lawan) ada minimal tiga dadu bermata 4. **Tidak ada dadu wild.**
- Giliran berputar **searah jarum jam (ke kiri)**. Pada gilirannya pemain boleh:
  1. **Naikkan tawaran**: jumlah lebih banyak dengan angka apa pun (*4 buah 2* mengalahkan *3 buah 4*), atau jumlah sama dengan angka lebih tinggi (*3 buah 5* mengalahkan *3 buah 4*).
  2. **Bluff**: semua dadu dibuka. Jika jumlahnya **kurang** dari tawaran, penawar kehilangan 1 dadu. Jika tidak, pemanggil yang kehilangan 1 dadu.
  3. **Spot On**: semua dadu dibuka. Jika jumlahnya **tepat sama**, *semua pemain lain* kehilangan 1 dadu. Jika meleset, pemanggil yang kehilangan 1 dadu.
- Dadu yang hilang tidak kembali. Pemain tanpa dadu tersingkir; **yang terakhir masih punya dadu memenangkan pot.**
- Pembuka ronde berikutnya berpindah **berlawanan arah jarum jam** dari pembuka ronde sebelumnya.
- Ante: **$20** per pemain.

**Tips gaya saloon:** tawar dadu yang benar-benar kamu punya, mulai dari angka rendah, dan ingat lawan NPC jarang sekali memakai Spot On. Saat lawan tinggal punya satu dadu, angka yang ia sebut pertama hampir selalu jujur.
"""
        )


def render_setup():
    ss = st.session_state
    if "default_names" not in ss:
        ss.default_names = ["Kamu"] + random.sample(NPC_NAMES, 3)
    with st.container(key="setup"):
        H("<div class='panel-title'>🃏 Pilih Meja</div>")
        loc = st.selectbox("Saloon", list(LOCATIONS), key="loc")
        H(f"<div class='panel-note'>{esc(LOCATIONS[loc])} · ante ${ANTE}</div>")
        n = st.segmented_control("Jumlah pemain di meja", [2, 3, 4], default=2, key="n_players") or 2
        seats = []
        for i in range(n):
            c1, c2 = st.columns([3, 2])
            with c1:
                name = st.text_input(f"Kursi {i + 1}", value=ss.default_names[i], key=f"name_{i}", max_chars=16)
            with c2:
                kind = st.segmented_control("Pemain", ["Manusia", "AI"], default="Manusia" if i == 0 else "AI",
                                            key=f"kind_{i}") or ("Manusia" if i == 0 else "AI")
            seats.append(dict(name=(name or f"Pemain {i + 1}").strip(), human=kind == "Manusia",
                              avatar=AVATARS[i % len(AVATARS)]))
        H("<div class='panel-note'>Lebih dari satu <b>Manusia</b> = mode <i>hotseat</i>: "
          "gantian di satu perangkat, cangkir ditutup tiap ganti giliran.</div>")
        names = [s["name"] for s in seats]
        dup = len(set(names)) != len(names)
        if dup:
            H("<div class='warn'>Nama pemain harus berbeda.</div>")
        if st.button(f"🪙 Duduk & bayar ante ${ANTE}", type="primary", disabled=dup, key="start"):
            for s in seats:
                s["money"] = ss.bank.get(s["name"], START_MONEY)
            ss.game = Game(seats, loc)
            st.rerun()
    render_rules()


# ----------------------------------------------------------------------------
# Aplikasi
# ----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Liar's Dice — Saloon", page_icon="🎲", layout="centered",
                       initial_sidebar_state="collapsed")
    H(CSS)
    ss = st.session_state
    ss.setdefault("bank", {})
    ss.setdefault("game", None)

    with st.sidebar:
        st.markdown("### ⚙️ Pengaturan")
        speed = st.select_slider("Kecepatan lawan AI", options=list(SPEEDS), value="Normal", key="speed")
        show_hint = st.toggle("Tampilkan peluang (bantuan belajar)", value=False, key="hint",
                              help="Tidak ada di game aslinya — matikan untuk pengalaman 1:1.")
        if ss.game is not None and st.button("🚪 Tinggalkan meja", key="leave"):
            ss.game = None
            st.rerun()
        if ss.bank:
            st.markdown("### 💰 Dompet")
            for k, v in ss.bank.items():
                md(f"- **{k}**: ${v}")

    g = ss.game
    if g is None:
        render_header()
        render_setup()
        return

    render_header(g.location)

    if g.phase == "gameover" and not g.banked:
        for p in g.players:
            ss.bank[p["name"]] = p["money"]
        g.banked = True

    hero = hero_index(g)
    if g.phase in ("reveal", "gameover"):
        render_result(g)
    render_table(g, hero)

    if g.phase == "bidding":
        cur = g.players[g.turn]
        if cur["human"]:
            if len(humans_of(g)) > 1 and hero != g.turn:
                render_cover(g, g.turn)
            else:
                render_hand(g, hero)
                render_controls(g, g.turn, show_hint)
        else:
            render_hand(g, hero)

    render_log(g)
    render_rules()

    # Penggerak AI: jalan otomatis dengan jeda agar terasa seperti di meja
    delay = SPEEDS.get(speed, 1.25)
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
