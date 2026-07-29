#!/usr/bin/env python3
"""
NW3 News Digest Agent
----------------------
Loops over a set of NW3-area search queries (Hampstead, Belsize Park,
Swiss Cottage, etc.), pulls recent news via Google News RSS, filters out
anything already seen, and rebuilds index.html so it can be served as a
GitHub Pages homepage.

Designed to be run once per invocation (e.g. by a GitHub Actions cron
schedule) rather than looping forever with a sleep() call.
"""

import html
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# --- Config ---------------------------------------------------------------

QUERIES = [
    "NW3 London",
    "Hampstead London",
    "Belsize Park London",
    "Swiss Cottage London",
    "Hampstead Heath",
]

ITEMS_FILE = "items.json"       # full history, used as both state + page data
HTML_FILE = "index.html"        # rebuilt fresh every run
MAX_ITEMS_PER_QUERY = 8
MAX_ITEMS_ON_PAGE = 150          # keep the page from growing forever


# --- Fetching ---------------------------------------------------------------

def fetch_news(query: str) -> list[dict]:
    """Fetch a Google News RSS feed for a query and parse entries."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-GB&gl=GB&ceid=GB:en"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [warn] fetch failed for '{query}': {e}")
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"  [warn] parse failed for '{query}': {e}")
        return []

    items = []
    for item in root.findall(".//item")[:MAX_ITEMS_PER_QUERY]:
        title = item.findtext("title", default="").strip()
        link = item.findtext("link", default="").strip()
        pub_date = item.findtext("pubDate", default="").strip()
        source = item.findtext("source", default="").strip()
        if title and link:
            items.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "source": source,
                "query": query,
                "seen_at": datetime.now(timezone.utc).isoformat(),
            })
    return items


# --- State (also doubles as the page's data source) -------------------------

def load_items() -> list[dict]:
    if not os.path.exists(ITEMS_FILE):
        return []
    with open(ITEMS_FILE, "r") as f:
        return json.load(f)


def save_items(items: list[dict]) -> None:
    with open(ITEMS_FILE, "w") as f:
        json.dump(items, f, indent=2)


# --- HTML page generation ----------------------------------------------------

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NW3 News Digest</title>
<style>
  :root {{
    color-scheme: light dark;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 720px;
    margin: 0 auto;
    padding: 24px 16px 64px;
    background: #0f1115;
    color: #e7e9ec;
    line-height: 1.5;
  }}
  header {{
    margin-bottom: 24px;
  }}
  h1 {{
    font-size: 1.6rem;
    margin: 0 0 4px;
  }}
  .subtitle {{
    color: #9aa1ab;
    font-size: 0.9rem;
  }}
  .item {{
    padding: 14px 0;
    border-bottom: 1px solid #232630;
  }}
  .item:last-child {{
    border-bottom: none;
  }}
  .item a {{
    color: #7cb3ff;
    text-decoration: none;
    font-weight: 600;
    font-size: 1.02rem;
  }}
  .item a:hover {{
    text-decoration: underline;
  }}
  .meta {{
    color: #9aa1ab;
    font-size: 0.82rem;
    margin-top: 4px;
  }}
  .tag {{
    display: inline-block;
    background: #1c2431;
    color: #8fb8ff;
    border-radius: 4px;
    padding: 1px 6px;
    margin-left: 6px;
    font-size: 0.75rem;
  }}
  footer {{
    margin-top: 32px;
    color: #6b7280;
    font-size: 0.8rem;
    text-align: center;
  }}
</style>
</head>
<body>
<header>
  <h1>NW3 News Digest</h1>
  <div class="subtitle">Hampstead · Belsize Park · Swiss Cottage — last updated {updated}</div>
</header>
<main>
{items_html}
</main>
<footer>Generated automatically by a GitHub Actions cron job.</footer>
</body>
</html>
"""

ITEM_TEMPLATE = """<div class="item">
  <a href="{link}" target="_blank" rel="noopener">{title}</a>
  <div class="meta">{source}{pub_date}<span class="tag">{query}</span></div>
</div>"""


def render_html(items: list[dict]) -> str:
    # newest first
    items_sorted = sorted(items, key=lambda i: i.get("seen_at", ""), reverse=True)
    items_sorted = items_sorted[:MAX_ITEMS_ON_PAGE]

    blocks = []
    for item in items_sorted:
        pub = f" · {html.escape(item['pub_date'])}" if item.get("pub_date") else ""
        blocks.append(ITEM_TEMPLATE.format(
            link=html.escape(item["link"]),
            title=html.escape(item["title"]),
            source=html.escape(item.get("source", "")),
            pub_date=pub,
            query=html.escape(item.get("query", "")),
        ))

    items_html = "\n".join(blocks) if blocks else "<p>No items yet.</p>"
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return PAGE_TEMPLATE.format(updated=updated, items_html=items_html)


def save_html(content: str) -> None:
    with open(HTML_FILE, "w") as f:
        f.write(content)


# --- Main run ----------------------------------------------------------------

def run_once() -> None:
    existing = load_items()
    seen_links = {item["link"] for item in existing}

    new_items = []
    for query in QUERIES:
        print(f"Checking: {query}")
        for item in fetch_news(query):
            if item["link"] not in seen_links:
                new_items.append(item)
                seen_links.add(item["link"])

    if new_items:
        print(f"Found {len(new_items)} new item(s).")
        existing.extend(new_items)
    else:
        print("No new items this run.")

    save_items(existing)
    save_html(render_html(existing))


if __name__ == "__main__":
    run_once()
