"""Run the same paragraph through several models and compare translation, idioms, cost and speed.

    python scripts/compare_models.py                      # built-in sample paragraph
    python scripts/compare_models.py path/to/paragraph.txt
    python scripts/compare_models.py file.txt google/gemini-2.5-flash anthropic/claude-haiku-4.5

Uses the same prompt the reader uses, so what you see here is what you'd get in the app.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
import llm  # noqa: E402
from app import tokenize  # noqa: E402
from dictionary import Dictionary  # noqa: E402

SAMPLE = ("रास्ते में उसे मास्टर जी दिखाई दिए। रामू ने आँखें चुराने की कोशिश की, क्योंकि पिछले हफ़्ते उसने "
          "गृहकार्य नहीं किया था। मास्टर जी मुस्कुराए और बोले, \"डरो मत, दूर के ढोल सुहावने होते हैं।\" "
          "परीक्षा का नतीजा आया तो पूरे गाँव में उसकी नाक कट गई, पर वह हाथ पर हाथ धरे नहीं बैठा।")
DEFAULT_MODELS = ["google/gemini-2.5-flash", "google/gemini-3.1-flash-lite", "openai/gpt-5-mini",
                  "anthropic/claude-haiku-4.5", "google/gemma-4-31b-it", "deepseek/deepseek-v4-flash"]


def main():
    args = sys.argv[1:]
    text = open(args.pop(0), encoding="utf-8").read().strip() if args and os.path.exists(args[0]) else SAMPLE
    models = args or DEFAULT_MODELS
    d = Dictionary()
    toks = tokenize(text)
    words = [(i, t["t"]) for i, t in enumerate(toks) if t["k"] == "w"]
    hints = {i: [l["word"] for l in d.analyze(w)["lemmas"]] for i, w in words}
    for m in models:
        print("=" * 80, "\n", m)
        t0 = time.time()
        try:
            data, cost = llm.annotate_paragraph(m, words, hints)
        except Exception as e:
            print("  FAILED:", e)
            continue
        got = {row[0] for row in data.get("words", []) if isinstance(row, list) and row}
        print(f"  {time.time() - t0:.1f}s  ${cost:.4f}  words covered {len(got)}/{len(words)}")
        print("  translation:", data.get("translation"))
        for u in data.get("units", []):
            ws = " ".join(toks[i]["t"] for i in u.get("idx", []) if 0 <= i < len(toks))
            print(f"  [{u.get('type')}] {ws} -- {u.get('meaning')}" + (f"  (lit. {u['literal']})" if u.get("literal") else ""))


if __name__ == "__main__":
    main()
