# -*- coding: utf-8 -*-
"""
cloud_sync.py - Gunluk gorev icin kisisel gist senkronu (gh CLI oturumuyla).

    python scripts\\cloud_sync.py pull     # gist -> masaustu (ilerleme + telefonda yazilan notlar)
    python scripts\\cloud_sync.py push     # masaustu -> gist (not cevaplari + son raporlar dahil)

Iki komut da cift yonlu ve kayipsiz birlestirir; fark: push, reports.json'daki
son raporlari da gist'e yazar ki telefonun Rapor sekmesi gorsun.
"""

import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cloudsync  # noqa: E402

LIVE = os.path.join(os.path.expanduser("~"), "Desktop", "⚡ Programlar", "data")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("pull", "push"):
        print(__doc__)
        return 2
    reports = None
    if cmd == "push":
        try:
            with open(os.path.join(LIVE, "reports.json"), "r", encoding="utf-8") as f:
                reports = (json.load(f) or {}).get("reports") or []
        except (OSError, ValueError):
            reports = []
        reports = sorted(reports, key=lambda r: r.get("day", ""), reverse=True)[:30]
    res = cloudsync.sync_personal(LIVE, write_local=True, reports=reports, timeout=10)
    if res == "kapali":
        print("HATA: gist anahtari yok (gh auth status kontrol et)")
        return 1
    notes = json.load(open(os.path.join(LIVE, "notes.json"), encoding="utf-8")).get("notes", [])
    openn = [n for n in notes if not (n.get("answer") or "").strip()]
    print(res)
    print("cevap bekleyen not: %d%s" % (len(openn), ("  (rapor: %d gun gonderildi)" % len(reports))
                                          if reports is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
