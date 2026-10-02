"""Hacker klavye pratigi: kamera ile "klavyeye bakma" tespiti.

Tek dosya, bagimsiz modul. Kendi basina calisir:  python hacker_typing.py
Ana uygulamaya sekme olarak takmak icin HackerTypingFrame(parent) yeterli.

Tespit mantigi (indirme gerektirmez, OpenCV'nin kendi yuz algilayicisi):
  - Baslarken "duz bak" kalibrasyonu: yuzun kadrajdaki konumu/boyu olculur.
  - Baktiginda yuz asagi kayar ve/veya algilanamaz hale gelir.
  - Esik asilirsa "KLAVYEYE BAKTIN" -> pratik askiya alinir, kafa kalkinca devam.
"""
import datetime
import json
import math
import os
import random
import time
import urllib.request

import customtkinter as ctk
import numpy as np
from PIL import Image

try:                                  # kamera bagimliliklari opsiyonel: yoksa kamerasiz mod
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    HAVE_CAMERA_LIBS = True
except ImportError:
    HAVE_CAMERA_LIBS = False

BG, FG, DIM, RED, AMBER = "#050a05", "#33ff66", "#1f7a3a", "#ff4444", "#ffb000"
MONO = ("Consolas", 22)
DAILY_SECONDS = 10 * 60           # gunluk drill hedefi (sadece gercekten yazilan sure)
IDLE_CUTOFF = 3.0                 # bu kadar sn tus yoksa sure sayilmaz
PROGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drill_progress.json")

LINES = [
    "nmap -sV -p- --min-rate 5000 10.10.10.5",
    "sudo apt update && sudo apt install -y gobuster",
    "curl -s http://target.local/robots.txt | grep Disallow",
    "echo 'cGFzc3dvcmQ=' | base64 -d",
    "hydra -l admin -P rockyou.txt ssh://192.168.1.10",
    "gobuster dir -u http://target -w common.txt -t 40",
    "python3 -m http.server 8000 --bind 0.0.0.0",
    "nc -lvnp 4444",
    "chmod +x exploit.sh && ./exploit.sh",
    "grep -rniE 'api[_-]?key|secret|token' ./src",
    "ssh -L 8080:127.0.0.1:80 user@10.10.10.5",
    "john --wordlist=rockyou.txt hashes.txt",
    "export TARGET=10.10.10.5; ping -c 3 $TARGET",
    "sqlmap -u 'http://t/?id=1' --batch --dbs",
    "tcpdump -i eth0 -nn port 443 -w capture.pcap",
]


class FileStore:
    """Gunluk ilerleme {tarih: {seconds, rounds, best_wpm}} -> JSON dosyasi.
    Lab'a gomulurken ayni arayuzle (load/save) progress.json'a yazan bir store verilir."""

    def __init__(self, path=PROGRESS):
        self.path = path

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
        except OSError:
            pass


def load_history(data):
    """Grafik icin: [(tarih, dakika, en_iyi_wpm, tur), ...] tarihe gore sirali."""
    out = []
    for d, v in sorted((data or {}).items()):
        try:
            out.append((d, round(float(v.get("seconds", 0)) / 60, 1),
                        float(v.get("best_wpm", 0)), int(v.get("rounds", 0))))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


class HistoryChart(ctk.CTkFrame):
    """Son N gun: dakika cubuklari (10 dk hedef cizgisi) + en iyi WPM cizgisi."""

    def __init__(self, parent, days=14, height=190, **kw):
        super().__init__(parent, fg_color=kw.pop("fg_color", "#0a140a"), **kw)
        self.days = days
        self.cv = ctk.CTkCanvas(self, height=height, bg=self.cget("fg_color"), highlightthickness=0)
        self.cv.pack(fill="both", expand=True, padx=8, pady=8)
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.data = {}

    def update_data(self, data):
        self.data = data
        self.draw()

    def draw(self):
        c = self.cv
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60 or h < 60:
            return
        today = datetime.date.today()
        days = [(today - datetime.timedelta(days=i)).isoformat() for i in range(self.days - 1, -1, -1)]
        mins = [float((self.data.get(d) or {}).get("seconds", 0)) / 60 for d in days]
        wpm = [float((self.data.get(d) or {}).get("best_wpm", 0)) for d in days]
        L, R, T, B = 36, 36, 14, 28
        pw, ph = w - L - R, h - T - B
        ymax = max(12.0, max(mins) * 1.15)
        wmax = max(20.0, max(wpm) * 1.15)
        goal_y = T + ph * (1 - DAILY_SECONDS / 60 / ymax)
        c.create_line(L, goal_y, w - R, goal_y, fill=AMBER, dash=(4, 3))
        c.create_text(L - 4, goal_y, text="10", fill=AMBER, anchor="e", font=("Consolas", 9))
        c.create_text(L - 4, T + ph, text="0", fill=DIM, anchor="e", font=("Consolas", 9))
        slot = pw / len(days)
        pts = []
        for i, d in enumerate(days):
            x0 = L + i * slot + slot * 0.18
            x1 = L + (i + 1) * slot - slot * 0.18
            y = T + ph * (1 - mins[i] / ymax)
            done = mins[i] >= DAILY_SECONDS / 60
            if mins[i] > 0:
                c.create_rectangle(x0, y, x1, T + ph, fill=FG if done else DIM, outline="")
            if wpm[i] > 0:
                pts.append(((x0 + x1) / 2, T + ph * (1 - wpm[i] / wmax)))
            if i % 2 == (len(days) - 1) % 2 or len(days) <= 7:
                c.create_text((x0 + x1) / 2, h - 12, text=d[8:], fill=DIM, font=("Consolas", 9))
        if len(pts) > 1:
            c.create_line(*[v for p in pts for v in p], fill="#00d4ff", width=2)
        for x, y in pts:
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#00d4ff", outline="")
        c.create_text(w - R + 4, T, text=f"{wmax:.0f}wpm", fill="#00d4ff", anchor="w", font=("Consolas", 9))
        c.create_text(L, 2, text="dakika (cubuk)  /  en iyi WPM (cizgi)", fill=DIM, anchor="nw",
                      font=("Consolas", 9))


class HeadTracker:
    """MediaPipe FaceLandmarker: bas egimi (pitch) + gozlerin asagi bakisi.

    Iki noktali kalibrasyon: ekrana bakis (S) ve klavyeye bakis (K).
    Her kare icin ozellik vektoru x=(pitch/20, gozAsagi/0.5) S->K dogrusuna
    izdusurulur: t=0 ekran, t=1 klavye. t>0.55 asagi, t<0.40 yukari (histerezis).
    """
    MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "face_landmarker.task")
    URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
           "face_landmarker/float16/1/face_landmarker.task")

    def __init__(self, cam_index=0, model_dir=None):
        self.cap = self.lm = None
        self.ok = False
        model = os.path.join(model_dir, "face_landmarker.task") if model_dir else self.MODEL
        if HAVE_CAMERA_LIBS:
            self.cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.ok = self.cap.isOpened()
        if self.ok:
            try:
                if not os.path.exists(model):
                    os.makedirs(os.path.dirname(model), exist_ok=True)
                    urllib.request.urlretrieve(self.URL, model)
            except OSError:                     # model indirilemedi (cevrimdisi): kamerasiz mod
                self.cap.release()
                self.ok = False
        if self.ok:
            opts = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=model),
                running_mode=vision.RunningMode.IMAGE, num_faces=1,
                output_face_blendshapes=True, output_facial_transformation_matrixes=True)
            self.lm = vision.FaceLandmarker.create_from_options(opts)
        self.S = self.K = None        # kalibrasyon noktalari (ozellik vektoru)
        self.high, self.low = 0.45, 0.28
        self.ema = None               # yumusatilmis skor
        self.over_since = None        # esigi asmaya basladigi an
        self.missing = 0
        self.feat = None
        self.t = None
        self.down_state = False

    @staticmethod
    def _feature(res):
        bs = {c.category_name: c.score for c in res.face_blendshapes[0]}
        eye = (bs.get("eyeLookDownLeft", 0) + bs.get("eyeLookDownRight", 0)) / 2
        R = res.facial_transformation_matrixes[0][:3, :3]
        pitch = math.degrees(math.atan2(R[2, 1], R[2, 2]))
        blink = (bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2
        return np.array([pitch / 20.0, eye / 0.5]), blink

    def read(self):
        """-> (down: bool|None, frame_bgr). None = kalibrasyon yok/kamera yok."""
        if not self.ok:
            return None, None
        ok, frame = self.cap.read()
        if not ok:
            return None, None
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = self.lm.detect(img)
        self.feat = None
        if res.face_landmarks:
            vec, blink = self._feature(res)
            self.missing = 0
            if blink < 0.35:              # goz kirpma/kisma kareleri atilir
                self.feat = vec
        else:
            self.missing += 1
        frame = cv2.flip(frame, 1)
        return self._decide(), frame

    def _decide(self):
        if self.S is None or self.K is None:
            return None
        if self.feat is None:
            self.t = None
            if self.missing >= 6:           # yuz kayboldu = buyuk ihtimalle egildi
                self.down_state = True
            return self.down_state
        d = self.K - self.S
        raw = float(np.dot(self.feat - self.S, d) / max(np.dot(d, d), 1e-6))
        self.ema = raw if self.ema is None else 0.8 * self.ema + 0.2 * raw
        self.t = self.ema
        now = time.time()
        if self.down_state:
            if self.t < self.low:
                self.down_state, self.over_since = False, None
        elif self.t > self.high:
            self.over_since = self.over_since or now
            if now - self.over_since > 0.35:  # 0.35 sn surekli asagi = bakis
                self.down_state = True
        else:
            self.over_since = None
        return self.down_state

    def calibrate(self, samples):
        """samples: ozellik vektorleri. Ortancayi dondurur (yetersizse None)."""
        if len(samples) < 8:
            return None
        return np.median(np.array(samples), axis=0)

    def release(self):
        if self.cap is not None:
            self.cap.release()
        if self.lm:
            self.lm.close()


class HackerTypingFrame(ctk.CTkFrame):
    def __init__(self, parent, cam_index=0, store=None, log_path="default", model_dir=None,
                 show_chart=True):
        super().__init__(parent, fg_color=BG)
        self._alive = True
        self.show_chart = show_chart
        self.store = store or FileStore()
        self.tracker = HeadTracker(cam_index, model_dir)
        self.state = "idle"        # idle | calibrating | typing | paused
        self.cal_samples, self.cal_until = [], 0
        self.target, self.typed = "", ""
        self.start_t = None
        self.errors = self.keystrokes = self.looks = 0
        self.up_since = None
        self.rounds, self.best_wpm = 0, 0.0
        self.today = datetime.date.today().isoformat()
        self.progress = self._load_progress()
        self.bonus = False                 # 10 dk dolduktan sonra serbest calisma
        self.last_key_t, self.last_tick, self._saved_at = 0.0, time.time(), time.time()
        if log_path == "default":
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_log.csv")
        self.log = open(log_path, "w", buffering=1) if log_path else None
        if self.log:
            self.log.write("zaman,durum,pitch,goz,skor,esik,asagi\n")
        self._build()
        self._top = self.winfo_toplevel()
        self._key_id = self._top.bind("<Key>", self._on_key, add="+")
        self.after(33, self._tick)

    # ---- arayuz
    def _build(self):
        self.cam = ctk.CTkLabel(self, text=("kamera yok: kamerasiz mod" if not HAVE_CAMERA_LIBS else "kamera yok")
                                if not self.tracker.ok else "",
                                width=320, height=240, text_color=DIM)
        self.cam.pack(pady=(14, 6))
        self.status = ctk.CTkLabel(self, text="", font=("Consolas", 26, "bold"), text_color=FG)
        self.status.pack(pady=4)
        self.text = ctk.CTkTextbox(self, width=900, height=110, font=MONO, fg_color="#0a140a",
                                   text_color=DIM, wrap="word", border_color=DIM, border_width=1)
        self.text.pack(pady=8, padx=20)
        self.text.tag_config("ok", foreground=FG)
        self.text.tag_config("bad", foreground=RED, background="#3a0a0a")
        self.text.configure(state="disabled")
        self.stats = ctk.CTkLabel(self, text="", font=("Consolas", 16), text_color=DIM)
        self.stats.pack(pady=4)
        self.daily = ctk.CTkLabel(self, text="", font=("Consolas", 16, "bold"), text_color=AMBER)
        self.daily.pack(pady=2)
        if self.show_chart:
            self.chart = HistoryChart(self)
            self.chart.pack(fill="x", padx=24, pady=(4, 2))
            self.after(200, lambda: self.chart.update_data(self.progress))
        row =ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=8)
        self.btn = ctk.CTkButton(row, text="Baslat (once kalibrasyon)", command=self.start,
                                 fg_color=DIM, hover_color="#2aa650", text_color="black")
        self.btn.pack(side="left", padx=8)
        ctk.CTkLabel(row, text="hassasiyet (sol=cok hassas)", text_color=DIM).pack(side="left", padx=(20, 4))
        self.sens = ctk.CTkSlider(row, from_=0.15, to=0.90, width=160, command=self._set_sens)
        self.sens.set(self.tracker.high)
        self.sens.pack(side="left")
        self._set_status("Hazir. Klavyeye bakmadan yazacaksin.", DIM)

    def _set_sens(self, v):
        self.tracker.high = float(v)                  # asagi sayma esigi
        self.tracker.low = max(float(v) - 0.17, 0.05)  # kalkis esigi (histerezis)

    def _set_status(self, msg, color=FG):
        self.status.configure(text=msg, text_color=color)

    def _render_text(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", self.target)
        for i, ch in enumerate(self.typed):
            tag = "ok" if ch == self.target[i] else "bad"
            self.text.tag_add(tag, f"1.{i}", f"1.{i + 1}")
        self.text.configure(state="disabled")

    # ---- gunluk drill ilerlemesi
    def _load_progress(self):
        return self.store.load()

    def _save_progress(self):
        self._saved_at = time.time()
        self.store.save(self.progress)
        if self.show_chart:
            self.chart.update_data(self.progress)

    def _day(self):
        return self.progress.setdefault(self.today, {"seconds": 0.0, "rounds": 0, "best_wpm": 0.0})

    def _streak(self):
        n, d = 0, datetime.date.today()
        if self.progress.get(d.isoformat(), {}).get("seconds", 0) < DAILY_SECONDS:
            d -= datetime.timedelta(days=1)       # bugun henuz bitmediyse dunden say
        while self.progress.get(d.isoformat(), {}).get("seconds", 0) >= DAILY_SECONDS:
            n, d = n + 1, d - datetime.timedelta(days=1)
        return n

    def _update_daily(self):
        sec = self._day()["seconds"]
        left = max(DAILY_SECONDS - sec, 0)
        txt = f"BUGUN {int(sec // 60):02d}:{int(sec % 60):02d} / 10:00"
        txt += "  TAMAM" if left == 0 else f"  (kalan {int(left // 60):02d}:{int(left % 60):02d})"
        if self._streak():
            txt += f"   seri {self._streak()} gun"
        self.daily.configure(text=txt)

    # ---- akis
    def start(self):
        if self._day()["seconds"] >= DAILY_SECONDS:
            self.bonus = True                      # hedef tamamsa fazla mesai
        if self.tracker.ok:
            self.tracker.S = self.tracker.K = None
            self.tracker.down_state, self.tracker.ema = False, None
            self.target = " ".join(random.sample(LINES, 3))   # kalibrasyonda metne bak
            self.typed = ""
            self._render_text()
            self.state, self.cal_samples = "cal_screen", []
            self.cal_until = time.time() + 4
            self._set_status("1/2  Asagidaki YAZIYA bak, rahat otur (4 sn)", AMBER)
        else:
            self.target = ""
            self._begin_typing()

    def _begin_typing(self):
        self.state = "typing"
        if not self.target:
            self.target = " ".join(random.sample(LINES, 3))
        self.typed, self.errors, self.keystrokes, self.looks = "", 0, 0, 0
        self.start_t = None
        self._render_text()
        self._set_status("YAZ. Klavyeye bakma.", FG)

    def _tick(self):
        if not self._alive:
            return
        now = time.time()
        dt, self.last_tick = min(now - self.last_tick, 0.2), now
        if self.state == "typing" and now - self.last_key_t < IDLE_CUTOFF:
            self._day()["seconds"] += dt          # sadece aktif yazma sayilir
            if now - self._saved_at > 5:
                self._save_progress()
        self._update_daily()
        down, frame = self.tracker.read()
        if frame is not None:
            img = ctk.CTkImage(Image.fromarray(cv2.cvtColor(
                cv2.resize(frame, (320, 240)), cv2.COLOR_BGR2RGB)), size=(320, 240))
            self.cam.configure(image=img)
            self.cam.image = img

        if self.state in ("cal_screen", "cal_keys"):
            if self.tracker.feat is not None:
                self.cal_samples.append(self.tracker.feat)
            if time.time() >= self.cal_until:
                pt = self.tracker.calibrate(self.cal_samples)
                if pt is None:
                    self.state = "idle"
                    self._set_status("Yuz bulunamadi, isigi/acini duzelt.", RED)
                elif self.state == "cal_screen":
                    self.tracker.S = pt
                    self.state, self.cal_samples = "cal_keys", []
                    self.cal_until = time.time() + 4
                    self._set_status("2/2  KLAVYEYE bak, yazarken baktigin gibi (4 sn)", AMBER)
                else:
                    self.tracker.K = pt
                    if np.linalg.norm(self.tracker.K - self.tracker.S) < 0.15:
                        self.state = "idle"
                        self._set_status("Ekran/klavye farki cok az. Basini/gozunu belirgin indir.", RED)
                    else:
                        self._begin_typing()
        elif self.state == "typing" and down:
            self.state, self.up_since = "paused", None
            self.looks += 1
            self._set_status("KLAVYEYE BAKTIN! Basini kaldir.", RED)
        elif self.state == "paused":
            if down is False:
                self.up_since = self.up_since or time.time()
                if time.time() - self.up_since > 0.8:   # 0.8 sn dik kalinca devam
                    self.state = "typing"
                    self._set_status("Devam. Klavyeye bakma.", FG)
            else:
                self.up_since = None
        if self.log and self.state in ("typing", "paused", "cal_screen", "cal_keys") \
                and self.tracker.feat is not None:
            f = self.tracker.feat
            self.log.write(f"{time.time():.2f},{self.state},{f[0]:.3f},{f[1]:.3f},"
                           f"{self.tracker.t if self.tracker.t is not None else ''},"
                           f"{self.tracker.high:.2f},{int(bool(down))}\n")
        self._update_stats()
        if self.state in ("typing", "paused") and self.tracker.t is not None:
            self.stats.configure(text=self.stats.cget("text").split("   skor")[0]
                                 + f"   skor {self.tracker.t:.2f} (esik {self.tracker.high:.2f})")
        self.after(33, self._tick)

    def _on_key(self, e):
        if self.state != "typing":
            return
        if e.keysym == "BackSpace":
            self.typed = self.typed[:-1]
        elif len(e.char) == 1 and e.char.isprintable() and len(self.typed) < len(self.target):
            if self.start_t is None:
                self.start_t = time.time()
            self.last_key_t = time.time()
            self.keystrokes += 1
            if e.char != self.target[len(self.typed)]:
                self.errors += 1
            self.typed += e.char
        else:
            return
        self._render_text()
        if len(self.typed) >= len(self.target):    # kirmizi olsa bile sona gelince biter
            self._finish()

    def _finish(self):
        self.state = "done"
        mins = max((time.time() - self.start_t) / 60, 1e-6)
        wpm = len(self.target) / 5 / mins
        acc = 100 * (1 - self.errors / max(self.keystrokes, 1))
        wrong = sum(a != b for a, b in zip(self.typed, self.target))   # sonda kalan kirmizilar
        self.rounds += 1
        self.best_wpm = max(self.best_wpm, wpm)
        day = self._day()
        day["rounds"] += 1
        day["best_wpm"] = max(day["best_wpm"], round(wpm, 1))
        self._save_progress()
        self._set_status(f"BITTI  {wpm:.0f} WPM  %{acc:.0f} dogruluk  {wrong} yanlis  {self.looks} bakis", AMBER)
        self.stats.configure(text=f"tur {self.rounds}   en iyi {self.best_wpm:.0f} WPM   sonraki yazi geliyor...")
        self.after(2500, self._next_round)

    def _next_round(self):
        if self._alive and self.state == "done":          # kalibrasyon korunur, tekrar yapilmaz
            day = self._day()
            if day["seconds"] >= DAILY_SECONDS and not self.bonus:
                self.state = "idle"
                self._set_status(f"GUNLUK 10 DK TAMAM  en iyi {day['best_wpm']:.0f} WPM  {day['rounds']} tur", AMBER)
                self.stats.configure(text="Yarin devam. Fazla mesai icin Baslat'a bas.")
                return
            self.target = ""
            self._begin_typing()

    def _update_stats(self):
        if self.state in ("typing", "paused") and self.start_t:
            mins = max((time.time() - self.start_t) / 60, 1e-6)
            wpm = len(self.typed) / 5 / mins
            self.stats.configure(text=f"tur {self.rounds + 1}   WPM {wpm:.0f}   hata {self.errors}   bakis {self.looks}")

    def destroy(self):
        self._alive = False
        try:
            self.store.save(self.progress)
            self._top.unbind("<Key>", self._key_id)
        except Exception:
            pass
        if self.log:
            self.log.close()
        self.tracker.release()
        super().destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    root = ctk.CTk(fg_color=BG)
    root.title("Hacker Klavye Pratigi")
    root.geometry("960x640")
    HackerTypingFrame(root).pack(fill="both", expand=True)
    root.mainloop()
