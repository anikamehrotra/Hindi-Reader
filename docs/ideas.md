# feature ideas -- not built, ranked

written 2026-09-24 after the first real story (lajwanti, 4,778 words, 43 paragraphs, ~$0.40). effort: S = an hour or two, M = a session, L = more.

## top picks

### 1. sentence alignment between hindi and english -- M
hover an english sentence in a translation and its hindi sentence lights up, and the reverse. fixes the "which line does this translation belong to" problem at the sentence level, not just the paragraph level. the model already sees sentence boundaries -- ask it to return the translation as a list of `[hindi sentence span, english sentence]` pairs instead of one string.

### 2. save words + review them -- M
a ☆ on every popup and idiom box. saved items keep the **sentence you met them in** (the best flashcard context there is). then:
- a review tab in the app with spaced repetition (the FSRS algorithm) -- cloze cards from your own sentences
- export to anki
- append to `🗣️ Languages/Hindi Vocab.md` in the vault, so vocab shows up in `/weekly-review`

### 3. story glossary so names + recurring words stay consistent -- S
~300 of lajwanti's 1,447 distinct words aren't in wiktionary, many of them names (सुंदरलाल, लाजो) and urdu vocabulary. one cheap pass over the whole story first → a glossary of characters, places and recurring terms → passed into every paragraph's prompt. consistent translations, names stop being flagged unknown, and a **characters panel** for free ("लाजो = lajwanti, sundarlal's wife").

### 4. word-origin colouring -- S
the dictionary already knows each word's origin. a toggle that tints words sanskrit / persian-arabic / english / native. bedi writes hindustani that moves between registers -- seeing that shift is interesting on its own and useful for a literature class.

### 5. pre-reading prep before class -- S
"prep" button on a story: the 30 words and idioms you're most likely not to know (weighted by frequency in the story), the characters, and an optional spoiler-free setup paragraph. five minutes before HIN 201 instead of stopping every other line.

### 6. correct the model when it's wrong -- S
edit a gloss or idiom in the popup. corrections are saved, shown instead of the model's, and fed into the story glossary (#3) so the fix carries forward.

## good, second tier

- **known-word tracking** -- mark words as known; known words stop getting the hover highlight; each text gets a "you know ~92% of this" score, so you can pick stories at the right difficulty (reading research puts comfortable reading around 95-98% known words). M
- **urdu script alongside** -- bedi, manto and rekhta texts are often urdu originals. wiktionary has urdu spellings for most headwords; show nastaliq in the popup always (partly done) or as a parallel line. S for popup, M for a parallel line
- **grammar lens** -- toggle highlighting of one construction at a time: ने (ergative) clauses, subjunctives, conjunctive participles (-कर), compound verbs. the model's grammar notes already carry most of this. M
- **ask the text** -- a chat box scoped to the story: "why does she go to the temple here?", "what does लाजो's name imply?" -- answers grounded in the text, saveable as notes. M
- **class notes into the vault** -- one button exports highlights + notes + saved words to `🎓 Academics/Fall 2026/HIN 201.md` under a heading for the story, matching the vault's course-note convention. S
- **cost controls** -- show an estimate before annotating, a per-text budget cap, and "annotate only the pages i'm reading". S
- **ocr review helpers** -- in the review screen, flag words that aren't in the dictionary and look like misreads (one letter away from a common word), click to jump the page image to that line. M
- **print / pdf handout** -- the story with glosses for hard words in the margin, for class or reading away from the laptop. M

## later / bigger

- **browser extension** -- see [browser-extension.md](browser-extension.md)
- **ipad / phone** -- serve the app on the home network (or deploy it) and use tap instead of hover. mostly works already on touch; needs a server that's reachable. M
- **platts** -- re-ocr the public-domain 1884 scan with a vision model into structured entries (~1,260 pages, ~$5-15 one-time), then it's a third offline dictionary layer. L
- **audio** -- parked (you said skip). browser text-to-speech for a sentence would be S if it ever matters.
- **writing practice** -- write a response in hindi and get corrections. check HIN 201's policy on ai help before this one.
