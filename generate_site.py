#!/usr/bin/env python3
"""
Weekend Sales matches -> static GitHub Pages site generator
===========================================================

Reads a matches.json produced by seraphim-weekend-scraper_0.2.py and renders
a single static page (docs/index.html) listing every match grouped by store
name, sorted alphabetically, in a clean magazine style similar to Seraphim.

The output is fully static (no JavaScript, no network calls) so it can be
served straight from GitHub Pages.

Folder layout (ready for GitHub Pages served from /docs):
    docs/
        index.html      <- generated page (commit this)
        matches.json    <- copy of the data the page was built from

Usage
-----
    python generate_site.py                        # docs/index.html from matches.json
    python generate_site.py --input out.json \
        --output docs/index.html --title "Sales"
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

DEFAULT_INPUT = Path(__file__).parent / "matches.json"
DEFAULT_OUTPUT = Path(__file__).parent / "docs" / "index.html"

STYLE = """
:root {
  --ink: #e8e8e6;
  --muted: #9a9a97;
  --faint: #6b6b68;
  --paper: #121213;
  --panel: #1b1b1d;
  --card: #1a1a1c;
  --line: #2a2a2d;
  --accent: #c084fc;
  --slurl-blue: #38bdf8;
  --pin-icon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%230a0a0b'%3E%3Cpath d='M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z'/%3E%3C/svg%3E");
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: var(--ink);
  background: var(--paper);
  line-height: 1.45;
}
a { color: var(--ink); text-decoration: none; }
a:hover { text-decoration: underline; }

.site-header {
  background: #0a0a0b;
  color: #fff;
  border-bottom: 3px solid var(--accent);
}
.site-header .wrap {
  max-width: 1200px;
  margin: 0 auto;
  padding: 18px 20px;
}
.site-header h1 {
  margin: 0;
  font-family: "Playfair Display", Georgia, "Times New Roman", serif;
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.site-header h1 a { color: #fff; }
.site-header p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.wrap { max-width: 1280px; margin: 0 auto; padding: 0 20px; }

.summary {
  padding: 12px 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  font-size: 13px;
  color: var(--muted);
}

.tabs {
  max-width: 1280px;
  margin: 0 auto;
  padding: 14px 20px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tab-btn {
  background: var(--panel);
  color: var(--muted);
  border: 1px solid var(--line);
  border-bottom: none;
  padding: 9px 22px;
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  cursor: pointer;
  border-radius: 8px 8px 0 0;
  font-family: inherit;
}
.tab-btn:hover { color: var(--ink); }
.tab-btn.active {
  background: var(--card);
  color: var(--ink);
  border-color: var(--accent);
}
.tab-btn.right { margin-left: auto; }
.tab-panel { display: none; }
.tab-panel[data-active] { display: block; }
.tab-count {
  padding: 12px 0 0;
  font-size: 12px;
  color: var(--muted);
}

.stores-title {
  margin: 18px 0 0;
  font-family: "Playfair Display", serif;
  font-size: 22px;
  font-weight: 600;
  color: var(--ink);
}
.store-directory {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 14px 0 26px;
}
@media (max-width: 1100px) {
  .store-directory { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 800px) {
  .store-directory { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 520px) {
  .store-directory { grid-template-columns: 1fr; }
}
.store-set-label {
  grid-column: 1 / -1;
  margin: 4px 0 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--muted);
}
.store-group {
  border: 1px solid var(--line);
  background: var(--card);
  padding: 10px 14px 12px;
  min-width: 0;
}
.store-group-letter {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--accent);
  border-bottom: 1px dashed var(--line);
  padding-bottom: 6px;
}
.store-group-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-wrap: anywhere;
}
.store-group-list li {
  font-size: 13px;
  padding: 2px 0;
}

.store-items {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  padding: 18px 0 26px;
}
@media (max-width: 1100px) {
  .store-items { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 800px) {
  .store-items { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 520px) {
  .store-items { grid-template-columns: 1fr; }
}
.card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--line);
  background: var(--card);
}
.card img {
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  display: block;
  border-bottom: 1px solid var(--line);
  opacity: 0;
  transition: opacity 0.3s ease;
}
.card img.loaded { opacity: 1; }
.card-body {
  padding: 9px 11px;
  min-width: 0;
}
.card-title {
  font-size: 14px;
  font-weight: 700;
  margin: 0 0 3px;
  overflow-wrap: anywhere;
}
.card-links {
  font-size: 12px;
  color: var(--muted);
  margin: 1px 0;
  overflow-wrap: anywhere;
}
.card-links a { color: var(--accent); }
.card-caption {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ink);
  border-top: 1px dashed var(--line);
  padding-top: 6px;
  overflow-wrap: anywhere;
}
.card-caption a { color: var(--accent); }
.card-caption a[href*="maps.secondlife.com"],
.card-links a[href*="maps.secondlife.com"] {
  display: inline-block;
  margin: 1px 2px 1px 0;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--slurl-blue);
  color: #0a0a0b;
  font-weight: 700;
}
.card-caption a[href*="maps.secondlife.com"]::before,
.card-links a[href*="maps.secondlife.com"]::before {
  content: "";
  display: inline-block;
  width: 11px;
  height: 11px;
  margin-right: 5px;
  vertical-align: -2px;
  background: var(--pin-icon) no-repeat center / contain;
}
.card-caption a[href*="maps.secondlife.com"]:hover,
.card-links a[href*="maps.secondlife.com"]:hover {
  background: #7dd3fc;
  text-decoration: none;
}

.empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--muted);
}

/* Fullscreen lightbox */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.94);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
}
.lightbox[hidden] { display: none; }
.lightbox img {
  max-width: 92vw;
  max-height: 72vh;
  object-fit: contain;
  box-shadow: 0 0 60px rgba(0, 0, 0, 0.9);
  cursor: zoom-out;
  transition: opacity 0.2s ease;
}
.lightbox.loading img { opacity: 0.25; }
.lb-spin {
  position: fixed;
  top: 50%;
  left: 50%;
  width: 54px;
  height: 54px;
  margin: -27px 0 0 -27px;
  border: 4px solid rgba(255, 255, 255, 0.15);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: lb-spin 0.8s linear infinite;
  z-index: 1002;
}
.lb-spin[hidden] { display: none; }
@keyframes lb-spin {
  to { transform: rotate(360deg); }
}
.lb-visit {
  display: inline-block;
  padding: 10px 26px;
  border-radius: 999px;
  background: var(--slurl-blue);
  color: #0a0a0b;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.3px;
  box-shadow: 0 0 24px rgba(56, 189, 248, 0.4);
}
.lb-visit::before {
  content: "";
  display: inline-block;
  width: 14px;
  height: 14px;
  margin-right: 7px;
  vertical-align: -2px;
  background: var(--pin-icon) no-repeat center / contain;
}
.lb-visit:hover {
  background: #7dd3fc;
  color: #0a0a0b;
  text-decoration: none;
}
.lb-visit[hidden] { display: none; }
.lb-info {
  position: fixed;
  left: 50%;
  bottom: 26px;
  transform: translateX(-50%);
  background: rgba(10, 10, 11, 0.8);
  color: #e8e8e6;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 18px;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.4px;
  max-width: 80vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lb-btn {
  position: fixed;
  z-index: 1001;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: rgba(20, 20, 22, 0.85);
  color: #e8e8e6;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease, color 0.15s ease;
}
.lb-btn:hover { background: var(--accent); color: #0a0a0b; }
.lb-close {
  top: 20px;
  right: 22px;
  font-size: 28px;
}
.lb-prev { left: 22px; top: 50%; transform: translateY(-50%); }
.lb-next { right: 22px; top: 50%; transform: translateY(-50%); }
@media (max-width: 640px) {
  .lb-prev, .lb-next { top: auto; bottom: 26px; transform: none; }
  .lb-info { display: none; }
}
.site-footer {
  background: #0a0a0b;
  color: var(--faint);
  padding: 16px 20px;
  font-size: 12px;
  text-align: center;
}
"""


ALLOWED_TAGS = {"a", "strong", "b", "em", "i", "u", "br"}
TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
SLURL_A_RE = re.compile(
    r'(<a\b[^>]*\bhref="[^"]*maps\.secondlife\.com[^"]*"[^>]*>)(.*?)(</a>)',
    re.I | re.S,
)


def sanitize_caption(raw: str) -> str:
    """Keep the rich text Seraphim publishes, but drop anything structural.

    Only inline tags (a/strong/b/em/i/u/br) survive; scripts, iframes and any
    block-level markup are removed so captions can never break the card grid.
    Stray unclosed inline tags are closed so the DOM stays balanced.
    """
    if not raw:
        return ""
    text = raw
    text = re.sub(r"<(script|style|iframe|object|embed|form)\b.*?</\1>", "", text, flags=re.I | re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    def keep(m: re.Match) -> str:
        closing, tag = m.group(1), m.group(2).lower()
        if tag in ALLOWED_TAGS:
            return f"</{tag}>" if closing else m.group(0)
        return ""

    text = TAG_RE.sub(keep, text)

    # Normalize every SLURL link (teleport) to a consistent "Visit store" label.
    text = SLURL_A_RE.sub(r"\1Visit store\3", text)

    for tag in ALLOWED_TAGS:
        if tag == "br":
            continue
        if text.count(f"<{tag}") > text.count(f"</{tag}>"):
            text += f"</{tag}>"
    return text.strip()


def extract_slurl(caption_html: str) -> str:
    """Pull the teleport URL (maps.secondlife.com) out of a caption."""
    if not caption_html:
        return ""
    m = re.search(r"https?://maps\.secondlife\.com/[^\"'\s]+", caption_html)
    return htmlmod.unescape(m.group(0)) if m else ""


def render_card(item: dict, index: int, tab: int) -> str:
    store = htmlmod.escape(item.get("store_name", ""))
    img = htmlmod.escape(item.get("image_url", ""))
    event_title = htmlmod.escape(item.get("source_event_title", ""))
    event_url = htmlmod.escape(item.get("source_event_url", ""))
    gallery_url = htmlmod.escape(item.get("gallery_url", ""))

    links = []
    if event_url:
        links.append(
            f'<a href="{event_url}" target="_blank" rel="noopener">{event_title or "Event page"}</a>'
        )
    if gallery_url and gallery_url != event_url:
        links.append(f'<a href="{gallery_url}" target="_blank" rel="noopener">Gallery</a>')

    caption = sanitize_caption(item.get("caption_html", ""))
    caption_html = f'<div class="card-caption">{caption}</div>' if caption else ""

    links_html = ""
    if links:
        joined = '<span class="sep"> &middot; </span>'.join(links)
        links_html = f'<div class="card-links">{joined}</div>'

    thumb = htmlmod.escape(item.get("thumb_url") or item.get("image_url", ""))

    return f"""
    <div class="card">
      <a href="{img}" target="_blank" rel="noopener" class="lb-link" data-tab="{tab}" data-index="{index}"><img src="{thumb}" alt="{store}" loading="lazy"></a>
      <div class="card-body">
        <p class="card-title">{store}</p>
        {links_html}
        {caption_html}
      </div>
    </div>"""


def render_flat_grid(matches: List[dict], tab: int) -> tuple:
    """Render one store list as a flat grid; return (html, lightbox items)."""
    by_store: Dict[str, List[dict]] = defaultdict(list)
    for item in matches:
        by_store[item.get("store_name") or ""].append(item)

    if not matches:
        return '<div class="empty"><p>No matches yet. Run the scraper and regenerate.</p></div>', []

    ordered = sorted(by_store.keys(), key=lambda n: n.lower())
    flat: List[dict] = []
    for store in ordered:
        flat.extend(by_store[store])
    cards = "\n".join(render_card(it, i, tab) for i, it in enumerate(flat))
    items = [
        {
            "img": it.get("image_url", ""),
            "thumb": it.get("thumb_url") or it.get("image_url", ""),
            "store": it.get("store_name", ""),
            "event_url": it.get("source_event_url", ""),
            "event_title": it.get("source_event_title", ""),
            "slurl": extract_slurl(it.get("caption_html", "")),
        }
        for it in flat
    ]
    return f'<div class="store-items">{cards}</div>', items


def parse_store_list(path: Path) -> Dict[str, List[str]]:
    """Parse a watchlist into categories keyed by their `# A` header letter."""
    categories: Dict[str, List[str]] = {}
    current = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            letter = line[1:].strip()
            if len(letter) == 1 and letter.isalpha():
                current = letter.upper()
                categories.setdefault(current, [])
            continue
        key = current or "Other"
        categories.setdefault(key, []).append(line)
    ordered = sorted(categories.items(), key=lambda kv: (kv[0] == "Other", kv[0]))
    return dict(ordered)


def render_stores_panel(store_sets: List[tuple], tab: int, title: str = "Stores on the watchlist") -> str:
    """Render the watchlist directory panel. `store_sets` is (label, categories)."""
    groups = []
    total = 0
    for label, categories in store_sets:
        total += sum(len(names) for names in categories.values())
        if len(store_sets) > 1:
            groups.append(
                f'<h3 class="store-set-label">{htmlmod.escape(label)}</h3>'
            )
        for letter, names in categories.items():
            lis = "\n".join(
                f"        <li>{htmlmod.escape(name)}</li>" for name in names
            )
            groups.append(
                f'    <section class="store-group">\n'
                f'      <h4 class="store-group-letter">{htmlmod.escape(letter)}</h4>\n'
                f'      <ul class="store-group-list">\n{lis}\n      </ul>\n'
                f"    </section>"
            )

    return (
        f'<div class="tab-panel" id="tab-{tab}">\n'
        f'  <h2 class="stores-title">{htmlmod.escape(title)}</h2>\n'
        f'  <div class="tab-count">{total} store(s) on your watchlist</div>\n'
        f'  <div class="store-directory">\n'
        f'    {"\n".join(groups)}\n'
        f"  </div>\n"
        f"</div>"
    )


def render_page(
    tabs: List[tuple],
    title: str,
    store_sets: List[tuple] = (),
    stores_label: str = "Watchlist",
) -> str:
    """Render the page. `tabs` is a list of (label, matches) tuples.

    When `store_sets` is non-empty, a right-aligned tab (labelled `stores_label`)
    listing the watchlist directories is appended after the match tabs.
    """
    panels = []
    tabs_data: List[dict] = []
    total = 0
    total_stores = 0
    for t, (label, matches) in enumerate(tabs):
        body, items = render_flat_grid(matches, t)
        total += len(items)
        total_stores += len({i["store"] for i in items})
        count = f'<div class="tab-count">{len(items)} match(es) across {len({i["store"] for i in items})} store(s)</div>'
        active = ' data-active=""' if t == 0 else ''
        panels.append(f'<div class="tab-panel" id="tab-{t}"{active}>{count}{body}</div>')
        tabs_data.append({"label": label, "items": items})

    store_tab = len(tabs)
    if store_sets:
        panels.append(render_stores_panel(store_sets, store_tab))

    tabs_json = json.dumps(tabs_data, ensure_ascii=False).replace("<", "\\u003c")
    button_count = len(tabs) + (1 if store_sets else 0)
    tabs_html = ""
    if button_count > 1:
        buttons = [
            f'  <button class="tab-btn{" active" if t == 0 else ""}" data-tab="{t}">'
            f'{htmlmod.escape(label)}</button>'
            for t, (label, _) in enumerate(tabs)
        ]
        if store_sets:
            buttons.append(
                f'  <button class="tab-btn right" data-tab="{store_tab}">'
                f'{htmlmod.escape(stores_label)}</button>'
            )
        tabs_html = (
            '<nav class="tabs" id="tabs">\n'
            + "\n".join(buttons)
            + "\n</nav>"
        )

    now = datetime.now().strftime("%B %d, %Y, %H:%M")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{htmlmod.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600&display=swap" rel="stylesheet">
<style>{STYLE}</style>
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <h1><a href="https://github.com/Atasly/Seraphim-SL-Watchlist">{htmlmod.escape(title)}</a></h1>
    <p>Second Life weekend sales &mdash; Curated and Compiled</p>
  </div>
</header>

{tabs_html}

<div class="summary wrap">
  {total} match(es) across {total_stores} store(s)
  &middot; sorted by store name
  &middot; generated {now}
</div>

<main class="wrap">{''.join(panels)}</main>

<footer class="site-footer">
  Generated by <a href="https://github.com/Atasly/Seraphim-SL-Watchlist">Seraphim SL Watchlist</a>
</footer>

<div id="lb" class="lightbox" hidden>
  <button id="lb-close" class="lb-btn lb-close" aria-label="Close" title="Close">&times;</button>
  <button id="lb-prev" class="lb-btn lb-prev" aria-label="Previous" title="Previous">&lsaquo;</button>
  <button id="lb-next" class="lb-btn lb-next" aria-label="Next" title="Next">&rsaquo;</button>
  <img id="lb-img" src="" alt="">
  <div id="lb-spin" class="lb-spin" hidden></div>
  <a id="lb-visit" class="lb-visit" href="#" target="_blank" rel="noopener" hidden>Visit store</a>
  <div id="lb-info" class="lb-info"></div>
</div>

<script>
const TABS = {tabs_json};
(function () {{
  const links = Array.from(document.querySelectorAll('.lb-link'));
  const lb = document.getElementById('lb');
  const img = document.getElementById('lb-img');
  const info = document.getElementById('lb-info');
  const vbtn = document.getElementById('lb-visit');
  const spin = document.getElementById('lb-spin');
  let curTab = 0;
  let curIdx = -1;
  let loadSeq = 0;

  function items(t) {{ return TABS[t] ? TABS[t].items : []; }}

  function show(tab, i) {{
    const list = items(tab);
    if (!list.length) return;
    curTab = tab;
    curIdx = (i + list.length) % list.length;
    const it = list[curIdx];
    loadSeq += 1;
    spin.hidden = false;
    lb.classList.add('loading');
    img.src = it.img;
    img.dataset.seq = loadSeq;
    img.alt = it.store;
    info.textContent = it.store + (it.event_title ? ' \\u2014 ' + it.event_title : '');
    if (it.slurl) {{
      vbtn.href = it.slurl;
      vbtn.hidden = false;
    }} else {{
      vbtn.href = '#';
      vbtn.hidden = true;
    }}
    lb.hidden = false;
    document.body.style.overflow = 'hidden';
    if (img.complete && img.naturalWidth) {{
      spin.hidden = true;
      lb.classList.remove('loading');
    }}
  }}
  img.addEventListener('load', function () {{
    if (img.dataset.seq == loadSeq) {{
      spin.hidden = true;
      lb.classList.remove('loading');
    }}
  }});
  img.addEventListener('error', function () {{
    if (img.dataset.seq == loadSeq) {{
      spin.hidden = true;
      lb.classList.remove('loading');
    }}
  }});
  function close() {{
    lb.hidden = true;
    img.src = '';
    spin.hidden = true;
    lb.classList.remove('loading');
    document.body.style.overflow = '';
  }}
  function nav(d) {{ show(curTab, curIdx + d); }}

  function selectTab(t) {{
    document.querySelectorAll('.tab-panel').forEach(function (p, i) {{
      if (i === t) p.setAttribute('data-active', '');
      else p.removeAttribute('data-active');
    }});
    document.querySelectorAll('.tab-btn').forEach(function (b) {{
      b.classList.toggle('active', Number(b.dataset.tab) === t);
    }});
  }}

  document.querySelectorAll('.card img').forEach(function (im) {{
    if (im.complete && im.naturalWidth) im.classList.add('loaded');
    else {{
      im.addEventListener('load', function () {{ im.classList.add('loaded'); }});
      im.addEventListener('error', function () {{ im.classList.add('loaded'); }});
    }}
  }});

  links.forEach(function (a) {{
    a.addEventListener('click', function (e) {{
      e.preventDefault();
      show(Number(a.dataset.tab) || 0, Number(a.dataset.index) || 0);
    }});
  }});
  document.querySelectorAll('.tab-btn').forEach(function (b) {{
    b.addEventListener('click', function () {{ selectTab(Number(b.dataset.tab) || 0); }});
  }});
  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', function () {{ nav(-1); }});
  document.getElementById('lb-next').addEventListener('click', function () {{ nav(1); }});
  lb.addEventListener('click', function (e) {{
    if (e.target === lb) close();
  }});
  document.addEventListener('keydown', function (e) {{
    if (lb.hidden) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') nav(-1);
    else if (e.key === 'ArrowRight') nav(1);
  }});

  selectTab(0);
}})();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render matches.json into a static GitHub Pages site."
    )
    parser.add_argument(
        "--input",
        action="append",
        help="Path to matches.json. Repeat for multiple store lists (one tab each).",
    )
    parser.add_argument(
        "--tab-label",
        action="append",
        help="Label for each tab. Repeat in the same order as --input.",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Where to write index.html.")
    parser.add_argument("--title", default="Seraphim SL Watchlist")
    parser.add_argument(
        "--stores-file",
        action="append",
        help="Path to a watchlist (e.g. Stores.txt). Repeatable; adds a "
        "right-aligned tab listing the watchlist.",
    )
    parser.add_argument(
        "--stores-label",
        default="Watchlist",
        help="Label for the right-aligned stores tab (default: Watchlist).",
    )
    parser.add_argument("--copy-data", help="Copy the input JSON here too (default: alongside output).")
    args = parser.parse_args()

    inputs = [Path(p) for p in (args.input or [str(DEFAULT_INPUT)])]
    for input_path in inputs:
        if not input_path.exists():
            print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
            raise SystemExit(1)

    labels = args.tab_label or []
    if len(labels) > len(inputs):
        print("ERROR: more --tab-label values than --input files", file=sys.stderr)
        raise SystemExit(1)
    labels = labels + [p.stem.replace("_", " ") for p in inputs[len(labels):]]

    tabs = []
    for label, input_path in zip(labels, inputs):
        matches = json.loads(input_path.read_text(encoding="utf-8"))
        tabs.append((label, matches))

    store_sets: List[tuple] = []
    for sf in (args.stores_file or []):
        store_path = Path(sf)
        if not store_path.exists():
            print(f"ERROR: stores file not found: {store_path}", file=sys.stderr)
            raise SystemExit(1)
        store_sets.append((store_path.stem.replace("_", " "), parse_store_list(store_path)))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_page(tabs, args.title, store_sets, args.stores_label), encoding="utf-8"
    )

    if args.copy_data:
        data_dst = Path(args.copy_data)
    else:
        data_dst = output_path.parent / inputs[0].name
    data_dst.parent.mkdir(parents=True, exist_ok=True)
    data_dst.write_bytes(inputs[0].read_bytes())

    total = sum(len(m) for _, m in tabs)
    total_stores = len({m.get("store_name") for _, m in tabs for m in m})
    dir_count = sum(len(names) for _, cats in store_sets for names in cats.values())
    print(f"Wrote {output_path} ({total} matches, {total_stores} stores, "
          f"{len(tabs) + (1 if store_sets else 0)} tab(s), "
          f"{dir_count} watchlist store(s))")
    if str(data_dst) != str(inputs[0]):
        print(f"Copied data to {data_dst}")


if __name__ == "__main__":
    main()
