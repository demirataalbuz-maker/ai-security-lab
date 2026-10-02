# -*- coding: utf-8 -*-
"""
quizgen.py - AI Security Lab sinav motoru.

Amac: soru havuzunu ELLE yazmadan uretmek. Kutuphanedeki her teknikten
(attacks.json) ve her aractan (tools.json) birden fazla soru KALIBI turer;
kutuphane buyudukce soru havuzu kendiliginden buyur.

Ayrica gunluk gorevin yazdigi ELLE hazirlanmis sorular (data/questions.json)
ayni havuza karisir; onlarin kalibi "hand"dir.

Tasarim kararlari:
  * Sorular 4 siklidir; CELDIRICILER ONCELIKLE AYNI KATTAN secilir ki
    "digerlerini biliyordum, eleyerek buldum" kolay olmasin.
  * Dogru cevaptan sonra kullaniciya "Emindim / Eleyerek buldum" sorulur.
    'Eleyerek' isaretlenen soru bilinmis SAYILMAZ; kutusu sifirlanir ve
    yakinda tekrar gelir.
  * Tekrar araligi Leitner kutulariyla: 1->ayni gun, 2->1 gun, 3->3 gun,
    4->7 gun, 5->16 gun.
  * Gunluk plan: her alandan (10 kat + ARAC) hedef kadar soru.

Soru sozlugu:
  {"key","tmpl","area","prompt","context","options"[4],"answer",
   "entry"(varsa teknik kaydi),"tool"(varsa arac kaydi)}
"""

import os
import json
import random
from datetime import date, datetime, timedelta

import attackdb

TOOL_AREA = "TOOLS"          # 11. alan: cephanelik
AREA_NAMES = dict(attackdb.CATEGORIES)
AREA_NAMES[TOOL_AREA] = "Cephanelik (araclar)"

DEFAULT_GOAL = 20            # alan basina gunluk hedef

# Leitner kutulari -> tekrar araligi (gun)
# En kısa aralık 1 GÜN: yanlış yapılan soru aynı gün geri gelirse cevap
# kısa süreli hafızadan "hatırlanır", öğrenilmiş sayılmaz (kullanıcının
# 2026-09-21'de yakaladığı hata: yanlış → aynı gün tekrar → hatırladı → kutu yükseldi).
BOX_DAYS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16}
MAX_BOX = 5

# Birbirinin cevabını veren "ayna" kalıplar: biri yanlışsa öteki de aynı
# ilişkiyi soruyor demektir, geri dönüşte ikisi de kullanılmaz.
MIRROR = {
    "mitig2tech": "tech2mitig", "tech2mitig": "mitig2tech",
    "code2name": "name2code", "name2code": "code2name",
    "func2tool": "tool2func", "tool2func": "func2tool",
    "story2cat": "tech2cat", "tech2cat": "story2cat",
}
DAY_CAP_PER_SRC = 2     # ince katlar için bile bir teknik günde en fazla 2 kez

TOOL_TYPE_LABEL = {
    "offense": "Saldiri araci",
    "defense": "Savunma araci",
    "both": "Hem saldiri hem savunma",
    "framework": "Cerceve / bilgi kaynagi",
}


# --------------------------------------------------------------------------
# Elle yazilan soru bankasi (gunluk gorev buraya yazar)
# --------------------------------------------------------------------------
def questions_path():
    return os.path.join(attackdb.data_dir(), "questions.json")


def _questions_seed_path():
    return os.path.join(attackdb._resource_dir(), "data", "questions.json")


def load_questions():
    """data/questions.json -> {"schema_version":1,"questions":[...]}"""
    path = questions_path()
    if not os.path.exists(path):
        seed = _questions_seed_path()
        if os.path.exists(seed) and os.path.abspath(seed) != os.path.abspath(path):
            try:
                with open(seed, "r", encoding="utf-8") as f:
                    db = json.load(f)
                save_questions(db)
                return db
            except (OSError, ValueError):
                pass
        return {"schema_version": 1, "questions": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "questions": []}
    if not isinstance(db, dict) or not isinstance(db.get("questions"), list):
        return {"schema_version": 1, "questions": []}
    return db


def save_questions(db):
    path = questions_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clean_question(raw, idx=0):
    """Elle yazilmis soruyu dogrula. (ok, soru_or_hata)"""
    if not isinstance(raw, dict):
        return False, "kayit nesne degil"
    prompt = (raw.get("prompt") or raw.get("soru") or "").strip()
    if not prompt:
        return False, "prompt bos"
    opts = raw.get("options") or raw.get("siklar") or []
    if not isinstance(opts, list) or len(opts) < 3:
        return False, "options en az 3 sik olmali"
    opts = [str(o).strip() for o in opts if str(o).strip()]
    if len(set(opts)) != len(opts):
        return False, "siklar birbirinin ayni"
    ans = raw.get("answer", raw.get("cevap"))
    if isinstance(ans, str):
        ans = ans.strip()
        if ans.upper() in ("A", "B", "C", "D", "E"):
            ans = "ABCDE".index(ans.upper())
        elif ans in opts:
            ans = opts.index(ans)
    try:
        ans = int(ans)
    except (TypeError, ValueError):
        return False, "answer gecersiz (0-tabanli indeks bekleniyor)"
    if not (0 <= ans < len(opts)):
        return False, "answer sik araliginin disinda"
    area = attackdb._norm_category(raw.get("area") or raw.get("category") or "")
    if area is None:
        area = TOOL_AREA if str(raw.get("area", "")).upper() == TOOL_AREA else None
    if area is None:
        return False, "area gecersiz (LLM01-LLM10 veya TOOLS)"
    qid = (raw.get("id") or "").strip()
    return True, {
        "id": qid,
        "area": area,
        "prompt": prompt,
        "context": (raw.get("context") or raw.get("senaryo") or "").strip(),
        "options": opts,
        "answer": ans,
        "explain": (raw.get("explain") or raw.get("aciklama") or "").strip(),
        "source_id": (raw.get("source_id") or raw.get("attack_id") or "").strip(),
        "source": (raw.get("source") or raw.get("kaynak") or "").strip(),
        "added": (raw.get("added") or date.today().isoformat()),
        "author": (raw.get("author") or "daily"),
    }


def import_questions(qdb, items):
    """Liste halinde elle yazilmis sorulari bankaya ekle.

    Donen: (added, dupes, errors)
    """
    seen = set()
    top = 0
    for q in qdb["questions"]:
        seen.add(" ".join((q.get("prompt") or "").lower().split()))
        try:
            top = max(top, int(str(q.get("id", "Q-0")).split("-")[-1]))
        except ValueError:
            pass
    added, dupes, errors = 0, 0, []
    for i, raw in enumerate(items):
        ok, res = clean_question(raw, i)
        if not ok:
            errors.append((i, res))
            continue
        norm = " ".join(res["prompt"].lower().split())
        if norm in seen:
            dupes += 1
            continue
        top += 1
        res["id"] = res["id"] or ("Q-%04d" % top)
        qdb["questions"].append(res)
        seen.add(norm)
        added += 1
    return added, dupes, errors


# --------------------------------------------------------------------------
# Senaryolar (gunluk gorev yazar, "Senaryolar" ekrani gosterir)
# --------------------------------------------------------------------------
def scenarios_path():
    return os.path.join(attackdb.data_dir(), "scenarios.json")


def _scenarios_seed_path():
    return os.path.join(attackdb._resource_dir(), "data", "scenarios.json")


def load_scenarios():
    path = scenarios_path()
    if not os.path.exists(path):
        seed = _scenarios_seed_path()
        if os.path.exists(seed) and os.path.abspath(seed) != os.path.abspath(path):
            try:
                with open(seed, "r", encoding="utf-8") as f:
                    db = json.load(f)
                save_scenarios(db)
                return db
            except (OSError, ValueError):
                pass
        return {"schema_version": 1, "scenarios": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "scenarios": []}
    if not isinstance(db, dict) or not isinstance(db.get("scenarios"), list):
        return {"schema_version": 1, "scenarios": []}
    return db


def save_scenarios(db):
    path = scenarios_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clean_scenario(raw):
    """Gunluk gorevin yazdigi senaryoyu dogrula. (ok, senaryo_or_hata)"""
    if not isinstance(raw, dict):
        return False, "kayit nesne degil"
    title = (raw.get("title") or raw.get("baslik") or "").strip()
    story = (raw.get("story") or raw.get("senaryo") or "").strip()
    if not title:
        return False, "title bos"
    if len(story) < 80:
        return False, "story cok kisa (en az 80 karakter anlatim bekleniyor)"
    area = attackdb._norm_category(raw.get("area") or raw.get("category") or "")
    if area is None:
        return False, "area gecersiz (LLM01-LLM10)"
    steps = raw.get("steps") or raw.get("adimlar") or []
    if isinstance(steps, str):
        steps = [s.strip() for s in steps.split("\n") if s.strip()]
    if not isinstance(steps, list):
        steps = []
    # Gerceklik etiketi: belgelenmis gercek vaka mi, gercege dayali kurgu mu?
    # Varsayilan KURGU'dur — etiketlenmemis icerik asla 'gercek' diye sunulmaz.
    truth_raw = str(raw.get("truth") or raw.get("gerceklik") or "").strip().lower()
    truth = "real" if truth_raw in ("real", "gercek", "gerçek", "documented",
                                    "belgelenmis", "true") else "composite"
    return True, {
        "id": (raw.get("id") or "").strip(),
        "day": (str(raw.get("day") or raw.get("gun") or "")[:10]
                or date.today().isoformat()),
        "title": title,
        "area": area,
        "truth": truth,
        "level": ("advanced" if str(raw.get("level") or "").strip().lower()
                  in ("advanced", "ileri", "adv") else "core"),
        "story": story,
        "steps": [str(s).strip() for s in steps if str(s).strip()],
        "question": (raw.get("question") or raw.get("soru") or "").strip(),
        "answer": (raw.get("answer") or raw.get("cevap") or "").strip(),
        "lesson": (raw.get("lesson") or raw.get("ders") or "").strip(),
        "source": (raw.get("source") or raw.get("kaynak") or "").strip(),
        "source_id": (raw.get("source_id") or raw.get("attack_id") or "").strip(),
    }


def import_scenarios(sdb, items):
    """Senaryolari bankaya ekle. Donen: (added, dupes, errors)"""
    seen = set()
    top = 0
    for s in sdb["scenarios"]:
        seen.add(" ".join((s.get("title") or "").lower().split()))
        try:
            top = max(top, int(str(s.get("id", "SC-0")).split("-")[-1]))
        except ValueError:
            pass
    added, dupes, errors = 0, 0, []
    for i, raw in enumerate(items):
        ok, res = clean_scenario(raw)
        if not ok:
            errors.append((i, res))
            continue
        norm = " ".join(res["title"].lower().split())
        if norm in seen:
            dupes += 1
            continue
        top += 1
        res["id"] = res["id"] or ("SC-%04d" % top)
        sdb["scenarios"].append(res)
        seen.add(norm)
        added += 1
    return added, dupes, errors


# --------------------------------------------------------------------------
# Not defteri — soru cozerken "bunu bilmiyorum" diye yazilanlar
# --------------------------------------------------------------------------
def notes_path():
    return os.path.join(attackdb.data_dir(), "notes.json")


def load_notes():
    try:
        with open(notes_path(), "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "notes": []}
    if not isinstance(db, dict) or not isinstance(db.get("notes"), list):
        return {"schema_version": 1, "notes": []}
    return db


def save_notes(db):
    path = notes_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def add_note(text, question=None, source="masaustu", db=None):
    """Soru cozerken alinan notu kaydet. Donen: eklenen not."""
    text = (text or "").strip()
    if not text:
        return None
    db = db if db is not None else load_notes()
    top = 0
    for n in db["notes"]:
        try:
            top = max(top, int(str(n.get("id", "N-0")).split("-")[-1]))
        except ValueError:
            pass
    q = question or {}
    entry = q.get("entry") or {}
    tool = q.get("tool") or {}
    note = {
        "id": "N-%04d" % (top + 1),
        "day": date.today().isoformat(),
        "time": datetime.now().strftime("%H:%M"),
        "text": text,
        "area": q.get("area", ""),
        "key": q.get("key", ""),
        "technique": entry.get("technique") or tool.get("name") or "",
        "question": _trim(q.get("prompt", ""), 240),
        "source": source,
        "answer": "",
        "answered_day": "",
    }
    db["notes"].append(note)
    save_notes(db)
    return note


def open_notes(db=None, limit=None):
    """Henuz cevaplanmamis notlar (gunluk gorev bunlari anlatir)."""
    db = db if db is not None else load_notes()
    rows = [n for n in db.get("notes", []) if not (n.get("answer") or "").strip()]
    rows.sort(key=lambda n: (n.get("day", ""), n.get("time", "")))
    return rows[:limit] if limit else rows


def answer_note(db, note_id, answer):
    for n in db.get("notes", []):
        if n.get("id") == note_id:
            n["answer"] = (answer or "").strip()
            n["answered_day"] = date.today().isoformat()
            return True
    return False


def notes_today(db=None):
    db = db if db is not None else load_notes()
    t = date.today().isoformat()
    return [n for n in db.get("notes", []) if n.get("day") == t]


# --------------------------------------------------------------------------
# Egitim yolu (path.json) — sifirdan ilerleyen modul/bolum mufredati
# --------------------------------------------------------------------------
def path_file():
    return os.path.join(attackdb.data_dir(), "path.json")


def load_path():
    path = path_file()
    if not os.path.exists(path):
        seed = os.path.join(attackdb._resource_dir(), "data", "path.json")
        if os.path.exists(seed) and os.path.abspath(seed) != os.path.abspath(path):
            try:
                with open(seed, "r", encoding="utf-8") as f:
                    db = json.load(f)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
                return db
            except (OSError, ValueError):
                pass
        return {"schema_version": 1, "modules": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "modules": []}
    if not isinstance(db, dict) or not isinstance(db.get("modules"), list):
        return {"schema_version": 1, "modules": []}
    return db


def _path_prog(progress):
    p = progress.setdefault("path", {})
    if not isinstance(p, dict):
        p = progress["path"] = {}
    p.setdefault("read", {})
    p.setdefault("done", {})
    return p


def section_read(progress, section_id):
    return bool(_path_prog(progress)["read"].get(section_id))


def set_section_read(progress, section_id, value=True):
    pp = _path_prog(progress)
    if value:
        pp["read"][section_id] = date.today().isoformat()
    else:
        pp["read"].pop(section_id, None)
    return progress


def module_done(progress, module_id):
    return bool(_path_prog(progress)["done"].get(module_id))


def set_module_done(progress, module_id, score=None):
    pp = _path_prog(progress)
    pp["done"][module_id] = {"day": date.today().isoformat(), "score": score}
    return progress


def module_status(progress, module):
    """(okunan_bolum, toplam_bolum, kontrol_gecildi_mi)"""
    secs = module.get("sections", [])
    read = sum(1 for s in secs if section_read(progress, s.get("id", "")))
    return read, len(secs), module_done(progress, module.get("id", ""))


def path_status(pathdb, progress):
    """Yolun genel durumu: (tamamlanan_modul, toplam_modul, okunan_bolum, toplam_bolum)"""
    mods = pathdb.get("modules", [])
    done = sum(1 for m in mods if module_done(progress, m.get("id", "")))
    read = total = 0
    for m in mods:
        r, t, _ = module_status(progress, m)
        read += r
        total += t
    return done, len(mods), read, total


def next_section(pathdb, progress):
    """Sirada okunacak ilk bolum (modul, bolum) — yoksa (None, None)."""
    for m in pathdb.get("modules", []):
        for s in m.get("sections", []):
            if not section_read(progress, s.get("id", "")):
                return m, s
    return None, None


TRUTH_LABEL = {
    "real": "🟢 GERÇEK VAKA  ·  belgelenmiş olay, kaynağı çözümde",
    "composite": "🟡 GERÇEĞE DAYALI KURGU  ·  teknik gerçek, olay kurgusal",
}


# --------------------------------------------------------------------------
# Pratik hedefler (dis kaynaklar: HTB / THM / PortSwigger / CTF / arac)
# --------------------------------------------------------------------------
def practice_path():
    return os.path.join(attackdb.data_dir(), "practice.json")


def load_practice():
    path = practice_path()
    if not os.path.exists(path):
        seed = os.path.join(attackdb._resource_dir(), "data", "practice.json")
        if os.path.exists(seed) and os.path.abspath(seed) != os.path.abspath(path):
            try:
                with open(seed, "r", encoding="utf-8") as f:
                    db = json.load(f)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(db, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
                return db
            except (OSError, ValueError):
                pass
        return {"schema_version": 1, "targets": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "targets": []}
    if not isinstance(db, dict) or not isinstance(db.get("targets"), list):
        return {"schema_version": 1, "targets": []}
    return db


_COST_ORDER = {"free": 0, "free-tier": 1, "paid": 2}


def practice_for(category=None, practice_db=None, limit=None):
    """Bir kat icin pratik yapilabilecek YASAL hedefler (once ucretsizler)."""
    db = practice_db if practice_db is not None else load_practice()
    rows = [t for t in db.get("targets", [])
            if not category or category in (t.get("areas") or [])]
    rows.sort(key=lambda t: (_COST_ORDER.get(t.get("cost"), 3),
                             0 if t.get("kind") in ("lab", "ctf") else 1,
                             t.get("name", "")))
    return rows[:limit] if limit else rows


def scenario_text(sc):
    """Senaryoyu okunur duz metne cevir (cozum haric)."""
    parts = [sc.get("story", "")]
    if sc.get("steps"):
        parts.append("\nOLAYIN AKISI:")
        for i, st in enumerate(sc["steps"], 1):
            parts.append("  %d. %s" % (i, st))
    if sc.get("question"):
        parts.append("\nSORU: %s" % sc["question"])
    return "\n".join(parts)


def scenario_solution(sc):
    parts = []
    if sc.get("answer"):
        parts.append("CEVAP: %s" % sc["answer"])
    if sc.get("lesson"):
        parts.append("\nDERS: %s" % sc["lesson"])
    if sc.get("source"):
        parts.append("\nKAYNAK: %s" % sc["source"])
    return "\n".join(parts) or "(cozum yazilmamis)"


# --------------------------------------------------------------------------
# Soru kaliplari (uretim)
# --------------------------------------------------------------------------
# Her kalip: (kod, gerekli_alan, soru_tipi)
ATTACK_TEMPLATES = [
    ("story2cat",   "story",      "Bu olay hangi OWASP LLM kategorisine girer?"),
    ("story2tech",  "story",      "Anlatilan saldiri teknigi asagidakilerden hangisidir?"),
    ("tech2cat",    None,         "Bu teknik hangi OWASP LLM katina girer?"),
    ("payload2tech", "example",   "Asagidaki payload/iz hangi teknige aittir?"),
    ("why2tech",    "why",        "Bu aciklama hangi teknigin NEDEN calistigini anlatir?"),
    ("mitig2tech",  "mitigation", "Bu onlem hangi saldiriya karsi alinir?"),
    ("case2tech",   "real_case",  "Bu gercek olay hangi teknige ornektir?"),
    ("tech2mitig",  "mitigation", "Bu saldiriya karsi dogru onlem hangisidir?"),
    ("cat2tech",    None,         "Asagidakilerden hangisi bu kat kapsamindadir?"),
]

TOOL_TEMPLATES = [
    ("func2tool", "Su isi yapan arac hangisidir?"),
    ("tool2func", "Bu arac ne ise yarar?"),
    ("tool2type", "Bu arac hangi turdendir?"),
]

TERM_TEMPLATES = [
    ("code2name", "Bu OWASP LLM kodu hangi kategoridir?"),
    ("name2code", "Bu kategori hangi OWASP LLM kodudur?"),
]


def build_specs(db, tools_db, qdb=None):
    """Havuzdaki tum soru kunyelerini (spec) uret. Sik uretimi sonra yapilir."""
    specs = []
    for a in db.get("attacks", []):
        aid = a.get("id", "")
        cat = a.get("category", "")
        if not aid or cat not in attackdb.CATEGORIES:
            continue
        for tmpl, field, _q in ATTACK_TEMPLATES:
            if field and not (a.get(field) or "").strip():
                continue
            specs.append({"key": "%s|%s" % (aid, tmpl), "tmpl": tmpl,
                          "area": cat, "src": aid})
    for t in (tools_db.get("tools", []) if isinstance(tools_db, dict) else []):
        tid = t.get("id", "")
        if not tid:
            continue
        for tmpl, _q in TOOL_TEMPLATES:
            specs.append({"key": "%s|%s" % (tid, tmpl), "tmpl": tmpl,
                          "area": TOOL_AREA, "src": tid})
    for cat in attackdb.CATEGORIES:
        for tmpl, _q in TERM_TEMPLATES:
            specs.append({"key": "%s|%s" % (cat, tmpl), "tmpl": tmpl,
                          "area": cat, "src": cat})
    for q in ((qdb or {}).get("questions", [])):
        qid = q.get("id") or ""
        if not qid:
            continue
        specs.append({"key": "%s|hand" % qid, "tmpl": "hand",
                      "area": q.get("area", ""), "src": qid})
    return specs


def _pick_distractors(pool, correct, n, rng, key=lambda x: x):
    """correct disinda n benzersiz celdirici sec (metin bazli tekillik)."""
    out, seen = [], {str(key(correct)).strip().lower()}
    for item in pool:
        if len(out) >= n:
            break
        txt = str(key(item)).strip().lower()
        if not txt or txt in seen:
            continue
        seen.add(txt)
        out.append(item)
    return out


def _same_cat_first(db, entry, rng):
    """Once ayni kattan, sonra digerlerinden karisik teknik listesi."""
    cat = entry.get("category")
    same = [a for a in db.get("attacks", [])
            if a.get("category") == cat and a.get("id") != entry.get("id")]
    other = [a for a in db.get("attacks", [])
             if a.get("category") != cat]
    rng.shuffle(same)
    rng.shuffle(other)
    return same + other


def _shuffle_options(options, correct_text, rng):
    """Siklari karistir, dogru cevabin indeksini dondur."""
    opts = list(options)
    rng.shuffle(opts)
    return opts, opts.index(correct_text)


def _trim(text, limit=160):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def make_question(spec, db, tools_db, qdb=None, rng=random):
    """Bir spec'ten tam soru uret (siklar dahil). Uretilemezse None."""
    tmpl = spec["tmpl"]
    src = spec["src"]

    if tmpl == "hand":
        for q in ((qdb or {}).get("questions", [])):
            if q.get("id") == src:
                opts, ans = _shuffle_options(q["options"],
                                             q["options"][q["answer"]], rng)
                entry = None
                if q.get("source_id"):
                    entry = _find_attack(db, q["source_id"])
                return {"key": spec["key"], "tmpl": "hand", "area": q.get("area"),
                        "prompt": q["prompt"], "context": q.get("context", ""),
                        "options": opts, "answer": ans, "entry": entry,
                        "tool": None, "hand": q}
        return None

    if tmpl in ("code2name", "name2code"):
        cat = src
        name = attackdb.CATEGORIES.get(cat)
        if not name:
            return None
        others = [c for c in attackdb.CATEGORIES if c != cat]
        rng.shuffle(others)
        picks = others[:3]
        if tmpl == "code2name":
            correct = name
            opts = [correct] + [attackdb.CATEGORIES[c] for c in picks]
            prompt = "OWASP LLM Top 10 (2026): '%s' hangi kategoridir?" % cat
        else:
            correct = cat
            opts = [correct] + picks
            prompt = "OWASP LLM Top 10 (2026): '%s' hangi koddur?" % name
        opts, ans = _shuffle_options(opts, correct, rng)
        return {"key": spec["key"], "tmpl": tmpl, "area": cat,
                "prompt": prompt, "context": "", "options": opts,
                "answer": ans, "entry": None, "tool": None}

    if tmpl in ("func2tool", "tool2func", "tool2type"):
        tools = (tools_db.get("tools", []) if isinstance(tools_db, dict) else [])
        tool = next((t for t in tools if t.get("id") == src), None)
        if not tool:
            return None
        pool = [t for t in tools if t.get("id") != src]
        rng.shuffle(pool)
        if tmpl == "func2tool":
            if not (tool.get("what") or "").strip():
                return None
            correct = tool.get("name", "")
            ds = _pick_distractors(pool, tool, 3, rng, key=lambda t: t.get("name", ""))
            opts = [correct] + [d.get("name", "") for d in ds]
            prompt = "Su isi yapan arac hangisidir?"
            context = _trim(tool.get("what", ""), 400)
        elif tmpl == "tool2func":
            correct = _trim(tool.get("what", ""), 170)
            ds = _pick_distractors(pool, tool, 3, rng,
                                   key=lambda t: _trim(t.get("what", ""), 170))
            opts = [correct] + [_trim(d.get("what", ""), 170) for d in ds]
            prompt = "'%s' araci ne ise yarar?" % tool.get("name", "")
            context = ""
        else:
            correct = TOOL_TYPE_LABEL.get(tool.get("type", ""), "Bilinmiyor")
            opts = [correct] + [v for k, v in TOOL_TYPE_LABEL.items()
                                if v != correct]
            opts = opts[:4]
            prompt = "'%s' araci hangi turdendir?" % tool.get("name", "")
            context = _trim(tool.get("what", ""), 220)
        if len(opts) < 3:
            return None
        opts, ans = _shuffle_options(opts, correct, rng)
        return {"key": spec["key"], "tmpl": tmpl, "area": TOOL_AREA,
                "prompt": prompt, "context": context, "options": opts,
                "answer": ans, "entry": None, "tool": tool}

    entry = _find_attack(db, src)
    if not entry:
        return None
    cat = entry.get("category", "")
    cat_name = attackdb.CATEGORIES.get(cat, cat)
    siblings = _same_cat_first(db, entry, rng)

    def tech_options():
        ds = _pick_distractors(siblings, entry, 3, rng,
                               key=lambda a: a.get("technique", ""))
        return [entry.get("technique", "")] + [d.get("technique", "") for d in ds]

    def cat_options():
        others = [c for c in attackdb.CATEGORIES if c != cat]
        rng.shuffle(others)
        return ["%s — %s" % (cat, cat_name)] + \
               ["%s — %s" % (c, attackdb.CATEGORIES[c]) for c in others[:3]]

    context, prompt, opts, correct = "", "", [], ""

    if tmpl == "story2cat":
        context = entry.get("story", "")
        prompt = "Bu olay hangi OWASP LLM kategorisine girer?"
        opts = cat_options()
        correct = opts[0]
    elif tmpl == "story2tech":
        context = entry.get("story", "")
        prompt = "Anlatilan saldiri teknigi asagidakilerden hangisidir?"
        opts = tech_options()
        correct = opts[0]
    elif tmpl == "tech2cat":
        prompt = "'%s' teknigi hangi OWASP LLM katina girer?" % entry.get("technique", "")
        opts = cat_options()
        correct = opts[0]
    elif tmpl == "payload2tech":
        context = _trim(entry.get("example", ""), 500)
        prompt = "Asagidaki payload/iz hangi teknige aittir?"
        opts = tech_options()
        correct = opts[0]
    elif tmpl == "why2tech":
        context = entry.get("why", "")
        prompt = "Bu aciklama hangi teknigin NEDEN calistigini anlatir?"
        opts = tech_options()
        correct = opts[0]
    elif tmpl == "mitig2tech":
        context = entry.get("mitigation", "")
        prompt = "Bu onlem hangi saldiriya karsi alinir?"
        opts = tech_options()
        correct = opts[0]
    elif tmpl == "case2tech":
        context = entry.get("real_case", "")
        prompt = "Bu gercek olay hangi teknige ornektir?"
        opts = tech_options()
        correct = opts[0]
    elif tmpl == "tech2mitig":
        correct = _trim(entry.get("mitigation", ""), 170)
        if not correct:
            return None
        ds = _pick_distractors(siblings, entry, 3, rng,
                               key=lambda a: _trim(a.get("mitigation", ""), 170))
        opts = [correct] + [_trim(d.get("mitigation", ""), 170) for d in ds
                            if (d.get("mitigation") or "").strip()]
        context = ""
        prompt = "'%s' saldirisina karsi dogru onlem hangisidir?" % entry.get("technique", "")
    elif tmpl == "cat2tech":
        correct = entry.get("technique", "")
        others = [a for a in db.get("attacks", []) if a.get("category") != cat]
        rng.shuffle(others)
        ds = _pick_distractors(others, entry, 3, rng,
                               key=lambda a: a.get("technique", ""))
        opts = [correct] + [d.get("technique", "") for d in ds]
        prompt = "Asagidakilerden hangisi %s — %s kapsamindadir?" % (cat, cat_name)
    else:
        return None

    if not correct:
        correct = opts[0] if opts else ""
    opts = [o for o in opts if str(o).strip()]
    if len(opts) < 3 or not context and tmpl in ("story2cat", "story2tech",
                                                 "why2tech", "mitig2tech",
                                                 "case2tech", "payload2tech"):
        return None
    opts, ans = _shuffle_options(opts, correct, rng)
    return {"key": spec["key"], "tmpl": tmpl, "area": cat, "prompt": prompt,
            "context": context, "options": opts, "answer": ans,
            "entry": entry, "tool": None}


def _find_attack(db, aid):
    for a in db.get("attacks", []):
        if a.get("id") == aid:
            return a
    return None


# --------------------------------------------------------------------------
# Ilerleme / tekrar araligi
# --------------------------------------------------------------------------
def _items(progress):
    it = progress.setdefault("items", {})
    if not isinstance(it, dict):
        it = progress["items"] = {}
    return it


def item_stat(progress, key):
    rec = _items(progress).get(key)
    if not isinstance(rec, dict):
        return {"n": 0, "ok": 0, "bad": 0, "elim": 0, "box": 1, "last": None}
    out = {"n": rec.get("n", 0), "ok": rec.get("ok", 0), "bad": rec.get("bad", 0),
           "elim": rec.get("elim", 0), "box": rec.get("box", 1),
           "last": rec.get("last")}
    return out


def _days_since(iso):
    if not iso:
        return 9999
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return 9999
    return (date.today() - d).days


def spec_weight(spec, progress, cat_acc):
    """Secim agirligi: gorulmemis > gecikmis tekrar > eleyerek bulunan > bilinen."""
    st = item_stat(progress, spec["key"])
    if st["n"] == 0:
        w = 3.0
    else:
        interval = BOX_DAYS.get(st["box"], 0)
        if _days_since(st["last"]) >= interval:
            w = 2.2 + 0.8 * st["bad"] + 0.6 * st["elim"]
        else:
            w = 0.1
    acc = cat_acc.get(spec["area"])
    if acc is None:
        w *= 1.8                       # hic calisilmamis alan one cikar
    else:
        w *= 1.0 + (1.0 - acc) * 1.5   # zayif alan agirlikli
    if spec["tmpl"] == "hand":
        w *= 1.4                       # elle yazilan sorular degerli
    return max(w, 0.01)


def _cat_accuracy(progress):
    out = {}
    for cat, rec in (progress.get("by_category") or {}).items():
        seen = rec.get("seen", 0)
        out[cat] = (rec.get("correct", 0) / seen) if seen else None
    for cat in list(attackdb.CATEGORIES) + [TOOL_AREA]:
        out.setdefault(cat, None)
    return out


def _weighted_take(candidates, weights, n, rng, used_src, max_per_src):
    """Agirlikli, tekrarsiz secim (ayni kaynaktan en fazla max_per_src)."""
    chosen = []
    pool = list(candidates)
    while pool and len(chosen) < n:
        total = sum(weights[s["key"]] for s in pool)
        if total <= 0:
            break
        r = rng.uniform(0, total)
        upto, pickidx = 0.0, len(pool) - 1
        for i, s in enumerate(pool):
            upto += weights[s["key"]]
            if upto >= r:
                pickidx = i
                break
        s = pool.pop(pickidx)
        if used_src.get(s["src"], 0) >= max_per_src:
            continue
        used_src[s["src"]] = used_src.get(s["src"], 0) + 1
        chosen.append(s)
    return chosen


def _is_weak(rec):
    """Bu soru kaydı hâlâ 'bilinmiyor' mu? (son sonuç yanlış/eleyerek)"""
    res = rec.get("last_result")
    if res is not None:
        return res in ("bad", "elim")
    # eski kayıt biçimi: son sonucu bilmiyoruz, temkinli davran
    return bool(rec.get("bad") or rec.get("elim")) and rec.get("box", 1) <= 1


def _is_due(rec):
    return _days_since(rec.get("last")) >= BOX_DAYS.get(rec.get("box", 1), 1)


def day_state(progress):
    """Bugünün durumu, teknik (kaynak) bazında.

    wrong_today : bugün yanlış/eleyerek yapılan teknikler — bugün bir daha GELMEZ
    seen_keys   : bugün sorulmuş soru künyeleri — aynı soru aynı gün tekrar gelmez
    src_today   : teknik başına bugün kaç soru soruldu
    weak        : {teknik: {"failed": {başarısız kalıplar}, "due": vadesi geldi mi}}
    """
    today = date.today().isoformat()
    wrong_today, seen_keys, src_today, weak = set(), set(), {}, {}
    for key, rec in _items(progress).items():
        if not isinstance(rec, dict):
            continue
        src, _, tmpl = key.partition("|")
        if rec.get("last") == today:
            seen_keys.add(key)
            src_today[src] = src_today.get(src, 0) + 1
            res = rec.get("last_result")
            if res in ("bad", "elim") or (res is None and (rec.get("bad") or rec.get("elim"))):
                wrong_today.add(src)
        if _is_weak(rec):
            w = weak.setdefault(src, {"failed": set(), "due": True})
            w["failed"].add(tmpl)
            if not _is_due(rec):
                w["due"] = False
    return wrong_today, seen_keys, src_today, weak


def pick_batch(specs, progress, n=20, areas=None, rng=random, max_per_src=1):
    """n soruluk künye listesi seç.

    Öncelik (kullanıcının istediği sıra):
      1) ELLE YAZILMIŞ, hiç çözülmemiş sorular (günün yeni soruları)
      2) Daha önce YANLIŞ/ELEYEREK yapılan teknikler — ama vadesi gelmişse ve
         FARKLI BİR AÇIDAN (başarısız olunan kalıp ve aynası hariç)
      3) Elle yazılmış, tekrar zamanı gelmiş sorular
      4) Motorun ürettiği kalan havuz

    Ezber/hatırlama koruması (kullanıcının 2026-09-21 şikâyeti):
      - Bugün yanlış/eleyerek yapılan teknik bugün HİÇBİR kalıpla gelmez.
      - Aynı soru aynı gün iki kez gelmez.
      - Bir sınavda bir teknikten tek soru; günde en fazla DAY_CAP_PER_SRC.
    """
    pool = [s for s in specs if not areas or s["area"] in areas]
    if not pool:
        return []
    items = _items(progress)
    wrong_today, seen_keys, src_today, weak = day_state(progress)

    def blocked(s):
        return (s["src"] in wrong_today or s["key"] in seen_keys
                or src_today.get(s["src"], 0) >= DAY_CAP_PER_SRC)

    avail = [s for s in pool if not blocked(s)]
    if not avail:
        return []
    cat_acc = _cat_accuracy(progress)
    weights = {s["key"]: spec_weight(s, progress, cat_acc) for s in avail}

    by_src = {}
    for s in avail:
        by_src.setdefault(s["src"], []).append(s)

    fresh_hand = [s for s in avail if s["tmpl"] == "hand" and s["key"] not in items]

    comeback = []
    for src, w in weak.items():
        if not w["due"] or src not in by_src:
            continue
        cands = [s for s in by_src[src]
                 if s["tmpl"] not in w["failed"]
                 and MIRROR.get(s["tmpl"]) not in w["failed"]]
        if not cands:          # farklı kalıp yok (ör. elle yazılmış soru): vadesi gelmiş aynısı
            cands = list(by_src[src])
        # önce hiç görülmemiş kalıp — cevabı tanıdık gelmesin
        cands.sort(key=lambda s: ((items.get(s["key"]) or {}).get("n", 0), rng.random()))
        comeback.append(cands[0])

    hand_due = [s for s in avail if s["tmpl"] == "hand" and s["key"] in items
                and _is_due(items[s["key"]])]
    taken = {s["key"] for s in fresh_hand + comeback + hand_due}
    rest = [s for s in avail if s["key"] not in taken]

    used_src, chosen = {}, []
    for group in (fresh_hand, comeback, hand_due, rest):
        if len(chosen) >= n:
            break
        chosen += _weighted_take(group, weights, n - len(chosen), rng,
                                 used_src, max_per_src)
    # İnce katta soru yetmediyse aynı teknikten ikinci (farklı kalıp) soruya izin ver
    if len(chosen) < n and max_per_src < DAY_CAP_PER_SRC:
        left = [s for s in avail if s["key"] not in {c["key"] for c in chosen}]
        used_day = dict(src_today)        # günlük sınır: bugün sorulanlar + bu sınav
        for k, v in used_src.items():
            used_day[k] = used_day.get(k, 0) + v
        chosen += _weighted_take(left, weights, n - len(chosen), rng,
                                 used_day, DAY_CAP_PER_SRC)
    return chosen


def record(progress, question, correct, sure=True):
    """Yaniti kaydet.

    correct=True, sure=True   -> kutu bir ust basamaga (gercekten biliyor)
    correct=True, sure=False  -> 'eleyerek buldum': kutu 1'e doner, yakinda gelir
    correct=False             -> kutu 1, yanlis sayaci artar
    """
    key = question["key"]
    area = question.get("area") or ""
    rec = _items(progress).setdefault(
        key, {"n": 0, "ok": 0, "bad": 0, "elim": 0, "box": 1, "last": None})
    rec["n"] = rec.get("n", 0) + 1
    if correct and sure:
        rec["ok"] = rec.get("ok", 0) + 1
        rec["box"] = min(MAX_BOX, rec.get("box", 1) + 1)
        rec["last_result"] = "ok"
    elif correct and not sure:
        rec["ok"] = rec.get("ok", 0) + 1
        rec["elim"] = rec.get("elim", 0) + 1
        rec["box"] = 1
        rec["last_result"] = "elim"
    else:
        rec["bad"] = rec.get("bad", 0) + 1
        rec["box"] = 1
        rec["last_result"] = "bad"
    rec["last"] = date.today().isoformat()

    # Gunluk plan sayaci
    plan = daily_plan(progress)
    plan["per_area"][area] = plan["per_area"].get(area, 0) + 1
    plan["total"] = plan.get("total", 0) + 1

    # Genel istatistik + seri (kat bazli dogruluk 'gercekten bildim'e bakar)
    if area in attackdb.CATEGORIES:
        attackdb.record_answer(progress, area, bool(correct and sure))
    else:
        attackdb._bump_day(progress)
        progress["seen"] = progress.get("seen", 0) + 1
        progress["answered_today"] = progress.get("answered_today", 0) + 1
        if correct and sure:
            progress["correct"] = progress.get("correct", 0) + 1
        td = progress.setdefault("tool_drill", {"seen": 0, "correct": 0})
        td["seen"] = td.get("seen", 0) + 1
        if correct and sure:
            td["correct"] = td.get("correct", 0) + 1
    return progress


# --------------------------------------------------------------------------
# Gunluk plan
# --------------------------------------------------------------------------
def goal_per_area(progress):
    try:
        g = int(progress.get("exam_goal", DEFAULT_GOAL))
    except (TypeError, ValueError):
        g = DEFAULT_GOAL
    return max(1, g)


def daily_plan(progress):
    """Bugunun plan kaydini dondur (gun degistiyse sifirlar)."""
    today = date.today().isoformat()
    plan = progress.get("daily_plan")
    if not isinstance(plan, dict) or plan.get("day") != today:
        plan = {"day": today, "per_area": {}, "total": 0}
        progress["daily_plan"] = plan
    plan.setdefault("per_area", {})
    plan.setdefault("total", 0)
    return plan


def plan_status(progress):
    """[(alan, yapilan, hedef, tamam_mi)] + ozet."""
    goal = goal_per_area(progress)
    plan = daily_plan(progress)
    rows = []
    for area in list(attackdb.CATEGORIES) + [TOOL_AREA]:
        done = plan["per_area"].get(area, 0)
        rows.append((area, done, goal, done >= goal))
    total_done = sum(r[1] for r in rows)
    total_goal = goal * len(rows)
    return rows, total_done, total_goal


def next_area(progress):
    """Bugun en geride kalan alan (esitlikte en zayif dogruluk)."""
    rows, _, _ = plan_status(progress)
    acc = _cat_accuracy(progress)
    remaining = [(r[2] - r[1], acc.get(r[0]) if acc.get(r[0]) is not None else -1.0, r[0])
                 for r in rows if not r[3]]
    if not remaining:
        return None
    remaining.sort(key=lambda x: (-x[0], x[1]))
    return remaining[0][2]


# --------------------------------------------------------------------------
# Zayif konular / yenilikler
# --------------------------------------------------------------------------
def weak_items(progress, limit=10):
    """En cok yanlis yapilan / eleyerek bulunan soru kunyeleri."""
    rows = []
    for key, rec in _items(progress).items():
        score = rec.get("bad", 0) * 2 + rec.get("elim", 0)
        if score:
            rows.append((score, key, rec))
    rows.sort(reverse=True)
    return rows[:limit]


def weak_entries(db, progress, limit=8):
    """Zayif sorulardan teknik kayitlarina cik (ders anlatimi icin)."""
    out, seen = [], set()
    for _score, key, _rec in weak_items(progress, limit * 3):
        src = key.split("|")[0]
        if src in seen:
            continue
        entry = _find_attack(db, src)
        if entry:
            seen.add(src)
            out.append(entry)
        if len(out) >= limit:
            break
    return out


def weak_areas(progress, limit=3):
    """Dogrulugu en dusuk alanlar (en az 3 soru gorulmus olanlar)."""
    acc = _cat_accuracy(progress)
    rows = []
    for area, a in acc.items():
        rec = (progress.get("by_category") or {}).get(area, {})
        if area == TOOL_AREA:
            rec = progress.get("tool_drill", {})
        seen = rec.get("seen", 0)
        if seen >= 3 and a is not None:
            rows.append((a, area))
        elif seen == 0:
            rows.append((-1.0, area))    # hic calisilmamis en zayiftir
    rows.sort()
    return [area for _a, area in rows[:limit]]


def recent_entries(db, days=7):
    """Son N gunde kutuphaneye eklenen teknikler (added alanina gore)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for a in db.get("attacks", []):
        added = (a.get("added") or "")[:10]
        if added and added >= cutoff:
            out.append(a)
    out.sort(key=lambda a: a.get("added", ""), reverse=True)
    return out


def lesson_text(entry):
    """Bir teknik kaydini duz metin ders haline getir."""
    parts = []
    cat = entry.get("category", "")
    parts.append("%s — %s" % (cat, attackdb.CATEGORIES.get(cat, "")))
    parts.append("TEKNIK: %s" % entry.get("technique", ""))
    if entry.get("story"):
        parts.append("\nSENARYO: %s" % entry["story"])
    if entry.get("why"):
        parts.append("\nNEDEN CALISIR: %s" % entry["why"])
    if entry.get("example"):
        parts.append("\nPAYLOAD/ORNEK: %s" % entry["example"])
    if entry.get("how_to_use"):
        parts.append("\nNASIL KULLANILIR: %s" % entry["how_to_use"])
    if entry.get("mitigation"):
        parts.append("\nONLEM: %s" % entry["mitigation"])
    if entry.get("real_case"):
        parts.append("\nGERCEK OLAY: %s" % entry["real_case"])
    if entry.get("source"):
        parts.append("\nKAYNAK: %s" % entry["source"])
    try:
        targets = practice_for(cat, limit=2)
    except Exception:
        targets = []
    if targets:
        parts.append("\n🎯 PRATİK: " + "   ·   ".join(
            "%s — %s" % (t.get("name", ""), t.get("url", "")) for t in targets))
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Gunluk rapor (gunluk gorev yazar, uygulama gosterir)
# --------------------------------------------------------------------------
def reports_path():
    return os.path.join(attackdb.data_dir(), "reports.json")


def load_reports():
    try:
        with open(reports_path(), "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "reports": []}
    if not isinstance(db, dict) or not isinstance(db.get("reports"), list):
        return {"schema_version": 1, "reports": []}
    return db


def save_reports(db):
    path = reports_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def add_report(title, body, day=None, stats=None, keep=60):
    """Gunun raporunu kaydet (ayni gune ikinci kez yazilirsa gunceller)."""
    db = load_reports()
    day = day or date.today().isoformat()
    rec = {"day": day, "title": title, "body": body, "stats": stats or {},
           "written": datetime.now().isoformat(timespec="seconds")}
    db["reports"] = [r for r in db["reports"] if r.get("day") != day]
    db["reports"].append(rec)
    db["reports"].sort(key=lambda r: r.get("day", ""), reverse=True)
    db["reports"] = db["reports"][:keep]
    save_reports(db)
    return rec


def latest_report():
    db = load_reports()
    return db["reports"][0] if db.get("reports") else None


def performance_snapshot(progress, db=None, days=1):
    """Gunluk gorevin analiz icin okudugu ozet: dun ne coztu, nerede zorlandi."""
    items = _items(progress)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = {k: v for k, v in items.items()
              if (v.get("last") or "") >= cutoff}
    per_area = {}
    for key, rec in recent.items():
        src = key.split("|")[0]
        area = TOOL_AREA
        if src.startswith("LLM"):
            area = src.split("-")[0] if "-" in src else src
        elif src.startswith("Q-"):
            area = "HAND"
        per_area.setdefault(area, {"n": 0, "bad": 0, "elim": 0})
        per_area[area]["n"] += rec.get("n", 0)
        per_area[area]["bad"] += rec.get("bad", 0)
        per_area[area]["elim"] += rec.get("elim", 0)
    rows, done, goal = plan_status(progress)
    return {
        "today_done": done, "today_goal": goal,
        "plan": {r[0]: [r[1], r[2]] for r in rows},
        "recent_items": len(recent),
        "per_area": per_area,
        "weak_areas": weak_areas(progress, 5),
        "streak": progress.get("streak", 0),
        "accuracy": (progress.get("correct", 0) / progress["seen"]
                     if progress.get("seen") else None),
    }


# --------------------------------------------------------------------------
# CLI: gunluk gorev ve testler icin durum raporu
# --------------------------------------------------------------------------
def _report():
    db = attackdb.load_attacks()
    tools = attackdb.load_tools()
    qdb = load_questions()
    prog = attackdb.load_progress()
    specs = build_specs(db, tools, qdb)
    by_tmpl = {}
    for s in specs:
        by_tmpl[s["tmpl"]] = by_tmpl.get(s["tmpl"], 0) + 1
    print("TEKNIK   : %d" % len(db.get("attacks", [])))
    print("ARAC     : %d" % len(tools.get("tools", [])))
    print("ELLE SORU: %d" % len(qdb.get("questions", [])))
    print("HAVUZ    : %d soru kunyesi" % len(specs))
    print("KALIPLAR : " + ", ".join("%s=%d" % kv for kv in sorted(by_tmpl.items())))
    rows, done, goal = plan_status(prog)
    print("\nBUGUN    : %d / %d" % (done, goal))
    print("PLAN     : " + "  ".join("%s %d/%d" % (r[0], r[1], r[2]) for r in rows))
    print("ZAYIF    : " + ", ".join(weak_areas(prog, 5) or ["(veri yok)"]))
    weak = weak_entries(db, prog, 5)
    if weak:
        print("YANLISLAR: " + ", ".join("%s %s" % (w.get("id"), w.get("technique"))
                                        for w in weak))
    rec = recent_entries(db, 7)
    print("SON 7 GUN: %d yeni teknik" % len(rec))
    hand_prompts = [q.get("prompt", "") for q in qdb.get("questions", [])]
    if hand_prompts:
        print("\nELLE YAZILMIS SORULARIN BASLIKLARI (tekrar etme):")
        for p in hand_prompts[-40:]:
            print("  - " + _trim(p, 110))


def _selftest(n=20):
    """Havuzdan n soru uretip tutarliligi kontrol et."""
    db = attackdb.load_attacks()
    tools = attackdb.load_tools()
    qdb = load_questions()
    prog = attackdb.load_progress()
    specs = build_specs(db, tools, qdb)
    rng = random.Random(7)
    picks = pick_batch(specs, prog, n, rng=rng)
    bad = 0
    for s in picks:
        q = make_question(s, db, tools, qdb, rng)
        if not q:
            print("URETILEMEDI: %s" % s["key"])
            bad += 1
            continue
        opts = q["options"]
        if len(opts) < 3 or len(set(opts)) != len(opts):
            print("SIK SORUNU : %s -> %r" % (s["key"], opts))
            bad += 1
        if not (0 <= q["answer"] < len(opts)):
            print("CEVAP SORUNU: %s" % s["key"])
            bad += 1
    print("%d soru uretildi, %d sorun" % (len(picks), bad))
    return bad


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(1 if _selftest(40) else 0)
    _report()
