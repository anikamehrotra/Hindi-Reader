# browser extension -- plan (not built)

goal: the same hover / idioms / select-to-translate / sticky notes, but on top of the page you're already reading -- rekhta first, any hindi site after.

## why rekhta is easy

rekhta pages are real html text, and every word is already its own element:

```html
<p data-l="1"><span data-m="\1e2i">aaj </span><span data-m="\1m1h">ik </span>…
```

so no ocr -- the extension reads exactly the words on screen. (`data-m` is rekhta's own id into its urdu dictionary; that's what drives their click-for-meaning.) two catches:
- rekhta already uses **click** on words, so ours should be **hover**
- poetry lines are given exact pixel widths, so we shouldn't rewrite their markup

## architecture

**recommended: thin extension, local server does the work**

```
rekhta tab ──► extension (content script) ──► background worker ──► localhost:8765
  hover, underlines,                                                 dictionary, transliteration,
  side panel of notes                                                prompts, openrouter key, cache, library
```

- reuses ~90% of what exists (dictionary db, transliterator, prompts, popup + notes ui code)
- the key stays in `.env`, never in the browser
- needs the server running -- the extension shows "start the reader" when it can't reach it; later, auto-start the server at login

**alternative: standalone extension** -- port the dictionary lookup + transliterator to javascript, ship a trimmed dictionary (~10-15 MB) inside the extension, key in extension storage. works on any computer with no server, ~2x the work. only worth it if this needs to run beyond the laptop.

## what it does on the page

| feature | how |
|---|---|
| hover a word | same popup as the app. on page load, send every distinct word on the page in one batch lookup, so transliteration + dictionary meanings are instant |
| meaning in context + idioms | annotate only paragraphs that scroll into view (an intersection observer); cache results on the server keyed by a hash of the paragraph text, so revisits are free |
| idiom / phrase underlines | the CSS Custom Highlight API (`CSS.highlights` + `::highlight()`) -- styles text ranges without touching rekhta's markup |
| floating toolbar | corner pill with the same toggles (idioms, phrases & verbs, translations) + on/off for this site |
| select → translate / note | same as the app. notes anchored by **text quote + a little prefix/suffix** (the approach the W3C web-annotation standard and hypothes.is use), so they re-attach after reloads and reflows. notes in a side panel |
| save to my reader | one click imports the page's text into the app library, so notes + annotations live there and work offline |
| transliteration above words | the one feature that needs to rewrite the page (ruby tags) -- opt-in, since it can squash rekhta's poetry line widths |

popups and toolbar live in a shadow root so rekhta's css can't touch them (or vice versa).

## new server endpoints needed

- `POST /api/lookup-batch` -- `{words: [...]}` → roman + dictionary lemmas per word
- `POST /api/annotate-text` -- `{text, context}` → the same per-paragraph annotation, cached by text hash
- CORS / origin allowance for the extension's `chrome-extension://…` origin

## feasibility + risks

| | |
|---|---|
| chrome / edge (manifest v3) | straightforward. localhost calls go through the background worker, which sidesteps the page's own security policy |
| firefox | small manifest differences, doable later |
| rekhta changing its markup | low risk -- read any devanagari text in the main content rather than depend on class names. the same extension then works on bbc hindi, hindwi, kavita kosh |
| infinite scroll / lazy content | a mutation observer picks up new text |
| clash with rekhta's click-for-meaning | ours is hover; theirs keeps working |
| **rekhta e-books** | those are page images in a viewer, not text -- would need `captureVisibleTab` + the existing ocr prompt. slower; a separate phase |
| terms of use | fine as a personal reading aid acting on the page you're viewing. "save to my reader" is a personal copy -- no bulk downloading |

## effort

- connected version: ~1-2 sessions (manifest, content script adapted from `static/app.js`, background worker, the three endpoints)
- standalone: +1-2 sessions

## open decisions

1. connected to the local app, or standalone?
2. chrome, edge, or both? (same build for both)
