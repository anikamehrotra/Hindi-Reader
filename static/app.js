// Hindi Reader -- frontend. No build step; talks to server/app.py.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const NARROW = new Set(["idiom", "proverb"]);
const UNIT_LABEL = {
  idiom: "idiom · muhāvarā", proverb: "proverb · lokokti", compound_verb: "compound verb",
  conjunct_verb: "conjunct verb", postposition: "compound postposition", phrase: "set phrase",
};
const POS_LABEL = { verb: "verb", noun: "noun", adj: "adjective", adv: "adverb", postp: "postposition", pron: "pronoun",
  particle: "particle", conj: "conjunction", det: "determiner", num: "numeral", intj: "interjection", name: "proper noun",
  phrase: "phrase", suffix: "suffix", prefix: "prefix" };

const state = {
  doc: null,          // full document from the server
  config: null,
  pinned: false,      // popover pinned by a click
  poll: null,
  paraSig: [],        // per-paragraph render signature, to re-render only what changed
};

const prefs = (() => {
  const d = { theme: "sepia", size: 25, idioms: true, phrases: false, roman: false, trans: false, last: null };
  try { return { ...d, ...JSON.parse(localStorage.getItem("hindiReaderPrefs") || "{}") }; } catch { return d; }
})();
function savePrefs() { try { localStorage.setItem("hindiReaderPrefs", JSON.stringify(prefs)); } catch {} }

async function api(path, opts = {}) {
  const res = await fetch("/api/" + path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers: opts.raw ? opts.headers : { "Content-Type": "application/json" },
    body: opts.raw ? opts.body : opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ------------------------------------------------------------ prefs / chrome
function applyPrefs() {
  document.documentElement.dataset.theme = prefs.theme;
  document.documentElement.style.setProperty("--size", prefs.size + "px");
  $("#tIdioms").checked = prefs.idioms; $("#tPhrases").checked = prefs.phrases;
  $("#tRoman").checked = prefs.roman; $("#tTrans").checked = prefs.trans;
  const r = $("#reader");
  r.classList.toggle("show-idioms", prefs.idioms);
  r.classList.toggle("show-phrases", prefs.phrases);
  r.classList.toggle("roman", prefs.roman);
  $$(".translation").forEach((el) => { if (!el.dataset.manual) el.hidden = !prefs.trans; });
  syncTransLabels();
}

function syncTransLabels() {
  $$("[data-toggle-trans]").forEach((b) => {
    const tr = b.closest(".col").querySelector(".translation");
    b.textContent = tr && !tr.hidden ? "▾ hide translation" : "▸ translation";
  });
  scheduleNoteLayout();  // anything that changes text size or adds translations moves the lines
}
$("#tIdioms").onchange = (e) => { prefs.idioms = e.target.checked; savePrefs(); applyPrefs(); };
$("#tPhrases").onchange = (e) => { prefs.phrases = e.target.checked; savePrefs(); applyPrefs(); };
$("#tRoman").onchange = (e) => { prefs.roman = e.target.checked; savePrefs(); applyPrefs(); };
$("#tTrans").onchange = (e) => { prefs.trans = e.target.checked; $$(".translation").forEach((el) => delete el.dataset.manual); savePrefs(); applyPrefs(); };
$("#smaller").onclick = () => { prefs.size = Math.max(16, prefs.size - 2); savePrefs(); applyPrefs(); };
$("#bigger").onclick = () => { prefs.size = Math.min(40, prefs.size + 2); savePrefs(); applyPrefs(); };
$("#themeBtn").onclick = () => {
  const order = ["sepia", "light", "dark"];
  prefs.theme = order[(order.indexOf(prefs.theme) + 1) % order.length]; savePrefs(); applyPrefs();
};

function openDrawer(open) {
  $("#drawer").classList.toggle("open", open);
  $("#scrim").classList.toggle("show", open);
  if (open) loadLibrary();
}
$("#libraryBtn").onclick = () => openDrawer(!$("#drawer").classList.contains("open"));
$("#scrim").onclick = () => openDrawer(false);

// ------------------------------------------------------------ library
async function loadLibrary() {
  const docs = await api("texts");
  const ul = $("#library");
  ul.innerHTML = docs.length ? "" : `<li class="muted" style="cursor:default">Nothing here yet.</li>`;
  for (const d of docs) {
    const li = document.createElement("li");
    li.className = state.doc?.id === d.id ? "active" : "";
    const status = { ocr: "reading scan…", review: "ready to review", annotating: `annotating ${d.annotated}/${d.paragraphs}`,
      partial: "some paragraphs failed", ready: "" }[d.status] || "";
    li.innerHTML = `<div class="t">${esc(d.title)}</div>
      <div class="m">${d.words ? d.words.toLocaleString() + " words · " : ""}${d.notes ? d.notes + " notes · " : ""}${status || new Date(d.created * 1000).toLocaleDateString()}</div>
      <button class="del" title="Delete">✕</button>`;
    li.onclick = (e) => {
      if (e.target.classList.contains("del")) return;
      openDrawer(false); openDoc(d.id);
    };
    $(".del", li).onclick = async () => {
      if (!confirm(`Delete "${d.title}" and its notes?`)) return;
      await api("texts/" + d.id, { method: "DELETE" });
      if (state.doc?.id === d.id) { state.doc = null; showEmpty(); }
      loadLibrary();
    };
    ul.appendChild(li);
  }
  return docs;
}

function showEmpty() {
  $("#empty").hidden = false; $("#reader").hidden = true; $("#review").hidden = true;
  $("#docTitle").textContent = "Hindi Reader"; $("#status").innerHTML = "";
  prefs.last = null; savePrefs();
}

async function openDoc(id) {
  clearInterval(state.poll);
  hidePopover(true);
  try { state.doc = await api("texts/" + id); } catch { showEmpty(); return; }
  prefs.last = id; savePrefs();
  state.paraSig = [];
  render(true);
  if (["ocr", "annotating"].includes(state.doc.status)) startPolling();
}

function startPolling() {
  clearInterval(state.poll);
  state.poll = setInterval(async () => {
    if (!state.doc) return clearInterval(state.poll);
    const id = state.doc.id;
    const fresh = await api("texts/" + id).catch(() => null);
    if (!fresh || state.doc?.id !== id) return;
    const wasReview = ["ocr", "review"].includes(state.doc.status);
    state.doc = fresh;
    if (wasReview && ["ocr", "review"].includes(fresh.status)) renderReview(false);
    else render(false);
    if (!["ocr", "annotating"].includes(fresh.status)) clearInterval(state.poll);
  }, 2000);
}

// ------------------------------------------------------------ render
function render(scroll) {
  const d = state.doc;
  $("#empty").hidden = true;
  $("#docTitle").textContent = d.title;
  renderStatus();
  if (["ocr", "review"].includes(d.status)) { $("#reader").hidden = true; renderReview(true); return; }
  $("#review").hidden = true;
  const reader = $("#reader");
  reader.hidden = false;
  if (scroll || !$(".title", reader)) {
    reader.innerHTML = `<h1 class="title">${esc(d.title)}</h1>
      <div class="byline">${d.source?.startsWith("file:") ? esc(d.source.slice(5)) + " · " : ""}${countWords(d).toLocaleString()} words</div>
      <div id="rows"></div>`;
    state.paraSig = [];
  }
  const rows = $("#rows");
  d.paragraphs.forEach((p, pi) => {
    const sig = JSON.stringify([p.ann?.status, p.units?.length, notesSig(pi)]);
    let row = rows.children[pi];
    if (!row) { row = document.createElement("div"); row.className = "row"; rows.appendChild(row); }
    if (state.paraSig[pi] !== sig) { renderRow(row, p, pi); state.paraSig[pi] = sig; }
  });
  applyPrefs();
  if (scroll) window.scrollTo(0, 0);
}

function countWords(d) { return d.paragraphs.reduce((n, p) => n + p.tokens.filter((t) => t.k === "w").length, 0); }

function notesSig(pi) {
  return (state.doc.notes || []).filter((n) => n.anchor.p0 <= pi && n.anchor.p1 >= pi).map((n) => n.id + n.color).join();
}

function renderStatus() {
  const d = state.doc, el = $("#status");
  const cost = d.cost ? ` · $${d.cost.toFixed(3)}` : "";
  const done = d.paragraphs.filter((p) => p.ann?.status === "done").length;
  if (d.status === "ocr") el.innerHTML = `<span class="dot"></span>reading scan…${cost}`;
  else if (d.status === "annotating") el.innerHTML = `<span class="dot"></span>annotating ${done}/${d.paragraphs.length}${cost}`;
  else if (d.status === "partial") {
    el.innerHTML = `${d.paragraphs.length - done} paragraphs not annotated · <button id="retryAll">retry</button>${cost}`;
    $("#retryAll").onclick = retryFailed;
  } else el.textContent = cost ? cost.slice(3) : "";
}

async function retryFailed() {
  await api(`texts/${state.doc.id}/annotate`, { body: {} });
  state.doc = await api("texts/" + state.doc.id);
  state.paraSig = [];
  render(false); startPolling();
}

/** Which units (model + Wiktionary) touch each token of a paragraph. */
function unitsByToken(p) {
  const model = p.ann?.units || [];
  const covered = new Set(model.flatMap((u) => u.idx));
  let dict = (p.units || []).filter((u) => !u.idx.some((i) => covered.has(i)));
  // two Wiktionary entries for one proverb (short and long form): keep the longer
  dict = dict.filter((u) => !dict.some((v) => v !== u && v.idx.length > u.idx.length && u.idx.every((i) => v.idx.includes(i))));
  // once the model has read the paragraph, a Wiktionary "idiom" it didn't confirm is shown as a plain phrase
  // (Wiktionary tags things like फिर से as idiomatic)
  if (p.ann?.status === "done") dict = dict.map((u) => (NARROW.has(u.type) ? { ...u, type: "phrase" } : u));
  const all = [...model, ...dict];
  const map = new Map();
  all.forEach((u, k) => {
    const lo = Math.min(...u.idx), hi = Math.max(...u.idx);
    const contiguous = hi - lo + 1 === u.idx.length * 2 - 1 || u.idx.every((i, j) => j === 0 || i - u.idx[j - 1] <= 2);
    const span = new Set(u.idx);
    // underline the spaces between adjacent words of the unit so it reads as one line
    if (contiguous) for (let i = lo; i <= hi; i++) if (p.tokens[i]?.k === "s") span.add(i);
    span.forEach((i) => { if (!map.has(i)) map.set(i, []); map.get(i).push(k); });
  });
  return { all, map };
}

function renderRow(row, p, pi) {
  const d = state.doc;
  const { all, map } = unitsByToken(p);
  const hl = highlightMap(pi);
  let html = "";
  p.tokens.forEach((t, i) => {
    const cls = [];
    const us = map.get(i) || [];
    if (us.some((k) => NARROW.has(all[k].type))) cls.push("u-idiom");
    if (us.some((k) => !NARROW.has(all[k].type))) cls.push("u-phrase");
    if (hl.has(i)) cls.push("hl-" + hl.get(i).color);
    const noteAttr = hl.has(i) ? ` data-note="${hl.get(i).id}"` : "";
    if (t.k === "w") {
      const info = d.dict?.[t.t];
      if (info && !info.lemmas.length && !p.ann?.words?.[i]) cls.push("unknown");
      html += `<span class="w ${cls.join(" ")}" data-i="${i}"${noteAttr}><ruby>${esc(t.t)}<rt>${esc(info?.roman || "")}</rt></ruby></span>`;
    } else if (t.k === "s" && t.t.includes("\n")) {
      html += `<br data-i="${i}">`;
    } else {
      html += `<span class="${cls.join(" ")}" data-i="${i}"${noteAttr}>${esc(t.t)}</span>`;
    }
  });
  const st = p.ann?.status;
  let foot = "";
  if (st === "running" || st === "pending") foot = `<span class="spin"></span><span>annotating…</span>`;
  else if (st === "error") foot = `<span class="err" title="${esc(p.ann.error)}">not annotated -- ${esc((p.ann.error || "").slice(0, 80))}</span><button data-retry>retry</button>`;
  else if (st === "done") foot = `<button data-toggle-trans></button>`;
  row.innerHTML = `<div class="col">
      <p class="para" data-p="${pi}">${html}</p>
      <div class="para-foot">${foot}</div>
      ${st === "done" ? `<div class="translation" hidden>${esc(p.ann.translation)}</div>` : ""}
    </div>
    <aside class="margin" data-p="${pi}"></aside>`;
  const tr = $(".translation", row);
  if (tr) tr.hidden = !prefs.trans;
  $("[data-toggle-trans]", row)?.addEventListener("click", () => { tr.hidden = !tr.hidden; tr.dataset.manual = "1"; syncTransLabels(); });
  $("[data-retry]", row)?.addEventListener("click", retryFailed);
  renderMarginNotes(pi);
}

// ------------------------------------------------------------ notes + highlights
function highlightMap(pi) {
  const map = new Map();
  for (const n of state.doc.notes || []) {
    const a = n.anchor;
    if (pi < a.p0 || pi > a.p1) continue;
    const lo = pi === a.p0 ? a.t0 : 0;
    const hi = pi === a.p1 ? a.t1 : state.doc.paragraphs[pi].tokens.length - 1;
    for (let i = lo; i <= hi; i++) map.set(i, n);
  }
  return map;
}

function renderMarginNotes(pi) {
  const margin = $(`.margin[data-p="${pi}"]`);
  if (!margin) return;
  margin.innerHTML = "";
  for (const n of (state.doc.notes || []).filter((n) => n.anchor.p0 === pi)) margin.appendChild(noteEl(n));
  scheduleNoteLayout();
}

/** Put each sticky note level with the line its highlight starts on, nudging
 *  notes down when two would overlap. On narrow screens the margin sits under
 *  the paragraph instead, and notes just stack. */
const WIDE = window.matchMedia("(min-width: 1001px)");
let layoutQueued = false;
function scheduleNoteLayout() {
  if (layoutQueued) return;
  layoutQueued = true;
  setTimeout(() => { layoutQueued = false; layoutNotes(); }, 0);
}
function layoutNotes() {
  for (const margin of $$(".margin")) {
    const notes = $$(".note", margin);
    margin.classList.toggle("placed", WIDE.matches && notes.length > 0);
    if (!WIDE.matches || !notes.length) {
      margin.style.minHeight = "";
      notes.forEach((el) => (el.style.top = ""));
      continue;
    }
    const pi = margin.dataset.p;
    const base = margin.getBoundingClientRect().top;
    const placed = notes.map((el) => {
      const n = state.doc.notes.find((x) => x.id === el.dataset.id);
      const tok = n && $(`.para[data-p="${pi}"] [data-i="${n.anchor.t0}"]`);
      return { el, want: tok ? tok.getBoundingClientRect().top - base - 6 : 0 };
    }).sort((a, b) => a.want - b.want);
    let bottom = 0;
    for (const p of placed) {
      const top = Math.max(p.want, bottom);
      p.el.style.top = top + "px";
      bottom = top + p.el.offsetHeight + 10;
    }
    margin.style.minHeight = bottom + "px";
  }
}
window.addEventListener("resize", scheduleNoteLayout);
WIDE.addEventListener?.("change", scheduleNoteLayout);
document.fonts?.ready.then(scheduleNoteLayout);
// font size, transliteration, translations shown/hidden: anything that reflows the text
new ResizeObserver(scheduleNoteLayout).observe($("#reader"));

function noteEl(n) {
  const el = document.createElement("div");
  el.className = "note " + (n.color || "yellow");
  el.dataset.id = n.id;
  el.innerHTML = `${n.kind === "translation" ? `<div class="kind">translation</div>` : ""}
    <div class="quote">${esc(n.quote)}</div>
    <textarea rows="1" placeholder="write a note…">${esc(n.text)}</textarea>
    <div class="bar">${["yellow", "pink", "blue", "green"].map((c) => `<button class="sw ${c}" data-c="${c}" title="${c}"></button>`).join("")}
      <button class="x" title="Delete note">delete</button></div>`;
  const ta = $("textarea", el);
  const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; scheduleNoteLayout(); };
  requestAnimationFrame(grow);
  let timer;
  ta.oninput = () => {
    grow(); clearTimeout(timer);
    timer = setTimeout(() => { n.text = ta.value; api(`texts/${state.doc.id}/notes/${n.id}`, { method: "PATCH", body: { text: ta.value } }); }, 400);
  };
  $$(".sw", el).forEach((b) => b.onclick = async () => {
    n.color = b.dataset.c;
    await api(`texts/${state.doc.id}/notes/${n.id}`, { method: "PATCH", body: { color: n.color } });
    rerenderParas(n.anchor.p0, n.anchor.p1);
  });
  $(".x", el).onclick = async () => {
    if (n.text && !confirm("Delete this note?")) return;
    await api(`texts/${state.doc.id}/notes/${n.id}`, { method: "DELETE" });
    state.doc.notes = state.doc.notes.filter((x) => x.id !== n.id);
    rerenderParas(n.anchor.p0, n.anchor.p1);
  };
  el.onmouseenter = () => $$(`[data-note="${n.id}"]`).forEach((s) => s.classList.add("glow"));
  el.onmouseleave = () => $$(".glow").forEach((s) => s.classList.remove("glow"));
  return el;
}

function rerenderParas(p0, p1) {
  for (let pi = p0; pi <= p1; pi++) state.paraSig[pi] = null;
  render(false);
}

async function addNote(anchor, quote, text = "", kind = "note") {
  const n = await api(`texts/${state.doc.id}/notes`, { body: { anchor, quote, text, kind, color: kind === "translation" ? "blue" : "yellow" } });
  state.doc.notes = [...(state.doc.notes || []), n];
  rerenderParas(anchor.p0, anchor.p1);
  const el = $(`.note[data-id="${n.id}"]`);
  if (el) {
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (!text) $("textarea", el).focus();
  }
}

// ------------------------------------------------------------ word popover
const pop = $("#popover");
let hoverTimer = null, hideTimer = null, activeWord = null;

function wordData(pi, i) {
  const d = state.doc, p = d.paragraphs[pi], t = p.tokens[i];
  const info = d.dict?.[t.t] || { roman: "", lemmas: [] };
  const ann = p.ann?.words?.[i];              // [meaning, lemma, grammar] from the model
  const lemmaWord = ann?.[1];
  const blocks = [];
  const seen = new Set();
  const push = (word, pos, gram) => {
    const entries = d.entries?.[word] || [];
    const e = entries.find((x) => !pos || x.pos === pos) || entries[0];
    const key = word + "|" + (e?.pos || pos || "");
    if (seen.has(key) || (!e && !word)) return;
    seen.add(key);
    blocks.push({ word, e, gram });
  };
  if (lemmaWord) {
    const dictMatch = info.lemmas.find((l) => l.word === lemmaWord);
    push(lemmaWord, dictMatch?.pos, dictMatch?.gram);
  }
  info.lemmas.forEach((l) => push(l.word, l.pos, l.gram));
  const units = unitsByToken(p).all.filter((u) => u.idx.includes(i));
  return { t, info, ann, blocks, units, status: p.ann?.status };
}

function senseList(e, limit) {
  const s = e.senses || [];
  const shown = s.slice(0, limit);
  return `<ol>${shown.map((x) => `<li>${esc(x.gloss)}${x.tags?.length ? ` <span class="tg">${esc(x.tags.join(", "))}</span>` : ""}</li>`).join("")}</ol>
    ${s.length > limit ? `<button class="more" data-more>+ ${s.length - limit} more senses</button>` : ""}`;
}

function popoverHTML(pi, i) {
  const { t, info, ann, blocks, units, status } = wordData(pi, i);
  let h = `<div class="head"><span class="hw">${esc(t.t)}</span><span class="rom">${esc(info.roman)}</span></div>`;
  if (ann?.[0]) h += `<div class="ctx">${esc(ann[0])}</div>`;
  else if (status === "running" || status === "pending") h += `<div class="pending">meaning in context is still loading…</div>`;
  if (ann?.[2]) h += `<div class="gram">${esc(ann[2])}</div>`;

  for (const u of units) {
    const narrow = NARROW.has(u.type);
    const p = state.doc.paragraphs[pi];
    const words = u.idx.map((k) => p.tokens[k].t);
    const romans = u.idx.map((k) => state.doc.dict?.[p.tokens[k].t]?.roman || "");
    h += `<div class="unit ${narrow ? "idiom" : ""}">
      <div class="ut">${esc(UNIT_LABEL[u.type] || u.type)}${u.source === "wiktionary" ? " · wiktionary" : ""}</div>
      <div class="uw">${esc(words.join(" "))} <span class="ur">${esc(romans.join(" "))}</span></div>
      ${u.meaning ? `<div class="um">${esc(u.meaning)}</div>` : ""}
      ${u.literal ? `<div class="ul">literally: ${esc(u.literal)}</div>` : ""}
      ${u.note && u.source !== "wiktionary" ? `<div class="un">${esc(u.note)}</div>` : ""}
    </div>`;
  }

  const [first, ...rest] = blocks;
  if (first) {
    const e = first.e;
    h += `<div class="sec"><div class="lemma">
        ${first.word !== t.t ? `<span class="l">${esc(first.word)}</span><span class="lr">${esc(e?.roman || "")}</span>` : ""}
        <span class="pos">${esc([POS_LABEL[e?.pos] || e?.pos, e?.gender, first.gram].filter(Boolean).join(" · "))}</span>
      </div>`;
    if (e?.see) h += `<div class="gram">see ${esc(e.see)}</div>`;
    h += e ? senseList(e, 3) : `<div class="gram">not in Wiktionary -- try Platts below</div>`;
    const tags = [];
    if (e?.origin) tags.push(`<span class="tag" title="${esc(e.etym || "")}">${esc(e.origin)}</span>`);
    if (e?.urdu) tags.push(`<span class="tag urdu" title="Urdu spelling">${esc(e.urdu)}</span>`);
    if (info.guess) tags.push(`<span class="tag" title="Found by stripping an ending -- double-check">best guess</span>`);
    if (tags.length) h += `<div class="tags">${tags.join("")}</div>`;
    h += `</div>`;
  } else if (!ann) {
    h += `<div class="sec gram">Not in the dictionary${status === "done" ? "" : " -- the model's reading will fill this in"}.</div>`;
  }
  if (rest.length) {
    h += `<div class="sec"><div class="gram" style="margin-bottom:4px">also could be</div>${rest.map((b) =>
      `<div class="lemma"><span class="l">${esc(b.word)}</span><span class="lr">${esc(b.e?.roman || "")}</span><span class="pos">${esc(POS_LABEL[b.e?.pos] || b.e?.pos || "")}</span>
       <span>${esc(b.e?.senses?.[0]?.gloss || "")}</span></div>`).join("")}</div>`;
  }
  const look = encodeURIComponent(first?.word || t.t);
  h += `<div class="links">
    <a href="https://dsal.uchicago.edu/cgi-bin/app/platts_query.py?qs=${look}&searchhws=yes&matchtype=exact" target="_blank" rel="noopener">Platts ↗</a>
    <a href="https://dsal.uchicago.edu/cgi-bin/app/mcgregor_query.py?qs=${look}&searchhws=yes&matchtype=exact" target="_blank" rel="noopener">McGregor ↗</a>
    <a href="https://en.wiktionary.org/wiki/${look}#Hindi" target="_blank" rel="noopener">Wiktionary ↗</a>
  </div>`;
  return h;
}

function placePopover(anchorEl) {
  const r = anchorEl.getBoundingClientRect();
  pop.hidden = false;
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = r.left + window.scrollX + r.width / 2 - pw / 2;
  left = Math.max(12 + window.scrollX, Math.min(left, window.scrollX + document.documentElement.clientWidth - pw - 12));
  let top = r.bottom + window.scrollY + 8;
  if (r.bottom + ph + 16 > window.innerHeight && r.top - ph - 8 > 0) top = r.top + window.scrollY - ph - 8;
  pop.style.left = left + "px"; pop.style.top = top + "px";
}

function showWord(span, pin = false) {
  const pi = +span.closest(".para").dataset.p, i = +span.dataset.i;
  activeWord?.classList.remove("active");
  activeWord = span; span.classList.add("active");
  pop.className = "popover";
  pop.innerHTML = popoverHTML(pi, i);
  $("[data-more]", pop)?.addEventListener("click", (e) => {
    e.stopPropagation();
    const { blocks } = wordData(pi, i);
    e.target.parentElement.querySelector("ol").outerHTML = senseList(blocks[0].e, 99).replace(/<button[\s\S]*$/, "");
    e.target.remove();
    placePopover(span);
  });
  state.pinned = pin;
  placePopover(span);
}

function hidePopover(force) {
  if (state.pinned && !force) return;
  pop.hidden = true; state.pinned = false;
  activeWord?.classList.remove("active"); activeWord = null;
}

document.addEventListener("mouseover", (e) => {
  const w = e.target.closest?.(".para .w");
  if (w) {
    clearTimeout(hideTimer);
    if (state.pinned || hasSelection()) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => showWord(w), 110);
  } else if (e.target.closest?.("#popover")) {
    clearTimeout(hideTimer);
  } else {
    clearTimeout(hoverTimer);
    if (!state.pinned && !pop.hidden && !pop.classList.contains("tr")) hideTimer = setTimeout(() => hidePopover(), 260);
  }
});

document.addEventListener("click", (e) => {
  const w = e.target.closest?.(".para .w");
  if (w && !hasSelection()) { showWord(w, true); return; }
  if (!e.target.closest?.("#popover") && !e.target.closest?.("#selbar")) hidePopover(true);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { hidePopover(true); $("#selbar").hidden = true; } });

// ------------------------------------------------------------ selection → translate / note
function hasSelection() { const s = window.getSelection(); return s && !s.isCollapsed && s.toString().trim().length > 0; }

function tokenOf(node, preferEnd) {
  let el = node.nodeType === 3 ? node.parentElement : node;
  if (el?.classList?.contains("para")) {
    // selection edge sits between tokens: use the child at that edge
    el = preferEnd ? el.lastElementChild : el.firstElementChild;
  }
  const tokEl = el?.closest?.("[data-i]");
  const para = el?.closest?.(".para");
  if (!tokEl || !para) return null;
  return { p: +para.dataset.p, i: +tokEl.dataset.i };
}

function selectionAnchor() {
  const s = window.getSelection();
  if (!s.rangeCount) return null;
  const r = s.getRangeAt(0);
  const a = tokenOf(r.startContainer, false), b = tokenOf(r.endContainer, true);
  if (!a || !b) return null;
  let [p0, t0, p1, t1] = [a.p, a.i, b.p, b.i];
  // an end offset of 0 means the selection stops right before this token
  if (r.endOffset === 0 && r.endContainer.nodeType === 3 && (p1 > p0 || t1 > t0)) t1 -= 1;
  const toks = (pi) => state.doc.paragraphs[pi].tokens;
  while (t0 <= toks(p0).length - 1 && toks(p0)[t0].k === "s" && (p0 < p1 || t0 < t1)) t0++;
  while (t1 > 0 && toks(p1)[t1].k === "s" && (p1 > p0 || t1 > t0)) t1--;
  return { p0, t0, p1, t1 };
}

function anchorText(a) {
  const out = [];
  for (let pi = a.p0; pi <= a.p1; pi++) {
    const toks = state.doc.paragraphs[pi].tokens;
    const lo = pi === a.p0 ? a.t0 : 0, hi = pi === a.p1 ? a.t1 : toks.length - 1;
    out.push(toks.slice(lo, hi + 1).map((t) => t.t).join(""));
  }
  return out.join("\n\n").trim();
}

let selAnchor = null;
document.addEventListener("mouseup", (e) => {
  if (e.target.closest?.("#selbar") || e.target.closest?.("#popover")) return;
  setTimeout(() => {
    const bar = $("#selbar");
    if (!hasSelection() || !window.getSelection().anchorNode?.parentElement?.closest("#reader")) { bar.hidden = true; return; }
    selAnchor = selectionAnchor();
    if (!selAnchor) { bar.hidden = true; return; }
    hidePopover(true);
    const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
    bar.hidden = false;
    bar.style.left = Math.max(8, rect.left + window.scrollX + rect.width / 2 - bar.offsetWidth / 2) + "px";
    bar.style.top = rect.top + window.scrollY - bar.offsetHeight - 8 + "px";
  }, 0);
});

$("#selbar").addEventListener("mousedown", (e) => e.preventDefault()); // keep the selection alive
$("#selbar").addEventListener("click", async (e) => {
  const act = e.target.dataset.act;
  if (!act || !selAnchor) return;
  const anchor = selAnchor, quote = anchorText(anchor);
  const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
  $("#selbar").hidden = true;
  window.getSelection().removeAllRanges();
  if (act === "note") return addNote(anchor, quote);
  // translate
  const fake = { getBoundingClientRect: () => rect };
  pop.className = "popover tr";
  pop.innerHTML = `<div class="src">${esc(quote)}</div><div class="pending">translating…</div>`;
  state.pinned = true; placePopover(fake);
  const ctx = [];
  for (let pi = Math.max(0, anchor.p0 - 1); pi <= Math.min(state.doc.paragraphs.length - 1, anchor.p1 + 1); pi++)
    ctx.push(state.doc.paragraphs[pi].tokens.map((t) => t.t).join(""));
  try {
    const r = await api("translate", { body: { text: quote, context: ctx.join("\n\n"), doc: state.doc.id } });
    const noteText = [r.translation, r.literal ? `lit. ${r.literal}` : "", ...(r.notes || []).map((n) => "• " + n)].filter(Boolean).join("\n");
    pop.innerHTML = `<div class="src">${esc(quote)}</div>
      <div class="trans">${esc(r.translation)}</div>
      ${r.literal ? `<div class="lit">literally: ${esc(r.literal)}</div>` : ""}
      ${r.notes?.length ? `<ul>${r.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      <div class="actions"><button class="btn small" data-close>Close</button><button class="btn small primary" data-save>Save as note</button></div>`;
    $("[data-close]", pop).onclick = () => hidePopover(true);
    $("[data-save]", pop).onclick = () => { hidePopover(true); addNote(anchor, quote, noteText, "translation"); };
    placePopover(fake);
    state.doc.cost = (state.doc.cost || 0) + (r.cost || 0); renderStatus();
  } catch (err) {
    pop.innerHTML = `<div class="src">${esc(quote)}</div><div class="err">${esc(err.message)}</div>`;
  }
});

// ------------------------------------------------------------ OCR review
function renderReview(full) {
  const d = state.doc, el = $("#review");
  el.hidden = false; $("#reader").hidden = true;
  const running = d.pages.filter((p) => p.status === "running").length;
  if (full || !$(".page", el) || $$(".page", el).length !== d.pages.length) {
    el.innerHTML = `<h1>Check the text</h1>
      <div class="sub">Each page was read ${d.pages.some((p) => p.via === "text layer") ? "from the PDF's text or " : ""}by the OCR model. Fix anything it misread,
        then start reading -- annotation runs on exactly what's in these boxes. A page that ends mid-sentence continues into the next paragraph.</div>
      <div id="pages">${d.pages.map((p) => `
        <div class="page" data-n="${p.n}">
          <img src="/api/texts/${d.id}/page/${p.n}" alt="page ${p.n}" loading="lazy">
          <div class="pt"><div class="ph"><span>page ${p.n} · <span class="pstat"></span></span><button class="btn small" data-reocr="${p.n}">re-run OCR</button></div>
          <textarea class="field hindi"></textarea></div>
        </div>`).join("")}</div>
      <div class="review-bar"><span class="muted" id="reviewNote"></span><button class="btn primary" id="startReading">Start reading →</button></div>`;
    $$("[data-reocr]", el).forEach((b) => b.onclick = async () => {
      await api(`texts/${d.id}/reocr`, { body: { page: +b.dataset.reocr } });
      const pg = state.doc.pages[+b.dataset.reocr - 1]; pg.status = "running"; pg.text = "";
      $(`.page[data-n="${b.dataset.reocr}"] textarea`).dataset.dirty = "";
      state.doc.status = "ocr"; renderReview(false); startPolling();
    });
    $("#startReading").onclick = async () => {
      const pages = $$(".page textarea", el).map((t) => t.value);
      $("#startReading").disabled = true;
      await api(`texts/${d.id}/confirm`, { body: { pages, text: joinPages(pages) } });
      await openDoc(d.id); startPolling();
    };
  }
  d.pages.forEach((p) => {
    const box = $(`.page[data-n="${p.n}"]`, el);
    const ta = $("textarea", box);
    if (!ta.dataset.dirty) { ta.value = p.text || ""; ta.oninput = () => (ta.dataset.dirty = "1"); }
    $(".pstat", box).textContent = p.status === "running" ? "reading…" : p.status === "error" ? "failed: " + (p.error || "") : `via ${p.via}`;
    ta.disabled = p.status === "running";
  });
  $("#startReading").disabled = running > 0;
  $("#reviewNote").textContent = running ? `${running} page${running > 1 ? "s" : ""} still being read…` : "";
  renderStatus();
}

function joinPages(pages) {
  let out = "";
  for (const raw of pages) {
    const t = raw.trim();
    if (!t) continue;
    if (out && !/[।॥?!"”’':]$/.test(out.trimEnd())) out = out.trimEnd() + " " + t;
    else out = out ? out + "\n\n" + t : t;
  }
  return out;
}

// ------------------------------------------------------------ add text dialog
const addDialog = $("#addDialog");
let addTab = "paste", addFile = null;
function openAdd() { addFile = null; $("#fileName").textContent = ""; $("#addText").value = ""; $("#addTitle").value = ""; setTab("paste"); addDialog.showModal(); }
function setTab(t) {
  addTab = t;
  $$(".tab", addDialog).forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tabpane", addDialog).forEach((p) => (p.hidden = p.dataset.pane !== t));
}
$$(".tab", addDialog).forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));
$("#addBtn").onclick = () => { openDrawer(false); openAdd(); };
$("#emptyAdd").onclick = openAdd;
$("#addCancel").onclick = () => addDialog.close();
$("#addFile").onchange = (e) => { addFile = e.target.files[0]; $("#fileName").textContent = addFile?.name || ""; };
const drop = $("#drop");
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); addFile = e.dataTransfer.files[0]; $("#fileName").textContent = addFile?.name || ""; };

$("#addForm").onsubmit = async (e) => {
  e.preventDefault();
  const title = $("#addTitle").value.trim();
  const btn = $("#addSubmit"); btn.disabled = true;
  try {
    let d;
    if (addTab === "paste") {
      const text = $("#addText").value;
      if (!text.trim()) return;
      d = await api("texts", { body: { title, text } });
    } else {
      if (!addFile) return;
      d = await api("upload", { raw: true, body: addFile,
        headers: { "X-Filename": encodeURIComponent(addFile.name), "X-Title": encodeURIComponent(title) } });
    }
    addDialog.close();
    await openDoc(d.id); startPolling();
  } catch (err) { alert(err.message); } finally { btn.disabled = false; }
};

// ------------------------------------------------------------ settings
const setDialog = $("#settingsDialog");
async function openSettings() {
  state.config = await api("config");
  const c = state.config;
  $("#keyState").textContent = c.has_key ? "-- a key is saved ✓" : "-- none yet";
  $("#apiKey").value = "";
  $("#mAnnotate").value = c.settings.models.annotate;
  $("#mTranslate").value = c.settings.models.translate;
  $("#mOcr").value = c.settings.models.ocr;
  $("#modelList").innerHTML = c.choices.map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("");
  $("#modelTable").innerHTML = c.choices.map((m) => `<div>${esc(m.label)}<br><code>${esc(m.id)}</code></div><div>${esc(m.price)}</div>`).join("");
  setDialog.showModal();
}
$("#settingsBtn").onclick = openSettings;
$("#settingsCancel").onclick = () => setDialog.close();
$("#settingsForm").onsubmit = async (e) => {
  e.preventDefault();
  await api("settings", { body: { api_key: $("#apiKey").value.trim() || undefined,
    models: { annotate: $("#mAnnotate").value.trim(), translate: $("#mTranslate").value.trim(), ocr: $("#mOcr").value.trim() } } });
  setDialog.close();
};

// ------------------------------------------------------------ boot
(async function boot() {
  applyPrefs();
  try { state.config = await api("config"); } catch {}
  const docs = await loadLibrary().catch(() => []);
  const last = docs.find((d) => d.id === prefs.last) || null;
  if (last) openDoc(last.id); else showEmpty();
  if (state.config && !state.config.has_key) setTimeout(() => {
    if (!docs.length) $("#empty p").insertAdjacentHTML("afterend",
      `<p class="muted small">No OpenRouter key yet -- the dictionary works without one, but meanings-in-context, idioms and translation need it. Add it under ⚙ Settings.</p>`);
  }, 0);
})();
