"""Shared cache of paid-for model output, committed to the repo so nobody pays twice.

    data/cache/<kind>/<key>.json      one small file per result -> no git merge conflicts

kinds
  annotate   paragraph text            -> words / units / translation
  translate  highlighted text + context -> translation, literal, notes
  ocr        page image bytes          -> transcription

Keys hash the input plus a version string; bump the version in llm.py when a prompt
changes enough that old answers should be redone.
"""
import hashlib
import json
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")


def norm(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def key(version, *parts):
    h = hashlib.sha256(version.encode())
    for p in parts:
        h.update(b"\x00")
        h.update(p if isinstance(p, bytes) else norm(p).encode())
    return h.hexdigest()[:32]


def _path(kind, k):
    return os.path.join(CACHE, kind, k + ".json")


def get(kind, k):
    try:
        with open(_path(kind, k), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def put(kind, k, value):
    path = _path(kind, k)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def has(kind, k):
    return os.path.exists(_path(kind, k))
