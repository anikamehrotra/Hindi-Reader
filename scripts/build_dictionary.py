"""Build data/dictionary.sqlite from the kaikki.org Wiktionary Hindi extract.

    python scripts/build_dictionary.py            # downloads the extract if missing

Tables
  entries(word, pos, roman, data)   one row per headword+part of speech; data is JSON
  forms(form, lemma, pos, gram)     every inflected form -> its dictionary word
  roman(form, roman)                Wiktionary's own romanization for any form
  phrases(phrase, first, n, idiomatic, gloss)   multi-word entries, for idiom matching
"""
import json
import os
import sqlite3
import sys
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "wiktionary-hindi.jsonl")
OUT = os.path.join(ROOT, "data", "dictionary.sqlite")
URL = "https://kaikki.org/dictionary/Hindi/kaikki.org-dictionary-Hindi.jsonl"

GRAM_ABBR = {
    "masculine": "m", "feminine": "f", "singular": "sg", "plural": "pl",
    "direct": "dir", "oblique": "obl", "vocative": "voc",
    "perfective": "perf", "habitual": "hab", "progressive": "prog",
    "infinitive": "inf", "conjunctive": "conj.ptcp", "agentive": "agent",
    "subjunctive": "subj", "future": "fut", "imperative": "imp", "past": "past",
    "present": "pres", "presumptive": "presum", "contrafactual": "contrafact",
    "first-person": "1", "second-person": "2", "third-person": "3",
    "stem": "stem", "participle": "ptcp", "adverbial": "adv",
    "intimate": "intim", "familiar": "fam", "formal": "formal",
}
SKIP_TAGS = {"table-tags", "inflection-template", "class", "romanization", "Urdu"}
ORIGIN = {"sa": "Sanskrit", "fa": "Persian", "ar": "Arabic", "en": "English", "pt": "Portuguese",
          "tr": "Turkish", "ota": "Ottoman Turkish", "chg": "Chagatai", "pra": "Prakrit",
          "inc-ohi": "Old Hindi", "fr": "French", "nl": "Dutch", "ur": "Urdu"}


def nfc(s):
    return unicodedata.normalize("NFC", s)


def gram(tags):
    return ".".join(GRAM_ABBR.get(t, t) for t in tags if t not in SKIP_TAGS)


def origin(e):
    """A one-word origin label from the etymology templates: (kind, language)."""
    for t in e.get("etymology_templates", []):
        name, args = t.get("name"), t.get("args", {})
        if name in ("bor", "lbor", "bor+", "der", "inh", "inh+", "ubor", "slbor", "psm"):
            lang = ORIGIN.get(args.get("2"))
            if lang:
                kind = {"lbor": "learned borrowing", "inh": "inherited", "inh+": "inherited",
                        "der": "derived"}.get(name, "borrowed")
                return f"{kind} from {lang}"
    return None


def short_etym(text):
    if not text:
        return None
    # the tree dump comes first; the prose sentence is the last line
    line = text.strip().splitlines()[-1]
    return line if len(line) <= 280 else line[:277] + "…"


def main():
    if not os.path.exists(RAW):
        os.makedirs(os.path.dirname(RAW), exist_ok=True)
        print("downloading", URL)
        urllib.request.urlretrieve(URL, RAW)

    if os.path.exists(OUT):
        os.remove(OUT)
    db = sqlite3.connect(OUT)
    db.executescript("""
        CREATE TABLE entries(word TEXT, pos TEXT, roman TEXT, data TEXT);
        CREATE TABLE forms(form TEXT, lemma TEXT, pos TEXT, gram TEXT);
        CREATE TABLE roman(form TEXT PRIMARY KEY, roman TEXT);
        CREATE TABLE phrases(phrase TEXT, first TEXT, n INTEGER, idiomatic INTEGER, gloss TEXT);
    """)
    forms, roman, n_entries = set(), {}, 0

    with open(RAW, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            word, pos = nfc(e["word"]), e["pos"]
            if pos in ("character", "punct", "symbol"):
                continue
            head_roman = next((nfc(x["form"]) for x in e.get("forms", [])
                               if "romanization" in x.get("tags", [])), None)
            urdu = next((x["form"] for x in e.get("forms", []) if "Urdu" in x.get("tags", [])), None)
            if head_roman and " " not in word:
                roman.setdefault(word, head_roman)

            senses, idiomatic = [], False
            for s in e.get("senses", []):
                tags = s.get("tags", [])
                if "form-of" in tags or s.get("form_of"):
                    for fo in s.get("form_of", []):
                        lemma = nfc(fo["word"])
                        forms.add((word, lemma, pos, gram([t for t in tags if t != "form-of"])))
                    continue
                gl = s.get("glosses") or s.get("raw_glosses")
                if not gl:
                    continue
                if "idiomatic" in tags:
                    idiomatic = True
                senses.append({
                    "gloss": ": ".join(gl) if len(gl) > 1 else gl[0],
                    "tags": [t for t in tags if t in ("idiomatic", "figuratively", "colloquial",
                                                      "formal", "literary", "archaic", "rare",
                                                      "transitive", "intransitive", "slang",
                                                      "derogatory", "poetic", "dated")],
                })
            if senses:
                gender = next((t for t in ("masculine", "feminine")
                               if any(t in s.get("tags", []) for s in e.get("senses", []))), None)
                data = {"senses": senses[:10], "gender": gender, "urdu": urdu,
                        "origin": origin(e), "etym": short_etym(e.get("etymology_text"))}
                db.execute("INSERT INTO entries VALUES (?,?,?,?)",
                           (word, pos, head_roman, json.dumps(data, ensure_ascii=False)))
                n_entries += 1
                forms.add((word, word, pos, "lemma"))
                parts = word.split()
                if len(parts) > 1:
                    db.execute("INSERT INTO phrases VALUES (?,?,?,?,?)",
                               (word, parts[0], len(parts),
                                int(idiomatic or pos == "proverb"),
                                senses[0]["gloss"]))

            for x in e.get("forms", []):
                if x.get("source") not in ("declension", "conjugation", "inflection"):
                    continue
                if set(x.get("tags", [])) & {"table-tags", "inflection-template", "class"}:
                    continue
                form = nfc(x["form"])
                if not form or form == "-" or " " in form:
                    continue
                forms.add((form, word, pos, gram(x.get("tags", []))))
                if x.get("roman"):
                    roman.setdefault(form, nfc(x["roman"]))

    db.executemany("INSERT INTO forms VALUES (?,?,?,?)", sorted(forms))
    db.executemany("INSERT INTO roman VALUES (?,?)", roman.items())
    db.executescript("""
        CREATE INDEX i_entries ON entries(word);
        CREATE INDEX i_forms ON forms(form);
        CREATE INDEX i_phrases ON phrases(first);
    """)
    db.commit()
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("entries", "forms", "roman", "phrases")}
    db.execute("VACUUM")
    db.close()
    print(counts, f"{os.path.getsize(OUT) / 1e6:.1f} MB")


if __name__ == "__main__":
    sys.exit(main())
