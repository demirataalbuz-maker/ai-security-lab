# -*- coding: utf-8 -*-
"""
sync_mobile.py - Cep surumu ile masaustu ilerlemesini birlestirir.

Cep surumu (Artifact) ilerlemeyi kendi veritabaninda `state/progress`
dokumaninda tutar; masaustu uygulamasi `Desktop\\⚡ Programlar\\data\\progress.json`
dosyasinda. Bu script ikisini BIRLESTIRIR (kayip yok, sayaclarda maksimum,
kutu/tarih daha yeni olandan).

Akis (gunluk gorev bunu yapar):
  1. ArtifactData ile `state/progress` okunur, bir dosyaya yazilir.
  2. python scripts/sync_mobile.py merge <o_dosya> --out merged.json
     -> Desktop\\⚡ Programlar\\data\\progress.json guncellenir, merged.json cep bicimiyle yazilir.
  3. ArtifactData ile merged.json icerigi `state/progress` dokumanina yazilir.

Telefon bicimi : {items, by_category, mastery, daily:{day,per,total}, ...}
Masaustu bicimi: {items, by_category, mastery, daily_plan:{day,per_area,total}, ...}
"""

import os
import sys
import json
import argparse
from datetime import date

LIVE = os.path.join(os.path.expanduser("~"), "Desktop", "⚡ Programlar", "data")
DESK_PATH = os.path.join(LIVE, "progress.json")


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _unwrap(doc):
    """ArtifactData'dan gelen dokuman {data:{...}} sarmalinda olabilir."""
    if not isinstance(doc, dict):
        return {}
    if isinstance(doc.get("data"), dict):
        return doc["data"]
    if isinstance(doc.get("fields"), dict):          # bazi ciktilar
        return _unwrap(doc["fields"])
    return doc


def _to_common(p):
    """Her iki bicimi ortak bir yapiya cevir."""
    p = dict(p or {})
    daily = p.get("daily") or {}
    plan = p.get("daily_plan") or {}
    per = dict(daily.get("per") or {})
    for k, v in (plan.get("per_area") or {}).items():
        per[k] = max(per.get(k, 0), v)
    day = daily.get("day") or plan.get("day") or None
    return {
        "items": dict(p.get("items") or {}),
        "by_category": dict(p.get("by_category") or {}),
        "mastery": dict(p.get("mastery") or {}),
        "day": day,
        "per": per,
        "streak": p.get("streak", 0) or 0,
        "best_streak": p.get("best_streak", 0) or 0,
        "last_day": p.get("last_day"),
        "seen": p.get("seen", 0) or 0,
        "correct": p.get("correct", 0) or 0,
        "tools_tried": list(p.get("tools_tried") or []),
        "tool_drill": dict(p.get("tool_drill") or {}),
        "answered_today": p.get("answered_today", 0) or 0,
    }


def merge(a, b):
    """Iki ilerleme kaydini birlestir (kayipsiz, monoton)."""
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
            newer = x if x.get("last_result") else y      # sonucu bilinen kayıt
        else:
            newer = x if x.get("box", 1) <= y.get("box", 1) else y   # temkinli olan
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
        out["by_category"][cat] = {
            "seen": max(x.get("seen", 0), y.get("seen", 0)),
            "correct": max(x.get("correct", 0), y.get("correct", 0)),
        }

    out["mastery"].update(B["mastery"])
    out["mastery"].update(A["mastery"])

    today = date.today().isoformat()
    per = {}
    for src in (A, B):
        if src["day"] != today:
            continue
        for k, v in src["per"].items():
            per[k] = max(per.get(k, 0), v)
    total = sum(per.values())

    out["streak"] = max(A["streak"], B["streak"])
    out["best_streak"] = max(A["best_streak"], B["best_streak"], out["streak"])
    out["last_day"] = max([d for d in (A["last_day"], B["last_day"]) if d] or [None])
    out["seen"] = max(A["seen"], B["seen"])
    out["correct"] = max(A["correct"], B["correct"])
    out["tools_tried"] = sorted(set(A["tools_tried"]) | set(B["tools_tried"]))
    td_a, td_b = A["tool_drill"], B["tool_drill"]
    out["tool_drill"] = {"seen": max(td_a.get("seen", 0), td_b.get("seen", 0)),
                         "correct": max(td_a.get("correct", 0), td_b.get("correct", 0))}
    out["answered_today"] = max(A["answered_today"], B["answered_today"]) \
        if (A["day"] == today or B["day"] == today) else 0
    out["_day"] = today
    out["_per"] = per
    out["_total"] = total
    return out


def to_desktop(m):
    return {
        "seen": m["seen"], "correct": m["correct"],
        "by_category": m["by_category"], "streak": m["streak"],
        "best_streak": m["best_streak"], "last_day": m["last_day"],
        "answered_today": m["answered_today"], "mastery": m["mastery"],
        "tools_tried": m["tools_tried"], "tool_drill": m["tool_drill"],
        "items": m["items"],
        "daily_plan": {"day": m["_day"], "per_area": m["_per"], "total": m["_total"]},
    }


def to_phone(m):
    return {
        "items": m["items"], "by_category": m["by_category"], "mastery": m["mastery"],
        "daily": {"day": m["_day"], "per": m["_per"], "total": m["_total"]},
        "streak": m["streak"], "best_streak": m["best_streak"],
        "last_day": m["last_day"], "seen": m["seen"], "correct": m["correct"],
    }


def cmd_merge(args):
    desk = _load(DESK_PATH)
    phone = _unwrap(_load(args.phone)) if args.phone else {}
    if not phone:
        print("UYARI: telefon ilerlemesi bos/okunamadi -> sadece masaustu korunuyor")
    m = merge(desk, phone)

    d_items = len(desk.get("items") or {})
    p_items = len(phone.get("items") or {})
    print("masaustu: %d soru kaydi   telefon: %d   birlesmis: %d"
          % (d_items, p_items, len(m["items"])))
    print("bugun: %d soru   ·   seri: %d   ·   toplam cevap: %d"
          % (m["_total"], m["streak"], m["seen"]))

    if args.dry_run:
        print("[dry-run] yazilmadi")
        return 0

    desk_out = to_desktop(m)
    tmp = DESK_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(desk_out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DESK_PATH)
    print("yazildi: %s" % DESK_PATH)

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.phone or ".")),
                                   "merged_progress.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(to_phone(m), f, ensure_ascii=False, indent=2)
    print("cep bicimi: %s  (bunu state/progress dokumaninin 'data' alanina yaz)" % out)
    return 0


def cmd_export(args):
    """Masaustu ilerlemesini cep bicimiyle disari yaz (ilk kurulum icin)."""
    m = merge(_load(DESK_PATH), {})
    out = args.out or "desktop_progress_phone_format.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(to_phone(m), f, ensure_ascii=False, indent=2)
    print("yazildi: %s  (%d soru kaydi)" % (out, len(m["items"])))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Cep ↔ masaustu ilerleme senkronu")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("merge", help="telefon ilerlemesini masaustuyle birlestir")
    p.add_argument("phone", nargs="?", help="ArtifactData'dan alinan state/progress JSON dosyasi")
    p.add_argument("--out", default=None)
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("export", help="masaustu ilerlemesini cep bicimine cevir")
    p.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.cmd == "merge":
        return cmd_merge(args)
    if args.cmd == "export":
        return cmd_export(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
