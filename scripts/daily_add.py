# -*- coding: utf-8 -*-
"""
daily_add.py - Gunluk gorevin AI Security Lab'e icerik yazma koprusu.

Neden var: attackdb.data_dir() frozen degilken PROJE klasorunu baz alir,
ama kullanicinin calistirdigi exe C:\\Users\\albuz\\Desktop\\⚡ Programlar\\data'yi okur.
Bu script iki tarafi da acikca yonetir:

    CANLI (exe bunu okur) : C:\\Users\\albuz\\Desktop\\⚡ Programlar\\data\\
    TOHUM (exe derlemesi) : <proje>\\data\\

Her yazma once CANLI dosyaya uygulanir, sonra TOHUM'a kopyalanir.
Boylece kullanicinin ilerlemesi/gecmisi kaybolmaz, exe yeniden derlemek
gerekmez.

Kullanim:
    python scripts/daily_add.py status
    python scripts/daily_add.py questions yeni_sorular.json
    python scripts/daily_add.py scenarios yeni_senaryolar.json
    python scripts/daily_add.py report rapor.txt --title "20 Eylul Raporu"
"""

import os
import sys
import json
import shutil
import argparse
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import attackdb    # noqa: E402
import quizgen     # noqa: E402

LIVE_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "⚡ Programlar", "data")
SEED_DIR = os.path.join(ROOT, "data")


def _paths(name):
    return os.path.join(LIVE_DIR, name), os.path.join(SEED_DIR, name)


def _load(name, empty):
    """Once CANLI, yoksa TOHUM, o da yoksa bos yapi."""
    live, seed = _paths(name)
    for path in (live, seed):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                if isinstance(db, dict):
                    return db
            except (OSError, ValueError):
                continue
    return dict(empty)


def _write_both(name, db, seed=True):
    live, seed_path = _paths(name)
    os.makedirs(LIVE_DIR, exist_ok=True)
    tmp = live + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, live)
    if seed:
        os.makedirs(SEED_DIR, exist_ok=True)
        shutil.copyfile(live, seed_path)
        return live, seed_path
    return live, None


def _read_items(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1:] if nl != -1 else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    data = json.loads(s)
    if isinstance(data, dict):
        for key in ("questions", "scenarios", "items", "sorular", "senaryolar"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    if isinstance(data, list):
        return data
    raise ValueError("beklenmeyen JSON yapisi")


# --------------------------------------------------------------------------
def cmd_status(_args):
    """Gunluk gorevin analiz icin okudugu durum raporu (CANLI veriden)."""
    attacks = _load("attacks.json", {"attacks": []})
    tools = _load("tools.json", {"tools": []})
    qdb = _load("questions.json", {"schema_version": 1, "questions": []})
    sdb = _load("scenarios.json", {"schema_version": 1, "scenarios": []})
    prog = _load("progress.json", {})

    specs = quizgen.build_specs(attacks, tools, qdb)
    rows, done, goal = quizgen.plan_status(prog)

    print("== KUTUPHANE ==")
    print("teknik: %d   arac: %d   elle soru: %d   senaryo: %d   havuz: %d"
          % (len(attacks.get("attacks", [])), len(tools.get("tools", [])),
             len(qdb.get("questions", [])), len(sdb.get("scenarios", [])),
             len(specs)))

    print("\n== KULLANICININ DURUMU ==")
    print("bugun cozulen: %d / %d" % (done, goal))
    print("seri: %d gun   ·   toplam cevap: %d   ·   dogru: %d"
          % (prog.get("streak", 0), prog.get("seen", 0), prog.get("correct", 0)))
    print("alan alan bugun: " +
          "  ".join("%s %d/%d" % (r[0], r[1], r[2]) for r in rows))

    print("\n== ZAYIF ALANLAR (buraya soru yaz) ==")
    weak = quizgen.weak_areas(prog, 5)
    for area in weak:
        rec = (prog.get("by_category") or {}).get(area, {})
        seen = rec.get("seen", 0)
        acc = (rec.get("correct", 0) / seen * 100) if seen else None
        print("  %s  %s  (%d soru gorulmus)"
              % (area, ("%%%.0f dogru" % acc) if acc is not None else "hic calisilmamis",
                 seen))

    items = prog.get("items", {}) or {}
    missed = []
    for key, rec in items.items():
        score = rec.get("bad", 0) * 2 + rec.get("elim", 0)
        if score:
            missed.append((score, key, rec))
    missed.sort(reverse=True)
    if missed:
        print("\n== EN COK TAKILDIGI SORULAR (yanlis*2 + eleyerek) ==")
        by_id = {a.get("id"): a for a in attacks.get("attacks", [])}
        for score, key, rec in missed[:15]:
            src = key.split("|")[0]
            name = (by_id.get(src) or {}).get("technique", src)
            print("  %-22s %-28s yanlis=%d eleyerek=%d"
                  % (src, name[:28], rec.get("bad", 0), rec.get("elim", 0)))

    notes = _load("notes.json", {"schema_version": 1, "notes": []})
    openn = [n for n in notes.get("notes", []) if not (n.get("answer") or "").strip()]
    print("\n== CEVAP BEKLEYEN NOTLAR (%d) — KULLANICI SINAVDA YAZDI, ACIKLA ==" % len(openn))
    for n in openn[:25]:
        print("  [%s] %s · %s · %s" % (n.get("id"), n.get("day"), n.get("area") or "-",
                                       n.get("technique") or "genel"))
        print("      NOT  : %s" % " ".join((n.get("text") or "").split())[:220])
        if n.get("question"):
            print("      SORU : %s" % " ".join(n["question"].split())[:160])
    if not openn:
        print("  (yok)")

    recent = quizgen.recent_entries(attacks, 7)
    print("\n== SON 7 GUNDE EKLENEN TEKNIKLER (%d) ==" % len(recent))
    for a in recent[:12]:
        print("  %s  %s  (%s)" % (a.get("id"), a.get("technique"), a.get("added")))

    print("\n== ZATEN YAZILMIS SORULAR (TEKRAR ETME, %d adet) =="
          % len(qdb.get("questions", [])))
    for q in qdb.get("questions", [])[-60:]:
        print("  [%s] %s" % (q.get("area", ""), " ".join(q.get("prompt", "").split())[:105]))

    print("\n== ZATEN YAZILMIS SENARYOLAR (TEKRAR ETME) ==")
    for s in sdb.get("scenarios", [])[-30:]:
        print("  [%s] %s (%s)" % (s.get("area", ""), s.get("title", ""), s.get("day", "")))
    return 0


def cmd_questions(args):
    qdb = _load("questions.json", {"schema_version": 1, "questions": []})
    qdb.setdefault("schema_version", 1)
    qdb.setdefault("questions", [])
    before = len(qdb["questions"])
    items = _read_items(args.file)
    added, dupes, errors = quizgen.import_questions(qdb, items)
    print("girdi: %d   eklenen: %d   mukerrer: %d   hatali: %d"
          % (len(items), added, dupes, len(errors)))
    for i, msg in errors:
        print("  ! #%d -> %s" % (i, msg))
    per_area = {}
    for q in qdb["questions"][before:]:
        per_area[q["area"]] = per_area.get(q["area"], 0) + 1
    if per_area:
        print("alan dagilimi: " + "  ".join("%s=%d" % kv for kv in sorted(per_area.items())))
    if added and not args.dry_run:
        live, seed = _write_both("questions.json", qdb)
        print("yazildi: %s\nkopya  : %s" % (live, seed))
        print("toplam elle soru: %d" % len(qdb["questions"]))
    elif args.dry_run:
        print("[dry-run] yazilmadi")
    return 0 if added or not items else 1


def cmd_scenarios(args):
    sdb = _load("scenarios.json", {"schema_version": 1, "scenarios": []})
    sdb.setdefault("schema_version", 1)
    sdb.setdefault("scenarios", [])
    items = _read_items(args.file)
    added, dupes, errors = quizgen.import_scenarios(sdb, items)
    print("girdi: %d   eklenen: %d   mukerrer: %d   hatali: %d"
          % (len(items), added, dupes, len(errors)))
    for i, msg in errors:
        print("  ! #%d -> %s" % (i, msg))
    if added and not args.dry_run:
        live, seed = _write_both("scenarios.json", sdb)
        print("yazildi: %s\nkopya  : %s" % (live, seed))
        print("toplam senaryo: %d" % len(sdb["scenarios"]))
    elif args.dry_run:
        print("[dry-run] yazilmadi")
    return 0 if added or not items else 1


def cmd_report(args):
    rdb = _load("reports.json", {"schema_version": 1, "reports": []})
    rdb.setdefault("schema_version", 1)
    rdb.setdefault("reports", [])
    with open(args.file, "r", encoding="utf-8") as f:
        body = f.read().strip()
    if not body:
        print("rapor bos, yazilmadi")
        return 1
    day = args.day or date.today().isoformat()
    title = args.title or ("%s — Günlük Rapor" % day)
    rdb["reports"] = [r for r in rdb["reports"] if r.get("day") != day]
    rdb["reports"].append({"day": day, "title": title, "body": body,
                           "stats": {}, "written": day})
    rdb["reports"].sort(key=lambda r: r.get("day", ""), reverse=True)
    rdb["reports"] = rdb["reports"][:60]
    if args.dry_run:
        print("[dry-run] yazilmadi")
        return 0
    live, seed = _write_both("reports.json", rdb)
    print("rapor yazildi: %s (%s)\nkopya: %s" % (live, day, seed))
    return 0


def cmd_notes_answer(args):
    """Notlara aciklama yaz. Girdi: [{"id":"N-0001","answer":"..."}]"""
    ndb = _load("notes.json", {"schema_version": 1, "notes": []})
    ndb.setdefault("notes", [])
    items = _read_items(args.file)
    today = date.today().isoformat()
    done, missing = 0, []
    for raw in items:
        nid = str((raw or {}).get("id", "")).strip()
        ans = str((raw or {}).get("answer", "")).strip()
        if not nid or not ans:
            continue
        hit = False
        for n in ndb["notes"]:
            if n.get("id") == nid:
                n["answer"] = ans
                n["answered_day"] = today
                hit = True
                done += 1
                break
        if not hit:
            missing.append(nid)
    print("girdi: %d   aciklanan: %d   bulunamayan: %s"
          % (len(items), done, ", ".join(missing) or "-"))
    if done and not args.dry_run:
        live, _ = _write_both("notes.json", ndb, seed=False)
        print("yazildi: %s" % live)
        kalan = len([n for n in ndb["notes"] if not (n.get("answer") or "").strip()])
        print("cevap bekleyen kalan not: %d" % kalan)
    return 0


def cmd_notes_import(args):
    """Telefondan gelen notlari birlestir. Girdi: not nesneleri listesi."""
    ndb = _load("notes.json", {"schema_version": 1, "notes": []})
    ndb.setdefault("notes", [])
    have = {n.get("id") for n in ndb["notes"]}
    items = _read_items(args.file)
    added = 0
    for raw in items:
        if not isinstance(raw, dict) or not (raw.get("text") or "").strip():
            continue
        nid = raw.get("id") or ""
        if nid and nid in have:
            continue
        if not nid:
            nid = "NP-%04d" % (len(ndb["notes"]) + added + 1)
        rec = dict(raw)
        rec["id"] = nid
        rec.setdefault("day", date.today().isoformat())
        rec.setdefault("source", "cep")
        rec.setdefault("answer", "")
        ndb["notes"].append(rec)
        have.add(nid)
        added += 1
    print("telefon notu: %d girdi, %d yeni" % (len(items), added))
    if added and not args.dry_run:
        live, _ = _write_both("notes.json", ndb, seed=False)
        print("yazildi: %s" % live)
    return 0


def main():
    ap = argparse.ArgumentParser(description="AI Security Lab gunluk icerik koprusu")
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    p = sub.add_parser("questions"); p.add_argument("file")
    p = sub.add_parser("scenarios"); p.add_argument("file")
    p = sub.add_parser("notes-answer"); p.add_argument("file")
    p = sub.add_parser("notes-import"); p.add_argument("file")
    p = sub.add_parser("report")
    p.add_argument("file")
    p.add_argument("--title", default=None)
    p.add_argument("--day", default=None)
    args = ap.parse_args()
    fn = {"status": cmd_status, "questions": cmd_questions,
          "scenarios": cmd_scenarios, "report": cmd_report,
          "notes-answer": cmd_notes_answer,
          "notes-import": cmd_notes_import}.get(args.cmd)
    if not fn:
        ap.print_help()
        return 2
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
