"""Agric News: articles posted by administrators plus optional public RSS feeds."""
from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

log = logging.getLogger(__name__)

CATEGORIES = ["Top News", "Farming Basics", "Tech", "Business"]
_cache: dict = {}
_TAG = re.compile(r"<[^>]+>")


def _text(el, *names):
    for name in names:
        found = el.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _clean(value, limit=260):
    value = html.unescape(_TAG.sub(" ", value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[: limit - 1].rsplit(" ", 1)[0] + "…"


def fetch_feed(url, timeout=10, limit=12):
    """Parse an RSS 2.0 or Atom feed into simple dicts. Cached for one hour."""
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    items = []
    try:
        import requests

        r = requests.get(url, timeout=timeout, headers={"User-Agent": "EO-Analytics/1.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        atom = "{http://www.w3.org/2005/Atom}"
        media = "{http://search.yahoo.com/mrss/}"
        entries = root.findall(".//item") or root.findall(f".//{atom}entry")
        for e in entries[:limit]:
            link = _text(e, "link")
            if not link:
                link_el = e.find(f"{atom}link")
                link = link_el.get("href") if link_el is not None else ""
            image = ""
            for tag in (f"{media}content", f"{media}thumbnail", "enclosure"):
                m = e.find(tag)
                if m is not None and m.get("url") and (m.get("type", "image").startswith("image")):
                    image = m.get("url")
                    break
            published = _text(e, "pubDate", f"{atom}updated", f"{atom}published")
            try:
                when = parsedate_to_datetime(published).date().isoformat() if published else ""
            except (TypeError, ValueError):
                when = published[:10]
            items.append(
                {
                    "title": _clean(_text(e, "title", f"{atom}title"), 160),
                    "summary": _clean(_text(e, "description", f"{atom}summary", f"{atom}content")),
                    "link": link,
                    "image": image,
                    "date": when,
                    "source": _clean(_text(root.find("channel") if root.find("channel") is not None else root, "title", f"{atom}title"), 60),
                    "category": "Top News",
                    "external": True,
                }
            )
    except Exception as exc:
        log.info("News feed %s unavailable: %s", url, exc)
    _cache[url] = (time.time(), items)
    return items
