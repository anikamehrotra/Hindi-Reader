"""Lookups against data/dictionary.sqlite (built by scripts/build_dictionary.py)."""
import json
import os
import re
import sqlite3
import threading
import unicodedata

from translit import transliterate

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dictionary.sqlite")

# endings tried when a form isn't in the tables at all (rare words, OCR variants)
SUFFIXES = sorted(["ों", "ें", "ाओं", "ियों", "ियाँ", "ियां", "ओं", "ाएँ", "ाएं", "एँ", "एं",
                   "ीं", "े", "ी", "ा", "ो", "ना", "ने", "नी", "कर", "के", "ता", "ते", "ती",
                   "या", "ये", "ई", "ए", "ईं", "ूँगा", "ेगा", "ेगी", "ेंगे", "ोगे"], key=len, reverse=True)
_ALT = re.compile(r"^(?:nuqtaless form|alternative (?:form|spelling)|obsolete (?:form|spelling)|"
                  r"misspelling|nonstandard (?:form|spelling)|synonym) of (\S+)")
POS_ORDER = {"verb": 0, "postp": 1, "pron": 1, "particle": 1, "conj": 1, "det": 1,
             "adv": 2, "adj": 2, "noun": 3, "name": 9}


def nfc(s):
    return unicodedata.normalize("NFC", s)


def variants(w):
    """Spelling variants Hindi texts use interchangeably."""
    out = [w]
    swaps = [("ँ", "ं"), ("ं", "ँ"), ("ये", "ए"), ("ए", "ये"), ("यी", "ई"), ("ई", "यी"), ("़", "")]
    for a, b in swaps:
        if a in w:
            out.append(w.replace(a, b))
    return list(dict.fromkeys(out))


class Dictionary:
    def __init__(self, path=DB_PATH):
        self.ok = os.path.exists(path)
        self._local = threading.local()
        self.path = path
        self.phrases_by_first = {}
        if self.ok:
            for phrase, first, n, idiomatic, gloss in self._db().execute(
                    "SELECT phrase, first, n, idiomatic, gloss FROM phrases"):
                self.phrases_by_first.setdefault(first, []).append(
                    {"words": phrase.split(), "idiomatic": bool(idiomatic), "gloss": gloss, "phrase": phrase})

    def _db(self):
        if not hasattr(self._local, "db"):
            self._local.db = sqlite3.connect(self.path, check_same_thread=False)
        return self._local.db

    def roman(self, w):
        w = nfc(w)
        if self.ok:
            for v in variants(w):
                row = self._db().execute("SELECT roman FROM roman WHERE form=?", (v,)).fetchone()
                if row:
                    return row[0]
            # known stem + ending: romanize the stem the dictionary's way
            for suf in SUFFIXES:
                if w.endswith(suf) and len(w) > len(suf) + 1:
                    row = self._db().execute("SELECT roman FROM roman WHERE form=?", (w[:-len(suf)],)).fetchone()
                    if row and not row[0].endswith("a"):
                        tail = transliterate("क" + suf)[1:] if suf[0] in "ािीुूेैोौंँ" else transliterate(suf)
                        return row[0] + tail
        return transliterate(w)

    def entry(self, lemma, follow=True):
        rows = self._db().execute("SELECT pos, roman, data FROM entries WHERE word=?", (lemma,)).fetchall()
        out = []
        for pos, roman, data in rows:
            d = json.loads(data)
            d.update(pos=pos, roman=roman or transliterate(lemma), word=lemma)
            # "nuqtaless form of ज़्यादा" -> show ज़्यादा's meanings instead of the pointer
            m = _ALT.match(d["senses"][0]["gloss"]) if d["senses"] else None
            if follow and m and len(d["senses"]) == 1:
                target = next((t for t in self.entry(nfc(m.group(1)), follow=False) if t["pos"] == pos), None)
                if target:
                    d["senses"] = target["senses"]
                    d["see"] = target["word"]
                    d["origin"] = d.get("origin") or target.get("origin")
                    d["etym"] = d.get("etym") or target.get("etym")
            out.append(d)
        return out

    def analyze(self, w):
        """Everything the popup needs for one surface form, minus context."""
        w = nfc(w)
        result = {"roman": self.roman(w), "lemmas": [], "guess": False}
        if not self.ok:
            return result
        found = []
        for v in variants(w):
            found = self._db().execute("SELECT lemma, pos, gram FROM forms WHERE form=?", (v,)).fetchall()
            if found:
                break
        if not found:
            for suf in SUFFIXES:
                if w.endswith(suf) and len(w) > len(suf) + 1:
                    stem = w[:-len(suf)]
                    for cand in (stem, stem + "ा", stem + "ना", stem + "ी"):
                        rows = self._db().execute("SELECT lemma, pos, gram FROM forms WHERE form=? AND gram='lemma'",
                                                  (cand,)).fetchall()
                        if rows:
                            found = rows
                            result["guess"] = True
                            break
                if found:
                    break
        # group by (lemma, pos), keep the most specific grammar label
        grouped = {}
        for lemma, pos, g in found:
            key = (lemma, pos)
            best = grouped.get(key)
            if best is None or (g != "lemma" and (best == "lemma" or len(g) > len(best))):
                grouped[key] = g
        lemmas = []
        for (lemma, pos), g in grouped.items():
            for e in self.entry(lemma):
                if e["pos"] == pos:
                    e["gram"] = "" if g == "lemma" else g
                    lemmas.append(e)
                    break
        lemmas.sort(key=lambda e: (e["pos"] == "name", e["word"] != w, POS_ORDER.get(e["pos"], 6)))
        result["lemmas"] = lemmas[:4]
        return result

    def match_phrases(self, words, lemmas):
        """Find multi-word Wiktionary entries in a paragraph.
        words: list of (token_index, surface); lemmas: token_index -> set of lemma candidates."""
        units = []
        for k, (ti, surface) in enumerate(words):
            keys = {surface} | lemmas.get(ti, set())
            for key in keys:
                for ph in self.phrases_by_first.get(key, []):
                    n = len(ph["words"])
                    if k + n > len(words):
                        continue
                    ok = True
                    for j in range(1, n):
                        tj, sj = words[k + j]
                        if ph["words"][j] != sj and ph["words"][j] not in lemmas.get(tj, set()):
                            ok = False
                            break
                    if ok:
                        units.append({"idx": [words[k + j][0] for j in range(n)],
                                      "type": "idiom" if ph["idiomatic"] else "phrase",
                                      "meaning": ph["gloss"], "literal": "", "note": f"Wiktionary: {ph['phrase']}",
                                      "source": "wiktionary"})
        return units
