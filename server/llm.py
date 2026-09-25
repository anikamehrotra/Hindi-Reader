"""OpenRouter calls: paragraph annotation, selection translation, page OCR."""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
URL = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")


def api_key():
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH, encoding="utf-8"):
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def save_api_key(key):
    lines = []
    if os.path.exists(ENV_PATH):
        lines = [l for l in open(ENV_PATH, encoding="utf-8") if not l.startswith("OPENROUTER_API_KEY=")]
    lines.append(f"OPENROUTER_API_KEY={key.strip()}\n")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


class LLMError(Exception):
    pass


def chat(model, messages, json_mode=False, max_tokens=8000, temperature=0.2):
    """Returns (text, cost_usd)."""
    key = api_key()
    if not key:
        raise LLMError("no OpenRouter key yet -- add one in Settings")
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "usage": {"include": True}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost", "X-Title": "Hindi Reader"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read())
            if "error" in data:
                raise LLMError(data["error"].get("message", str(data["error"])))
            text = data["choices"][0]["message"].get("content") or ""
            cost = (data.get("usage") or {}).get("cost") or 0
            return text, cost
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:400]
            last = LLMError(f"{e.code}: {msg}")
            if e.code in (400, 401, 402, 403, 404):
                raise last
        except (urllib.error.URLError, TimeoutError) as e:
            last = LLMError(str(e))
        time.sleep(2 * (attempt + 1))
    raise last


def parse_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


ANNOTATE_SYSTEM = """You annotate Hindi literary prose for a heritage-speaker reader at an advanced intermediate level (reading short stories, e.g. Premchand).

You get one paragraph. Every word token is shown as  <index>:<word>  sometimes followed by [dictionary forms we found]. Return ONLY a JSON object:

{
  "translation": "a faithful, natural English translation of the paragraph",
  "words": [[index, "meaning in this sentence", "dictionary form", "grammar"], ...],
  "units": [{"idx": [indexes], "type": "...", "literal": "...", "meaning": "...", "note": "..."}]
}

words -- one entry for EVERY word index, in order.
  - meaning: the English sense this word has *here*, 1-5 words. For postpositions/particles give the function ("of", "emphatic: only", "polite verb ending").
  - dictionary form: the Hindi headword in Devanagari (infinitive for verbs: गया -> जाना; direct singular for nouns/adjectives: लड़कियों -> लड़की). Same as the word if already the base form.
  - grammar: very short, e.g. "perf. m.sg", "obl. pl", "fut. 3sg f", "conj. participle ('having done')", "" if nothing useful.

units -- multi-word expressions where the words together mean something the parts don't. idx may be non-contiguous (an idiom split by an object). type is one of:
  - "idiom": muhavara / fixed figurative expression (आँखें चुराना, नाक कटना, हाथ धो बैठना, दाल में काला)
  - "proverb": lokokti / saying
  - "compound_verb": main verb + vector verb (खा लिया, बैठ गया, रो पड़ी) -- note what the vector adds
  - "conjunct_verb": noun/adjective + करना/होना/लेना/देना etc. (इंतज़ार करना, पसंद आना)
  - "postposition": compound postposition (के बारे में, की ओर, के बावजूद)
  - "phrase": any other set phrase or collocation worth learning
  literal: word-for-word English (for idioms/proverbs especially). meaning: what it actually means here. note: register, nuance, or origin if genuinely useful, else "".
Be generous with compound_verb / conjunct_verb / postposition, and precise with idiom / proverb -- only real figurative idioms and sayings get those two labels.
No commentary outside the JSON."""


def annotate_paragraph(model, para_tokens, hints, prev_text=""):
    """para_tokens: list of (index, word). hints: index -> list of dictionary forms."""
    parts = []
    for i, w in para_tokens:
        h = hints.get(i)
        parts.append(f"{i}:{w}" + (f"[{','.join(h[:3])}]" if h else ""))
    user = ""
    if prev_text:
        user += f"(Previous paragraph, for context only -- do not annotate:)\n{prev_text[-600:]}\n\n"
    user += "Paragraph:\n" + " ".join(parts)
    msgs = [{"role": "system", "content": ANNOTATE_SYSTEM}, {"role": "user", "content": user}]
    text, cost = chat(model, msgs, json_mode=True, max_tokens=16000)
    try:
        data = parse_json(text)
    except Exception:
        # one retry with a nudge; models occasionally truncate or wrap the JSON
        text, cost2 = chat(model, msgs + [{"role": "assistant", "content": text[:2000]},
                                          {"role": "user", "content": "That was not valid JSON. Return the complete JSON object only."}],
                           json_mode=True, max_tokens=16000)
        cost += cost2
        data = parse_json(text)
    return data, cost


TRANSLATE_SYSTEM = """You help a heritage Hindi speaker read literature. They highlighted a passage. Return ONLY JSON:
{"translation": "natural English", "literal": "closer word-for-word rendering, only if it differs meaningfully, else \\"\\"", "notes": ["short notes on idioms, grammar, cultural references or tricky words in the passage -- 0 to 4 items"]}"""


def translate_selection(model, selection, context):
    user = f"Context (surrounding text):\n{context}\n\nHighlighted passage:\n{selection}"
    text, cost = chat(model, [{"role": "system", "content": TRANSLATE_SYSTEM}, {"role": "user", "content": user}],
                      json_mode=True, max_tokens=2000)
    return parse_json(text), cost


OCR_PROMPT = """Transcribe the Hindi text on this scanned page exactly, in Unicode Devanagari.
- Keep the author's spelling and punctuation (।, ॥, quotation marks).
- Line breaks: do NOT reproduce the printed line breaks. Every paragraph must be one single line of text, however many lines it takes up on the page. The only newlines in your output are paragraph breaks, written as one blank line between paragraphs. A new paragraph is where the printed text starts a new indented line or leaves a gap -- not wherever a printed line happens to end.
- Undo end-of-line hyphenation (a word split across two printed lines becomes one word).
- Leave out running headers, page numbers and footnote markers.
- If a word is unreadable write [?].
Output only the transcription, nothing else."""


def unwrap_lines(text):
    """Safety net for models that still copy the printed line breaks: when the output
    marks paragraphs with blank lines, any single newline is just a wrapped line."""
    text = text.replace("\r\n", "\n").strip()
    if not re.search(r"\n\s*\n", text):
        return text
    paras = re.split(r"\n\s*\n", text)
    return "\n\n".join(re.sub(r"\s*\n\s*", " ", p).strip() for p in paras if p.strip())


def ocr_page(model, jpeg_bytes):
    b64 = base64.b64encode(jpeg_bytes).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": OCR_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    text, cost = chat(model, msgs, max_tokens=8000, temperature=0)
    text = re.sub(r"^```\w*\n?|```$", "", text.strip()).strip()
    return unwrap_lines(text), cost
