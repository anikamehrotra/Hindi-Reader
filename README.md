# hindi reader

a local reading app for hindi prose -- paste text or upload a pdf/scan, hover any word for its transliteration and meaning, see idioms underlined, highlight a passage to translate it or pin a sticky note to it.

## run it

```
start.bat
```

or `python server/app.py --open`, then go to http://localhost:8765. needs python 3.10+ and `pip install pymupdf` (only for pdfs). the first run builds the dictionary (~1 min, downloads 155 MB of wiktionary data once).

add your openrouter key under ⚙ settings -- it's saved to `.env` here and never leaves the machine except to openrouter. without a key the dictionary layer still works: transliteration, dictionary meanings, wiktionary idioms.

## how it works

| layer | source | when |
|---|---|---|
| transliteration | wiktionary's own romanization for the ~87k forms it has; a rule-based converter with schwa deletion for everything else (matches wiktionary 89% on held-out forms) | instant, offline |
| dictionary word + meanings + origin | wiktionary via [kaikki.org](https://kaikki.org/dictionary/Hindi/) -- 26k headwords, 199k inflected forms mapped back to their dictionary word | instant, offline |
| idioms from the dictionary | 2.2k multi-word wiktionary entries, matched on dictionary forms so नाक कट गई finds नाक कटना | instant, offline |
| meaning in this sentence, grammar, idioms, compound verbs, paragraph translation | the model, once per paragraph when a text is added | ~8¢ per 1,000 words (lajwanti: $0.40 for 4,778) |
| highlight → translate | the model, live | fractions of a cent |
| scans | the model reads each page image; you check the text before annotation | ~0.3¢ a page |

everything lives in `data/library/<id>.json` (text, annotations, notes) plus `data/library/<id>/` (page images for scans). it's committed on purpose, so annotations you've paid for travel with the repo -- which is also why this repo is **private**: the library holds full texts of copyrighted stories. delete a file to delete a text.

**nobody pays twice.** every model answer is also saved to `data/cache/` (one small file per answer, so two people adding translations never merge-conflict) and committed:

| cache | keyed on | effect |
|---|---|---|
| `annotate/` | the paragraph's exact text | someone uploading or pasting the same story gets every already-done paragraph instantly, free, even without a key |
| `translate/` | highlighted text + its surrounding paragraphs | the same highlight in the same story comes back free, marked "saved translation" |
| `ocr/` | the page image | the same pdf's pages don't get read twice ("re-run ocr" in the review screen deliberately skips the cache) |

when a prompt changes enough that old answers should be redone, bump the version strings at the top of `server/llm.py`. pull before reading to pick up other people's translations; commit `data/cache/` after.

**underlines**: solid red = idiom or proverb. dotted blue ("phrases & verbs") = compound verbs (खा लिया), conjunct verbs (इंतज़ार करना), compound postpositions (के बारे में), set phrases.

## models

defaults are all `google/gemini-2.5-flash`: cheap, strong at hindi, and the best-measured model on real devanagari scans in the [2026 devanagari ocr benchmark](https://arxiv.org/abs/2606.29213) (86.3 chrF++ on real scans vs 82.2 claude opus 4.7, 75.2 qwen3-vl-8b, 58.5 gpt-5.5 -- gpt is fine for translation but bad at devanagari ocr). change them in settings; any openrouter model id works.

to compare models on your own text (uses the real prompt, prints translation, idioms found, cost, speed):

```
python scripts/compare_models.py some-paragraph.txt google/gemini-2.5-flash anthropic/claude-haiku-4.5 google/gemma-4-31b-it
```

## platts

platts isn't bundled. the chicago library that hosts the clean version disallows scraping, and the internet archive's ocr of the 1884 scan is unusable for devanagari. every popup links to platts, mcgregor and wiktionary. a later option: re-ocr the public-domain scan with a vision model into structured entries (~1,260 pages, roughly $5-15 one-time).

## plans

- [browser extension](docs/browser-extension.md) -- the same reader on top of rekhta
- [feature ideas](docs/ideas.md) -- ranked, not built
