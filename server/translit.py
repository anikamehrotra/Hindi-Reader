"""Devanagari -> scholarly romanization, matching Wiktionary's Hindi scheme.

Used only for words the Wiktionary tables don't already romanize. The hard part
of Hindi transliteration is schwa deletion (कमरा is kamrā, not kamarā), handled
by the standard right-to-left rule  a -> 0 / VC_CV  plus word-final deletion.
"""
import unicodedata

CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ṅ",
    "च": "c", "छ": "ch", "ज": "j", "झ": "jh", "ञ": "ñ",
    "ट": "ṭ", "ठ": "ṭh", "ड": "ḍ", "ढ": "ḍh", "ण": "ṇ",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "ळ": "ḷ", "व": "v",
    "श": "ś", "ष": "ṣ", "स": "s", "ह": "h",
}
NUKTA_CONS = {
    "क": "q", "ख": "x", "ग": "ġ", "ज": "z", "झ": "ž", "ड": "ṛ", "ढ": "ṛh",
    "फ": "f", "न": "ṉ", "र": "ṟ", "य": "ẏ",
}
VOWELS = {
    "अ": "a", "आ": "ā", "इ": "i", "ई": "ī", "उ": "u", "ऊ": "ū", "ऋ": "ŕ",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऍ": "ê", "ऑ": "ŏ", "ॠ": "ṝ",
}
MATRAS = {
    "ा": "ā", "ि": "i", "ी": "ī", "ु": "u", "ू": "ū", "ृ": "ŕ",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "ê", "ॉ": "ŏ", "ॄ": "ṝ",
}
VIRAMA, NUKTA, ANUSVARA, CANDRABINDU, VISARGA = "्", "़", "ं", "ँ", "ः"
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
PUNCT = {"।": ".", "॥": ".", "ऽ": "'", "ॐ": "om"}
TILDE = "̃"

# anusvara before a stop takes the nasal of that stop's class
_CLASS_NASAL = {}
for nasal, row in (("ṅ", "कखगघ"), ("ñ", "चछजझ"), ("ṇ", "टठडढ"), ("n", "तथदध"), ("m", "पफबभ")):
    for c in row:
        _CLASS_NASAL[c] = nasal


_VOICED = set("गघजझडढदधबभ")


def _nasalize(v):
    # ai/au take a double tilde spanning both letters, as Wiktionary writes them (a͠i)
    if v in ("ai", "au"):
        return v[0] + "͠" + v[1]
    return v + TILDE


def _parse(word):
    """Split into units: ('C', roman, base) consonants, ('V', roman, explicit) vowels,
    ('N', mark) nasal marks, ('X', text) anything else."""
    units, i, n = [], 0, len(word)
    while i < n:
        ch = word[i]
        if ch in CONS:
            nukta = i + 1 < n and word[i + 1] == NUKTA
            rom = NUKTA_CONS.get(ch, CONS[ch]) if nukta else CONS[ch]
            i += 2 if nukta else 1
            units.append(("C", rom, ch))
            if i < n and word[i] in MATRAS:
                units.append(("V", MATRAS[word[i]], True)); i += 1
            elif i < n and word[i] == VIRAMA:
                i += 1  # bare consonant, no vowel
            else:
                units.append(("V", "a", False))  # inherent schwa
        elif ch in VOWELS:
            units.append(("V", VOWELS[ch], True)); i += 1
        elif ch in (ANUSVARA, CANDRABINDU):
            units.append(("N", ch)); i += 1
        elif ch == VISARGA:
            units.append(("X", "ḥ")); i += 1
        elif ch in DIGITS:
            units.append(("X", DIGITS[ch])); i += 1
        elif ch in PUNCT:
            units.append(("X", PUNCT[ch])); i += 1
        elif ch in ("‌", "‍"):
            i += 1
        else:
            units.append(("X", ch)); i += 1
    return units


def _delete_schwas(units):
    """Mark inherent schwas that are silent. Returns set of unit indexes to drop."""
    drop = set()
    vowel_idx = [k for k, u in enumerate(units) if u[0] == "V"]
    if not vowel_idx:
        return drop
    # word-final: drop unless it's the only vowel, or it follows a conjunct (mitra, viśva)
    last = vowel_idx[-1]
    if units[last] == ("V", "a", False) and len(vowel_idx) > 1 and last == len(units) - 1:
        cons_before = 0
        k = last - 1
        while k >= 0 and units[k][0] == "C":
            cons_before += 1; k -= 1
        after_i_y = units[last - 1][1] == "y" and last >= 2 and units[last - 2][1] in ("i", "ī")
        if cons_before < 2 and not after_i_y:
            drop.add(last)
    # medial: a -> 0 / V C _ C V, scanning right to left
    for pos in reversed(vowel_idx[1:-1]):
        u = units[pos]
        if u != ("V", "a", False) or pos in drop:
            continue
        if pos + 1 < len(units) and units[pos + 1][0] == "N":
            continue  # nasalized schwa stays
        # exactly one consonant on each side, a sounding vowel beyond each
        if not (pos - 2 >= 0 and units[pos - 1][0] == "C" and units[pos - 2][0] in ("V", "N")):
            continue
        prev_v = pos - 2 if units[pos - 2][0] == "V" else pos - 3
        if prev_v < 0 or units[prev_v][0] != "V" or prev_v in drop:
            continue
        if not (pos + 2 < len(units) and units[pos + 1][0] == "C" and units[pos + 2][0] == "V"):
            continue
        if pos + 2 in drop:
            continue
        drop.add(pos)
    return drop


def transliterate(word):
    word = unicodedata.normalize("NFC", word)
    if "-" in word:
        return "-".join(transliterate(p) for p in word.split("-"))
    units = _parse(word)
    drop = _delete_schwas(units)
    out = []
    for k, u in enumerate(units):
        if k in drop:
            continue
        kind = u[0]
        if kind == "C":
            out.append(u[1])
        elif kind == "V":
            out.append(u[1])
        elif kind == "N":
            nxt = units[k + 1] if k + 1 < len(units) else None
            prev = out[-1] if out else ""
            stop_next = nxt and nxt[0] == "C" and nxt[2] in _CLASS_NASAL
            # before a voiced stop the nasal is always a consonant (āñjnā, ṭāṅg, -eṅge);
            # before a voiceless one only anusvara makes it one (kāmpnā vs ā̃kh)
            if stop_next and (nxt[2] in _VOICED or (u[1] == ANUSVARA and prev in ("a", "i", "u", "ā"))):
                out.append(_CLASS_NASAL[nxt[2]])
            elif u[1] == ANUSVARA and prev in ("a", "i", "u") and nxt and nxt[0] == "C":
                out.append("n" if nxt[2] in "सशष" else "ṃ")
            elif out and out[-1] and out[-1][-1] in "aāiīuūeoŕêŏ":
                out[-1] = _nasalize(out[-1]) if len(out[-1]) <= 2 else out[-1] + TILDE
            else:
                out.append("ṃ")
        else:
            out.append(u[1])
    return unicodedata.normalize("NFC", "".join(out))
