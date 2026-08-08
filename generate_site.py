#!/usr/bin/env python3
"""
Weekend Sales matches -> static GitHub Pages site generator
===========================================================

Reads a matches.json produced by seraphim-weekend-scraper.py and renders
a single static page (docs/index.html) listing every match grouped by store
name, sorted alphabetically, in a clean magazine style similar to Seraphim.

The output is fully static (no JavaScript, no network calls) so it can be
served straight from GitHub Pages.

Folder layout (ready for GitHub Pages served from /docs):
    docs/
        index.html      <- generated page (commit this)

Usage
-----
    python generate_site.py                        # docs/index.html from matches.json
    python generate_site.py --input out.json \
        --output docs/index.html --title "Sales"
    python generate_site.py --copy-data            # also write docs/matches.json
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

STYLE = """:root {
  --bg: #0a0a0f;
  --panel: #12121c;
  --panel2: #181826;
  --panel3: #1f1f30;
  --border: rgba(255, 255, 255, .07);
  --border-strong: rgba(255, 255, 255, .14);
  --text: #eae8f2;
  --muted: #8b88a2;
  --faint: #5b5870;
  --accent: #c084fc;
  --accent-dim: rgba(192, 132, 252, .14);
  --accent-glow: rgba(192, 132, 252, .35);
  --pin: #8a5fd8;
  --pin-hover: #9a70e8;
  --pin-dim: rgba(138, 95, 216, .35);
  --radius: 14px;
  --radius-sm: 9px;
  --font: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --pin-icon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23ffffff'%3E%3Cpath d='M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z'/%3E%3C/svg%3E");
}
* { box-sizing: border-box; }
html { scrollbar-gutter: stable; }
html, body { margin: 0; padding: 0; }
body {
  background:
    radial-gradient(1100px 520px at 85% -8%, rgba(192, 132, 252, .10), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(192, 132, 252, .05), transparent 55%),
    var(--bg);
  color: var(--text);
  font-family: var(--font);
  font-size: 15px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
::selection { background: var(--accent-dim); color: var(--accent); }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--panel3); border-radius: 20px; border: 2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background: var(--accent-glow); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.site-header {
  background: rgba(12, 12, 19, .78);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
}
.site-header .wrap {
  max-width: 1280px;
  margin: 0 auto;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.brand-dot {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  flex: 0 0 auto;
  background: var(--accent);
  box-shadow: 0 0 0 5px var(--accent-dim), 0 0 18px var(--accent);
}
.site-header h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: .6px;
  line-height: 1.2;
  text-transform: uppercase;
}
.site-header h1 a { color: var(--text); }
.brand-sub {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 2px;
  text-transform: uppercase;
}

.wrap { max-width: 1280px; margin: 0 auto; padding: 0 20px; }

.summary {
  display: flex;
  justify-content: flex-start;
  padding: 16px 20px 0;
}
.summary .pill {
  font-size: 12.5px;
  color: var(--muted);
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 6px 16px;
}

.tabs {
  max-width: 1280px;
  margin: 0 auto;
  padding: 14px 20px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-bottom: 1px solid var(--border);
}
.tab-btn {
  padding: 8px 18px;
  margin-bottom: -1px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-bottom: none;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  color: var(--muted);
  font-family: var(--font);
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s;
}
.tab-btn:hover { color: var(--text); border-color: var(--border-strong); }
.tab-btn.active {
  background: var(--panel3);
  color: var(--accent);
  border-color: var(--border-strong);
  border-bottom: 2px solid var(--accent);
}
.tab-btn.right { margin-left: auto; }
.tab-panel { display: none; }
.tab-panel[data-active] { display: block; animation: fade .2s ease; }
@keyframes fade {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}
.tab-count {
  padding: 14px 0 4px;
  font-size: 12.5px;
  color: var(--muted);
}

.stores-title {
  margin: 22px 0 2px;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: .3px;
  color: var(--text);
}
.store-directory {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  padding: 16px 0 26px;
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
  margin: 8px 0 0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.6px;
  text-transform: uppercase;
  color: var(--muted);
}
.store-group {
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: var(--radius);
  padding: 12px 14px 14px;
  min-width: 0;
  transition: border-color .15s;
}
.store-group:hover { border-color: var(--border-strong); }
.store-group-letter {
  margin: 0 0 10px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.4px;
  color: var(--accent);
  border-bottom: 1px dashed var(--border-strong);
  padding-bottom: 8px;
}
.store-group-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-wrap: anywhere;
}
.store-group-list li {
  font-size: 13px;
  padding: 2.5px 0;
  color: var(--text);
  opacity: .9;
}

.store-items {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
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
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: var(--radius);
  overflow: hidden;
  transition: transform .16s ease, border-color .16s, box-shadow .16s;
}
.card:hover {
  border-color: var(--accent);
  transform: translateY(-3px);
  box-shadow: 0 10px 34px rgba(192, 132, 252, .13);
}
.card img {
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  display: block;
  transition: transform .3s ease, opacity .3s;
  opacity: 0;
}
.card img.loaded { opacity: 1; }
.card:hover img { transform: scale(1.06); }
.card-body {
  padding: 11px 12px 12px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
  flex: 1;
}
.card-title {
  font-size: 13.5px;
  font-weight: 650;
  line-height: 1.3;
  margin: 0;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 35px;
}
.card-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: auto;
}
.badge {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .3px;
  padding: 2px 8px;
  border-radius: 20px;
  background: var(--panel2);
  color: var(--muted);
  border: 1px solid var(--border);
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.badge a { color: inherit; }
.badge a:hover { color: var(--accent); text-decoration: none; }
.badge.slurl {
  background: var(--pin);
  color: #fff;
  border-color: transparent;
}
.badge.slurl::before {
  content: "";
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 4px;
  vertical-align: -1px;
  background: var(--pin-icon) no-repeat center / contain;
}
.badge.slurl a { color: #fff; }
.badge.slurl a:hover { text-decoration: underline; }
.card-caption {
  font-size: 12px;
  color: var(--muted);
  overflow-wrap: anywhere;
}
.card-caption a { color: var(--accent); }
.card-caption a[href*="maps.secondlife.com"] {
  display: inline-block;
  margin: 1px 2px 1px 0;
  padding: 2px 9px;
  border-radius: 20px;
  background: var(--pin);
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .2px;
}
.card-caption a[href*="maps.secondlife.com"]::before {
  content: "";
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 4px;
  vertical-align: -1px;
  background: var(--pin-icon) no-repeat center / contain;
}
.card-caption a[href*="maps.secondlife.com"]:hover {
  background: var(--pin-hover);
  text-decoration: none;
}

.empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--muted);
}

/* Lightbox */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: none;
  align-items: center;
  justify-content: center;
  background: rgba(5, 5, 9, .88);
  backdrop-filter: blur(8px);
}
.lightbox:not([hidden]) { display: flex; animation: fade .18s ease; }
.lightbox figure {
  margin: 0;
  max-width: min(900px, 92vw);
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.lightbox img {
  max-width: 100%;
  max-height: 78vh;
  object-fit: contain;
  border-radius: var(--radius);
  border: 1px solid var(--border-strong);
  box-shadow: 0 20px 70px rgba(0, 0, 0, .6);
  background: var(--panel);
  transition: opacity .2s ease;
}
.lightbox.loading img { opacity: .25; }
.lb-spin {
  position: fixed;
  top: 50%;
  left: 50%;
  width: 54px;
  height: 54px;
  margin: -27px 0 0 -27px;
  border: 4px solid rgba(255, 255, 255, .15);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: lb-spin .8s linear infinite;
  z-index: 1002;
}
.lb-spin[hidden] { display: none; }
@keyframes lb-spin {
  to { transform: rotate(360deg); }
}
.lb-cap {
  color: var(--text);
  text-align: center;
  font-size: 13.5px;
}
.lb-cap .lb-title {
  font-weight: 700;
  font-size: 15px;
  display: block;
  margin-bottom: 6px;
}
.lb-cap .lb-meta {
  color: var(--muted);
  font-size: 12.5px;
  max-width: min(640px, 86vw);
  margin: 0 auto;
  overflow-wrap: anywhere;
}
.lb-row { margin-top: 10px; }
.lb-visit {
  display: inline-block;
  padding: 7px 18px;
  border-radius: 20px;
  background: var(--pin);
  color: #fff;
  font-weight: 600;
  font-size: 13px;
  letter-spacing: .3px;
  box-shadow: 0 4px 20px var(--pin-dim);
}
.lb-visit:hover {
  background: var(--pin-hover);
  color: #fff;
  text-decoration: none;
}
.lb-visit::before {
  content: "";
  display: inline-block;
  width: 11px;
  height: 11px;
  margin-right: 6px;
  vertical-align: -1px;
  background: var(--pin-icon) no-repeat center / contain;
}
.lb-btn {
  position: fixed;
  z-index: 1001;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  cursor: pointer;
  background: var(--panel2);
  border: 1px solid var(--border-strong);
  color: var(--text);
  font-size: 22px;
  line-height: 1;
  transition: all .15s;
}
.lb-btn:hover {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--accent);
}
.lb-close { top: 20px; right: 22px; font-size: 26px; }
.lb-prev { left: 20px; top: 50%; transform: translateY(-50%); }
.lb-next { right: 20px; top: 50%; transform: translateY(-50%); }
@media (max-width: 640px) {
  .lb-prev, .lb-next { top: auto; bottom: 22px; transform: none; }
}

.site-footer {
  border-top: 1px solid var(--border);
  color: var(--faint);
  padding: 18px 20px;
  font-size: 12px;
  text-align: center;
}
.site-footer a { color: var(--muted); }
.site-footer a:hover { color: var(--accent); }
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

    badges = []
    if event_url:
        badges.append(
            f'<span class="badge"><a href="{event_url}" target="_blank" rel="noopener">{event_title or "Event page"}</a></span>'
        )
    if gallery_url and gallery_url != event_url:
        badges.append(
            f'<span class="badge"><a href="{gallery_url}" target="_blank" rel="noopener">Gallery</a></span>'
        )

    caption = sanitize_caption(item.get("caption_html", ""))
    caption_html = f'<div class="card-caption">{caption}</div>' if caption else ""
    badges_html = f'<div class="card-badges">{"".join(badges)}</div>' if badges else ""

    thumb = htmlmod.escape(item.get("thumb_url") or item.get("image_url", ""))

    return f"""
    <div class="card">
      <a href="{img}" target="_blank" rel="noopener" class="card-anchor" data-tab="{tab}" data-index="{index}"><img src="{thumb}" alt="{store}" loading="lazy"></a>
      <div class="card-body">
        <p class="card-title">{store}</p>
        {badges_html}
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
        f'  <div class="tab-count">{total} store(s) - Contact Atasly resident for more</div>\n'
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
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='40' fill='%23c084fc'/></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{STYLE}</style>
</head>
<body>
<header class="site-header">
  <div class="wrap">
    <span class="brand-dot"></span>
    <div>
      <h1><a href="https://github.com/Atasly/Seraphim-SL-Watchlist">{htmlmod.escape(title)}</a></h1>
      <p class="brand-sub">Second Life weekend sales &mdash; Curated and Compiled</p>
    </div>
  </div>
</header>

{tabs_html}

<div class="summary wrap"><span class="pill">
  {total} match(es) across {total_stores} store(s)
  &middot; sorted by store name
  &middot; generated {now}
</span></div>

<main class="wrap">{''.join(panels)}</main>

<footer class="site-footer">
  Generated by <a href="https://github.com/Atasly/Seraphim-SL-Watchlist">Seraphim SL Watchlist</a>
</footer>

<div id="lb" class="lightbox" hidden aria-hidden="true">
  <button id="lb-close" class="lb-btn lb-close" aria-label="Close" title="Close">&times;</button>
  <button id="lb-prev" class="lb-btn lb-prev" aria-label="Previous" title="Previous">&#8249;</button>
  <button id="lb-next" class="lb-btn lb-next" aria-label="Next" title="Next">&#8250;</button>
  <div id="lb-spin" class="lb-spin" hidden></div>
  <figure>
    <img id="lb-img" src="" alt="">
    <figcaption id="lb-cap" class="lb-cap"></figcaption>
  </figure>
</div>

<script>
const TABS = {tabs_json};
(function () {{
  const links = Array.from(document.querySelectorAll('.card-anchor'));
  const lb = document.getElementById('lb');
  const img = document.getElementById('lb-img');
  const cap = document.getElementById('lb-cap');
  const spin = document.getElementById('lb-spin');
  let curTab = 0;
  let curIdx = -1;
  let loadSeq = 0;

  function items(t) {{ return TABS[t] ? TABS[t].items : []; }}

  function esc(s) {{
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }}

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
    let html = '<span class="lb-title">' + esc(it.store) + '</span>';
    if (it.event_title) html += '<div class="lb-meta">' + esc(it.event_title) + '</div>';
    if (it.slurl) html += '<div class="lb-row"><a class="lb-visit" href="' + esc(it.slurl) + '" target="_blank" rel="noopener">Visit store &#8599;</a></div>';
    cap.innerHTML = html;
    lb.hidden = false;
    lb.setAttribute('aria-hidden', 'false');
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
    lb.setAttribute('aria-hidden', 'true');
    img.src = '';
    cap.innerHTML = '';
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
    parser.add_argument(
        "--copy-data",
        nargs="?",
        const="",
        help="Copy the input JSON into docs/ (default: disabled). "
        "Optional destination path; defaults to docs/matches.json.",
    )
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

    if args.copy_data is not None:
        data_dst = Path(args.copy_data) if args.copy_data else output_path.parent / inputs[0].name
        data_dst.parent.mkdir(parents=True, exist_ok=True)
        data_dst.write_bytes(inputs[0].read_bytes())
        print(f"Copied data to {data_dst}")

    total = sum(len(m) for _, m in tabs)
    total_stores = len({m.get("store_name") for _, m in tabs for m in m})
    dir_count = sum(len(names) for _, cats in store_sets for names in cats.values())
    print(f"Wrote {output_path} ({total} matches, {total_stores} stores, "
          f"{len(tabs) + (1 if store_sets else 0)} tab(s), "
          f"{dir_count} watchlist store(s))")


if __name__ == "__main__":
    main()
