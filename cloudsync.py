# -*- coding: utf-8 -*-
"""
cloudsync.py - Internet uzerinden iki is:

1) ICERIK GUNCELLEMESI (herkes icin, hesap gerekmez)
   Herkese acik GitHub deposundaki data/*.json dosyalari indirilir; yerelde
   olmayan teknik/arac/soru/senaryo kayitlari id'ye gore eklenir. Yerel kayitlar
   asla silinmez ya da ezilmez. Arkadasin exe'si yeni icerigi boyle alir.

2) KISISEL SENKRON (sadece sahibinin hesabi)
   Ilerleme + notlar, kullanicinin kendi GitHub hesabindaki GIZLI bir gist'te
   ("ai-security-lab-sync") tutulur. Laptop ve telefon ayni gist'e yazar/okur,
   birlestirme kayipsizdir (sayaclarda maksimum, not cevaplari korunur).
   Anahtar: Ayarlar'a girilen gist yetkili token, yoksa kurulu `gh` CLI'nin
   oturumu. Ikisi de yoksa kisisel senkron kapali kalir (arkadas modu).

Internet yoksa her sey sessizce atlanir; uygulama yerel veriyle calisir.
"""

import os
import sys
import json
import threading
import subprocess
import urllib.request
from datetime import date, datetime

REPO = "demirataalbuz-maker/ai-security-lab-icerik"
RAW = "https://raw.githubusercontent.com/%s/main/data/" % REPO
SITE = "https://demirataalbuz-maker.github.io/ai-security-lab-icerik/"
API = "https://api.github.com"
GIST_DESC = "ai-security-lab-sync"
SYNC_FILE = "sync.json"
REPORTS_FILE = "reports.json"

# (dosya, liste anahtari) — id'ye gore birlestirilen icerik
CONTENT = (("attacks.json", "attacks"), ("tools.json", "tools"),
           ("questions.json", "questions"), ("scenarios.json", "scenarios"))


# --------------------------------------------------------------------------
# yardimcilar
# --------------------------------------------------------------------------
def _load(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _http(url, method="GET", token=None, body=None, timeout=6):
    headers = {"User-Agent": "AI-Security-Lab", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------
# 1) icerik guncellemesi
# --------------------------------------------------------------------------
def pull_content(data_dir, timeout=6):
    """Depodaki yeni kayitlari yerele ekle. Donen: {dosya: eklenen_sayi} (cevrimdisi: None)."""
    added = {}
    for name, key in CONTENT:
        try:
            remote = _http(RAW + name, timeout=timeout)
        except Exception:
            return None if not added else added
        rows = remote.get(key) if isinstance(remote, dict) else None
        if not isinstance(rows, list):
            continue
        path = os.path.join(data_dir, name)
        local = _load(path)
        if not isinstance(local, dict) or not isinstance(local.get(key), list):
            local = dict(remote)
            local[key] = []
        have = {r.get("id") for r in local[key] if isinstance(r, dict)}
        new = [r for r in rows if isinstance(r, dict) and r.get("id") and r["id"] not in have]
        if new:
            local[key].extend(new)
            if key == "attacks" and isinstance(remote.get("categories"), dict):
                cats = local.setdefault("categories", {})
                for k, v in remote["categories"].items():
                    cats.setdefault(k, v)
            _save(path, local)
        added[name] = len(new)
    return added


# --------------------------------------------------------------------------
# 2) kisisel senkron — ayar ve anahtar
# --------------------------------------------------------------------------
def _config_path():
    base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "AI-Security-Lab")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "sync.json")


def load_config():
    c = _load(_config_path(), {})
    return c if isinstance(c, dict) else {}


def save_config(cfg):
    _save(_config_path(), cfg)


def _gh_token():
    """Kurulu ve oturum acmis gh CLI varsa onun token'i (diske yazilmaz)."""
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                             timeout=5, creationflags=flags)
        tok = (out.stdout or "").strip()
        return tok or None
    except Exception:
        return None


def get_token():
    return (load_config().get("token") or "").strip() or _gh_token()


def find_gist(token, create=True, timeout=6):
    cfg = load_config()
    gid = cfg.get("gist_id")
    if gid:
        return gid
    for page in (1, 2, 3):
        rows = _http(API + "/gists?per_page=100&page=%d" % page, token=token, timeout=timeout)
        for g in rows:
            if g.get("description") == GIST_DESC:
                cfg["gist_id"] = g["id"]
                save_config(cfg)
                return g["id"]
        if len(rows) < 100:
            break
    if not create:
        return None
    blank = {"progress": {}, "notes": [], "updated": _now(), "device": "masaustu"}
    g = _http(API + "/gists", "POST", token, {
        "description": GIST_DESC, "public": False,
        "files": {SYNC_FILE: {"content": json.dumps(blank, ensure_ascii=False)},
                  REPORTS_FILE: {"content": "[]"}}}, timeout=timeout)
    cfg["gist_id"] = g["id"]
    save_config(cfg)
    return g["id"]


def _now():
    return datetime.now().isoformat(timespec="seconds")


def read_gist(token, gid, timeout=6):
    """Donen: (sync_dict, reports_list)"""
    g = _http(API + "/gists/" + gid, token=token, timeout=timeout)
    files = g.get("files") or {}

    def content(name, default):
        f = files.get(name)
        if not f:
            return default
        raw = f.get("content")
        if f.get("truncated") and f.get("raw_url"):
            req = urllib.request.Request(f["raw_url"], headers={"User-Agent": "AI-Security-Lab"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
        try:
            return json.loads(raw or "null") or default
        except ValueError:
            return default

    return content(SYNC_FILE, {}), content(REPORTS_FILE, [])


def write_gist(token, gid, sync=None, reports=None, timeout=8):
    files = {}
    if sync is not None:
        files[SYNC_FILE] = {"content": json.dumps(sync, ensure_ascii=False)}
    if reports is not None:
        files[REPORTS_FILE] = {"content": json.dumps(reports, ensure_ascii=False)}
    if files:
        _http(API + "/gists/" + gid, "PATCH", token, {"files": files}, timeout=timeout)


# --------------------------------------------------------------------------
# birlestirme
# --------------------------------------------------------------------------
def _to_common(p):
    p = dict(p or {})
    daily = p.get("daily") or {}
    plan = p.get("daily_plan") or {}
    per = dict(daily.get("per") or {})
    for k, v in (plan.get("per_area") or {}).items():
        per[k] = max(per.get(k, 0), v)
    return {
        "items": dict(p.get("items") or {}),
        "by_category": dict(p.get("by_category") or {}),
        "mastery": dict(p.get("mastery") or {}),
        "day": daily.get("day") or plan.get("day") or None,
        "per": per,
        "streak": p.get("streak", 0) or 0,
        "best_streak": p.get("best_streak", 0) or 0,
        "last_day": p.get("last_day"),
        "seen": p.get("seen", 0) or 0,
        "correct": p.get("correct", 0) or 0,
        "tools_tried": list(p.get("tools_tried") or []),
        "tool_drill": dict(p.get("tool_drill") or {}),
        "answered_today": p.get("answered_today", 0) or 0,
        "path": dict(p.get("path") or {}),
    }


def merge_progress(a, b):
    """Iki ilerleme kaydini (masaustu ya da telefon bicimi) kayipsiz birlestir."""
    A, B = _to_common(a), _to_common(b)
    out = {"items": {}, "by_category": {}, "mastery": {}}
    for key in set(A["items"]) | set(B["items"]):
        x, y = A["items"].get(key), B["items"].get(key)
        if not x or not y:
            out["items"][key] = x or y
            continue
        lx, ly = (x.get("last") or ""), (y.get("last") or "")
        if lx != ly:
            newer = x if lx > ly else y
        elif bool(x.get("last_result")) != bool(y.get("last_result")):
            newer = x if x.get("last_result") else y
        else:
            newer = x if x.get("box", 1) <= y.get("box", 1) else y
        out["items"][key] = {
            "n": max(x.get("n", 0), y.get("n", 0)),
            "ok": max(x.get("ok", 0), y.get("ok", 0)),
            "bad": max(x.get("bad", 0), y.get("bad", 0)),
            "elim": max(x.get("elim", 0), y.get("elim", 0)),
            "box": newer.get("box", 1),
            "last": newer.get("last"),
        }
        if newer.get("last_result"):
            out["items"][key]["last_result"] = newer["last_result"]
    for cat in set(A["by_category"]) | set(B["by_category"]):
        x = A["by_category"].get(cat) or {}
        y = B["by_category"].get(cat) or {}
        out["by_category"][cat] = {"seen": max(x.get("seen", 0), y.get("seen", 0)),
                                   "correct": max(x.get("correct", 0), y.get("correct", 0))}
    out["mastery"].update(B["mastery"])
    out["mastery"].update(A["mastery"])
    today = date.today().isoformat()
    per = {}
    for src in (A, B):
        if src["day"] == today:
            for k, v in src["per"].items():
                per[k] = max(per.get(k, 0), v)
    out["streak"] = max(A["streak"], B["streak"])
    out["best_streak"] = max(A["best_streak"], B["best_streak"], out["streak"])
    out["last_day"] = max([d for d in (A["last_day"], B["last_day"]) if d] or [None])
    out["seen"] = max(A["seen"], B["seen"])
    out["correct"] = max(A["correct"], B["correct"])
    out["tools_tried"] = sorted(set(A["tools_tried"]) | set(B["tools_tried"]))
    ta, tb = A["tool_drill"], B["tool_drill"]
    out["tool_drill"] = {"seen": max(ta.get("seen", 0), tb.get("seen", 0)),
                         "correct": max(ta.get("correct", 0), tb.get("correct", 0))}
    out["answered_today"] = (max(A["answered_today"], B["answered_today"])
                             if today in (A["day"], B["day"]) else 0)
    path = {"read": {}, "done": {}}
    for src in (B, A):
        for part in ("read", "done"):
            path[part].update((src["path"] or {}).get(part) or {})
    out["path"] = path
    out["_day"], out["_per"], out["_total"] = today, per, sum(per.values())
    return out


def to_desktop(m, base=None):
    d = dict(base or {})
    d.update({
        "seen": m["seen"], "correct": m["correct"], "by_category": m["by_category"],
        "streak": m["streak"], "best_streak": m["best_streak"], "last_day": m["last_day"],
        "answered_today": m["answered_today"], "mastery": m["mastery"],
        "tools_tried": m["tools_tried"], "tool_drill": m["tool_drill"], "items": m["items"],
        "daily_plan": {"day": m["_day"], "per_area": m["_per"], "total": m["_total"]},
    })
    return d


def to_store(m):
    """Gist'te tutulan bicim: telefon bicimi + masaustunun ek alanlari."""
    return {
        "items": m["items"], "by_category": m["by_category"], "mastery": m["mastery"],
        "daily": {"day": m["_day"], "per": m["_per"], "total": m["_total"]},
        "streak": m["streak"], "best_streak": m["best_streak"], "last_day": m["last_day"],
        "seen": m["seen"], "correct": m["correct"], "tools_tried": m["tools_tried"],
        "tool_drill": m["tool_drill"], "answered_today": m["answered_today"],
        "path": m["path"],
    }


def merge_notes(a, b):
    """Id'ye gore birlesim; cevabi olan kayit cevapsizi gecer."""
    by = {}
    order = []
    for src in (a or [], b or []):
        for n in src:
            if not isinstance(n, dict) or not n.get("id"):
                continue
            cur = by.get(n["id"])
            if cur is None:
                by[n["id"]] = dict(n)
                order.append(n["id"])
            elif (n.get("answer") or "").strip() and not (cur.get("answer") or "").strip():
                cur["answer"] = n["answer"]
                cur["answered_day"] = n.get("answered_day", "")
    rows = [by[i] for i in order]
    rows.sort(key=lambda n: (n.get("day", ""), n.get("time", "")))
    return rows


# --------------------------------------------------------------------------
# senkron islemleri
# --------------------------------------------------------------------------
_lock = threading.Lock()


def sync_personal(data_dir, write_local=True, reports=None, timeout=6):
    """Yerel <-> gist cift yonlu birlestirme.

    write_local=False: sadece gist'e yazar (uygulama acikken arka plan itmesi;
    yerel dosyalara dokunmaz, boylece ekrandaki durumla yarismaz).
    reports: verilirse gist'teki rapor listesi bununla birlestirilir.
    Donen: durum metni.
    """
    token = get_token()
    if not token:
        return "kapali"
    with _lock:
        gid = find_gist(token, timeout=timeout)
        remote, rreports = read_gist(token, gid, timeout=timeout)
        ppath = os.path.join(data_dir, "progress.json")
        npath = os.path.join(data_dir, "notes.json")
        local_p = _load(ppath, {}) or {}
        local_n = _load(npath, {}) or {}
        m = merge_progress(local_p, remote.get("progress") or {})
        notes = merge_notes(local_n.get("notes") or [], remote.get("notes") or [])
        if write_local:
            _save(ppath, to_desktop(m, local_p))
            nd = dict(local_n) if isinstance(local_n, dict) else {}
            nd.setdefault("schema_version", 1)
            nd["notes"] = notes
            _save(npath, nd)
        new_reports = None
        if reports is not None:
            byday = {r.get("day"): r for r in (rreports or []) if isinstance(r, dict)}
            for r in reports:
                if isinstance(r, dict) and r.get("day"):
                    byday[r["day"]] = r
            new_reports = sorted(byday.values(), key=lambda r: r.get("day", ""),
                                 reverse=True)[:30]
        write_gist(token, gid, {"progress": to_store(m), "notes": notes,
                                "updated": _now(), "device": "masaustu"},
                   new_reports, timeout=timeout + 2)
        return "tamam: %d soru kaydi, %d not" % (len(m["items"]), len(notes))


class Pusher:
    """Uygulama acikken kayitlardan birkac saniye sonra gist'e iter (arka plan)."""

    def __init__(self, data_dir, delay=4.0):
        self.data_dir, self.delay = data_dir, delay
        self._timer = None
        self.last = ""

    def schedule(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.delay, self._run)
        self._timer.daemon = True
        self._timer.start()

    def _run(self):
        try:
            self.last = sync_personal(self.data_dir, write_local=False)
        except Exception as e:
            self.last = "hata: %s" % e

    def flush(self, timeout=6):
        if self._timer:
            self._timer.cancel()
            self._timer = None
            try:
                sync_personal(self.data_dir, write_local=False, timeout=timeout)
            except Exception:
                pass
