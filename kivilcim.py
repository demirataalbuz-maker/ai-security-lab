# -*- coding: utf-8 -*-
"""
kivilcim.py - Uygulamanin icindeki mini arkadas: Kivilcim.

Mor bir alev-bot. Serin buyudukce alevi buyur (kor -> mor -> uc murekkep -> tacli),
gelmedigin gunlerde kuser / soner. Mesajlari kullanicinin gercek verisinden
uretilir (bugunku plan, zayif alan, son yanlis teknik, yeni sorular, cevaplanan notlar).

Cizim tk.Canvas uzerinde; sekiller telefon surumundeki SVG yollarindan orneklenir,
her karede titreme/ziplama/sallanma donusumu uygulanip yeniden cizilir (~20 fps).
Bildirim: pencerenin sag altindan kayan kart. Konfeti: pencerenin ustune acilan
seffaf (transparentcolor) bir katman.
"""

import math
import random
import tkinter as tk
from datetime import date, datetime

import customtkinter as ctk

import attackdb
import quizgen

# ---- sekiller (telefonla ayni SVG yollari, viewBox 0 0 200 230, taban 100,205) ----
OUT = "M100 200C55 200 35 165 42 130C48 100 70 88 72 60C86 76 90 90 92 92C98 70 108 45 100 18C130 40 158 80 160 125C165 170 140 200 100 200Z"
MID = "M100 196C66 196 52 168 58 138C63 116 80 106 82 86C92 100 95 108 95 108C102 90 112 72 108 52C128 72 146 100 146 134C148 170 128 196 100 196Z"
CORE = "M100 192C80 192 70 176 73 158C76 142 88 134 92 120C100 132 104 136 104 136C110 124 116 112 116 100C128 116 134 136 132 154C130 178 118 192 100 192Z"

PAL = [  # dis, dis2, orta, orta2, cekirdek
    ("#b0442a", "#ff8a4c", "#ff8a4c", "#ffb07a", "#ffd9b8"),   # kor
    ("#8f52d6", "#c07cff", "#b37aff", "#a88bff", "#f3e9ff"),   # kucuk mor
    ("#c05ad6", "#c07cff", "#c07cff", "#7f8cff", "#f3e9ff"),   # mor + kivilcim
    ("#ff4a3d", "#c07cff", "#c07cff", "#4a86ff", "#f7efff"),   # uc murekkep
    ("#ff4a3d", "#ff6fb5", "#c07cff", "#4a86ff", "#ffffff"),   # tacli
]
SCALE = [.55, .72, .86, 1.0, 1.1]
SPARKS = [0, 2, 5, 8, 12]
GRAY = ("#4d4855", "#6a6474", "#6a6474", "#7a7382", "#bdb6c8")
TITLE = {"new": "KIVILCIM", "happy": "KIVILCIM · MUTLU", "wait": "KIVILCIM · BEKLİYOR",
         "sulk": "KIVILCIM · KÜS", "out": "KIVILCIM · SÖNÜYOR"}


def _parse(path, steps=10):
    """Sadece M/C/Z iceren SVG yolunu nokta listesine cevir."""
    nums = [float(x) for x in __import__("re").findall(r"-?\d+(?:\.\d+)?", path)]
    x0, y0 = nums[0], nums[1]
    pts = [(x0, y0)]
    i = 2
    while i + 5 < len(nums) + 0:
        x1, y1, x2, y2, x3, y3 = nums[i:i + 6]
        for s in range(1, steps + 1):
            t = s / steps
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
            pts.append((a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3))
        x0, y0 = x3, y3
        i += 6
    return pts


def _rounded(x, y, w, h, r, n=6):
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                       (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


P_OUT, P_MID, P_CORE = _parse(OUT), _parse(MID), _parse(CORE)
P_VISOR = _rounded(64, 138, 72, 31, 15.5)
P_CROWN = [(78, 22), (84, 4), (92, 16), (100, 0), (108, 16), (116, 4), (122, 22)]


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


class Kivilcim:
    def __init__(self, app, parent, bg, colors):
        """app: ana pencere; parent: kartin yerlesecegi cerceve; bg: canvas zemini (tek renk)."""
        self.app, self.bg, self.C = app, bg, colors
        self.canvas = tk.Canvas(parent, width=76, height=88, bg=bg, highlightthickness=0, bd=0,
                                cursor="hand2")
        self.k = 76 / 200.0
        self.t = 0.0
        self.mood = "wait"
        self.anim = None            # ("jump"|"shake", baslangic)
        self.blink_at = 0
        self.particles = []
        self.msg_idx = 0
        self.nudges = 0
        self.last_act = datetime.now()
        self.toast = None
        self._toast_after = None
        self.canvas.bind("<Button-1>", lambda e: self.on_click())
        app.bind_all("<Button>", self._touch, add="+")
        app.bind_all("<Key>", self._touch, add="+")
        self.refresh()
        self._tick()
        app.after(1600, self.greet)
        app.after(30000, self._idle_check)

    # ------------------------------------------------------------------ veri
    def _prog(self):
        return attackdb.load_progress()

    def _away(self, p):
        ld = p.get("last_day")
        if not ld:
            return None
        try:
            return (date.today() - date.fromisoformat(ld[:10])).days
        except ValueError:
            return None

    def eff_streak(self, p=None):
        p = p or self._prog()
        d = self._away(p)
        return 0 if (d is None or d > 1) else int(p.get("streak", 0) or 0)

    def calc_mood(self, p=None):
        d = self._away(p or self._prog())
        if d is None:
            return "new"
        return {0: "happy", 1: "wait", 2: "sulk"}.get(d, "out")

    @staticmethod
    def level(s):
        return 0 if s == 0 else 1 if s < 3 else 2 if s < 7 else 3 if s < 30 else 4

    def refresh(self):
        p = self._prog()
        self.mood = self.calc_mood(p)
        self.streak = self.eff_streak(p)
        self.lvl = 0 if self.mood == "out" else self.level(self.streak)

    def facts(self):
        p = self._prog()
        rows, done, goal = quizgen.plan_status(p)
        nxt = quizgen.next_area(p)
        left = 0
        if nxt:
            left = next((r[2] - r[1] for r in rows if r[0] == nxt), 0)
        weak = quizgen.weak_areas(p, 2)
        items = p.get("items") or {}
        today = date.today().isoformat()
        try:
            qs = quizgen.load_questions().get("questions", [])
        except Exception:
            qs = []
        new_q = sum(1 for q in qs if q.get("added") == today
                    and not any(k.startswith(q.get("id", "?") + "|") for k in items))
        bad = None
        for k, v in items.items():
            if v.get("last_result") == "bad" and (bad is None or (v.get("last") or "") > (bad[1].get("last") or "")):
                bad = (k, v)
        bad_name = None
        if bad:
            src = bad[0].split("|")[0]
            try:
                for a in attackdb.load_attacks().get("attacks", []):
                    if a.get("id") == src:
                        bad_name = a.get("technique")
                        break
            except Exception:
                pass
        try:
            notes = quizgen.load_notes().get("notes", [])
        except Exception:
            notes = []
        answered = sum(1 for n in notes if (n.get("answer") or "").strip() and n.get("answered_day") == today)
        open_n = sum(1 for n in notes if not (n.get("answer") or "").strip())
        return dict(done=done, goal=goal, nxt=nxt, left=left, weak=weak, new_q=new_q,
                    bad=bad_name, answered=answered, open=open_n, streak=self.eff_streak(p),
                    best=int(p.get("best_streak", 0) or 0), away=self._away(p))

    def messages(self):
        f, m, out = self.facts(), self.mood, []
        if m == "new":
            out += ["Selam! Ben Kıvılcım. Her gün soru çözdükçe büyürüm, gelmezsen sönerim. İlk soruyla yak beni 🔥",
                    "Günde %d soru hedefimiz var ama 20 soruyla başlasak bile yanarım." % f["goal"]]
        elif m == "happy":
            if f["done"] >= f["goal"]:
                out.append("%d/%d! Bugün her alanı bitirdin. Efsanesin 👑" % (f["goal"], f["goal"]))
            else:
                out.append("Bugün %d soru çözdün.%s" % (f["done"], (" Sırada %s, %d soru kaldı." % (f["nxt"], f["left"])) if f["nxt"] else ""))
            out.append("Seri %d gün! %s" % (f["streak"], "Rekorundasın, bak alevime!" if f["streak"] >= f["best"] and f["streak"] > 1
                                            else "Rekorun %d, yaklaşıyoruz." % f["best"]))
            if f["bad"]:
                out.append("En son “%s”da takıldın. Birkaç gün sonra başka açıdan soracağım 😏" % f["bad"])
        elif m == "wait":
            out.append("Bugün daha gelmedin… %s20 soru, 10 dakika." % (("%d günlük serin gece yarısı söner! " % f["streak"]) if f["streak"] else ""))
            if f["new_q"]:
                out.append("Sabah %d yeni soru geldi, ilk sen çöz." % f["new_q"])
            if f["answered"]:
                out.append("Notlarından %d tanesine cevap geldi. Notlarım'da seni bekliyor." % f["answered"])
            if f["weak"]:
                out.append("En zayıf alanın %s. Bugün oraya yüklenelim mi?" % f["weak"][0])
        elif m == "sulk":
            out += ["Dün gelmedin. Hmph.", "…",
                    "Serimiz söndü sayılır. %sBir tur çözersen affederim belki." % (("%s soruların hazır. " % f["weak"][0]) if f["weak"] else "")]
        else:
            out += ["Ben burada tek başıma yandım durdum 🥲",
                    "%s gündür yoksun. Tek bir soru yeter, yeniden yanarım." % (f["away"] or "Kaç")]
            if f["new_q"] or f["open"]:
                bits = []
                if f["new_q"]:
                    bits.append("%d yeni soru" % f["new_q"])
                if f["open"]:
                    bits.append("%d açık not" % f["open"])
                out.append("Bu arada %s birikti." % " ve ".join(bits))
        return [x for x in out if x]

    # ------------------------------------------------------------------ cizim
    def _xf(self, pts, sx=1.0, sy=1.0, skew=0.0, body=None):
        """Nokta listesine alev titremesi + govde hareketi + seviye olcegi uygula."""
        L = SCALE[self.lvl] * (0.9 if self.mood == "sulk" else 1.0)
        dy, rot, mirror, bsx, bsy = body
        ca, sa = math.cos(rot), math.sin(rot)
        out = []
        ox, oy = 100.0, 205.0
        for x, y in pts:
            x, y = x - ox, y - oy
            x, y = x * sx + skew * y, y * sy                    # titreme
            x, y = x * bsx, y * bsy
            x = -x if mirror else x
            x, y = x * ca - y * sa, x * sa + y * ca             # sallanma
            x, y = x * L, y * L + dy
            out += [(x + ox) * self.k, (y + oy + 20) * self.k]
        return out

    def _body(self):
        t, m = self.t, self.mood
        dy, rot, mirror, bsx, bsy = 0.0, 0.0, False, 1.0, 1.0
        if m == "happy":
            ph = (t % 2.4) / 2.4
            if 0.6 < ph < 0.8:
                dy = -16 * math.sin((ph - 0.6) / 0.2 * math.pi)
            elif 0.8 <= ph < 0.95:
                bsx, bsy = 1.04, 0.95
        elif m in ("wait", "new"):
            rot = math.radians(4) * math.sin(t * 2.1)
        elif m == "sulk":
            mirror, rot = True, math.radians(-4)
        else:
            dy = 3 * math.sin(t * 1.6)
        if self.anim:
            kind, t0 = self.anim
            e = self.t - t0
            if e > 0.6:
                self.anim = None
            elif kind == "jump":
                dy += -26 * math.sin(e / 0.6 * math.pi)
                rot += math.radians(-6) * math.sin(e / 0.6 * math.pi)
            else:
                dy += 0
                rot += 0
                bsx *= 1.0
                dy += 0
                self._shake = 6 * math.sin(e * 40) * (1 - e / 0.6)
        return dy, rot, mirror, bsx, bsy

    def _draw(self):
        c = self.canvas
        c.delete("all")
        pal = GRAY if self.mood == "out" else PAL[self.lvl]
        if self.mood == "sulk":
            pal = tuple(_mix(x, "#6a6474", .45) for x in pal)
        t = self.t
        self._shake = 0.0
        body = self._body()
        f1 = (1 - .02 * math.sin(t * 3.9), 1 + .04 * math.sin(t * 3.9), .03 * math.sin(t * 2.7))
        f2 = (1 - .04 * math.sin(t * 5.7 + 1), 1 + .06 * math.sin(t * 5.7 + 1), -.05 * math.sin(t * 5.7))
        base = self._xf([(100, 205)], body=body)
        L = SCALE[self.lvl]
        bx = base[0] + self._shake * self.k
        c.create_oval(bx - 44 * L * self.k, (225 - 7 * L) * self.k, bx + 44 * L * self.k, (225 + 7 * L) * self.k,
                      fill=_mix(self.bg, "#000000", .45), outline="")
        halo = _mix(self.bg, pal[1], .28)
        c.create_polygon(self._xf(P_OUT, f1[0] * 1.08, f1[1] * 1.06, f1[2], body), fill=halo, outline="", smooth=True)
        c.create_polygon(self._xf(P_OUT, *f1, body=body), fill=pal[0], outline="", smooth=True)
        c.create_polygon(self._xf(P_MID, *f2, body=body), fill=pal[2], outline="", smooth=True)
        c.create_polygon(self._xf(P_CORE, *f2, body=body), fill=pal[4], outline="", smooth=True)
        c.create_polygon(self._xf(P_VISOR, body=body), fill="#0e0d12", outline=_mix("#0e0d12", "#c07cff", .45))
        self._eyes(body)
        if self.lvl == 4 and self.mood != "out":
            bob = 3 * math.sin(t * 3)
            c.create_polygon(self._xf([(x, y + bob) for x, y in P_CROWN], body=body),
                             fill="#ffc15e", outline="#0e0d12", width=1)
        if self._shake:
            c.move("all", self._shake * self.k, 0)
        # parcaciklar
        for p in self.particles:
            x, y, r, col = p["x"], p["y"], p["r"], p["c"]
            c.create_oval((x - r) * self.k, (y - r) * self.k, (x + r) * self.k, (y + r) * self.k,
                          fill=col, outline="")

    def _eyes(self, body):
        c, m = self.canvas, self.mood
        W = "#f3e9ff"
        blink = self.mood in ("happy", "wait", "new") and 0 <= (self.t - self.blink_at) < 0.15
        look = 0.0
        if m in ("wait", "new"):
            ph = (self.t % 4.0) / 4.0
            look = -4 if 0.45 < ph < 0.6 else (4 if 0.7 < ph < 0.85 else 0)

        def line(pts, col=W, w=4):
            c.create_line(self._xf(pts, body=body), fill=col, width=max(1, w * self.k * 1.6),
                          capstyle="round", smooth=True)

        if blink:
            line([(80, 153), (92, 153)])
            line([(108, 153), (120, 153)])
        elif m == "happy":
            line([(79, 157), (86, 148), (93, 157)])
            line([(107, 157), (114, 148), (121, 157)])
            for x in (72, 128):
                pts = self._xf([(x - 6, 161), (x + 6, 167)], body=body)
                c.create_oval(*pts, fill="#c65a9a", outline="")
        elif m in ("wait", "new"):
            for x in (86, 114):
                pts = self._xf([(x - 6.5 + look, 146.5), (x + 6.5 + look, 159.5)], body=body)
                c.create_oval(*pts, fill=W, outline="")
        elif m == "sulk":
            line([(79, 152), (93, 155)])
            line([(107, 155), (121, 152)])
        else:
            line([(79, 150), (86, 156), (93, 153)], "#bdb6c8", 3.5)
            line([(107, 153), (114, 156), (121, 150)], "#bdb6c8", 3.5)
            pts = self._xf([(85, 160), (91, 169)], body=body)
            c.create_oval(*pts, fill="#7fb4ff", outline="")

    def _step_particles(self):
        pal = PAL[self.lvl]
        n = 0 if self.mood in ("out", "sulk") else SPARKS[self.lvl]
        if self.mood == "out" and random.random() < 0.05 and len(self.particles) < 4:
            self.particles.append({"x": 98 + random.random() * 6, "y": 120, "vx": -0.25, "vy": -0.9,
                                   "r": 6, "c": "#4a4555", "life": 1.0, "grow": .12})
        if n and random.random() < n / 40.0:
            self.particles.append({"x": 70 + random.random() * 60, "y": 140 + random.random() * 40,
                                   "vx": random.uniform(-.6, .6), "vy": random.uniform(-2.8, -1.6),
                                   "r": random.uniform(1.6, 3.2),
                                   "c": "#ffc15e" if random.random() < .33 else pal[1], "life": 1.0, "grow": 0})
        keep = []
        for p in self.particles:
            p["x"] += p["vx"]; p["y"] += p["vy"]; p["life"] -= 0.025; p["r"] += p["grow"]
            if p["life"] > 0:
                keep.append(p)
        self.particles = keep

    def _tick(self):
        try:
            self.t += 0.05
            if random.random() < 0.012:
                self.blink_at = self.t
            self._step_particles()
            self._draw()
        except tk.TclError:
            return
        self.app.after(50, self._tick)

    def burst(self, n=14):
        pal = PAL[self.lvl]
        for _ in range(n):
            self.particles.append({"x": 100, "y": 130, "vx": random.uniform(-3, 3), "vy": random.uniform(-4, -1.5),
                                   "r": random.uniform(2, 4), "c": random.choice(("#ffc15e", pal[1], "#ff4a3d")),
                                   "life": 1.0, "grow": 0})

    # ------------------------------------------------------------------ bildirim
    def say(self, text, title=None, action=True, ms=9000, go_text="Sınava başla"):
        app, C = self.app, self.C
        self.hide()
        card = ctk.CTkFrame(app, fg_color=C["card"], border_width=1, border_color=C["accent"], corner_radius=14)
        ctk.CTkLabel(card, text=title or TITLE[self.mood], anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold", family=C["display"]),
                     text_color=C["accent"]).pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(card, text=text, anchor="w", justify="left", wraplength=290,
                     font=ctk.CTkFont(size=13), text_color=C["text"]).pack(fill="x", padx=16, pady=(0, 10))
        if action:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=(0, 12))
            ctk.CTkButton(row, text=go_text, height=32, font=ctk.CTkFont(size=12, weight="bold"),
                          fg_color=C["accent"], hover_color=C["accent_dk"], text_color=C["ink"],
                          command=lambda: (self.hide(), self.app.show_exam())).pack(side="left", padx=4, expand=True, fill="x")
            ctk.CTkButton(row, text="Sonra", height=32, font=ctk.CTkFont(size=12),
                          command=self.hide).pack(side="left", padx=4, expand=True, fill="x")
        self.toast = card
        self._slide(card, 360)
        self._toast_after = app.after(ms, self.hide)

    def _slide(self, card, x):
        if self.toast is not card:
            return
        try:
            card.place(relx=1.0, rely=1.0, x=-18 + x, y=-18, anchor="se")
            card.lift()
        except tk.TclError:
            return
        if x > 0:
            self.app.after(16, lambda: self._slide(card, int(x * 0.72)))

    def hide(self):
        if self._toast_after:
            try:
                self.app.after_cancel(self._toast_after)
            except Exception:
                pass
            self._toast_after = None
        if self.toast is not None:
            try:
                self.toast.destroy()
            except tk.TclError:
                pass
            self.toast = None

    def confetti(self):
        """Pencerenin ustune seffaf katman acip konfeti yagdir (Windows)."""
        app = self.app
        try:
            app.update_idletasks()
            x, y, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
            top = tk.Toplevel(app)
            top.overrideredirect(True)
            key = "#010203"
            top.configure(bg=key)
            top.attributes("-transparentcolor", key)
            top.attributes("-topmost", True)
            top.geometry("%dx%d+%d+%d" % (w, h, x, y))
            cv = tk.Canvas(top, width=w, height=h, bg=key, highlightthickness=0)
            cv.pack()
        except tk.TclError:
            return
        cols = ("#ff4a3d", "#c07cff", "#4a86ff", "#ffc15e", "#7fd6a4", "#ff6fb5")
        bits = [{"x": w / 2 + random.uniform(-60, 60), "y": h * 0.6, "vx": random.uniform(-11, 11),
                 "vy": random.uniform(-22, -9), "c": random.choice(cols), "a": random.uniform(0, 6.28),
                 "s": random.uniform(5, 9)} for _ in range(90)]
        state = {"n": 0}

        def frame():
            state["n"] += 1
            try:
                cv.delete("all")
                for b in bits:
                    b["vy"] += 0.8; b["x"] += b["vx"]; b["y"] += b["vy"]; b["vx"] *= 0.985; b["a"] += 0.3
                    s, ca = b["s"], abs(math.cos(b["a"]))
                    cv.create_rectangle(b["x"] - s * ca, b["y"] - s * .6, b["x"] + s * ca, b["y"] + s * .6,
                                        fill=b["c"], outline="")
                if state["n"] < 55:
                    top.after(30, frame)
                else:
                    top.destroy()
            except tk.TclError:
                pass
        frame()

    # ------------------------------------------------------------------ olaylar
    def _touch(self, _e=None):
        self.last_act = datetime.now()

    def greet(self):
        msgs = self.messages()
        if msgs:
            self.say(msgs[0])

    def on_click(self):
        if self.toast is not None:
            self.hide()
            return
        msgs = self.messages()
        self.say(msgs[self.msg_idx % len(msgs)])
        self.msg_idx += 1
        self.anim = ("shake" if self.mood == "sulk" else "jump", self.t)

    def on_record(self, correct, sure, before):
        """before = {'mood', 'best', 'area'} — kayittan ONCEKI durum."""
        self.refresh()
        p = self._prog()
        was = before.get("mood")
        streak = int(p.get("streak", 0) or 0)
        if was != "happy":
            self.anim = ("jump", self.t)
            self.burst(18)
            if was in ("sulk", "out"):
                self.say("Geldin! 🥹 Küslük bitti, yeniden yanıyorum.", action=False, ms=4500)
            elif streak > 1:
                self.say("Seri %d gün oldu! 🔥" % streak, action=False, ms=4000)
            else:
                self.say("Ateş yandı! İlk soru tamam 🔥", action=False, ms=4000)
            if streak > (before.get("best") or 0) and streak > 1:
                self.app.after(1300, lambda: (self.confetti(),
                                              self.say("Yeni rekor: %d gün! 👑" % streak, action=False, ms=5000)))
            return
        if correct and sure:
            self.anim = ("jump", self.t)
            self.burst(10)
        elif not correct:
            self.anim = ("shake", self.t)
        rows, done, goal = quizgen.plan_status(p)
        per = dict((r[0], r[1]) for r in rows).get(before.get("area"), 0)
        g = quizgen.goal_per_area(p)
        if per == g:
            self.confetti()
            self.say("%s bugünlük bitti (%d/%d)! Sıradaki alana geçelim mi?" % (before.get("area"), g, g),
                     action=False, ms=5500)
        if done == goal:
            self.app.after(900, lambda: (self.confetti(),
                                         self.say("%d/%d. Bugün bütün alanları bitirdin. Taç senin 👑" % (goal, goal),
                                                  action=False, ms=7000)))

    def on_exam_done(self, total, sure):
        if not total:
            return
        pct = round(sure / total * 100)
        if pct >= 80:
            self.confetti()
            self.say("Gerçek bilgi oranın %%%d. Alevim bundan büyüyor 🔥" % pct, go_text="Yeni sınav")
        elif pct >= 50:
            self.say("%%%d gerçek bilgi. Fena değil; yanlışların birkaç gün sonra başka açıdan gelecek." % pct,
                     go_text="Yeni sınav")
        else:
            self.say("%%%d… Üzülme, ben de ilk başta kordum. Çalışman gerekenler ekranda 👇" % pct, action=False)

    def _idle_check(self):
        try:
            f = None
            idle = (datetime.now() - self.last_act).total_seconds()
            if self.nudges < 2 and idle > 240 and self.toast is None:
                f = self.facts()
                if f["done"] < f["goal"]:
                    self.nudges += 1
                    self.last_act = datetime.now()
                    self.anim = ("jump", self.t)
                    self.say(("Mola uzadı 👀 %s" % (("%s'de %d soru kaldı." % (f["nxt"], f["left"])) if f["nxt"] else ""))
                             if f["done"] else "Buradayım, bekliyorum… Bir tur çözelim mi? 🔥")
        finally:
            try:
                self.app.after(30000, self._idle_check)
            except tk.TclError:
                pass
