# -*- coding: utf-8 -*-
"""
build_mobile.py - Cep surumunun tek dosyalik HTML'ini uretir.

Masaustundeki CANLI veriyi (C:\\Users\\albuz\\Desktop\\⚡ Programlar\\data) app.html sablonuna
gomer ve mobile/dist/index.html olarak yazar. Artifact olarak bu dosya yayinlanir.

    python mobile/build_mobile.py

Gunluk/haftalik gorev kutuphaneyi buyuttukten sonra bunu calistirip artifact'i
yeniden yayimlayabilir; gunluk SORU ve SENARYOlar ise artifact veritabanina
yazildigi icin yeniden yayim GEREKTIRMEZ.
"""

import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(os.path.expanduser("~"), "Desktop", "⚡ Programlar", "data")
SEED = os.path.join(ROOT, "data")
TEMPLATE = os.path.join(ROOT, "mobile", "app.html")
OUT_DIR = os.path.join(ROOT, "mobile", "dist")
OUT = os.path.join(OUT_DIR, "index.html")

# Cep surumune gidecek alanlar (sayfayi sismanlatmamak icin secili)
ATTACK_FIELDS = ("id", "category", "technique", "story", "example", "why",
                 "how_to_use", "mitigation", "real_case", "source", "level",
                 "status", "year")
TOOL_FIELDS = ("id", "name", "vendor", "type", "areas", "what", "how_to_use",
               "install", "source")


def load(name, key, fallback_key=None):
    for base in (LIVE, SEED):
        path = os.path.join(base, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                db = json.load(f)
        except (OSError, ValueError) as exc:
            print("  ! %s okunamadi: %s" % (path, exc))
            continue
        if isinstance(db, dict):
            return db, db.get(key) or db.get(fallback_key or key) or []
        if isinstance(db, list):
            return {}, db
    return {}, []


def slim(rows, fields):
    return [{k: r.get(k) for k in fields if r.get(k) not in (None, "")} for r in rows]


def main():
    adb, attacks = load("attacks.json", "attacks")
    _, tools = load("tools.json", "tools")
    _, practice = load("practice.json", "targets")
    _, questions = load("questions.json", "questions")
    _, scenarios = load("scenarios.json", "scenarios")
    _, pathmods = load("path.json", "modules")

    cats = adb.get("categories") or {}
    if not cats:
        print("HATA: attacks.json icinde categories yok.")
        return 2

    seed = {
        "built": __import__("datetime").date.today().isoformat(),
        "categories": cats,
        "attacks": slim(attacks, ATTACK_FIELDS),
        "tools": slim(tools, TOOL_FIELDS),
        "practice": practice,
        "questions": questions,
        "scenarios": scenarios,
        "path": pathmods,
    }
    payload = json.dumps(seed, ensure_ascii=False, separators=(",", ":"))
    # </script> dizisi JSON icinde gecerse sayfayi kirar
    payload = payload.replace("</", "<\\/")

    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()
    if "__SEED_DATA__" not in html:
        print("HATA: sablonda __SEED_DATA__ yer tutucusu yok.")
        return 2
    html = html.replace("__SEED_DATA__", payload)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    kb = os.path.getsize(OUT) / 1024.0
    print("YAZILDI : %s  (%.0f KB)" % (OUT, kb))
    print("ICERIK  : %d teknik · %d arac · %d pratik hedefi · %d elle soru · %d senaryo · %d modul"
          % (len(seed["attacks"]), len(seed["tools"]), len(seed["practice"]),
             len(seed["questions"]), len(seed["scenarios"]), len(seed["path"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
