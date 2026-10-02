# -*- coding: utf-8 -*-
"""
publish_content.py - Ortak icerigi herkese acik GitHub deposuna gonderir.

Depo: https://github.com/demirataalbuz-maker/ai-security-lab-icerik
  data/attacks.json, tools.json, questions.json, scenarios.json  -> exe'ler buradan yeni icerik ceker
  index.html                                                      -> telefon surumu (GitHub Pages)

SADECE icerik gider. progress.json, notes.json, reports.json (kisisel) ASLA gitmez;
onlar kullanicinin gizli gist'inde durur (bkz. cloudsync.py).

    python scripts\\publish_content.py            # derle + commit + push
    python scripts\\publish_content.py --dry-run  # sadece neyin degisecegini goster
"""

import os
import sys
import json
import shutil
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(os.path.expanduser("~"), "Desktop", "⚡ Programlar", "data")
SITE = os.path.join(os.path.dirname(ROOT), "ai-security-lab-site")
CONTENT = ("attacks.json", "tools.json", "questions.json", "scenarios.json")
PRIVATE = ("progress.json", "notes.json", "reports.json")


def git(*args, check=True):
    r = subprocess.run(["git", "-C", SITE] + list(args), capture_output=True,
                       text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise SystemExit("git %s hatasi:\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    if not os.path.isdir(os.path.join(SITE, ".git")):
        raise SystemExit("depo klonu yok: %s" % SITE)

    os.makedirs(os.path.join(SITE, "data"), exist_ok=True)
    counts = {}
    for name in CONTENT:
        src = os.path.join(LIVE, name)
        with open(src, "r", encoding="utf-8") as f:
            db = json.load(f)                         # bozuk JSON'u asla yayinlama
        rows = next((v for v in db.values() if isinstance(v, list)), [])
        counts[name] = len(rows)
        shutil.copyfile(src, os.path.join(SITE, "data", name))

    r = subprocess.run([sys.executable, os.path.join(ROOT, "mobile", "build_mobile.py")],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("telefon sayfasi derlenemedi:\n" + r.stdout + r.stderr)
    shutil.copyfile(os.path.join(ROOT, "mobile", "dist", "index.html"),
                    os.path.join(SITE, "index.html"))
    shutil.copyfile(os.path.join(ROOT, "mobile", "apple-touch-icon.png"),
                    os.path.join(SITE, "apple-touch-icon.png"))

    for name in PRIVATE:                              # emniyet kilidi
        for p in (os.path.join(SITE, name), os.path.join(SITE, "data", name)):
            if os.path.exists(p):
                raise SystemExit("KISISEL DOSYA DEPODA: %s — yayin durduruldu" % p)

    git("add", "-A")
    status = git("status", "--porcelain")
    print("icerik: " + "  ".join("%s=%d" % (k.split(".")[0], v) for k, v in counts.items()))
    if not status:
        print("degisiklik yok — gonderilmedi")
        return 0
    print(status)
    if args.dry_run:
        git("reset", "-q")
        print("[dry-run] gonderilmedi")
        return 0
    msg = args.message or ("Gunluk icerik: %d soru, %d senaryo"
                           % (counts["questions.json"], counts["scenarios.json"]))
    msg += "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    git("commit", "-q", "-m", msg)
    git("push", "-q", "origin", "HEAD:main")
    print("gonderildi: https://github.com/demirataalbuz-maker/ai-security-lab-icerik")
    return 0


if __name__ == "__main__":
    sys.exit(main())
