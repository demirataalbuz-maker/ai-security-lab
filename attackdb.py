# -*- coding: utf-8 -*-
"""
attackdb.py - AI Security Lab veri katmani.

Sorumluluklar:
  * Saldiri veritabanini (attacks.json) yaziya-acik bir konumdan oku/yaz.
  * Ilk calistirmada, exe'nin icine gomulu tohumu yaziya-acik konuma kopyala.
  * Gunluk siniflandirma testi icin soru sec (zayif kategorileri agirlikli).
  * Ilerleme/streak durumunu progress.json'da tut.
  * Disaridan (Kimi/baska AI) uretilen JSON'u dogrula ve kutuphaneye ekle.
  * Baska AI'ya verilecek "uretici prompt"u sagla.

Tasarim notu: exe hicbir aga baglanmaz. Sadece kendi klasorundeki
data/ altini okur-yazar. Icerik buyutme, kullanicinin baska bir AI'dan
aldigi JSON'u yapistirmasiyla olur (import_entries).
"""

import os
import sys
import json
import random
from datetime import date, datetime

SCHEMA_VERSION = 1

# OWASP GenAI LLM Top 10 2026 (yayin: 4 Agustos 2026). Sira/adlar 2025'ten degisti.
CATEGORIES = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Excessive Agency",
    "LLM04": "Supply Chain",
    "LLM05": "Data and Model Poisoning",
    "LLM06": "Unbounded Consumption",
    "LLM07": "Misinformation",
    "LLM08": "Hidden Context Exposure",
    "LLM09": "Vector and Embedding Weaknesses",
    "LLM10": "Improper Output Handling",
}

# Bir kaydin tasimasi gereken zorunlu alanlar.
REQUIRED_FIELDS = ("category", "technique", "example", "how_to_use")
# Opsiyonel ama beklenen alanlar (eksikse bos doldurulur).
OPTIONAL_FIELDS = ("real_case", "year", "severity", "why", "mitigation", "title")

SEVERITIES = ("LOW", "MEDIUM", "MEDIUM-HIGH", "HIGH", "CRITICAL")


# --------------------------------------------------------------------------
# Yol yardimcilari
# --------------------------------------------------------------------------
def _app_dir():
    """Yaziya-acik veri klasorunun ana dizini.

    Frozen (PyInstaller) ise exe'nin bulundugu klasor; degilse bu dosyanin
    klasoru. Boylece exe'nin yanina data/ yazilir ve icerik orada buyur.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _resource_dir():
    """Salt-okunur gomulu kaynak dizini (PyInstaller _MEIPASS) veya app dir."""
    return getattr(sys, "_MEIPASS", _app_dir())


def data_dir():
    d = os.path.join(_app_dir(), "data")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        # Exe salt-okunur bir yerdeyse kullanici profiline dus.
        d = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "AI-Security-Lab", "data")
        os.makedirs(d, exist_ok=True)
    return d


def attacks_path():
    return os.path.join(data_dir(), "attacks.json")


def progress_path():
    return os.path.join(data_dir(), "progress.json")


def _seed_path():
    """Gomulu tohum attacks.json'un yolu (varsa)."""
    return os.path.join(_resource_dir(), "data", "attacks.json")


# --------------------------------------------------------------------------
# Ilk kurulum / yukleme
# --------------------------------------------------------------------------
def _empty_db():
    return {"schema_version": SCHEMA_VERSION,
            "categories": dict(CATEGORIES),
            "attacks": []}


def ensure_seeded():
    """Yaziya-acik attacks.json yoksa gomulu tohumdan olustur."""
    dest = attacks_path()
    if os.path.exists(dest):
        return dest
    seed = _seed_path()
    db = None
    if os.path.exists(seed) and os.path.abspath(seed) != os.path.abspath(dest):
        try:
            with open(seed, "r", encoding="utf-8") as f:
                db = json.load(f)
        except (OSError, ValueError):
            db = None
    if db is None:
        db = _empty_db()
    save_attacks(db)
    return dest


def load_attacks():
    """attacks.json'u yukle; bozuk/eksikse guvenli bir yapiya dus."""
    ensure_seeded()
    try:
        with open(attacks_path(), "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return _empty_db()
    if not isinstance(db, dict):
        return _empty_db()
    db.setdefault("schema_version", SCHEMA_VERSION)
    db.setdefault("categories", dict(CATEGORIES))
    if not isinstance(db.get("attacks"), list):
        db["attacks"] = []
    return db


def save_attacks(db):
    tmp = attacks_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, attacks_path())


def load_progress():
    try:
        with open(progress_path(), "r", encoding="utf-8") as f:
            p = json.load(f)
    except (OSError, ValueError):
        p = {}
    p.setdefault("seen", 0)
    p.setdefault("correct", 0)
    p.setdefault("by_category", {})   # {"LLM01": {"seen": n, "correct": m}}
    p.setdefault("streak", 0)
    p.setdefault("best_streak", 0)
    p.setdefault("last_day", None)
    p.setdefault("answered_today", 0)
    p.setdefault("mastery", {})       # {"LLM01-003": "known" | "review" | "new"}
    if not isinstance(p.get("mastery"), dict):
        p["mastery"] = {}
    return p


def save_progress(p):
    tmp = progress_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    os.replace(tmp, progress_path())


# --------------------------------------------------------------------------
# Gunluk test mantigi
# --------------------------------------------------------------------------
MASTERY_STATES = ("new", "review", "known")


def get_mastery(progress, attack_id):
    """Bir teknigin ustalik durumu: 'known' | 'review' | 'new'."""
    st = progress.get("mastery", {}).get(attack_id)
    return st if st in MASTERY_STATES else "new"


def set_mastery(progress, attack_id, state):
    """Teknigi isaretle. 'new' ise kaydi silip varsayilana dondur."""
    if state not in MASTERY_STATES:
        return progress
    m = progress.setdefault("mastery", {})
    if state == "new":
        m.pop(attack_id, None)
    else:
        m[attack_id] = state
    return progress


def mastery_stats(db, progress):
    """Kapsama tablosu: kategori basina ve toplam {known, review, new, total}.

    Donen sozlukte her LLM0X anahtari + 'TOTAL' anahtari bulunur.
    """
    out = {cat: {"known": 0, "review": 0, "new": 0, "total": 0} for cat in CATEGORIES}
    out["TOTAL"] = {"known": 0, "review": 0, "new": 0, "total": 0}
    for a in db.get("attacks", []):
        cat = a.get("category", "")
        if cat not in out:
            continue
        st = get_mastery(progress, a.get("id", ""))
        out[cat][st] += 1
        out[cat]["total"] += 1
        out["TOTAL"][st] += 1
        out["TOTAL"]["total"] += 1
    return out


def category_stats(progress):
    """Her kategori icin (seen, correct, dogruluk_orani) dondurur."""
    out = {}
    for cat in CATEGORIES:
        rec = progress.get("by_category", {}).get(cat, {})
        seen = rec.get("seen", 0)
        correct = rec.get("correct", 0)
        acc = (correct / seen) if seen else None
        out[cat] = {"seen": seen, "correct": correct, "accuracy": acc}
    return out


def pick_question(db, progress, rng=random):
    """Zayif kategorileri agirlikli olarak bir saldiri ornegi sec.

    Agirlik = kategori agirligi * ustalik agirligi.
      kategori = 1.0 + (yanlis-oran * 3), hic gorulmemis kat = 2.5
      ustalik  = new 1.6 / review 2.4 / known 0.25
    Boylece hem zorlandigin katlar hem de HENUZ BILMEDIGIN teknikler one cikar.
    """
    attacks = db.get("attacks", [])
    if not attacks:
        return None
    stats = category_stats(progress)

    def cat_weight(cat):
        s = stats.get(cat, {"seen": 0, "accuracy": None})
        if s["seen"] == 0:
            return 2.5                      # hic gorulmemis kat one cikar
        acc = s["accuracy"] if s["accuracy"] is not None else 0.0
        return 1.0 + (1.0 - acc) * 3.0      # dusuk dogruluk -> yuksek agirlik

    # Ustalik agirligi: bilmedigin/tekrar isaretledigin teknikler one cikar.
    # Amac skor degil KAPSAMA -> "known" isaretliler nadiren sorulur.
    _MW = {"new": 1.6, "review": 2.4, "known": 0.25}

    def mastery_weight(a):
        return _MW.get(get_mastery(progress, a.get("id", "")), 1.0)

    weights = [cat_weight(a.get("category", "")) * mastery_weight(a) for a in attacks]
    total = sum(weights)
    if total <= 0:
        return rng.choice(attacks)
    r = rng.uniform(0, total)
    upto = 0.0
    for a, w in zip(attacks, weights):
        upto += w
        if upto >= r:
            return a
    return attacks[-1]


def _bump_day(progress):
    """Gunluk streak'i guncelle. Ilk yanit gunu baslatir; ardisik gunlerde artar."""
    today = date.today().isoformat()
    last = progress.get("last_day")
    if last == today:
        return
    if last is None:
        progress["streak"] = 1
    else:
        try:
            ly, lm, ld = (int(x) for x in last.split("-"))
            delta = (date.today() - date(ly, lm, ld)).days
        except (ValueError, AttributeError):
            delta = 99
        if delta == 1:
            progress["streak"] = progress.get("streak", 0) + 1
        elif delta > 1:
            progress["streak"] = 1
        # delta <= 0 (ayni gun / saat kaymasi): dokunma
    progress["best_streak"] = max(progress.get("best_streak", 0),
                                  progress.get("streak", 0))
    progress["last_day"] = today
    progress["answered_today"] = 0


def record_answer(progress, category, correct):
    """Bir yaniti kaydet ve gunluk/streak sayaclarini guncelle."""
    _bump_day(progress)
    progress["seen"] = progress.get("seen", 0) + 1
    progress["answered_today"] = progress.get("answered_today", 0) + 1
    bc = progress.setdefault("by_category", {})
    rec = bc.setdefault(category, {"seen": 0, "correct": 0})
    rec["seen"] += 1
    if correct:
        progress["correct"] = progress.get("correct", 0) + 1
        rec["correct"] += 1
    return progress


# --------------------------------------------------------------------------
# Icerik buyutme (disaridan JSON iceri aktarma)
# --------------------------------------------------------------------------
def _norm_category(value):
    """'LLM01', 'llm1', '1', 'Prompt Injection' gibi girdileri LLM0X'e cevir."""
    if value is None:
        return None
    v = str(value).strip()
    up = v.upper().replace(" ", "")
    if up in CATEGORIES:
        return up
    # 'LLM1' -> 'LLM01'
    if up.startswith("LLM"):
        num = up[3:]
        if num.isdigit():
            key = "LLM%02d" % int(num)
            if key in CATEGORIES:
                return key
    # sadece sayi
    if up.isdigit():
        key = "LLM%02d" % int(up)
        if key in CATEGORIES:
            return key
    # kategori adiyla eslesme
    for k, name in CATEGORIES.items():
        if name.lower() == v.lower():
            return k
    return None


def _entry_signature(entry):
    """Yinelenen tespiti icin kaba imza: kategori + ornegin ilk 80 karakteri."""
    ex = (entry.get("example", "") or "").strip().lower()
    return (entry.get("category", ""), ex[:80])


def _clean_entry(raw):
    """Ham dict'i sema uyumlu bir kayda cevir. (ok, entry_or_hata_mesaji)"""
    if not isinstance(raw, dict):
        return False, "kayit bir nesne (obje) degil"
    cat = _norm_category(raw.get("category") or raw.get("owasp") or raw.get("kat"))
    if cat is None:
        return False, "gecersiz/eksik category (LLM01-LLM10 olmali)"
    example = (raw.get("example") or raw.get("payload") or raw.get("ornek") or "").strip()
    if not example:
        return False, "example (payload) alani bos"
    technique = (raw.get("technique") or raw.get("teknik") or "Genel").strip()
    how = (raw.get("how_to_use") or raw.get("how") or raw.get("kullanim") or "").strip()
    if not how:
        return False, "how_to_use alani bos"
    story = (raw.get("story") or raw.get("tanim") or raw.get("definition")
             or raw.get("senaryo") or "").strip()
    entry = {
        "id": "",  # ekleme sirasinda atanacak
        "category": cat,
        "category_name": CATEGORIES[cat],
        "technique": technique,
        "story": story,
        "example": example,
        "real_case": (raw.get("real_case") or raw.get("case") or raw.get("ornek_olay") or "").strip(),
        "year": raw.get("year") or raw.get("yil") or "",
        "severity": (str(raw.get("severity") or raw.get("risk") or "MEDIUM")).upper().strip(),
        "why": (raw.get("why") or raw.get("neden") or "").strip(),
        "how_to_use": how,
        "mitigation": (raw.get("mitigation") or raw.get("onlem") or "").strip(),
        "level": ("advanced" if str(raw.get("level") or raw.get("seviye") or "").strip().lower()
                  in ("advanced", "ileri", "adv") else "core"),
        "source": (raw.get("source") or raw.get("kaynak") or "").strip(),
    }
    if entry["severity"] not in SEVERITIES:
        entry["severity"] = "MEDIUM"
    return True, entry


def _next_id(db, cat):
    n = sum(1 for a in db["attacks"] if a.get("category") == cat)
    return "%s-%03d" % (cat, n + 1)


def parse_import_text(text):
    """Yapistirilan metinden kayit listesi cikar.

    Kabul edilen bicimler:
      * {"attacks": [ ... ]}
      * [ {...}, {...} ]
      * tek nesne {...}
    Ayrica metin bir kod blogu (```json ... ```) icine sarilmis olabilir.
    """
    if not text or not text.strip():
        raise ValueError("Bos girdi.")
    s = text.strip()
    # ```json ... ``` veya ``` ... ``` cerçevesini soy
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    # Ilk '{' veya '[' ile son '}' / ']' arasini almayi dene (etraftaki laf icin)
    try:
        data = json.loads(s)
    except ValueError:
        start = min([i for i in (s.find("{"), s.find("[")) if i != -1] or [-1])
        end = max(s.rfind("}"), s.rfind("]"))
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Gecerli JSON bulunamadi.")
        data = json.loads(s[start:end + 1])

    if isinstance(data, dict) and "attacks" in data:
        items = data["attacks"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = [data]
    else:
        raise ValueError("Beklenmeyen JSON yapisi.")
    if not isinstance(items, list):
        raise ValueError("'attacks' bir liste olmali.")
    return items


def import_entries(db, text):
    """Metni ayristir, dogrula, yinelenenleri ele, db'ye ekle ve kaydet.

    Donen: (added, skipped_dupe, errors) -- errors: [(index, mesaj), ...]
    db yerinde guncellenir; en az bir kayit eklendiyse diske yazilir.
    """
    items = parse_import_text(text)
    existing = {_entry_signature(a) for a in db["attacks"]}
    added = 0
    skipped = 0
    errors = []
    for i, raw in enumerate(items):
        ok, res = _clean_entry(raw)
        if not ok:
            errors.append((i, res))
            continue
        sig = _entry_signature(res)
        if sig in existing:
            skipped += 1
            continue
        res["id"] = _next_id(db, res["category"])
        db["attacks"].append(res)
        existing.add(sig)
        added += 1
    if added:
        save_attacks(db)
    return added, skipped, errors


# --------------------------------------------------------------------------
# Baska bir AI'ya verilecek uretici prompt
# --------------------------------------------------------------------------
# Uretimin yaslanacagi guvenilir kaynaklar (halusinasyona karsi capa).
TRUSTED_SOURCES = (
    "MITRE ATLAS (atlas.mitre.org) — AI saldiri taksonomisi",
    "OWASP GenAI / LLM Top 10 (genai.owasp.org)",
    "NVIDIA garak (github.com/NVIDIA/garak) — LLM zafiyet tarama problari",
    "Microsoft PyRIT (github.com/Azure/PyRIT) — red team otomasyonu",
    "AI Vulnerability Database — AVID (avidml.org)",
    "MITRE ATT&CK (tedarik zinciri / cikti isleme icin)",
)


def generator_prompt(count=10, category=None, existing_names=None):
    """Kullanicinin baska bir AI'a (Claude/Kimi/vb.) yapistirip yeni ornek
    uretecegi prompt. Guvenilir kaynaklara yaslanir, mukerrer engeller,
    istege bagli olarak tek bir kategoriyi hedefler.

    category      : "LLM01".."LLM10" ise sadece o kat icin uretir; None = hepsi
    existing_names: kutuphanede zaten olan teknik adlari (mukerrer onlemek icin)
    """
    src_lines = "\n".join("  - " + s for s in TRUSTED_SOURCES)

    if category and category in CATEGORIES:
        hedef = ("SADECE su kategori icin uret:\n  %s = %s\n"
                 "(Her ornekte \"category\": \"%s\" olacak.)"
                 % (category, CATEGORIES[category], category))
    else:
        cat_lines = "\n".join("  %s = %s" % (k, v) for k, v in CATEGORIES.items())
        hedef = ("Su 10 kategoriye DENGELI dagit "
                 "(zayif/az ornekli katlara agirlik ver):\n" + cat_lines)

    haric = ""
    if existing_names:
        adlar = ", ".join(sorted(set(existing_names)))
        haric = ("\nKUTUPHANEDE ZATEN OLANLAR (bunlari TEKRAR URETME, "
                 "farkli/yeni teknikler bul):\n" + adlar + "\n")

    return (
        "Sen kidemli bir AI red-team uzmanisin. Asagidaki OWASP GenAI LLM "
        "kategorileri icin GERCEK, egitici saldiri teknikleri uret.\n\n"
        "== KAYNAK KURALI (EN ONEMLISI) ==\n"
        "Teknikleri UYDURMA. Yalnizca su guvenilir kaynaklarda/literaturde "
        "gercekten var olan teknikleri kullan:\n" + src_lines + "\n"
        "Her teknik icin 'source' alanina GERCEK bir kaynak (URL/makale/CVE) "
        "yaz. Emin degilsen o teknigi ekleme; uydurma bilgi verme.\n\n"
        "== HEDEF ==\n" + hedef + "\n" + haric + "\n"
        "TAM olarak %d adet uret. Cikti SADECE gecerli JSON olsun (baska "
        "aciklama yazma). Su semaya birebir uy:\n\n"
        "{\n"
        '  "attacks": [\n'
        "    {\n"
        '      "category": "LLM01",              // LLM01..LLM10\n'
        '      "technique": "kisa teknik adi (Ingilizce literatur adi olabilir)",\n'
        '      "story": "SENARYO: hangi sistem/bota ne yapildi, saldirgan ne yapti, ne oldu (2-4 cumle, Turkce). Kategori adini YAZMA.",\n'
        '      "example": "gercek payload / saldiri kalibi",\n'
        '      "real_case": "biliniyorsa gercek olay/yil (yoksa bos)",\n'
        '      "year": 2024,\n'
        '      "severity": "LOW|MEDIUM|HIGH|CRITICAL",\n'
        '      "why": "neden calisir - 1 cumle",\n'
        '      "how_to_use": "savunmada/tanimada nasil kullanirim - somut, Turkce",\n'
        '      "mitigation": "onlem - 1 cumle",\n'
        '      "level": "core (temel) VEYA advanced (az bilinen/ileri)",\n'
        '      "source": "GERCEK kaynak: URL / makale / CVE / ATLAS teknik no"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "== KURALLAR ==\n"
        "- 'source' HER kayitta dolu ve gercek olsun (uydurma link YASAK).\n"
        "- Az bilinen ama gercek GUCLU teknikleri tercih et; 'level':'advanced' isaretle.\n"
        "- 'story' en onemli alan: gercek/gercekci somut olay anlat "
        "('falanca bota sunu yaptilar, soyle oldu'). Icinde OWASP kategori "
        "adini (orn. 'Prompt Injection') YAZMA ki quizde tahmin edilebilsin.\n"
        "- 'example' egitim amacli gercek saldiri kalibi olsun.\n"
        "- Ayni teknigi tekrar etme; yukaridaki 'zaten olanlar' listesinden kacin.\n"
        "- Sadece tek bir JSON dondur.\n"
    ) % count
