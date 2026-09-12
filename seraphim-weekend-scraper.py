#!/usr/bin/env python3
"""
Seraphim SL + AltSL + external gallery Weekend Sales Scraper
============================================================

Scans weekend-sale galleries and reports/saves every image whose store name
matches a store list you maintain yourself (stores.txt, one name per line,
matched case-insensitively, exact name only).  Facebook photo captions are the
exception: they are compared with prefix matching (see the facebook source).

Supported sources
-----------------
seraphimsl
    By default this scans the Seraphim homepage feed (FEATURED, BOOSTED and
    BLOG FEED modules) through the WordPress REST API, keeping only listings
    whose title/excerpt mentions a weekend sale (sale, friday, saturday,
    sunday, weekend, deals, kinky 69, waifu dreams, 7dayssale). Pass
    --category-page (or any other --listing-url) to scan the classic
    weekend-sales category page instead.  Event pages normally embed an
    Envira Gallery; when a post has no inline gallery it instead points to a
    third-party sale site (link text usually contains "Gallery").  The scraper
    detects those links and hands them to a dedicated adapter for that site.

altsl
    AltSL. The homepage can discover the current Alt Weekend Sale and Scene
    Weekend Sale pages automatically, or a specific weekly sale URL can be
    supplied directly.

External gallery adapters (selected automatically by hostname)
--------------------------------------------------------------
altsl.com                       Envira Gallery markup.
35lsunday.com                   WordPress figure/tiled galleries.
*.wordpress.com                 WordPress gallery-item blocks.
*.wixsite.com                   Wix galleries (wix-warmup-data JSON).
home.evoshopevent.com           EvoShop JSON API (/store/getweekendsalesimages.php).
facebook.com                    Facebook photo albums: Playwright + cookies to list
                                the photos, then HTTP photo pages for clean captions.
anything else                   Generic best-effort image collector.

Examples
--------
    pip install requests beautifulsoup4
    pip install playwright && python -m playwright install chromium   # facebook source only

    # Facebook albums need your session cookies (see fb_cookies.json):
    #   c_user:"<id>"
    #   xs:"<token>"

    python seraphim_weekend_scraper.py

    python seraphim_weekend_scraper.py --no-facebook   # skip facebook albums (faster)
    python seraphim_weekend_scraper.py --category-page # legacy category listing

    python seraphim_weekend_scraper.py --source altsl \
        --listing-url https://altsl.com/

    python seraphim_weekend_scraper.py --source wordpress \
        --listing-url https://35lsunday.com/

    python seraphim_weekend_scraper.py --source wix \
        --listing-url https://hypeeventssl.wixsite.com/hypeeventssl/miix-weekend-gallery

    python seraphim_weekend_scraper.py --output out.json \
        --stores-file mystores.txt
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import time
import unicodedata
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 "
    "WeekendSalesScraper/1.0"
)

REQUEST_TIMEOUT = 30
DEBUG = False
SKIP_FACEBOOK = False
STORE_LIST_FILE = Path(__file__).parent / "stores.txt"
FB_COOKIE_FILE = Path(__file__).parent / "fb_cookies.json"

# Hosts that are galleries/sales sites worth auto-following even when the link
# text does not contain the word "gallery".
KNOWN_EXTERNAL_HOSTS = {
    "altsl.com",
    "35lsunday.com",
    "home.evoshopevent.com",
    "wanderlustsl.com",
    "flickr.com",
    "www.flickr.com",
    "enegry-sl.com",
    "access-sl.com",
    "www.access-sl.com",
}
# Hosts that never contain a scrapeable gallery (login walls, maps, nav noise).
SKIP_EXTERNAL_HOSTS = {
    "instagram.com",
}

# A homepage feed listing is only opened (scraped) when its title or excerpt
# mentions one of these, i.e. it actually looks like a weekend sale.
SALE_FEED_KEYWORDS = (
    "sale", "sales", "friday", "fridays", "saturday", "saturdays",
    "sunday", "sundays", "weekend", "deals",
    "kinky 69", "waifu dreams", "7dayssale",
)


def debug_log(msg: str) -> None:
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Store list
# ---------------------------------------------------------------------------
def load_store_list(path: Path = STORE_LIST_FILE) -> List[str]:
    """Load store names from a plain text file, one per line, lowercased."""
    if not path.exists():
        return []

    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line.lower())
    return names


def load_event_names(path: Path) -> List[tuple]:
    """Load tracked event names as (display, lower) alias pairs."""
    if not path.exists():
        return []

    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append((line, line.lower()))
    return names


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def compute_default_since_date(reference: Optional[date] = None) -> date:
    """Most recent Friday, inclusive of today if today is Friday."""
    ref = reference or datetime.now().date()
    days_since_friday = (ref.weekday() - 4) % 7
    return ref - timedelta(days=days_since_friday)


def parse_post_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None

    text = text.strip()
    for fmt in (
        "%b %d, %Y",
        "%B %d, %Y",
        "%d/%m/%y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


WEEKEND_DAYS = {"friday", "saturday", "sunday"}


def sale_day_for_event(event: EventPage) -> str:
    """Day (friday/saturday/sunday) the sale belongs to.

    Prefers the event's posted date when it falls on a weekend day, otherwise
    falls back to the run date (the day the script was executed).
    """
    ev_date = parse_post_date(event.posted_date)
    if ev_date is not None:
        day = ev_date.strftime("%A").lower()
        if day in WEEKEND_DAYS:
            return day
    return datetime.now().date().strftime("%A").lower()


# ---------------------------------------------------------------------------
# Shared text helpers
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Double-unescape handles values such as A&amp;Y / A&amp;amp;Y."""
    text = html.unescape(html.unescape(text))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def cache_bust_url(url: str) -> str:
    """Add a per-request cache-busting query param.

    Seraphim's nginx page cache serves stale copies of pages and of the
    WordPress REST feed; a unique query string forces the origin to be hit.
    """
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={int(time.time())}"


_EVENT_OPENING_DATE_RE = re.compile(
    r"Event Opening Date:\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)

_EVENT_CLOSING_DATE_RE = re.compile(
    r"(?:Event Closing Date|End Date):\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


def extract_event_opening_date(text: str) -> str:
    """Pull 'Event Opening Date: August 8, 2026' out of an excerpt."""
    match = _EVENT_OPENING_DATE_RE.search(text)
    return match.group(1) if match else ""


def extract_event_closing_date(text: str) -> str:
    """Pull 'Event Closing Date:/End Date:' out of an excerpt as ISO date."""
    match = _EVENT_CLOSING_DATE_RE.search(text or "")
    if not match:
        return ""
    parsed = parse_post_date(match.group(1))
    return parsed.isoformat() if parsed else ""


def name_from_image_url(url: str) -> str:
    """Derive a store-ish name from an image filename (best effort)."""
    path = urlparse(url).path
    stem = Path(path).stem or ""
    name = re.sub(r"[-_]+", " ", stem)
    name = re.sub(r"\s+", " ", name).strip()
    for prefix in ("pic", "ad", "logo", "banner", "ss", "new"):
        if name.lower().startswith(prefix) and len(name) > len(prefix) + 1:
            name = name[len(prefix):].lstrip("- _").strip()
            break
    return name


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class EventPage:
    title: str
    url: str
    posted_date: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    excerpt: str = ""


@dataclass
class GalleryItem:
    store_name: str
    image_url: str
    thumb_url: str = ""
    caption_html: str = ""
    source_event_title: str = ""
    source_event_url: str = ""
    gallery_url: str = ""
    match_kind: str = "exact"
    slurl: str = ""
    match_text: str = ""
    media_id: str = ""
    sale_day: str = ""
    matched_at: str = ""


# ---------------------------------------------------------------------------
# Base source adapter
# ---------------------------------------------------------------------------
class SaleSource:
    name = "base"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def fetch(self, url: str) -> BeautifulSoup:
        # The site sits behind an nginx page cache that also caches the
        # WordPress REST API; a per-request query param forces a fresh copy.
        request_url = cache_bust_url(url)
        debug_log(f"[fetch] GET {request_url}")
        resp = self.session.get(request_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        debug_log(f"[fetch] OK {resp.status_code}: {resp.url} ({len(resp.text):,} bytes)")
        return BeautifulSoup(resp.text, "html.parser")

    def list_event_pages(
        self,
        listing_url: str,
        since_date: Optional[date] = None,
        max_pages: int = 20,
    ) -> List[EventPage]:
        del since_date, max_pages
        return [EventPage(title=self._title_from_url(listing_url), url=listing_url)]

    @staticmethod
    def _title_from_url(url: str) -> str:
        return urlparse(url).netloc or url

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        raise NotImplementedError

    def finalize_item_images(self, items: List[GalleryItem]) -> None:
        """Post-match hook: download/save local copies of item images.

        Called once per run with the unique matched items; the default does
        nothing (remote hotlinking).  Sources override it to persist images.
        """


# ---------------------------------------------------------------------------
# Seraphim source
# ---------------------------------------------------------------------------
class SeraphimSource(SaleSource):
    name = "seraphimsl"

    @staticmethod
    def _page_url(base_url: str, page_num: int) -> str:
        if page_num <= 1:
            return base_url
        return f"{base_url.rstrip('/')}/page/{page_num}/"

    def list_event_pages(
        self,
        listing_url: str,
        since_date: Optional[date] = None,
        max_pages: int = 20,
    ) -> List[EventPage]:
        if self._is_homepage(listing_url):
            return self._list_homepage_feed(
                listing_url, since_date=since_date, max_pages=max_pages
            )

        events: List[EventPage] = []
        seen_urls = set()

        for page_num in range(1, max_pages + 1):
            page_url = self._page_url(listing_url, page_num)
            debug_log(f"[listing] fetching page {page_num}: {page_url}")

            try:
                soup = self.fetch(page_url)
            except requests.RequestException as e:
                debug_log(f"[listing] FAILED page {page_num}: {e}")
                break

            content_divs = soup.select("div.post-content")
            if not content_divs:
                debug_log(f"[listing] no event blocks on page {page_num}; stopping")
                break

            stop_paginating = False
            new_on_this_page = 0

            for content_div in content_divs:
                title_link = content_div.select_one("h2.post-title a")
                if not title_link:
                    continue

                url = urljoin(page_url, title_link.get("href", ""))
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = title_link.get_text(strip=True)
                date_span = content_div.select_one(".post-meta .updated")
                posted_date_text = date_span.get_text(strip=True) if date_span else None
                ev_date = parse_post_date(posted_date_text)

                if since_date is not None and ev_date is not None and ev_date < since_date:
                    debug_log(
                        f"[listing] '{title}' ({posted_date_text}) is before cutoff "
                        f"{since_date}; stopping pagination"
                    )
                    stop_paginating = True
                    break

                tags = [a.get_text(strip=True) for a in content_div.select(".post-meta a[rel='tag']")]
                events.append(
                    EventPage(
                        title=title,
                        url=url,
                        posted_date=posted_date_text,
                        tags=tags,
                    )
                )
                new_on_this_page += 1
                debug_log(f"[listing] in range: '{title}' -> {url}")

            if stop_paginating or new_on_this_page == 0:
                break

        debug_log(f"[listing] scan complete: {len(events)} event page(s)")
        return events

    @staticmethod
    def _is_homepage(url: str) -> bool:
        return urlparse(url).path.strip("/") == ""

    @staticmethod
    def _matches_feed_keywords(title: str, excerpt: str = "") -> bool:
        haystack = f"{title} {excerpt}".lower()
        return any(k in haystack for k in SALE_FEED_KEYWORDS)

    @staticmethod
    def _feed_last_page(module: BeautifulSoup) -> Optional[int]:
        pages = []
        for anchor in module.select("ul.pagination a.pagination-page[data-page]"):
            try:
                pages.append(int(anchor.get("data-page")))
            except (TypeError, ValueError):
                continue
        return max(pages) if pages else None

    def _list_homepage_feed(
        self,
        listing_url: str,
        since_date: Optional[date] = None,
        max_pages: int = 20,
    ) -> List[EventPage]:
        """Scan the homepage FEATURED / BOOSTED / BLOG FEED modules.

        Category IDs and per-page counts come from each module's data
        attributes; the posts themselves are fetched from the WordPress REST
        API (the browser paginates the blog feed with AJAX on the same URL,
        which a scraper cannot replay). Each module stops at its declared last
        page, when a REST page comes back empty, or at the --since-date cutoff.
        """
        soup = self.fetch(listing_url)
        events: List[EventPage] = []
        seen_urls = set()

        for module in soup.select("div.posts-blog-feed-module"):
            title_el = module.select_one("h1.feed-title")
            feed_title = title_el.get_text(strip=True) if title_el else ""
            category_ids = (module.get("data-category_id") or "").strip()
            if not category_ids:
                continue
            try:
                per_page = int(module.get("data-posts_per_page") or "33")
            except (TypeError, ValueError):
                per_page = 33
            last_page = self._feed_last_page(module)
            debug_log(
                f"[listing] feed module {feed_title!r}: categories={category_ids} "
                f"per_page={per_page} last_page={last_page}"
            )
            events.extend(
                self._feed_module_events(
                    listing_url,
                    category_ids,
                    feed_title,
                    per_page=per_page,
                    last_page=last_page,
                    since_date=since_date,
                    max_pages=max_pages,
                    seen_urls=seen_urls,
                )
            )

        debug_log(f"[listing] homepage feed scan: {len(events)} event page(s)")
        return events

    def _feed_module_events(
        self,
        listing_url: str,
        category_ids: str,
        feed_title: str,
        per_page: int,
        last_page: Optional[int],
        since_date: Optional[date],
        max_pages: int,
        seen_urls: set,
    ) -> List[EventPage]:
        events: List[EventPage] = []
        per_page = max(1, min(per_page, 100))
        base = urljoin(listing_url, "/wp-json/wp/v2/posts")
        limit = last_page or max_pages
        declared_total = 0

        for page_num in range(1, limit + 1):
            rest_url = (
                f"{base}?categories={category_ids}&per_page={per_page}"
                f"&page={page_num}&orderby=date&order=desc"
            )
            rest_url = cache_bust_url(rest_url)
            try:
                resp = self.session.get(rest_url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                posts = resp.json()
            except (requests.RequestException, ValueError) as exc:
                debug_log(f"[listing] REST fetch failed ({rest_url}): {exc}")
                break
            if not isinstance(posts, list) or not posts:
                debug_log(
                    f"[listing] feed {feed_title!r} empty on page {page_num}; stopping"
                )
                break
            if not declared_total:
                try:
                    declared_total = int(resp.headers.get("X-WP-TotalPages") or 0)
                except (TypeError, ValueError):
                    declared_total = 0
                if last_page and declared_total:
                    declared_total = min(declared_total, last_page)

            stop = False
            for post in posts:
                event = self._event_from_rest_post(post)
                if event is None or event.url in seen_urls:
                    continue
                # The feed is ordered by publish date, so the cutoff must use
                # the post's publication date. The excerpt-derived opening
                # date can predate the window (e.g. an event that opened last
                # week but was announced this week) and would otherwise stop
                # pagination early and drop the rest of the batch.
                published = None
                post_day = (post.get("date") or "")[:10]
                try:
                    published = date.fromisoformat(post_day) if post_day else None
                except ValueError:
                    published = None
                if (
                    since_date is not None
                    and published is not None
                    and published < since_date
                ):
                    debug_log(
                        f"[listing] '{event.title}' published {published} is before "
                        f"cutoff {since_date}; stopping pagination"
                    )
                    stop = True
                    break
                seen_urls.add(event.url)
                if not self._matches_feed_keywords(event.title, event.excerpt):
                    debug_log(
                        f"[listing] filtered out (no sale keyword): '{event.title}'"
                    )
                    continue
                events.append(event)
                debug_log(f"[listing] in range: '{event.title}' -> {event.url}")

            if stop or (declared_total and page_num >= declared_total):
                break

        return events

    def list_recent_posts(
        self, since_date: Optional[date] = None, max_pages: int = 10
    ) -> List[EventPage]:
        """All recent posts from the WordPress REST feed (no category filter).

        The homepage feed modules only cover their own categories; event
        announcements often live outside them. This scan pages the global
        feed (newest first) until a post is older than ``since_date``.
        """
        base = "https://www.seraphimsl.com/wp-json/wp/v2/posts"
        events: List[EventPage] = []
        for page_num in range(1, max_pages + 1):
            rest_url = (
                f"{base}?per_page=100&orderby=date&order=desc&page={page_num}"
            )
            rest_url = cache_bust_url(rest_url)
            try:
                resp = self.session.get(rest_url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                posts = resp.json()
            except (requests.RequestException, ValueError) as exc:
                debug_log(f"[events] REST fetch failed ({rest_url}): {exc}")
                break
            if not isinstance(posts, list) or not posts:
                break
            stop = False
            for post in posts:
                event = self._event_from_rest_post(post)
                if event is None:
                    continue
                post_day = (post.get("date") or "")[:10]
                try:
                    posted = date.fromisoformat(post_day) if post_day else None
                except ValueError:
                    posted = None
                if since_date is not None and posted is not None and posted < since_date:
                    stop = True
                    break
                events.append(event)
            if stop:
                break
        debug_log(f"[events] recent-post scan: {len(events)} post(s)")
        return events

    @staticmethod
    def _event_from_rest_post(post: dict) -> Optional[EventPage]:
        try:
            title = clean_text(post["title"]["rendered"])
            link = (post.get("link") or "").strip()
        except (KeyError, TypeError):
            return None
        if not title or not link:
            return None
        excerpt_raw = post.get("excerpt") or {}
        excerpt_html = (
            excerpt_raw.get("rendered", "") if isinstance(excerpt_raw, dict) else ""
        )
        excerpt_text = clean_text(re.sub(r"<[^>]+>", " ", excerpt_html))
        posted_date = extract_event_opening_date(excerpt_text)
        if not posted_date:
            posted = (post.get("date") or "").strip()
            posted_date = posted[:10] if posted else ""
        return EventPage(
            title=title, url=link, posted_date=posted_date, excerpt=excerpt_text
        )

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        debug_log(f"[event] fetching: {event.url}")
        soup = self.fetch(event.url)

        gallery_links = soup.select("a.envira-gallery-link")
        debug_log(f"[event] {len(gallery_links)} Envira item(s)")

        if gallery_links:
            return self._parse_envira_items(gallery_links, event)

        # No inline gallery: the post usually links out to a third-party site
        # (link text containing "Gallery"). Parse that URL via its adapter.
        external_urls = self._find_external_gallery_links(soup, event.url)
        if external_urls:
            debug_log(f"[event] no inline gallery; {len(external_urls)} external link(s)")

        items: List[GalleryItem] = []
        for external_url in external_urls:
            items.extend(self._parse_external_gallery(external_url, event))
        return items

    def _parse_envira_items(self, gallery_links, event: EventPage) -> List[GalleryItem]:
        items: List[GalleryItem] = []
        for link in gallery_links:
            img = link.select_one("img")
            if not img:
                continue

            # Prefer the full-resolution image. The anchor carries
            # data-envira-retina / href with the original (non-thumbnail) URL,
            # while the <img> src is the small "name-300x225.jpg" crop.
            image_url = (
                link.get("data-envira-retina")
                or link.get("data-envira-full")
                or link.get("data-envira-src")
                or link.get("href")
                or img.get("data-envira-retina")
                or img.get("data-envira-src")
                or img.get("src")
                or ""
            )
            image_url = urljoin(event.url, image_url) if image_url else ""

            # Low-res grid crop (e.g. "name-300x225.jpg") rendered on the event
            # page; the site uses this for the card and only loads the full
            # image_url inside the lightbox. Seraphim only, by design.
            thumb_url = img.get("src") or link.get("data-thumb") or ""
            thumb_url = urljoin(event.url, thumb_url) if thumb_url else ""
            if thumb_url == image_url:
                thumb_url = ""

            caption_html = link.get("data-caption", "") or ""
            store_name = self._extract_store_name(link, caption_html)

            if not store_name or not image_url:
                continue

            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    thumb_url=thumb_url,
                    caption_html=caption_html,
                    source_event_title=event.title,
                    source_event_url=event.url,
                )
            )
        return items

    def _find_external_gallery_links(self, soup: BeautifulSoup, page_url: str) -> List[str]:
        content = soup.select_one(".entry-content")
        if content is None:
            content = soup

        links: List[str] = []
        seen = set()
        for anchor in content.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            absolute = urljoin(page_url, href)
            host = urlparse(absolute).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if not host or host == "seraphimsl.com":
                continue
            if host in SKIP_EXTERNAL_HOSTS or host.endswith("secondlife.com"):
                continue

            text = anchor.get_text(" ", strip=True).lower()
            if "gallery" not in text and not is_known_external_host(host):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
            debug_log(f"[event] external gallery link: {text!r} -> {absolute}")

        return links

    def _parse_external_gallery(self, gallery_url: str, event: EventPage) -> List[GalleryItem]:
        source_cls = resolve_source_class(gallery_url) or GenericGallerySource
        if source_cls is FacebookSource and SKIP_FACEBOOK:
            debug_log("[external] skipping facebook gallery (--no-facebook)")
            return []
        debug_log(f"[external] adapter={source_cls.name} url={gallery_url}")

        adapter = source_cls()
        external_event = EventPage(title=event.title, url=gallery_url)
        try:
            items = adapter.parse_event_page(external_event)
        except requests.RequestException as exc:
            debug_log(f"[external] FAILED {gallery_url}: {exc}")
            return []

        for item in items:
            item.source_event_title = event.title
            item.source_event_url = event.url
            item.gallery_url = gallery_url
        debug_log(f"[external] {source_cls.name}: {len(items)} item(s)")
        return items

    _CAPTION_NOISE_PREFIX = re.compile(
        r"^(teleport to|tp to|visit)\s+",
        re.IGNORECASE,
    )

    @classmethod
    def _extract_store_name(cls, link, caption_html: str = "") -> str:
        title_attr = (link.get("title") or "").strip()
        if title_attr:
            return clean_text(title_attr)

        parent_item = link.find_parent("div", class_="envira-gallery-item-inner")
        if parent_item is not None:
            title_span = parent_item.select_one(".envira-title")
            if title_span:
                text = title_span.get_text(strip=True)
                if text:
                    return clean_text(text)

        if caption_html:
            cap_soup = BeautifulSoup(caption_html, "html.parser")
            first_strong = cap_soup.find("strong")
            if first_strong:
                cap_link = first_strong.find("a")
                text = cap_link.get_text(strip=True) if cap_link else first_strong.get_text(strip=True)
                text = cls._CAPTION_NOISE_PREFIX.sub("", text).strip()
                if text:
                    return clean_text(text)

        return ""


# ---------------------------------------------------------------------------
# AltSL source
# ---------------------------------------------------------------------------
class AltSLSource(SaleSource):
    """
    AltSL adapter.

    The homepage contains links to the current Alt Weekend Sale and Scene
    Weekend Sale. A direct weekly URL can also be passed to --listing-url.

    Gallery markup is Envira Gallery, e.g.:

        <a class="envira-gallery-link"
           href="IMAGE_URL"
           title="Depression ⭐"
           data-caption="<a href=\"SLURL\">Visit Store</a>">
            <img data-envira-retina="IMAGE_URL" ...>
        </a>
    """

    name = "altsl"
    BASE_URL = "https://altsl.com/"
    SALE_PATH_PATTERNS = (
        "/scene-weekend-sale/",
        "/alt-weekend-sale/",
    )

    def list_event_pages(
        self,
        listing_url: str,
        since_date: Optional[date] = None,
        max_pages: int = 20,
    ) -> List[EventPage]:
        del since_date, max_pages  # AltSL URLs identify the current weekly pages.

        listing_url = listing_url.rstrip("/") + "/"
        parsed = urlparse(listing_url)
        path = parsed.path.lower()

        # A direct weekly sale URL.
        if any(pattern in path for pattern in self.SALE_PATH_PATTERNS):
            title = self._title_from_url(listing_url)
            return [EventPage(title=title, url=listing_url)]

        # Otherwise, discover the two current sale pages from the homepage.
        soup = self.fetch(listing_url)
        events: List[EventPage] = []
        seen_urls = set()

        for anchor in soup.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            if not href:
                continue

            absolute_url = urljoin(listing_url, href)
            parsed_link = urlparse(absolute_url)

            if parsed_link.netloc.lower() not in {"altsl.com", "www.altsl.com", ""}:
                continue

            normalized_path = parsed_link.path.lower()
            if not any(pattern in normalized_path for pattern in self.SALE_PATH_PATTERNS):
                continue

            clean_url = absolute_url.split("#", 1)[0].rstrip("/") + "/"
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)

            anchor_text = anchor.get_text(" ", strip=True)
            title = anchor_text or self._title_from_url(clean_url)

            if "/scene-weekend-sale/" in normalized_path:
                if title.lower() in {"view", "view sale", "current sale"}:
                    title = "Scene Weekend Sale"
            elif "/alt-weekend-sale/" in normalized_path:
                if title.lower() in {"view", "view sale", "current sale"}:
                    title = "Alt Weekend Sale"

            events.append(EventPage(title=title, url=clean_url))
            debug_log(f"[altsl listing] discovered: '{title}' -> {clean_url}")

        # Stable order: Alt first, Scene second.
        def sort_key(event: EventPage):
            p = urlparse(event.url).path.lower()
            if "/alt-weekend-sale/" in p:
                return 0
            if "/scene-weekend-sale/" in p:
                return 1
            return 2

        events.sort(key=sort_key)
        debug_log(f"[altsl listing] discovered {len(events)} sale page(s)")
        return events

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        debug_log(f"[altsl event] fetching: {event.url}")
        soup = self.fetch(event.url)
        items: List[GalleryItem] = []

        # Stable Envira selector. The numeric envira-gallery-* class changes.
        gallery_links = soup.select("a.envira-gallery-link")
        debug_log(f"[altsl event] {len(gallery_links)} Envira item(s) found")

        if not gallery_links:
            debug_log(
                "[altsl event] diagnostic: "
                f"{len(soup.select('a'))} links, "
                f"{len(soup.select('img'))} images, "
                f"title={soup.title.get_text(strip=True) if soup.title else 'n/a'}"
            )

        for index, link in enumerate(gallery_links):
            img = link.select_one("img")
            if not img:
                debug_log(f"[altsl event] item {index}: no image")
                continue

            # Prefer the original image URL. data-envira-retina on the anchor
            # is present in the supplied AltSL markup; some variants put the
            # same value on the img instead.
            image_url = (
                link.get("data-envira-retina")
                or img.get("data-envira-retina")
                or link.get("data-envira-src")
                or img.get("data-envira-src")
                or link.get("href")
                or img.get("src")
                or ""
            )
            image_url = urljoin(event.url, image_url) if image_url else ""

            caption_html = (
                link.get("data-caption")
                or img.get("data-caption")
                or ""
            )

            store_name = self._extract_store_name(link, caption_html)

            if not store_name or not image_url:
                debug_log(
                    f"[altsl event] item {index}: skipped; "
                    f"store={store_name!r}, image={image_url!r}"
                )
                continue

            debug_log(
                f"[altsl event] item {index}: "
                f"store={store_name!r} image={image_url}"
            )

            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    caption_html=caption_html,
                    source_event_title=event.title,
                    source_event_url=event.url,
                )
            )

        debug_log(f"[altsl event] parsed {len(items)} item(s)")
        return items

    @classmethod
    def _extract_store_name(cls, link, caption_html: str = "") -> str:
        # 1. Supplied AltSL markup has title="Depression ⭐".
        title_attr = (link.get("title") or "").strip()
        if title_attr:
            return clean_text(title_attr)

        # 2. data-title is also supplied by Envira Gallery.
        data_title = (link.get("data-title") or "").strip()
        if data_title:
            return clean_text(data_title)

        # 3. Rendered .envira-title span.
        parent_item = link.find_parent("div", class_="envira-gallery-item-inner")
        if parent_item is not None:
            title_span = parent_item.select_one(".envira-title")
            if title_span:
                text = title_span.get_text(" ", strip=True)
                if text:
                    return clean_text(text)

        # 4. Caption fallback.
        if caption_html:
            cap_soup = BeautifulSoup(caption_html, "html.parser")
            text = cap_soup.get_text(" ", strip=True)
            text = re.sub(
                r"^(visit\s+store|visit|teleport\s+to|tp\s+to)\s*:?\s*",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
            if text:
                return clean_text(text)

        return ""

    @staticmethod
    def _title_from_url(url: str) -> str:
        path = urlparse(url).path.lower()
        if "/scene-weekend-sale/" in path:
            return "Scene Weekend Sale"
        if "/alt-weekend-sale/" in path:
            return "Alt Weekend Sale"
        return "AltSL Weekend Sale"


# ---------------------------------------------------------------------------
# WordPress gallery source (35lsunday.com, *.wordpress.com, ...)
# ---------------------------------------------------------------------------
class WordPressGallerySource(SaleSource):
    """
    Parses WordPress galleries:

    * figure blocks / tiled galleries where store names live in the img's
      data-image-title / title / alt attributes (e.g. 35lsunday.com).
    * .gallery-item blocks (e.g. 30levents.wordpress.com), falling back to a
      name derived from the image filename.

    On blog index pages it parses the post that contains the most gallery
    items (the current round usually has the biggest gallery).
    """

    name = "wordpress"

    @staticmethod
    def _img_url(img: object) -> str:
        for attr in ("data-orig-file", "data-large-file", "data-src", "data-lazy-src", "src"):
            value = img.get(attr)
            if value:
                value = str(value).split("?", 1)[0].strip()
                if value:
                    return value
        return ""

    @classmethod
    def _name_from_img(cls, img: object) -> str:
        for attr in ("data-image-title", "title", "alt"):
            value = img.get(attr)
            if value:
                value = clean_text(str(value))
                if value:
                    return value
        return ""

    def _container_items(self, container: BeautifulSoup) -> List[GalleryItem]:
        items: List[GalleryItem] = []
        seen = set()

        for node in container.select(".gallery-item, figure"):
            img = node.select_one("img")
            if not img:
                continue

            image_url = self._img_url(img)
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)

            store_name = self._name_from_img(img)
            if not store_name:
                store_name = name_from_image_url(image_url)
            if not store_name:
                continue

            caption = ""
            figcaption = node.select_one("figcaption")
            if figcaption:
                caption = figcaption.get_text(" ", strip=True)

            link = node.select_one("a[href]")
            if link:
                href = link.get("href", "")
                if urlparse(href).netloc.endswith("secondlife.com"):
                    if not caption:
                        caption = f'<a href="{href}" target="_blank">Visit store</a>'
                    else:
                        caption = f'<a href="{href}" target="_blank">{caption}</a>'

            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    caption_html=caption,
                )
            )
        return items

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        soup = self.fetch(event.url)

        containers = soup.select("article")
        if not containers:
            containers = [soup]

        parsed: List[GalleryItem] = []
        for container in containers:
            candidate = self._container_items(container)
            if len(candidate) > len(parsed):
                parsed = candidate

        for item in parsed:
            item.source_event_title = event.title
            item.source_event_url = event.url
        debug_log(f"[wordpress] parsed {len(parsed)} item(s)")
        return parsed


# ---------------------------------------------------------------------------
# Wanderlust gallery source (wanderlustsl.com, Robo Gallery)
# ---------------------------------------------------------------------------
_PW_PLAYWRIGHT = None
_PW_BROWSER = None
_PW_CONTEXT = None


def _playwright_fetch_html(url: str) -> str:
    """Load a page in headless Chromium and return the rendered HTML.

    Some external gallery hosts (e.g. wanderlustsl.com) sit behind a
    Cloudflare managed challenge that plain requests cannot pass.  A real
    browser runs the challenge script and then exposes the full gallery
    markup; we wait for a known gallery selector to confirm it resolved.
    """
    from playwright.sync_api import sync_playwright

    global _PW_PLAYWRIGHT, _PW_BROWSER, _PW_CONTEXT
    if _PW_CONTEXT is None:
        if _PW_PLAYWRIGHT is None:
            _PW_PLAYWRIGHT = sync_playwright().start()
        if _PW_BROWSER is None:
            _PW_BROWSER = _PW_PLAYWRIGHT.chromium.launch(headless=True)
        _PW_CONTEXT = _PW_BROWSER.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )

    page = _PW_CONTEXT.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(
                ".rbs-img, .envira-gallery-link, .gallery-item",
                timeout=30000,
            )
        except Exception:
            debug_log("[playwright] gallery selector never appeared; using current DOM")
        return page.content()
    finally:
        try:
            page.close()
        except Exception:
            pass


class WanderlustGallerySource(SaleSource):
    """
    Wanderlust Weekend uses the Robo Gallery plugin, whose items are divs
    carrying the store/item caption in data-descbox:

        <div class="rbs-img ...">
          <div class="rbs-img-image rbs-lightbox" data-descbox="Store - Item">
            <div class="rbs-img-thumbs"
                 data-thumbnail="THUMB_URL" title="Store - Item"></div>
            <div class="rbs-img-data-popup" data-popup="FULL_URL"></div>
            <div class="thumbnail-overlay">
              <div class="rbsIcons"><a href="SLURL"><i ...></i></a></div>
            </div>
          </div>
          <div class="rbs-img-content">Store - Item</div>
        </div>

    The caption is "StoreName - ItemName"; the store name is the part before
    the first " - ".
    """

    name = "wanderlust"

    def fetch(self, url: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(_playwright_fetch_html(url), "html.parser")
        except Exception as exc:
            debug_log(f"[wanderlust] browser fetch failed, falling back to requests: {exc}")
            return super().fetch(url)

    @classmethod
    def _store_name_from_caption(cls, caption: str) -> str:
        for sep in (" - ", " – "):
            if sep in caption:
                return caption.split(sep, 1)[0].strip()
        return caption

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        soup = self.fetch(event.url)
        items: List[GalleryItem] = []
        seen = set()

        for node in soup.select("div.rbs-img"):
            image_div = node.select_one(".rbs-img-image")
            title = ""
            if image_div is not None:
                title = (
                    image_div.get("data-descbox")
                    or image_div.get("title")
                    or ""
                )
            if not title:
                content = node.select_one(".rbs-img-content")
                if content is not None:
                    title = content.get_text(" ", strip=True)
            title = clean_text(title)
            if not title:
                continue

            image_url = ""
            popup = node.select_one(".rbs-img-data-popup")
            if popup is not None:
                image_url = popup.get("data-popup") or ""
            thumb_url = ""
            thumb = node.select_one(".rbs-img-thumbs")
            if thumb is not None:
                thumb_url = thumb.get("data-thumbnail") or ""
                if not image_url:
                    image_url = thumb_url
            image_url = urljoin(event.url, str(image_url).split("?", 1)[0])
            thumb_url = urljoin(event.url, thumb_url) if thumb_url else ""
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)

            caption = ""
            link = node.select_one('.rbsIcons a[href*="secondlife.com"]')
            if link is not None:
                href = link.get("href") or ""
                caption = f'<a href="{href}" target="_blank">Visit store</a>'

            store_name = self._store_name_from_caption(title)
            if not store_name:
                continue

            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    thumb_url=thumb_url,
                    caption_html=caption,
                )
            )

        for item in items:
            item.source_event_title = event.title
            item.source_event_url = event.url
        debug_log(f"[wanderlust] parsed {len(items)} item(s)")
        return items


# ---------------------------------------------------------------------------
# Flickr album source (flickr.com/photos/<user>/albums/<set>)
# ---------------------------------------------------------------------------
class FlickrGallerySource(SaleSource):
    """Flickr photoset albums.

    The album page is a JS-heavy shell, so photo titles and images are read
    from the public photoset Atom feed every album page links to
    (services/feeds/photoset.gne).  Photo titles look like
    "<Store> - <EventName>"; the store name is the photo title with the album
    title stripped off, plus bracket punctuation ("[ kunst ]", "{geek}").
    """

    name = "flickr"

    @staticmethod
    def _strip_brackets(name: str) -> str:
        for open_char, close_char in (("[", "]"), ("{", "}"), ("(", ")")):
            if name.startswith(open_char) and name.endswith(close_char):
                return name[1:-1].strip()
        return name

    @classmethod
    def _store_name_from_title(cls, photo_title: str, album_title: str) -> str:
        title = clean_text(photo_title)
        if not title:
            return ""

        if album_title:
            words = re.findall(r"[0-9A-Za-z']+", album_title)
            if len(words) >= 2:
                joined = r"[^0-9A-Za-z]*".join(re.escape(w) for w in words)
                match = re.search(joined + r"[^0-9A-Za-z]*$", title, re.IGNORECASE)
                if match:
                    store = title[: match.start()].strip(" \t-–—|")
                    store = cls._strip_brackets(store)
                    if store:
                        return clean_text(store)

        match = re.search(r"\s*[-–—]\s*", title)
        store = title[: match.start()].strip() if match else title
        store = cls._strip_brackets(store)
        return clean_text(store)

    @classmethod
    def _album_title(cls, soup: BeautifulSoup) -> str:
        node = soup.select_one('meta[property="og:title"]')
        if node is None:
            node = soup.select_one("title")
        if node is None:
            return ""
        title = node.get("content") or node.get_text(" ", strip=True) or ""
        return clean_text(title.split("| Flickr", 1)[0])

    @classmethod
    def _feed_url(cls, soup: BeautifulSoup, page_url: str) -> str:
        node = soup.select_one('link[rel="alternate"][type="application/atom+xml"]')
        if node is None:
            return ""
        href = node.get("href")
        if not href:
            return ""
        return urljoin(page_url, href)

    def _items_from_feed(self, feed_url: str, album_title: str) -> List[GalleryItem]:
        items: List[GalleryItem] = []
        seen = set()
        try:
            resp = self.session.get(feed_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            debug_log(f"[flickr] feed fetch failed: {exc}")
            return items
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            feed = BeautifulSoup(resp.text, "html.parser")
        for entry in feed.find_all("entry"):
            title_node = entry.find("title")
            if title_node is None:
                continue
            store_name = self._store_name_from_title(
                title_node.get_text(), album_title
            )
            if not store_name:
                continue

            image_url = ""
            enclosure = entry.find("link", rel="enclosure")
            if enclosure is not None:
                image_url = (enclosure.get("href") or "").strip()
            if not image_url:
                content_node = entry.find("content")
                if content_node is not None:
                    img = BeautifulSoup(
                        content_node.get_text(), "html.parser"
                    ).find("img")
                    if img is not None:
                        image_url = img.get("src") or ""
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)
            if not image_url.startswith("http"):
                image_url = "https:" + image_url

            caption = ""
            content_node = entry.find("content")
            if content_node is not None:
                content_soup = BeautifulSoup(
                    content_node.get_text(), "html.parser"
                )
                slink = content_soup.select_one('a[href*="secondlife.com"]')
                if slink is not None:
                    href = (slink.get("href") or "").strip()
                    caption = f'<a href="{href}" target="_blank">Visit store</a>'

            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    caption_html=caption,
                )
            )
        return items

    def _items_from_ssr(self, soup: BeautifulSoup) -> List[GalleryItem]:
        items: List[GalleryItem] = []
        seen = set()
        album_title = self._album_title(soup)
        for anchor in soup.select("a.photo-link[title]"):
            store_name = self._store_name_from_title(
                anchor.get("title") or "", album_title
            )
            if not store_name:
                continue
            img = anchor.find_previous("img")
            image_url = img.get("src") if img is not None else ""
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)
            if not image_url.startswith("http"):
                image_url = "https:" + image_url
            items.append(GalleryItem(store_name=store_name, image_url=image_url))
        return items

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        soup = self.fetch(event.url)
        album_title = self._album_title(soup)
        feed_url = self._feed_url(soup, event.url)
        items = self._items_from_feed(feed_url, album_title) if feed_url else []
        if not items:
            debug_log("[flickr] feed empty; falling back to SSR photo cards")
            items = self._items_from_ssr(soup)
        for item in items:
            item.source_event_title = event.title
            item.source_event_url = event.url
        debug_log(f"[flickr] parsed {len(items)} item(s)")
        return items


# ---------------------------------------------------------------------------
# Tilda store-list source (e.g. enegry-sl.com/energylist)
# ---------------------------------------------------------------------------
class TildaGallerySource(SaleSource):
    """Tilda-built store lists.

    Each vendor is a .js-product card: the store name lives in the
    .js-product-name element, the full image on img[data-original], and the
    SLURL on a.js-product-link (secondlife:// scheme).
    """

    name = "tilda"

    @staticmethod
    def _slurl_to_web(href: str) -> str:
        if href.startswith("secondlife://"):
            return "https://maps.secondlife.com/secondlife/" + href[len("secondlife://"):]
        return href

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        soup = self.fetch(event.url)
        items: List[GalleryItem] = []
        seen = set()

        for card in soup.select(".js-product"):
            name_node = card.select_one(".js-product-name")
            if name_node is None:
                continue
            store_name = clean_text(name_node.get_text())
            if not store_name:
                continue

            img = card.select_one("img[src]")
            image_url = ""
            if img is not None:
                image_url = (
                    img.get("data-original")
                    or img.get("data-orig-file")
                    or img.get("data-large-file")
                    or img.get("src")
                    or ""
                )
            image_url = str(image_url).split("?", 1)[0].strip()
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)

            caption = ""
            link = card.select_one('a[href*="secondlife.com"], a[href^="secondlife://"]')
            if link is not None:
                href = (link.get("href") or "").strip()
                if href:
                    caption = (
                        f'<a href="{self._slurl_to_web(href)}" target="_blank">'
                        "Visit store</a>"
                    )

            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    caption_html=caption,
                )
            )

        for item in items:
            item.source_event_title = event.title
            item.source_event_url = event.url
        debug_log(f"[tilda] parsed {len(items)} item(s)")
        return items


# ---------------------------------------------------------------------------
# Wix gallery source (*.wixsite.com)
# ---------------------------------------------------------------------------
class WixGallerySource(SaleSource):
    """
    Wix galleries keep their item data (store name, image, SLURL) in the
    wix-warmup-data JSON blob embedded in the page. Fall back to SSR
    .gallery-item images when the blob is missing.
    """

    name = "wix"
    MEDIA_BASE = "https://static.wixstatic.com/media/"

    @classmethod
    def _iter_gallery_items(cls, node):
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key == "items"
                    and isinstance(value, list)
                    and value
                    and isinstance(value[0], dict)
                    and ("mediaUrl" in value[0] or "metaData" in value[0])
                ):
                    yield value
                else:
                    yield from cls._iter_gallery_items(value)
        elif isinstance(node, list):
            for entry in node:
                yield from cls._iter_gallery_items(entry)

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        soup = self.fetch(event.url)
        items: List[GalleryItem] = []

        script = soup.select_one('script#wix-warmup-data[type="application/json"]')
        if script is not None:
            try:
                data = json.loads(script.get_text())
            except json.JSONDecodeError as exc:
                debug_log(f"[wix] warmup JSON decode failed: {exc}")
                data = {}

            for gallery_items in self._iter_gallery_items(data):
                for entry in gallery_items:
                    meta = entry.get("metaData") or {}
                    store_name = clean_text(meta.get("title") or "")
                    media = (entry.get("mediaUrl") or "").strip()
                    if not store_name or not media:
                        continue

                    image_url = self.MEDIA_BASE + media
                    slurl = ((meta.get("link") or {}).get("data") or {}).get("url", "")
                    caption = (
                        f'<a href="{slurl}" target="_blank">Visit store</a>'
                        if slurl else ""
                    )
                    items.append(
                        GalleryItem(
                            store_name=store_name,
                            image_url=image_url,
                            caption_html=caption,
                        )
                    )

        if not items:
            items = self._ssr_gallery_items(soup)

        for item in items:
            item.source_event_title = event.title
            item.source_event_url = event.url
        debug_log(f"[wix] parsed {len(items)} item(s)")
        return items

    def _ssr_gallery_items(self, soup: BeautifulSoup) -> List[GalleryItem]:
        items: List[GalleryItem] = []
        seen = set()
        for node in soup.select(".gallery-item"):
            img = node.select_one("img")
            if not img:
                continue
            src = (img.get("src") or "").strip()
            if not src or src in seen:
                continue
            seen.add(src)
            store_name = clean_text(img.get("alt") or "")
            if not store_name:
                store_name = name_from_image_url(src)
            if store_name:
                items.append(
                    GalleryItem(store_name=store_name, image_url=src)
                )
        return items


# ---------------------------------------------------------------------------
# EvoShop source (home.evoshopevent.com)
# ---------------------------------------------------------------------------
class EvoShopSource(SaleSource):
    """
    EvoShop renders its weekend vendor album via a JSON API instead of static
    HTML. The page declares the endpoint in a script tag:
    WEEKEND_IMAGES_URL = '/store/getweekendsalesimages.php'.
    """

    name = "evoshop"
    API_PATH = "/store/getweekendsalesimages.php"
    IMAGE_BASE = "https://home.evoshopevent.com/"

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        self.fetch(event.url)  # sanity check the site is reachable

        api_url = urljoin(event.url, self.API_PATH)
        debug_log(f"[evoshop] API: {api_url}")
        resp = self.session.get(api_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        try:
            data = resp.json()
        except ValueError as exc:
            debug_log(f"[evoshop] non-JSON API response: {exc}")
            return []

        entries: List[dict] = []
        if isinstance(data, dict):
            for group in data.values():
                if isinstance(group, dict):
                    entries.extend(group.values())
                elif isinstance(group, list):
                    entries.extend(group)
        elif isinstance(data, list):
            for group in data:
                if isinstance(group, dict):
                    entries.append(group)
                elif isinstance(group, list):
                    entries.extend(group)

        items: List[GalleryItem] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            store_name = clean_text(entry.get("storename") or "")
            if not store_name:
                continue

            seller_id = entry.get("sellerid")
            item_id = entry.get("itemid")

            image_name = ""
            for field in ("image1", "image2", "image3"):
                value = entry.get(field) or ""
                if value and ".." not in value:
                    image_name = value
                    break
            if not image_name:
                continue

            if seller_id and item_id:
                image_url = (
                    f"{self.IMAGE_BASE}admin/creatorfilesweekend/"
                    f"{seller_id}/{item_id}/{image_name}"
                )
            else:
                image_url = urljoin(event.url, image_name)

            caption = ""
            if entry.get("storelocation"):
                caption = (
                    f'<a href="{entry["storelocation"]}" target="_blank">'
                    "Visit store</a>"
                )
            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    caption_html=caption,
                )
            )

        for item in items:
            item.source_event_title = event.title
            item.source_event_url = event.url
        debug_log(f"[evoshop] parsed {len(items)} item(s)")
        return items


# ---------------------------------------------------------------------------
# Generic fallback source
# ---------------------------------------------------------------------------
class GenericGallerySource(SaleSource):
    """
    Best-effort fallback for any site without a dedicated adapter: collect the
    content images and derive store names from alt/title/data-image-title
    attributes, falling back to the image filename.
    """

    name = "generic"

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        soup = self.fetch(event.url)
        items: List[GalleryItem] = []
        seen = set()

        for img in soup.select("img[src]"):
            image_url = (
                img.get("data-orig-file")
                or img.get("data-large-file")
                or img.get("src")
                or ""
            )
            image_url = str(image_url).split("?", 1)[0].strip()
            if not image_url or image_url in seen:
                continue
            seen.add(image_url)

            store_name = clean_text(
                img.get("data-image-title") or img.get("title") or img.get("alt") or ""
            )
            if not store_name:
                store_name = name_from_image_url(image_url)
            if not store_name:
                continue

            caption = ""
            link = img.find_parent("a", href=True)
            if link and urlparse(link.get("href", "")).netloc.endswith("secondlife.com"):
                caption = f'<a href="{link.get("href")}" target="_blank">Visit store</a>'

            items.append(
                GalleryItem(
                    store_name=store_name,
                    image_url=image_url,
                    caption_html=caption,
                )
            )

        for item in items:
            item.source_event_title = event.title
            item.source_event_url = event.url
        debug_log(f"[generic] parsed {len(items)} item(s)")
        return items


# ---------------------------------------------------------------------------
# Facebook source (Playwright + session cookies)
# ---------------------------------------------------------------------------
_FB_PLAYWRIGHT = None
_FB_BROWSER = None
_FB_CONTEXT = None


def _load_fb_cookies(path: Path) -> List[dict]:
    """Load cookies from a JSON file into Playwright cookie dicts.

    Accepted formats:
      * a list of cookie objects (Playwright/browser-export format);
      * a plain {"c_user": ..., "xs": ..., ...} name/value map;
      * a text file with one `name:"value"` (or name=value) per line.
    """
    if not path.exists():
        return []
    text = ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        debug_log(f"[facebook] could not read {path}: {exc}")
        return []

    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if data is None:
        pairs = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r'^([^:=\s]+)\s*[:=]\s*"?([^"\r\n]*)"?\s*$', line)
            if m:
                pairs.append((m.group(1), m.group(2)))
        data = dict(pairs)
        if not data:
            debug_log(f"[facebook] no cookies parsed from {path}")
            return []

    if isinstance(data, dict):
        return [
            {
                "name": name,
                "value": str(value),
                "domain": ".facebook.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
            }
            for name, value in data.items()
        ]
    if isinstance(data, list):
        cookies = []
        for c in data:
            if not isinstance(c, dict) or "name" not in c or "value" not in c:
                continue
            try:
                expires = int(float(c.get("expires", -1)))
            except (TypeError, ValueError):
                expires = -1
            cookies.append(
                {
                    "name": c["name"],
                    "value": str(c["value"]),
                    "domain": c.get("domain", ".facebook.com"),
                    "path": c.get("path", "/"),
                    "secure": c.get("secure", True),
                    "httpOnly": c.get("httpOnly", False),
                    "sameSite": c.get("sameSite") or "Lax",
                    "expires": expires,
                }
            )
        return cookies
    return []


def _fb_get_browser_context(cookie_file: Path):
    global _FB_PLAYWRIGHT, _FB_BROWSER, _FB_CONTEXT
    from playwright.sync_api import sync_playwright

    if _FB_CONTEXT is None:
        if _FB_PLAYWRIGHT is None:
            _FB_PLAYWRIGHT = sync_playwright().start()
        if _FB_BROWSER is None:
            _FB_BROWSER = _FB_PLAYWRIGHT.chromium.launch(headless=True)
        _FB_CONTEXT = _FB_BROWSER.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        cookies = _load_fb_cookies(cookie_file)
        if cookies:
            try:
                _FB_CONTEXT.add_cookies(cookies)
                debug_log(f"[facebook] loaded {len(cookies)} cookie(s) from {cookie_file}")
            except Exception as exc:
                debug_log(f"[facebook] failed to add cookies: {exc}")
        else:
            debug_log(f"[facebook] no cookies in {cookie_file}; logged-out view only")
    return _FB_CONTEXT


def _fb_dismiss_dialogs(page) -> None:
    for sel in [
        'div[role="dialog"] button:has-text("Allow all cookies")',
        'div[role="dialog"] button:has-text("Allow all")',
        'button:has-text("Allow all cookies")',
        'div[role="dialog"] button:has-text("Only essential cookies")',
        'div[role="dialog"] button[aria-label="Close"]',
    ]:
        try:
            if page.locator(sel).first.is_visible(timeout=1200):
                page.locator(sel).first.click()
                page.wait_for_timeout(800)
        except Exception:
            pass


def _fb_scroll_to_load(page, selector: str) -> None:
    last = -1
    idle = 0
    for _ in range(150):
        page.mouse.wheel(0, 6000)
        page.wait_for_timeout(400)
        n = page.locator(selector).count()
        if n == last:
            idle += 1
        else:
            idle = 0
            last = n
        if idle >= 8 or (n == 0 and idle >= 3):
            break


_FB_FBID_RE = re.compile(r"fbid=(\d+)")
_FB_PHOTO_META_RE = re.compile(r'<meta name="description" content="([^"]*)"')
_FB_OG_IMAGE_RE = re.compile(r'<meta property="og:image" content="([^"]*)"')
_FB_SLURL_RE = re.compile(r"https?://maps\.secondlife\.com/[^\"'\s<]+")
_FB_LREDIR_RE = re.compile(r"l\.facebook\.com/l\.php\?u=([^\"'\s<]+)")
_FB_HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}
_FB_COOKIE_DICT: dict = {}
_FB_COOKIE_LOADED = False
_FB_SET_ID = ""

# Where downloaded Facebook photos (large + small) are saved so the generated
# site can serve them from the GitHub Pages docs/ root.
FB_IMAGES_DIR = Path(__file__).parent / "docs" / "img" / "fb"
FB_THUMB_WIDTH = 640


def _fb_ensure_cookies(cookie_file: Path) -> None:
    global _FB_COOKIE_DICT, _FB_COOKIE_LOADED
    if not _FB_COOKIE_LOADED:
        _FB_COOKIE_DICT = {c["name"]: c["value"] for c in _load_fb_cookies(cookie_file)}
        _FB_COOKIE_LOADED = True
        debug_log(f"[facebook] loaded {len(_FB_COOKIE_DICT)} cookie(s) for http photo fetch")


def _fb_clean_caption(raw: str) -> str:
    """Clean a photo caption read from <meta name="description">.

    The caption is emitted as HTML numeric character references for the fancy
    unicode letters (&#x1d413;...).  Unescape them, NFKC-fold them back to
    ASCII (mathematical-bold -> plain), and drop any embedded http(s) URLs.
    Line breaks are preserved so the first line can be used as the store name.
    """
    if not raw:
        return ""
    text = html.unescape(html.unescape(raw))
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"https?://[^\s]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _fb_extract_slurl(raw: str) -> str:
    """Pull a maps.secondlife.com teleport URL out of a raw photo caption."""
    if not raw:
        return ""
    m = _FB_SLURL_RE.search(raw)
    if m:
        return html.unescape(m.group(0).rstrip(".,;)]}'\""))
    m = _FB_LREDIR_RE.search(raw)
    if m:
        try:
            decoded = parse_qs(html.unescape(m.group(1))).get("u", [""])[0]
        except Exception:
            decoded = ""
        if "maps.secondlife.com" in decoded:
            return decoded
    return ""


def _fb_fetch_caption(fbid: str) -> tuple:
    """Fetch one photo page over HTTP; return (clean caption, slurl).

    The caption comes from <meta name="description">, the teleport URL is
    read out of the same raw text before it is cleaned.
    """
    url = f"https://www.facebook.com/photo/?fbid={fbid}&set={_FB_SET_ID}"
    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(
                url,
                headers=_FB_HTTP_HEADERS,
                cookies=_FB_COOKIE_DICT or None,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            resp = None
        if resp is not None and resp.status_code == 200:
            break
        time.sleep(0.4 * (attempt + 1))
    if resp is None or resp.status_code != 200:
        return "", ""
    m = _FB_PHOTO_META_RE.search(resp.text)
    if not m:
        return "", ""
    return _fb_clean_caption(m.group(1)), _fb_extract_slurl(m.group(1))


def _fb_extract_photos(page, selector: str, event: EventPage) -> List[GalleryItem]:
    """List album photos with Playwright, then fetch clean captions over HTTP.

    The album grid only exposes the OCR alt text, so each photo page is read
    separately: its <meta name="description"> holds the real caption (e.g.
    "Two Moon Gardens", possibly in mathematical-bold unicode).  Caption
    fetches run in a small thread pool.  The first caption line becomes the
    store name; the teleport URL is kept aside for the site's Visit-store pill.
    """
    fbids: List[str] = []
    seen: set = set()
    links = page.locator(selector)
    count = links.count()
    for i in range(count):
        try:
            href = links.nth(i).get_attribute("href") or ""
        except Exception:
            continue
        m = _FB_FBID_RE.search(href)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            fbids.append(m.group(1))

    if not fbids:
        return []

    results: List[tuple] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_fb_fetch_caption, fbids))

    if results and not any(caption for caption, _ in results):
        debug_log(f"[facebook] no photo captions fetched from {event.url} — session cookies may be stale")

    items: List[GalleryItem] = []
    for fbid, (caption, slurl) in zip(fbids, results):
        if not caption:
            continue
        lines = [ln.strip() for ln in caption.split("\n") if ln.strip()]
        store = lines[0] if lines else caption
        items.append(
            GalleryItem(
                store_name=store,
                image_url=f"https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id={fbid}",
                thumb_url="",
                caption_html=caption,
                match_kind="caption",
                slurl=slurl,
                match_text=caption,
                media_id=fbid,
            )
        )

    for item in items:
        item.source_event_title = event.title
        item.source_event_url = event.url
    return items


def _fb_fetch_og_image(fbid: str) -> str:
    """Return the full-size og:image URL for a photo page (or empty)."""
    url = f"https://www.facebook.com/photo/?fbid={fbid}&set={_FB_SET_ID}"
    try:
        resp = requests.get(
            url,
            headers=_FB_HTTP_HEADERS,
            cookies=_FB_COOKIE_DICT or None,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        return ""
    if resp is None or resp.status_code != 200:
        return ""
    m = _FB_OG_IMAGE_RE.search(resp.text)
    return html.unescape(m.group(1)) if m else ""


def _fb_is_valid_image(path: Path) -> bool:
    """Return True when path exists and decodes as a real Pillow image."""
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def _fb_download_image(url: str) -> bytes:
    """Fetch a photo URL with the session headers/cookies; return raw bytes."""
    if not url:
        return b""
    try:
        resp = requests.get(
            url,
            headers=_FB_HTTP_HEADERS,
            cookies=_FB_COOKIE_DICT or None,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException:
        return b""
    if resp is None or resp.status_code != 200:
        return b""
    return resp.content


def _fb_save_item_images(item: GalleryItem) -> None:
    """Download one matched Facebook photo and write large + small local files.

    The large image comes from the photo page's og:image meta (session-cookie
    fetch); if that is unavailable the public lookaside crawler URL is tried.
    The small version is a Pillow thumbnail.  Only when both local files are
    real, decodable images does the item's image_url/thumb_url switch to the
    relative paths the site can serve from docs/; otherwise the remote
    lookaside URL stays untouched so the page never points at broken files.
    """
    if not item.media_id:
        return
    fbid = item.media_id
    try:
        FB_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    large = FB_IMAGES_DIR / f"{fbid}.jpg"
    small = FB_IMAGES_DIR / f"{fbid}-s.jpg"

    if not _fb_is_valid_image(large):
        if large.exists():
            try:
                large.unlink()
            except OSError:
                pass
        data = _fb_download_image(_fb_fetch_og_image(fbid)) or _fb_download_image(item.image_url)
        if not data:
            debug_log(f"[facebook] could not download image for photo {fbid}")
            return
        try:
            large.write_bytes(data)
        except OSError:
            return
        if not _fb_is_valid_image(large):
            try:
                large.unlink()
            except OSError:
                pass
            debug_log(f"[facebook] downloaded data is not a real image for photo {fbid}")
            return

    if not _fb_is_valid_image(small):
        try:
            with Image.open(large) as im:
                im = im.convert("RGB")
                if im.width > FB_THUMB_WIDTH:
                    im.thumbnail((FB_THUMB_WIDTH, FB_THUMB_WIDTH))
                im.save(small, "JPEG", quality=88)
        except Exception as exc:
            debug_log(f"[facebook] thumbnail failed for photo {fbid}: {exc}")
        if not _fb_is_valid_image(small):
            debug_log(f"[facebook] no usable thumbnail for photo {fbid}")
            return

    item.image_url = f"img/fb/{fbid}.jpg"
    item.thumb_url = f"img/fb/{fbid}-s.jpg"
    debug_log(f"[facebook] saved local images for photo {fbid}")


class FacebookSource(SaleSource):
    """Scrape Facebook photo albums.

    The album page is a JS shell, so a headless Chromium browser (Playwright)
    with your session cookies (--fb-cookies file, default fb_cookies.json) is
    used to load it and scroll through all photos.  Each photo's clean caption
    (the store name in readable text, not the OCR alt text) is then read over
    plain HTTP from that photo page's <meta name="description">.  Captions are
    NFKC-normalized and matched with prefix matching.
    """

    name = "facebook"

    def __init__(self, cookie_file: Optional[Path] = None) -> None:
        super().__init__()
        self.cookie_file = Path(cookie_file) if cookie_file is not None else FB_COOKIE_FILE

    def parse_event_page(self, event: EventPage) -> List[GalleryItem]:
        global _FB_SET_ID
        items: List[GalleryItem] = []
        try:
            from playwright.sync_api import TimeoutError as PWTimeout
        except ImportError:
            debug_log(
                "[facebook] playwright not installed: "
                "pip install playwright && python -m playwright install chromium"
            )
            return items

        try:
            context = _fb_get_browser_context(self.cookie_file)
            page = context.new_page()
        except Exception as exc:
            debug_log(f"[facebook] browser startup failed: {exc}")
            return items

        try:
            page.goto(event.url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            _fb_dismiss_dialogs(page)
            selector = 'a[href*="photo.php?fbid="], a[href*="/photo/?fbid="]'
            _fb_scroll_to_load(page, selector)
            _fb_ensure_cookies(self.cookie_file)
            set_id = (parse_qs(urlparse(event.url).query).get("set") or [""])[0]
            if set_id:
                _FB_SET_ID = set_id
            items = _fb_extract_photos(page, selector, event)
        except PWTimeout:
            debug_log(f"[facebook] timed out loading {event.url}")
        except Exception as exc:
            debug_log(f"[facebook] failed to parse {event.url}: {exc}")
        finally:
            try:
                page.close()
            except Exception:
                pass

        debug_log(f"[facebook] parsed {len(items)} item(s) from {event.url}")
        return items

    def finalize_item_images(self, items: List[GalleryItem]) -> None:
        """Download matched Facebook photos (large + small) to docs/img/fb/."""
        todo: List[GalleryItem] = [
            it for it in items if it.match_kind == "caption" and it.media_id
        ]
        if not todo:
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            ex.map(_fb_save_item_images, todo)


class AccessSLSource(FacebookSource):
    """ACCESS SL Weekend Sales, discovered via its Facebook photo album.

    The album URL rotates every week, so the listing page (access-sl.com/hwsale)
    is scanned for the "Facebook Album" button and its current media-set link is
    scraped with the regular FacebookSource machinery.
    """

    name = "accesssl"
    ACCESS_PAGE = "https://www.access-sl.com/hwsale"
    ALBUM_LINK_RE = re.compile(r'href="(https?://(?:www\.)?(?:facebook\.com|fb\.com)/media/set/[^"]*)"')

    def list_event_pages(
        self,
        listing_url: str,
        since_date: Optional[date] = None,
        max_pages: int = 20,
    ) -> List[EventPage]:
        del since_date, max_pages
        page_url = listing_url or self.ACCESS_PAGE
        soup = self.fetch(page_url)
        album_url = ""
        link = soup.select_one('a[aria-label="Facebook Album"]')
        if link:
            album_url = link.get("href") or ""
        if not album_url:
            m = self.ALBUM_LINK_RE.search(str(soup))
            if m:
                album_url = html.unescape(m.group(1))
        if not album_url:
            debug_log(f"[accesssl] no Facebook album link found on {page_url}")
            return []
        album_url = urljoin(page_url, album_url)
        debug_log(f"[accesssl] found album: {album_url}")
        return [
            EventPage(
                title="ACCESS SL Weekend Sales",
                url=album_url,
                excerpt="Facebook photo album linked from ACCESS SL",
            )
        ]


# ---------------------------------------------------------------------------
# Source registry + dispatch
# ---------------------------------------------------------------------------
SOURCES = {
    "seraphimsl": SeraphimSource,
    "altsl": AltSLSource,
    "wordpress": WordPressGallerySource,
    "wanderlust": WanderlustGallerySource,
    "flickr": FlickrGallerySource,
    "tilda": TildaGallerySource,
    "wix": WixGallerySource,
    "evoshop": EvoShopSource,
    "facebook": FacebookSource,
    "accesssl": AccessSLSource,
    "generic": GenericGallerySource,
}


def resolve_source_class(url: str) -> Optional[type]:
    """Return the adapter class best suited for an external gallery URL."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "altsl.com":
        return AltSLSource
    if host == "35lsunday.com":
        return WordPressGallerySource
    if host == "wanderlustsl.com":
        return WanderlustGallerySource
    if host == "flickr.com":
        return FlickrGallerySource
    if host == "enegry-sl.com":
        return TildaGallerySource
    if host == "home.evoshopevent.com":
        return EvoShopSource
    if host == "access-sl.com":
        return AccessSLSource
    if host == "facebook.com":
        return FacebookSource
    if host == "wixsite.com" or host.endswith(".wixsite.com"):
        return WixGallerySource
    if host == "wordpress.com" or host.endswith(".wordpress.com"):
        return WordPressGallerySource
    return None


def is_known_external_host(host: str) -> bool:
    """True if a host has a dedicated adapter (used to auto-follow links)."""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in KNOWN_EXTERNAL_HOSTS:
        return True
    if host == "wixsite.com" or host.endswith(".wixsite.com"):
        return True
    if host == "wordpress.com" or host.endswith(".wordpress.com"):
        return True
    return False


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def matches_store_list(store_name: str, store_list_lower: List[str]) -> bool:
    return store_name.lower() in store_list_lower


def _fb_norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip().lower()


def matches_caption_list(caption: str, store_list_lower: List[str]) -> bool:
    """Match a Facebook photo caption against the store list.

    Captions are the real caption text (e.g. "Two Moon Gardens"), NFKC-folded
    so fancy unicode letters (mathematical bold) compare cleanly.  A store
    matches when the caption starts with the store name: "two moon garden"
    matches "Two Moon Gardens" but "moon" does not.  Wildcard entries like
    *B.D.R.* match when their core appears anywhere in the caption.
    """
    cap = _fb_norm(caption)
    if not cap:
        return False
    for target in store_list_lower:
        t = _fb_norm(target)
        if not t:
            continue
        if "*" in t:
            core = t.replace("*", "")
            if core and core in cap:
                return True
        elif cap.startswith(t):
            return True
    return False


def find_matches(items: List[GalleryItem], store_list_lower: List[str]) -> List[GalleryItem]:
    matches: List[GalleryItem] = []
    for it in items:
        if it.match_kind == "caption":
            if matches_caption_list(it.match_text or it.store_name, store_list_lower):
                matches.append(it)
        elif matches_store_list(it.store_name, store_list_lower):
            matches.append(it)
    return matches


def find_event_matches(posts: List[EventPage], event_names: List[tuple]) -> List[dict]:
    """Match tracked event names against recent post titles/excerpts.

    A name matches on word boundaries, so 'Appare' also matches 'Appare!'
    but not 'Apparel'. Returns one dict per matching post; the first alias
    in file order wins. The closing date comes from the excerpt when present.
    """
    matches: List[dict] = []
    for ev in posts:
        hay = f"{ev.title} {ev.excerpt}".lower()
        for display, lower in event_names:
            if re.search(rf"(?<!\w){re.escape(lower)}(?!\w)", hay):
                posted = parse_post_date(ev.posted_date)
                matches.append(
                    {
                        "event_name": display,
                        "title": ev.title,
                        "url": ev.url,
                        "posted_date": posted.isoformat() if posted else ev.posted_date,
                        "closing_date": extract_event_closing_date(ev.excerpt),
                    }
                )
                break
    return matches


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    global FB_COOKIE_FILE, SKIP_FACEBOOK
    parser = argparse.ArgumentParser(
        description="Scrape weekend sale galleries for matching stores."
    )
    parser.add_argument(
        "--listing-url",
        default="https://www.seraphimsl.com/",
        help="Listing/homepage/direct sale URL to scan (default: Seraphim "
        "homepage feed: featured, boosted and blog feed).",
    )
    parser.add_argument(
        "--category-page",
        action="store_true",
        help="Scan the legacy weekend-sales category page "
        "(https://www.seraphimsl.com/category/recurring-events/weekend-sales/) "
        "instead of the homepage feed.",
    )
    parser.add_argument(
        "--no-facebook",
        action="store_true",
        help="Skip opening facebook.com gallery links (faster testing; links "
        "are still detected).",
    )
    parser.add_argument(
        "--source",
        default="seraphimsl",
        choices=SOURCES.keys(),
        help="Website adapter to use.",
    )
    parser.add_argument(
        "--stores-file",
        action="append",
        help="Path to a stores list. Repeat for multiple lists; each gets its own "
        "--output (same order).",
    )
    parser.add_argument(
        "--fb-cookies",
        default=str(FB_COOKIE_FILE),
        help="Path to Facebook session cookies for --source facebook.",
    )
    parser.add_argument(
        "--output",
        action="append",
        help="Where to write JSON results. Repeat alongside --stores-file (same "
        "order); defaults to matches.json.",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Limit number of event/sale pages (useful for testing).",
    )
    parser.add_argument(
        "--since-date",
        default=None,
        help="Only include Seraphim events posted on/after YYYY-MM-DD. Defaults to most recent Friday.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug output to stderr.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum listing pages for paginated sources.",
    )
    parser.add_argument(
        "--events-file",
        default=None,
        help="Path to a tracked-events name list (one per line). Enables the "
        "event-tracking pass.",
    )
    parser.add_argument(
        "--events-output",
        default=None,
        help="Where to write the tracked-event snapshot (required with "
        "--events-file).",
    )
    parser.add_argument(
        "--events-since-days",
        type=int,
        default=21,
        help="How many days back the event pass scans for announcements.",
    )
    args = parser.parse_args()

    if args.category_page:
        args.listing_url = (
            "https://www.seraphimsl.com/category/recurring-events/weekend-sales/"
        )

    if args.since_date:
        try:
            since_date = datetime.strptime(args.since_date, "%Y-%m-%d").date()
        except ValueError:
            print(
                f"Invalid --since-date '{args.since_date}', expected YYYY-MM-DD",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        since_date = compute_default_since_date()

    FB_COOKIE_FILE = Path(args.fb_cookies)
    SKIP_FACEBOOK = args.no_facebook

    if args.debug:
        global DEBUG
        DEBUG = True

    store_files = [Path(p) for p in (args.stores_file or [str(STORE_LIST_FILE)])]
    out_paths = [Path(p) for p in (args.output or ["matches.json"])]
    if len(store_files) != len(out_paths):
        print(
            "ERROR: number of --stores-file and --output values must match. "
            f"Got {len(store_files)} store list(s) and {len(out_paths)} output(s).",
            file=sys.stderr,
        )
        sys.exit(1)

    store_lists = []
    for sf in store_files:
        slist = load_store_list(sf)
        store_lists.append(slist)
        if not slist:
            print(
                f"WARNING: no stores loaded from {sf}. Nothing will match for it.",
                file=sys.stderr,
            )

    source = SOURCES[args.source]()

    print(f"Source: {args.source}")
    print(f"Fetching listing page: {args.listing_url}")
    print(f"Since date: {since_date}")

    try:
        events = source.list_event_pages(
            args.listing_url,
            since_date=since_date,
            max_pages=args.max_pages,
        )
    except requests.RequestException as e:
        print(f"ERROR fetching listing page: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(events)} event/sale page(s).")

    if args.max_events is not None:
        events = events[: args.max_events]

    all_matches: List[List[GalleryItem]] = [[] for _ in store_lists]

    matched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for event in events:
        print(f"  Parsing: {event.title} ({event.url})")

        try:
            items = source.parse_event_page(event)
        except requests.RequestException as e:
            print(f"    ERROR fetching event page: {e}", file=sys.stderr)
            continue

        sale_day = sale_day_for_event(event)
        for item in items:
            item.sale_day = sale_day
            item.matched_at = matched_at

        debug_log(
            f"[match] '{event.title}': {len(items)} gallery item(s) parsed total"
        )

        event_matches = False
        for idx, slist in enumerate(store_lists):
            matches = find_matches(items, slist)
            all_matches[idx].extend(matches)
            event_matches = event_matches or bool(matches)
            matched_names = {m.store_name for m in matches}
            for item in items:
                status = "MATCH" if item.store_name in matched_names else "no match"
                debug_log(
                    f"[match][{store_files[idx].stem}] {status}: store={item.store_name!r}"
                )
            if matches:
                print(
                    f"    [{store_files[idx].stem}] {len(matches)} match(es): "
                    + ", ".join(m.store_name for m in matches)
                )

        if not event_matches:
            print("    -> 0 matches")

    matched_items: List[GalleryItem] = []
    seen_ids: set = set()
    for matches in all_matches:
        for m in matches:
            if id(m) not in seen_ids:
                seen_ids.add(id(m))
                matched_items.append(m)
    if matched_items:
        source.finalize_item_images(matched_items)

    for idx, out_path in enumerate(out_paths):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                [m.__dict__ for m in all_matches[idx]],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Wrote {len(all_matches[idx])} match(es) to {out_path}")

    if args.events_file:
        if not args.events_output:
            print(
                "ERROR: --events-output is required with --events-file.",
                file=sys.stderr,
            )
            sys.exit(1)
        events_path = Path(args.events_file)
        event_names = load_event_names(events_path)
        if not event_names:
            print(f"WARNING: no event names loaded from {events_path}.")
        events_since = datetime.now().date() - timedelta(days=args.events_since_days)
        print(f"Events: scanning recent posts since {events_since}")
        try:
            recent_posts = source.list_recent_posts(
                since_date=events_since, max_pages=args.max_pages
            )
        except requests.RequestException as e:
            print(f"ERROR fetching recent posts: {e}", file=sys.stderr)
            sys.exit(1)
        tracked = find_event_matches(recent_posts, event_names)
        for entry in tracked:
            entry["first_seen"] = matched_at
        out_events = Path(args.events_output)
        out_events.parent.mkdir(parents=True, exist_ok=True)
        out_events.write_text(
            json.dumps(tracked, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote {len(tracked)} tracked event(s) to {out_events}")


if __name__ == "__main__":
    main()
