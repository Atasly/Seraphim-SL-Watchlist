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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from urllib.parse import quote, unquote

DEFAULT_INPUT = Path(__file__).parent / "matches.json"
DEFAULT_OUTPUT = Path(__file__).parent / "docs" / "index.html"

# Per-tab tag line shown above the summary counts in the page header.
# Keyed by the tab label (--tab-label). The active tab's tag is shown.
# TODO: replace each TODO below with a short description of what the
# category contains (e.g. what "single" means for your watchlist).
TAB_TAGS = {
    "single": "Where individual weekend sales are (mostly) mod.",
    "fatpack": "Where fatpacks, on weekend sales or not, are (mostly) mod.",
    "build": "Weekend sales focusing on stores with furnitures/building resources",
}

FB_LOOKASIDE_URL = "https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id={}"
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")
_DOCS_DIR = DEFAULT_OUTPUT.parent

_COPY_ICON = (
    '<svg class="icon-copy" viewBox="0 0 16 16" width="12" height="12" fill="none" '
    'stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.2"/>'
    '<path d="M10.5 3.5v-1A1.5 1.5 0 0 0 9 1H3.5A1.5 1.5 0 0 0 2 2.5v6A1.5 1.5 0 0 0 3.5 10h1"/></svg>'
    '<svg class="icon-copied" viewBox="0 0 16 16" width="12" height="12" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
    'aria-hidden="true"><path d="M2.5 8.5 6 12 13.5 4.5"/></svg>'
)


def _local_image_usable(url: str) -> bool:
    """True when a docs-relative image path exists and looks like a real image."""
    if not url or "://" in url or url.startswith(("//", "data:", "/")):
        return False
    path = (_DOCS_DIR / url).resolve()
    try:
        if not path.is_file():
            return False
        with open(path, "rb") as fh:
            head = fh.read(12)
        return head.startswith(_IMAGE_MAGIC)
    except OSError:
        return False


def resolve_item_image(item: dict, field: str) -> str:
    """Resolve item[field] to a URL the page can actually serve.

    Local img/fb/... paths are used only when the file is present and looks
    like a real image; otherwise the Facebook lookaside URL is substituted
    (when a media_id is known) so a card never points at a missing file.
    Non-local URLs pass through unchanged.
    """
    url = item.get(field) or ""
    if not url:
        return ""
    if url.startswith("img/fb/"):
        if _local_image_usable(url):
            return url
        media_id = item.get("media_id") or ""
        if media_id:
            return FB_LOOKASIDE_URL.format(quote(media_id, safe=""))
        return ""
    return url

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
.summary-tag {
  font-weight: 600;
  color: var(--accent);
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

.daybar {
  max-width: 1280px;
  margin: 0 auto;
  padding: 14px 20px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip {
  padding: 7px 16px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--muted);
  font-family: var(--font);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s;
}
.chip:hover { color: var(--text); border-color: var(--border-strong); }
.chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.chip .chip-count {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(127, 127, 127, .18);
  font-size: 11px;
  font-weight: 700;
}
.chip.active .chip-count { background: rgba(0, 0, 0, .18); }
.card[data-day] { }
.card[hidden] { display: none; }
.card.hidden { display: none; }
.daybar[hidden] { display: none; }

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

.events-count {
  margin: 2px 0 14px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .3px;
  color: var(--muted);
}
.event-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0 26px;
}
.event-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  border: 1px solid var(--border);
  background: var(--panel);
  border-radius: var(--radius);
  padding: 12px 14px;
  color: inherit;
  transition: border-color .15s;
}
.event-row:hover { border-color: var(--border-strong); }
.event-badge {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .5px;
  text-transform: uppercase;
  padding: 3px 9px;
  border-radius: 20px;
  white-space: nowrap;
}
.event-badge.active {
  background: rgba(74, 222, 128, .12);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, .35);
}
.event-badge.new {
  background: var(--accent-dim);
  color: var(--accent);
  border: 1px solid var(--accent-glow);
}
.event-badge.closing {
  background: rgba(251, 146, 60, .13);
  color: #fb923c;
  border: 1px solid rgba(251, 146, 60, .4);
}
.event-badge.cat-burgundy {
  background: rgba(190, 24, 60, .15);
  color: #fb7185;
  border: 1px solid rgba(190, 24, 60, .45);
}
.event-badge.cat-violet {
  background: rgba(160, 100, 250, .14);
  color: #c4b5fd #8F00FF;
  border: 1px solid rgba(160, 100, 250, .4);
}
.event-badge.cat-turquoise {
  background: rgba(45, 212, 191, .12);
  color: #2dd4bf;
  border: 1px solid rgba(45, 212, 191, .4);
}
.event-badge.cat-gold {
  background: rgba(250, 204, 21, .12);
  color: #facc15;
  border: 1px solid rgba(250, 204, 21, .4);
}
.event-badge.cat-grey {
  background: var(--panel2);
  color: var(--muted);
  border: 1px solid var(--border);
}
.event-badge.ended {
  background: var(--panel2);
  color: var(--muted);
  border: 1px solid var(--border);
}
.event-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--accent);
}
.event-title {
  font-size: 13px;
  color: var(--text);
  opacity: .92;
  min-width: 0;
  overflow-wrap: anywhere;
}
.event-dates {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  white-space: nowrap;
}
@media (max-width: 640px) {
  .event-dates { margin-left: 0; }
}
.event-directory {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 0 26px;
}
.event-chip {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .3px;
  padding: 4px 11px;
  border-radius: 20px;
  background: var(--panel);
  color: var(--muted);
  border: 1px solid var(--border);
  white-space: nowrap;
}
.event-chip.active {
  background: rgba(74, 222, 128, .12);
  color: #4ade80;
  border-color: rgba(74, 222, 128, .35);
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
.copy-btn {
  all: unset;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-left: 5px;
  vertical-align: middle;
  border-radius: 6px;
  color: rgba(255, 255, 255, .85);
  cursor: pointer;
}
.copy-btn:hover { background: rgba(255, 255, 255, .16); }
.copy-btn:active { background: rgba(255, 255, 255, .24); }
.copy-btn svg { width: 12px; height: 12px; }
.copy-btn .icon-copied { display: none; }
.copy-btn.copied .icon-copy { display: none; }
.copy-btn.copied .icon-copied { display: block; }
.card-noimg {
  display: grid;
  place-items: center;
  aspect-ratio: 4 / 3;
  background: var(--panel3);
  color: var(--muted);
}
.card-noimg span {
  font-size: 34px;
  font-weight: 700;
  opacity: .5;
}
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
.lb-count {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .5px;
  margin-bottom: 6px;
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
.lb-row .copy-btn {
  width: 30px;
  height: 30px;
  margin-left: 8px;
  vertical-align: middle;
  border: 1px solid var(--border);
  background: var(--panel2);
  color: var(--muted);
}
.lb-row .copy-btn svg { width: 14px; height: 14px; }
.lb-row .copy-btn:hover { color: #fff; background: var(--panel3); }
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

/* Back-to-top button */
.back-to-top {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 900;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: rgba(24, 24, 38, .9);
  backdrop-filter: blur(8px);
  color: var(--text);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  visibility: hidden;
  transform: translateY(8px);
  transition: opacity .18s ease, visibility .18s ease, transform .18s ease,
              background .15s ease, border-color .15s ease, color .15s ease;
}

.back-to-top.visible {
  opacity: 1;
  visibility: visible;
  transform: none;
}

.back-to-top:hover {
  background: var(--accent-dim);
  border-color: var(--accent);
  color: var(--accent);
}

.back-to-top:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

@media (max-width: 640px) {
  .back-to-top {
    right: 14px;
    bottom: 14px;
  }
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

    # Drop the teleport link entirely — the card badge is the single
    # "Visit store" button — then clean up leftover empty tags/separators.
    text = SLURL_A_RE.sub("", text)
    text = re.sub(r"<(\w+)\s*></\1>", "", text)
    text = re.sub(r"^(?:[\s\u00a0]*(?:-|–|—|\|)[\s\u00a0]*)+", "", text)

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


_SLURL_SIM_RE = re.compile(r"/secondlife/([^/]+)/")


def sim_from_slurl(slurl: str) -> str:
    """Decoded region/sim name from a maps.secondlife.com teleport URL."""
    if not slurl:
        return ""
    m = _SLURL_SIM_RE.search(slurl)
    return unquote(m.group(1)) if m else ""


def render_card(item: dict, index: int, tab: int) -> str:
    store = htmlmod.escape(item.get("store_name", ""))
    img = resolve_item_image(item, "image_url")
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

    slurl = item.get("slurl") or extract_slurl(item.get("caption_html", ""))
    if slurl:
        badges.append(
            f'<span class="badge slurl"><a href="{htmlmod.escape(slurl)}" target="_blank" rel="noopener">Visit store</a>'
            f'<button class="copy-btn" type="button" data-slurl="{htmlmod.escape(slurl)}" title="Copy link" aria-label="Copy link">{_COPY_ICON}</button></span>'
        )

    caption = sanitize_caption(item.get("caption_html", ""))
    caption_html = f'<div class="card-caption">{caption}</div>' if caption else ""
    badges_html = f'<div class="card-badges">{"".join(badges)}</div>' if badges else ""

    thumb = resolve_item_image(item, "thumb_url") or img
    day = htmlmod.escape(item.get("sale_day", ""))
    run = htmlmod.escape(item.get("matched_at", ""))

    if img:
        anchor = (
            f'<a href="{htmlmod.escape(img)}" target="_blank" rel="noopener" class="card-anchor" '
            f'data-tab="{tab}" data-index="{index}">'
            f'<img src="{htmlmod.escape(thumb)}" alt="{store}" loading="lazy"></a>'
        )
    else:
        initial = htmlmod.escape((item.get("store_name") or "?")[:1].upper())
        anchor = f'<div class="card-noimg"><span>{initial}</span></div>'

    return f"""
    <div class="card" data-day="{day}" data-run="{run}">
      {anchor}
      <div class="card-body">
        <p class="card-title">{store}</p>
        {badges_html}
        {caption_html}
      </div>
    </div>"""


def _run_label(run: str) -> str:
    try:
        return datetime.fromisoformat(run).strftime("%b %d %H:%M")
    except (TypeError, ValueError):
        return run


def render_flat_grid(matches: List[dict], tab: int) -> tuple:
    """Render one store list as a flat grid; return (html, lightbox items)."""
    if not matches:
        return '<div class="empty"><p>No matches yet. Run the scraper and regenerate.</p></div>', []

    # Order by landmark (region/sim) first so same-sim stores sit together
    # and reduce hopping between sims, then by store name within a sim.
    def sim_key(it: dict) -> str:
        slurl = it.get("slurl") or extract_slurl(it.get("caption_html", ""))
        return sim_from_slurl(slurl)

    flat = sorted(
        matches,
        key=lambda it: (
            sim_key(it).lower(),
            it.get("store_name", "").lower(),
        ),
    )
    cards = "\n".join(render_card(it, i, tab) for i, it in enumerate(flat))
    items = [
        {
            "img": resolve_item_image(it, "image_url"),
            "thumb": resolve_item_image(it, "thumb_url") or resolve_item_image(it, "image_url"),
            "store": it.get("store_name", ""),
            "event_url": it.get("source_event_url", ""),
            "event_title": it.get("source_event_title", ""),
            "slurl": it.get("slurl") or extract_slurl(it.get("caption_html", "")),
            "day": it.get("sale_day", ""),
            "run": it.get("matched_at", ""),
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


def _parse_loose_date(v):
    """ISO date first, then common 'Month d, YYYY' shapes; else None."""
    if not v:
        return None
    try:
        return datetime.fromisoformat(v).date()
    except (TypeError, ValueError):
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date()
        except (TypeError, ValueError):
            continue
    return None


def _fmt_event_range(posted: str, closing: str) -> str:
    """'Aug 14 – Aug 23, 2026' style range from date strings (best effort)."""
    o, c = _parse_loose_date(posted), _parse_loose_date(closing)
    if c is None and o is None:
        return ""
    if c is None:
        return f"since {o:%b %d, %Y}"
    if o is None or o.year != c.year:
        return f"{c:%b %d, %Y}"
    if o == c:
        return f"{c:%b %d, %Y}"
    return f"{o:%b %d} \u2013 {c:%b %d, %Y}"


_EVENT_CAT_COLORS = (
    ("kinky", "burgundy"),
    ("flf", "violet"),
    ("syndicate", "turquoise"),
    ("asian", "gold"),
)


def _event_cat_color_key(category: str) -> str:
    low = (category or "").lower()
    for keyword, key in _EVENT_CAT_COLORS:
        if keyword in low:
            return key
    return "grey"


def parse_event_categories(path) -> dict:
    """Map each event alias in a watched-events file to its category.

    A '# comment' line starts a category when it is short and free of
    sentence punctuation ('# Kinky', '# FLF'); prose comments like the
    file's usage note are ignored. Names before any header fall back to
    'Others'. Returns {alias_lower: (display_label, color_key)}.
    """
    path = Path(path)
    cat_map: dict = {}
    if not path.exists():
        return cat_map
    current = ("Others", "grey")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            header = line[1:].strip()
            if (
                header
                and len(header) <= 30
                and not any(ch in header for ch in ".,;!?")
            ):
                current = (header, _event_cat_color_key(header))
            continue
        cat_map[line.lower()] = current
    return cat_map


def render_events_panel(
    events: List[dict],
    tab: int,
    event_names: List[str] = None,
    event_cats: dict = None,
) -> str:
    """Render the tracked-events panel.

    Deliberately avoids .card/.tab-count class names so the run-filter
    script (which toggles those globally) cannot touch event rows.
    When `event_names` is provided, a 'Watched events' directory listing
    every watched name (active chips carry the closing date) is appended.
    Active rows also carry a category pill when `event_cats` maps their
    alias to one.
    """
    today = datetime.now().date()

    def closing_of(ev: dict):
        return _parse_loose_date(ev.get("closing_date"))

    def badge_for(ev: dict) -> tuple:
        """(css_class, label) for one event row.

        Active events get 'New' when opened less than 7 days ago, else
        'Closing' when less than 3 days remain; New wins over Closing.
        """
        if is_ended(ev):
            return ("ended", "Ended")
        opening = _parse_loose_date(ev.get("posted_date"))
        closing = closing_of(ev)
        if opening is not None and (today - opening).days < 7:
            return ("new", "New")
        if closing is not None and (closing - today).days < 3:
            return ("closing", "Closing")
        return ("active", "Active")

    def is_ended(ev: dict) -> bool:
        closing = closing_of(ev)
        return ev.get("status") == "ended" or (closing is not None and closing < today)

    active = sorted(
        (ev for ev in events if not is_ended(ev)),
        key=lambda ev: (closing_of(ev) is None, closing_of(ev) or today),
    )
    ended = sorted(
        (ev for ev in events if is_ended(ev)),
        key=lambda ev: closing_of(ev) or today,
        reverse=True,
    )

    rows_html = []
    for ev in active + ended:
        name = htmlmod.escape(ev.get("event_name") or "?")
        title = htmlmod.escape(ev.get("title") or "")
        url = htmlmod.escape(ev.get("url") or "", quote=True)
        dates = _fmt_event_range(ev.get("posted_date"), ev.get("closing_date"))
        badge, label = badge_for(ev)
        cat_html = ""
        if badge != "ended" and event_cats:
            cat = event_cats.get((ev.get("event_name") or "").strip().lower())
            if cat:
                cat_label, cat_key = cat
                cat_html = (
                    f'\n      <span class="event-badge cat-{cat_key}">'
                    f"{htmlmod.escape(cat_label)}</span>"
                )
        rows_html.append(
            f'    <a class="event-row" href="{url}" target="_blank" rel="noopener">\n'
            f'      <span class="event-badge {badge}">{label}</span>{cat_html}\n'
            f'      <span class="event-name">{name}</span>\n'
            f'      <span class="event-title">{title}</span>\n'
            f'      <span class="event-dates">{htmlmod.escape(dates)}</span>\n'
            f"    </a>"
        )

    body = "\n".join(rows_html) if rows_html else (
        '    <div class="empty"><p>No tracked events right now.</p></div>'
    )

    directory_html = ""
    if event_names:
        active_until = {}
        for ev in active:
            name = (ev.get("event_name") or "").strip().lower()
            closing = closing_of(ev)
            if name and closing and (name not in active_until or closing > active_until[name]):
                active_until[name] = closing
        chips_html = []
        for name in sorted(event_names, key=lambda n: n.lower()):
            display = htmlmod.escape(name)
            closing = active_until.get(name.strip().lower())
            if closing:
                chips_html.append(
                    f'<span class="event-chip active">{display} &middot; until {closing:%b %d}</span>'
                )
            else:
                chips_html.append(f'<span class="event-chip">{display}</span>')
        directory_html = (
            f'\n  <h3 class="store-set-label">Watched events</h3>\n'
            f'  <div class="event-directory">\n'
            f'    {" ".join(chips_html)}\n'
            f"  </div>"
        )

    return (
        f'<div class="tab-panel" id="tab-{tab}">\n'
        f'  <h2 class="stores-title">Tracked events</h2>\n'
        f'  <div class="events-count">{len(active)} active &middot; '
        f"{len(ended)} ended</div>\n"
        f'  <div class="event-list">\n{body}\n  </div>'
        f"{directory_html}\n"
        f"</div>"
    )


def render_page(
    tabs: List[tuple],
    title: str,
    store_sets: List[tuple] = (),
    stores_label: str = "Watchlist",
    events: List[dict] = None,
    events_label: str = "Events",
    event_names: List[str] = None,
    event_cats: dict = None,
) -> str:
    """Render the page. `tabs` is a list of (label, matches) tuples.

    When `events` is non-empty, a tab (labelled `events_label`) listing the
    tracked events is inserted after the match tabs. When `store_sets` is
    non-empty, a right-aligned tab (labelled `stores_label`) listing the
    watchlist directories is appended last.
    """
    panels = []
    tabs_data: List[dict] = []
    total = 0
    total_stores = 0
    for t, (label, matches) in enumerate(tabs):
        body, items = render_flat_grid(matches, t)
        total += len(items)
        total_stores += len({i["store"] for i in items})
        #count = f'<div class="tab-count">{len(items)} match(es) across {len({i["store"] for i in items})} store(s)</div>'
        active = ' data-active=""' if t == 0 else ''
        panels.append(f'<div class="tab-panel" id="tab-{t}"{active}>{body}</div>')
        tabs_data.append(
            {"label": label, "items": items, "tag": TAB_TAGS.get(label, "")}
        )

    events_tab = None
    if events is not None:
        events_tab = len(tabs)
        panels.append(
            render_events_panel(events, events_tab, event_names or [], event_cats or {})
        )

    store_tab = len(tabs) + (1 if events is not None else 0)
    if store_sets:
        panels.append(render_stores_panel(store_sets, store_tab))

    tabs_json = json.dumps(tabs_data, ensure_ascii=False).replace("<", "\\u003c")
    button_count = len(tabs) + (1 if store_sets else 0) + (1 if events is not None else 0)
    tabs_html = ""
    if button_count > 1:
        buttons = [
            f'  <button class="tab-btn{" active" if t == 0 else ""}" data-tab="{t}">'
            f'{htmlmod.escape(label)}</button>'
            for t, (label, _) in enumerate(tabs)
        ]
        # Right-aligned group: the FIRST right button carries margin-left:auto
        # (pushing itself and everything after it to the far edge); any further
        # ones must sit adjacent, or flexbox would distribute the free space
        # between them.
        right_side = []
        if events is not None:
            right_side.append((events_tab, events_label))
        if store_sets:
            right_side.append((store_tab, stores_label))
        for i, (tab_idx, tab_label) in enumerate(right_side):
            buttons.append(
                f'  <button class="tab-btn{" right" if i == 0 else ""}" '
                f'data-tab="{tab_idx}">{htmlmod.escape(tab_label)}</button>'
            )
        tabs_html = (
            '<nav class="tabs" id="tabs">\n'
            + "\n".join(buttons)
            + "\n</nav>"
        )

    # Run-bar counts reflect the active category tab, so the initial render
    # (tab 0) seeds the chips; JS recomputes them when the tab changes.
    first_tab_items = tabs_data[0]["items"] if tabs_data else []
    all_total = len(first_tab_items)
    run_counts: Dict[str, int] = {}
    for it in first_tab_items:
        run = it.get("run") or ""
        if run:
            run_counts[run] = run_counts.get(run, 0) + 1
    daybar_html = ""
    if run_counts:
        rows = [("all", "All", all_total)] + [
            (run, _run_label(run), run_counts[run])
            for run in sorted(run_counts)  # oldest run first
        ]
        daybar_html = (
            '<nav class="daybar" id="daybar">\n'
            + "\n".join(
                f'  <button class="chip{" active" if run == "all" else ""}" '
                f'data-run="{run}"><span class="chip-label">{label}</span> <span class="chip-count">{n}</span></button>'
                for run, label, n in rows
            )
            + "\n</nav>"
        )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    tag0 = tabs_data[0].get("tag", "") if tabs_data else ""
    if tag0:
        tag_html = (
            f'<span class="summary-tag" id="summary-tag">'
            f"{htmlmod.escape(tag0)}</span> &middot; "
        )
    else:
        tag_html = '<span class="summary-tag" id="summary-tag"></span>'

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

{daybar_html}

<div class="summary wrap"><span class="pill">
  {tag_html}
  {total} match(es) across {total_stores} store(s)
  &middot; sorted by store
  &middot; generated <time id="generated-at" datetime="{now}"></time>
</span></div>

<main class="wrap">{''.join(panels)}</main>

<footer class="site-footer">
  This work is not afiliated with Seraphim. All credits go to [SeraphimSL](https://www.seraphimsl.com/) team for their invaluable work.
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

<button id="back-to-top" class="back-to-top" type="button" aria-label="Back to top" title="Back to top">&#8593;</button>

<script>
const TABS = {tabs_json};
(function () {{
  const links = Array.from(document.querySelectorAll('.card-anchor'));
  const lb = document.getElementById('lb');
  const img = document.getElementById('lb-img');
  const cap = document.getElementById('lb-cap');
  const spin = document.getElementById('lb-spin');
  const backToTop = document.getElementById('back-to-top');
  let curTab = 0;
  let curIdx = -1;
  let loadSeq = 0;
  let activeRun = 'all';

  function items(t) {{ return TABS[t] ? TABS[t].items : []; }}

  function runMatches(run) {{
    return activeRun === 'all' || run === activeRun;
  }}

  function visibleIndices(tab) {{
    const list = items(tab);
    const out = [];
    for (let i = 0; i < list.length; i++) {{
      if (runMatches(list[i].run)) out.push(i);
    }}
    return out;
  }}

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
    const vis = visibleIndices(tab);
    const pos = vis.indexOf(curIdx);
    const shown = pos === -1 ? curIdx + 1 : pos + 1;
    const shownOf = pos === -1 ? list.length : vis.length;
    let html = '<div class="lb-count">' + shown + ' / ' + shownOf + '</div>';
    html += '<span class="lb-title">' + esc(it.store) + '</span>';
    if (it.event_title) html += '<div class="lb-meta">' + esc(it.event_title) + '</div>';
    if (it.slurl) html += '<div class="lb-row"><a class="lb-visit" href="' + esc(it.slurl) + '" target="_blank" rel="noopener">Visit store &#8599;</a><button class="copy-btn lb-copy" type="button" data-slurl="' + esc(it.slurl) + '" title="Copy link" aria-label="Copy link"><svg class="icon-copy" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.2"/><path d="M10.5 3.5v-1A1.5 1.5 0 0 0 9 1H3.5A1.5 1.5 0 0 0 2 2.5v6A1.5 1.5 0 0 0 3.5 10h1"/></svg><svg class="icon-copied" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 8.5 6 12 13.5 4.5"/></svg></button></div>';
    cap.innerHTML = html;
    lb.hidden = false;
    lb.setAttribute('aria-hidden', 'false');
    if (img.complete && img.naturalWidth) {{
      spin.hidden = true;
      lb.classList.remove('loading');
    }}
    const link = document.querySelector('.card-anchor[data-tab="' + curTab + '"][data-index="' + curIdx + '"]');
    if (link) link.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
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
    const link = document.querySelector('.card-anchor[data-tab="' + curTab + '"][data-index="' + curIdx + '"]');
    if (link) link.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }}
  function nav(d) {{
    const vis = visibleIndices(curTab);
    if (!vis.length) return;
    let pos = vis.indexOf(curIdx);
    if (pos === -1) pos = 0;
    pos = (pos + d + vis.length) % vis.length;
    show(curTab, vis[pos]);
  }}

  function applyFilter() {{
    let visible = 0;
    const storeSet = new Set();
    document.querySelectorAll('.card').forEach(function (card) {{
      const ok = runMatches(card.dataset.run || '');
      card.classList.toggle('hidden', !ok);
      if (ok) {{
        visible++;
        const title = card.querySelector('.card-title');
        if (title) storeSet.add(title.textContent);
      }}
    }});
    const countEl = document.querySelector('.tab-panel[data-active] .tab-count');
    if (countEl) {{
      countEl.textContent = visible + ' match(es) across ' + storeSet.size + ' store(s)';
    }}
  }}

  function updateRunCounts() {{
    const list = items(curTab);
    const counts = {{}};
    for (let i = 0; i < list.length; i++) {{
      const r = list[i].run;
      if (r) counts[r] = (counts[r] || 0) + 1;
    }}
    const daybar = document.getElementById('daybar');
    if (!daybar) return;
    daybar.querySelectorAll('.chip').forEach(function (chip) {{
      const r = chip.dataset.run;
      const n = r === 'all' ? list.length : (counts[r] || 0);
      const span = chip.querySelector('.chip-count');
      if (span) span.textContent = n;
    }});
  }}

  function selectTab(t) {{
    curTab = t;
    document.querySelectorAll('.tab-panel').forEach(function (p, i) {{
      if (i === t) p.setAttribute('data-active', '');
      else p.removeAttribute('data-active');
    }});
    document.querySelectorAll('.tab-btn').forEach(function (b) {{
      b.classList.toggle('active', Number(b.dataset.tab) === t);
    }});
    const daybar = document.getElementById('daybar');
    if (daybar) daybar.hidden = document.querySelector('.tab-panel[data-active] .card') == null;
    const tagEl = document.getElementById('summary-tag');
    if (tagEl) tagEl.textContent = (TABS[t] && TABS[t].tag) || '';
    updateRunCounts();
    applyFilter();
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
  const daybar = document.getElementById('daybar');
  if (daybar) {{
    daybar.querySelectorAll('.chip').forEach(function (chip) {{
      chip.addEventListener('click', function () {{
        activeRun = chip.dataset.run;
        daybar.querySelectorAll('.chip').forEach(function (c) {{
          c.classList.toggle('active', c === chip);
        }});
        applyFilter();
        if (!lb.hidden) close();
      }});
    }});
  }}
  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', function () {{ nav(-1); }});
  document.getElementById('lb-next').addEventListener('click', function () {{ nav(1); }});
  lb.addEventListener('click', function (e) {{
    if (e.target === lb) close();
  }});
  function updateBackToTop() {{
    if (backToTop) backToTop.classList.toggle('visible', window.scrollY > 300);
  }}

  if (backToTop) {{
    backToTop.addEventListener('click', function () {{
      window.scrollTo({{ top: 0, behavior: 'smooth' }});
    }});
    window.addEventListener('scroll', updateBackToTop, {{ passive: true }});
    updateBackToTop();
  }}

  document.addEventListener('keydown', function (e) {{
    if (!lb.hidden) {{
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') nav(-1);
      else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') nav(1);
      return;
    }}
    if (e.key === 'Escape') window.scrollTo({{ top: 0, behavior: 'smooth' }});
  }});

  document.addEventListener('click', function (e) {{
    var btn = e.target && e.target.closest ? e.target.closest('.copy-btn') : null;
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    var text = btn.getAttribute('data-slurl') || '';
    if (!text) return;
    var ok = function () {{
      btn.classList.add('copied');
      setTimeout(function () {{ btn.classList.remove('copied'); }}, 1500);
    }};
    var legacy = function () {{
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {{ document.execCommand('copy'); }} catch (err) {{}}
      document.body.removeChild(ta);
      ok();
    }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(text).then(ok).catch(legacy);
    }} else {{
      legacy();
    }}
  }});

  selectTab(0);

  var gen = document.getElementById('generated-at');
  if (gen) {{
    var gd = new Date(gen.getAttribute('datetime'));
    if (!isNaN(gd)) {{
      gen.textContent = gd.toLocaleString(undefined, {{month:'long', day:'numeric', year:'numeric', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}});
    }}
  }}
  var fmtChip = function (iso) {{
    var d = new Date(iso);
    if (isNaN(d)) return null;
    return d.toLocaleString(undefined, {{month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}});
  }};
  var daybar2 = document.getElementById('daybar');
  if (daybar2) {{
    daybar2.querySelectorAll('.chip[data-run]').forEach(function (chip) {{
      if (chip.dataset.run === 'all') return;
      var lbl = chip.querySelector('.chip-label');
      if (!lbl) return;
      var t = fmtChip(chip.dataset.run);
      if (t) lbl.textContent = t;
    }});
  }}
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
        "--events-file",
        default=None,
        help="Path to a tracked-events JSON (from consolidate_matches.py "
        "--events-main). Adds an Events tab left of the stores tab.",
    )
    parser.add_argument(
        "--events-label",
        default="Events",
        help="Label for the tracked-events tab (default: Events).",
    )
    parser.add_argument(
        "--events-list",
        default=None,
        help="Path to the watched-events name list (e.g. Events.txt). Adds a "
        "'Watched events' directory to the events panel.",
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

    events = None
    if args.events_file:
        events_path = Path(args.events_file)
        if not events_path.exists():
            print(f"ERROR: events file not found: {events_path}", file=sys.stderr)
            raise SystemExit(1)
        events = json.loads(events_path.read_text(encoding="utf-8"))

    event_names: List[str] = []
    event_cats: dict = {}
    if args.events_list:
        list_path = Path(args.events_list)
        if not list_path.exists():
            print(f"ERROR: events list not found: {list_path}", file=sys.stderr)
            raise SystemExit(1)
        for line in list_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                event_names.append(line)
        event_cats = parse_event_categories(list_path)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_page(
            tabs,
            args.title,
            store_sets,
            args.stores_label,
            events,
            args.events_label,
            event_names,
            event_cats,
        ),
        encoding="utf-8",
    )

    if args.copy_data is not None:
        data_dst = Path(args.copy_data) if args.copy_data else output_path.parent / inputs[0].name
        data_dst.parent.mkdir(parents=True, exist_ok=True)
        data_dst.write_bytes(inputs[0].read_bytes())
        print(f"Copied data to {data_dst}")

    total = sum(len(m) for _, m in tabs)
    total_stores = len({m.get("store_name") for _, m in tabs for m in m})
    dir_count = sum(len(names) for _, cats in store_sets for names in cats.values())
    event_count = len(events) if events is not None else 0
    print(f"Wrote {output_path} ({total} matches, {total_stores} stores, "
          f"{len(tabs) + (1 if store_sets else 0) + (1 if events is not None else 0)} tab(s), "
          f"{event_count} tracked event(s), "
          f"{dir_count} watchlist store(s))")


if __name__ == "__main__":
    main()
