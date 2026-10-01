"""Hindi Reader -- local server.   python server/app.py   then open http://localhost:8765"""
import json
import mimetypes
import os
import random
import re
import string
import sys
import threading
import time
import traceback
import unicodedata
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache  # noqa: E402
import llm  # noqa: E402
from dictionary import Dictionary  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
LIBRARY = os.path.join(ROOT, "data", "library")
SETTINGS_PATH = os.path.join(ROOT, "data", "settings.json")
PORT = int(os.environ.get("PORT", 8765))

DEFAULT_SETTINGS = {
    "models": {
        "annotate": "google/gemini-2.5-flash",
        "translate": "google/gemini-2.5-flash",
        "ocr": "google/gemini-2.5-flash",
    },
}
# shown in the settings dropdowns; any OpenRouter model id can also be typed in
MODEL_CHOICES = [
    {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash -- default; best measured Devanagari OCR", "price": "$0.30 / $2.50"},
    {"id": "google/gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite -- cheapest good option", "price": "$0.25 / $1.50"},
    {"id": "google/gemini-3.8-flash", "label": "Gemini 3.8 Flash -- newest Flash", "price": "$0.75 / $3.75"},
    {"id": "openai/gpt-5-mini", "label": "GPT-5 mini (translation only -- weak at Devanagari OCR)", "price": "$0.25 / $2.00"},
    {"id": "anthropic/claude-haiku-4.5", "label": "Claude Haiku 4.5", "price": "$1.00 / $5.00"},
    {"id": "anthropic/claude-sonnet-5", "label": "Claude Sonnet 5 -- best quality, pricier", "price": "$2.00 / $10.00"},
    {"id": "google/gemma-4-31b-it", "label": "Gemma 4 31B -- open weights", "price": "$0.09 / $0.34"},
    {"id": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash -- open weights, no images", "price": "$0.08 / $0.16"},
    {"id": "qwen/qwen3.5-397b-a17b", "label": "Qwen 3.5 397B -- open weights", "price": "$0.55 / $3.50"},
]

DICT = Dictionary()
POOL = ThreadPoolExecutor(max_workers=4)
LOCKS = {}
LOCKS_GUARD = threading.Lock()

WORD_RE = r"[ऀ-ॣॱ-ॿ‌‍]+(?:-[ऀ-ॣॱ-ॿ‌‍]+)*"
TOKEN_RE = re.compile(rf"(?P<w>{WORD_RE})|(?P<x>[A-Za-z][A-Za-z'’]*)|(?P<n>[0-9०-९]+(?:[.,][0-9०-९]+)*)|(?P<s>\s+)|(?P<p>.)")
SENTENCE_END = {"।", "॥", "?", "!", "."}
CHUNK_WORDS = 160


# ---------------------------------------------------------------- storage

def settings():
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if os.path.exists(SETTINGS_PATH):
        saved = json.load(open(SETTINGS_PATH, encoding="utf-8"))
        s["models"].update(saved.get("models", {}))
    return s


def lock_for(doc_id):
    with LOCKS_GUARD:
        return LOCKS.setdefault(doc_id, threading.RLock())


def doc_path(doc_id):
    if not re.fullmatch(r"[\w-]+", doc_id):
        raise KeyError(doc_id)
    return os.path.join(LIBRARY, doc_id + ".json")


def load(doc_id):
    # reads take the lock too: on Windows a file open for reading can't be replaced
    with lock_for(doc_id), open(doc_path(doc_id), encoding="utf-8") as f:
        return json.load(f)


def save(doc):
    path = doc_path(doc["id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    # antivirus / indexers can still hold the file for a moment
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


def update(doc_id, fn):
    """Read-modify-write a document under its lock."""
    with lock_for(doc_id):
        doc = load(doc_id)
        fn(doc)
        doc["updated"] = time.time()
        save(doc)
        return doc


def new_id():
    return time.strftime("%Y%m%d-%H%M%S-") + "".join(random.choices(string.ascii_lowercase, k=4))


def summary(doc):
    paras = doc.get("paragraphs", [])
    words = sum(1 for p in paras for t in p["tokens"] if t["k"] == "w")
    done = sum(1 for p in paras if p.get("ann", {}).get("status") == "done")
    return {"id": doc["id"], "title": doc["title"], "created": doc["created"], "status": doc["status"],
            "words": words, "paragraphs": len(paras), "annotated": done, "cost": round(doc.get("cost", 0), 4),
            "notes": len(doc.get("notes", [])), "source": doc.get("source")}


# ---------------------------------------------------------------- text -> tokens -> dictionary

def clean_text(text):
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("﻿", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def tokenize(paragraph):
    toks = []
    for m in TOKEN_RE.finditer(paragraph):
        toks.append({"t": m.group(), "k": m.lastgroup})
    return toks


def build_paragraphs(text):
    paras = [p.strip() for p in re.split(r"\n\s*\n", clean_text(text)) if p.strip()]
    return [{"tokens": tokenize(p), "units": [], "ann": {"status": "pending"}} for p in paras]


def dictionary_pass(doc):
    """Attach dictionary analysis for every distinct word and the Wiktionary phrase matches."""
    forms = doc.setdefault("dict", {})
    entries = doc.setdefault("entries", {})
    for p in doc["paragraphs"]:
        for t in p["tokens"]:
            if t["k"] == "w" and t["t"] not in forms:
                a = DICT.analyze(t["t"])
                forms[t["t"]] = {"roman": a["roman"], "guess": a["guess"],
                                 "lemmas": [{"word": l["word"], "pos": l["pos"], "gram": l["gram"]} for l in a["lemmas"]]}
                for l in a["lemmas"]:
                    entries.setdefault(l["word"], [])
                    if not any(e["pos"] == l["pos"] for e in entries[l["word"]]):
                        entries[l["word"]].append({k: v for k, v in l.items() if k != "gram"})
    for p in doc["paragraphs"]:
        words = [(i, t["t"]) for i, t in enumerate(p["tokens"]) if t["k"] == "w"]
        lemmas = {i: {l["word"] for l in forms[w]["lemmas"]} for i, w in words}
        p["units"] = DICT.match_phrases(words, lemmas)


def add_llm_lemmas(doc, words):
    entries = doc.setdefault("entries", {})
    for v in words.values():
        lemma = v[1] if len(v) > 1 else None
        if lemma and lemma not in entries:
            found = DICT.entry(unicodedata.normalize("NFC", lemma))
            entries[lemma] = found  # [] means "looked, not in Wiktionary"


# ---------------------------------------------------------------- background jobs

def chunks(tokens):
    """Split a paragraph's word tokens into ~CHUNK_WORDS pieces at sentence ends."""
    out, cur = [], []
    for i, t in enumerate(tokens):
        if t["k"] == "w":
            cur.append((i, t["t"]))
        if cur and len(cur) >= CHUNK_WORDS and t["k"] == "p" and t["t"] in SENTENCE_END:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def annotate_one(doc_id, pi):
    try:
        doc = load(doc_id)
        p = doc["paragraphs"][pi]
        model = settings()["models"]["annotate"]
        prev = ""
        if pi > 0:
            prev = "".join(t["t"] for t in doc["paragraphs"][pi - 1]["tokens"])
        translation, words, units, cost = [], {}, [], 0
        for chunk in chunks(p["tokens"]):
            hints = {i: [l["word"] for l in doc["dict"].get(w, {}).get("lemmas", [])] for i, w in chunk}
            data, c = llm.annotate_paragraph(model, chunk, hints, prev)
            cost += c
            translation.append(data.get("translation", ""))
            for row in data.get("words", []):
                if isinstance(row, list) and row and isinstance(row[0], int):
                    words[str(row[0])] = [str(x) for x in row[1:4]]
            for u in data.get("units", []):
                idx = [i for i in u.get("idx", []) if isinstance(i, int) and 0 <= i < len(p["tokens"])]
                if idx:
                    u["idx"] = sorted(idx)
                    u["source"] = "model"
                    units.append(u)
            prev = " ".join(w for _, w in chunk)

        result = {"translation": " ".join(translation), "words": words, "units": units, "model": model}
        cache.put("annotate", para_key(p), result)

        def apply(d):
            d["paragraphs"][pi]["ann"] = {"status": "done", **result}
            d["cost"] = d.get("cost", 0) + cost
            add_llm_lemmas(d, words)
            refresh_status(d)
        update(doc_id, apply)
    except Exception as e:  # keep the reader usable; the paragraph can be retried
        traceback.print_exc()
        msg = str(e)[:300]

        def fail(d):
            d["paragraphs"][pi]["ann"] = {"status": "error", "error": msg}
            refresh_status(d)
        update(doc_id, fail)


def refresh_status(doc):
    if doc["status"] in ("ocr", "review"):
        return
    states = [p.get("ann", {}).get("status") for p in doc["paragraphs"]]
    if any(s in ("pending", "running") for s in states):
        doc["status"] = "annotating"
    elif any(s == "error" for s in states):
        doc["status"] = "partial"
    else:
        doc["status"] = "ready"


def para_key(p):
    return cache.key(llm.ANNOTATE_VERSION, "".join(t["t"] for t in p["tokens"]))


def start_annotation(doc_id, only_failed=False):
    """Paragraphs someone already paid for come straight from data/cache/; the rest go to the model."""
    has_key = bool(llm.api_key())
    todo = []

    def mark(d):
        for i, p in enumerate(d["paragraphs"]):
            s = p["ann"].get("status")
            if s == "done" or (only_failed and s != "error"):
                continue
            hit = cache.get("annotate", para_key(p))
            if hit:
                p["ann"] = {"status": "done", "cached": True, **hit}
                add_llm_lemmas(d, hit.get("words", {}))
            elif has_key:
                p["ann"] = {"status": "running"}
                todo.append(i)
            else:
                p["ann"] = {"status": "error", "error": "no OpenRouter key yet -- add one in Settings, then retry"}
        refresh_status(d)
    update(doc_id, mark)
    for i in todo:
        POOL.submit(annotate_one, doc_id, i)


def text_layer_ok(text):
    """Is an extracted PDF text layer real Unicode Devanagari (not a legacy-font mess)?"""
    dev = len(re.findall(r"[ऀ-ॿ]", text))
    if dev < 40:
        return False
    # a word starting with a vowel sign or virama means glyph-order extraction went wrong
    broken = len(re.findall(r"(?:^|\s)[ा-्]", text))
    words = max(1, len(re.findall(WORD_RE, text)))
    return broken / words < 0.02


def ocr_one(doc_id, n, jpeg, force=False):
    k = cache.key(llm.OCR_VERSION, jpeg)
    hit = None if force else cache.get("ocr", k)
    if hit:
        text, cost, err = hit["text"], 0, None
    else:
        try:
            text, cost = llm.ocr_page(settings()["models"]["ocr"], jpeg)
            err = None
            cache.put("ocr", k, {"text": text, "model": settings()["models"]["ocr"]})
        except Exception as e:
            traceback.print_exc()
            text, cost, err = "", 0, str(e)[:300]

    def apply(d):
        d["pages"][n].update(text=unicodedata.normalize("NFC", text), status="error" if err else "done", error=err)
        d["cost"] = d.get("cost", 0) + cost
        if all(pg["status"] != "running" for pg in d["pages"]):
            d["status"] = "review"
    update(doc_id, apply)


def ingest_file(doc_id, filename, blob):
    """PDF or image -> pages (text layer or OCR) -> review."""
    pages_dir = os.path.join(LIBRARY, doc_id)
    os.makedirs(pages_dir, exist_ok=True)
    jobs, pages = [], []
    if filename.lower().endswith(".pdf"):
        import fitz  # PyMuPDF
        pdf = fitz.open(stream=blob, filetype="pdf")
        for n, page in enumerate(pdf):
            pix = page.get_pixmap(dpi=200)
            jpeg = pix.tobytes("jpeg", jpg_quality=80)
            with open(os.path.join(pages_dir, f"{n + 1}.jpg"), "wb") as f:
                f.write(jpeg)
            layer = page.get_text()
            if text_layer_ok(layer):
                # one block per paragraph, its printed lines joined back together
                blocks = [re.sub(r"\s*\n\s*", " ", b[4]).strip() for b in page.get_text("blocks") if b[6] == 0]
                pages.append({"n": n + 1, "status": "done", "via": "text layer",
                              "text": unicodedata.normalize("NFC", "\n\n".join(b for b in blocks if b))})
            else:
                pages.append({"n": n + 1, "status": "running", "via": "OCR", "text": ""})
                jobs.append((n, jpeg))
    else:
        from io import BytesIO
        import fitz
        img = fitz.open(stream=BytesIO(blob).read(), filetype=filename.rsplit(".", 1)[-1].lower())
        pix = img[0].get_pixmap(dpi=200) if img.page_count else None
        jpeg = pix.tobytes("jpeg", jpg_quality=85) if pix else blob
        with open(os.path.join(pages_dir, "1.jpg"), "wb") as f:
            f.write(jpeg)
        pages.append({"n": 1, "status": "running", "via": "OCR", "text": ""})
        jobs.append((0, jpeg))

    def apply(d):
        d["pages"] = pages
        d["status"] = "ocr" if jobs else "review"
    update(doc_id, apply)
    if not llm.api_key():
        # pages someone already read are still free; only the rest need a key
        cached = [(n, jpeg) for n, jpeg in jobs if cache.has("ocr", cache.key(llm.OCR_VERSION, jpeg))]
        for n, jpeg in cached:
            ocr_one(doc_id, n, jpeg)
        jobs = [j for j in jobs if j not in cached]
    if jobs and not llm.api_key():
        def no_key(d):
            for pg in d["pages"]:
                if pg["status"] == "running":
                    pg.update(status="error", error="no OpenRouter key -- add one in Settings, then retry OCR")
            d["status"] = "review"
        update(doc_id, no_key)
        return
    for n, jpeg in jobs:
        POOL.submit(ocr_one, doc_id, n, jpeg)


def join_pages(pages):
    """Pages -> one text; a page that ends mid-sentence continues the same paragraph."""
    out = ""
    for pg in pages:
        t = (pg.get("text") or "").strip()
        if not t:
            continue
        if out and out.rstrip()[-1:] not in "।॥?!\"”’':":
            out = out.rstrip() + " " + t
        else:
            out = (out + "\n\n" + t) if out else t
    return out


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "HindiReader/1.0"

    def log_message(self, fmt, *args):
        if "/api/texts/" in (args[0] if args else "") and "GET" in (args[0] if args else ""):
            return  # polling noise
        sys.stderr.write("%s\n" % (fmt % args))

    # -- helpers
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        b = self.body()
        return json.loads(b) if b else {}

    def send_file(self, path):
        if not os.path.isfile(path):
            return self.send_json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def route(self, method):
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
        try:
            if not parts or parts[0] != "api":
                rel = "index.html" if not parts else "/".join(parts)
                path = os.path.normpath(os.path.join(STATIC, rel))
                if not path.startswith(STATIC):
                    return self.send_json({"error": "bad path"}, 400)
                return self.send_file(path)
            return self.api(method, parts[1:], parse_qs(url.query))
        except KeyError as e:
            return self.send_json({"error": f"not found: {e}"}, 404)
        except FileNotFoundError:
            return self.send_json({"error": "not found"}, 404)
        except llm.LLMError as e:
            return self.send_json({"error": str(e)}, 502)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": str(e)}, 500)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    # -- API
    def api(self, method, p, q):
        if p == ["config"] and method == "GET":
            return self.send_json({"has_key": bool(llm.api_key()), "settings": settings(),
                                   "choices": MODEL_CHOICES, "dictionary": DICT.ok})

        if p == ["settings"] and method == "POST":
            b = self.json_body()
            if b.get("api_key"):
                llm.save_api_key(b["api_key"])
            s = settings()
            s["models"].update({k: v for k, v in (b.get("models") or {}).items() if v})
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2)
            return self.send_json({"ok": True, "has_key": bool(llm.api_key()), "settings": s})

        if p == ["lookup"] and method == "GET":
            w = q.get("w", [""])[0]
            a = DICT.analyze(w)
            return self.send_json(a)

        if p == ["translate"] and method == "POST":
            b = self.json_body()
            k = cache.key(llm.TRANSLATE_VERSION, b["text"], b.get("context", ""))
            hit = cache.get("translate", k)
            if hit:
                return self.send_json({**hit, "cost": 0, "cached": True})
            model = settings()["models"]["translate"]
            result, cost = llm.translate_selection(model, b["text"], b.get("context", ""))
            cache.put("translate", k, {**result, "model": model})
            if b.get("doc"):
                update(b["doc"], lambda d: d.__setitem__("cost", d.get("cost", 0) + cost))
            result["cost"] = cost
            return self.send_json(result)

        if p == ["texts"] and method == "GET":
            docs = []
            for fn in os.listdir(LIBRARY):
                if fn.endswith(".json"):
                    try:
                        docs.append(summary(load(fn[:-5])))
                    except Exception:
                        pass
            docs.sort(key=lambda d: d["created"], reverse=True)
            return self.send_json(docs)

        if p == ["texts"] and method == "POST":
            b = self.json_body()
            text = clean_text(b.get("text", ""))
            if not text:
                return self.send_json({"error": "empty text"}, 400)
            doc = {"id": new_id(), "title": (b.get("title") or text.split("\n")[0][:40]).strip(),
                   "created": time.time(), "source": "paste", "status": "annotating",
                   "paragraphs": build_paragraphs(text), "notes": [], "cost": 0, "position": 0}
            dictionary_pass(doc)
            save(doc)
            start_annotation(doc["id"])
            return self.send_json(summary(load(doc["id"])))

        if p == ["upload"] and method == "POST":
            filename = unquote(self.headers.get("X-Filename", "upload.pdf"))
            title = unquote(self.headers.get("X-Title", "")) or os.path.splitext(filename)[0]
            blob = self.body()
            doc = {"id": new_id(), "title": title, "created": time.time(), "source": "file:" + filename,
                   "status": "ocr", "pages": [], "paragraphs": [], "notes": [], "cost": 0, "position": 0}
            save(doc)
            POOL.submit(ingest_file, doc["id"], filename, blob)
            return self.send_json(summary(doc))

        if len(p) >= 2 and p[0] == "texts":
            doc_id = p[1]
            rest = p[2:]
            if not rest and method == "GET":
                return self.send_json(load(doc_id))
            if not rest and method == "PATCH":
                b = self.json_body()
                return self.send_json(summary(update(doc_id, lambda d: d.update(
                    {k: v for k, v in b.items() if k in ("title", "position")}))))
            if not rest and method == "DELETE":
                os.remove(doc_path(doc_id))
                return self.send_json({"ok": True})
            if len(rest) == 2 and rest[0] == "page":
                return self.send_file(os.path.join(LIBRARY, doc_id, f"{int(rest[1])}.jpg"))
            if rest == ["confirm"] and method == "POST":
                b = self.json_body()
                text = b.get("text")

                def confirm(d):
                    if b.get("pages"):
                        for pg, t in zip(d["pages"], b["pages"]):
                            pg["text"] = t
                    d["paragraphs"] = build_paragraphs(text if text is not None else join_pages(d["pages"]))
                    d["status"] = "annotating"
                    dictionary_pass(d)
                update(doc_id, confirm)
                start_annotation(doc_id)
                return self.send_json(summary(load(doc_id)))
            if rest == ["reocr"] and method == "POST":
                n = int(self.json_body()["page"])
                jpeg = open(os.path.join(LIBRARY, doc_id, f"{n}.jpg"), "rb").read()
                update(doc_id, lambda d: (d["pages"][n - 1].update(status="running", text="", error=None),
                                          d.__setitem__("status", "ocr")))
                POOL.submit(ocr_one, doc_id, n - 1, jpeg, True)  # explicit re-run skips the cache
                return self.send_json({"ok": True})
            if rest == ["annotate"] and method == "POST":
                start_annotation(doc_id, only_failed=True)
                return self.send_json(summary(load(doc_id)))
            if rest == ["notes"] and method == "POST":
                b = self.json_body()
                note = {"id": new_id(), "created": time.time(), "text": b.get("text", ""),
                        "color": b.get("color", "yellow"), "anchor": b["anchor"], "quote": b.get("quote", ""),
                        "kind": b.get("kind", "note")}
                update(doc_id, lambda d: d.setdefault("notes", []).append(note))
                return self.send_json(note)
            if len(rest) == 2 and rest[0] == "notes":
                nid = rest[1]
                if method == "PATCH":
                    b = self.json_body()

                    def patch(d):
                        for n in d.get("notes", []):
                            if n["id"] == nid:
                                n.update({k: v for k, v in b.items() if k in ("text", "color")})
                    update(doc_id, patch)
                    return self.send_json({"ok": True})
                if method == "DELETE":
                    update(doc_id, lambda d: d.__setitem__("notes", [n for n in d.get("notes", []) if n["id"] != nid]))
                    return self.send_json({"ok": True})
        return self.send_json({"error": "no such endpoint"}, 404)


def resume_jobs():
    """Anything left 'running' when the server stopped gets picked back up."""
    for fn in os.listdir(LIBRARY):
        if not fn.endswith(".json"):
            continue
        try:
            doc = load(fn[:-5])
        except Exception:
            continue
        if any(p.get("ann", {}).get("status") in ("running", "pending") for p in doc.get("paragraphs", [])):
            def reset(d):
                for p in d["paragraphs"]:
                    if p["ann"].get("status") in ("running", "pending"):
                        p["ann"] = {"status": "error", "error": "interrupted"}
            update(doc["id"], reset)
            start_annotation(doc["id"], only_failed=True)


def seed_cache():
    """Every paragraph already annotated in the library goes into the shared cache."""
    added = 0
    for fn in os.listdir(LIBRARY):
        if not fn.endswith(".json"):
            continue
        try:
            doc = load(fn[:-5])
        except Exception:
            continue
        for p in doc.get("paragraphs", []):
            ann = p.get("ann", {})
            if ann.get("status") != "done":
                continue
            k = para_key(p)
            if not cache.has("annotate", k):
                cache.put("annotate", k, {f: ann[f] for f in ("translation", "words", "units", "model") if f in ann})
                added += 1
    if added:
        print(f"cache: added {added} annotated paragraphs from the library")


def main():
    os.makedirs(LIBRARY, exist_ok=True)
    seed_cache()
    if not DICT.ok:
        print("! dictionary missing -- run:  python scripts/build_dictionary.py")
    resume_jobs()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Hindi Reader running at {url}  (ctrl+c to stop)")
    if "--open" in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
