#!/usr/bin/env python3
"""
NW3 News Digest Agent
----------------------
Fetches recent NW3-area news (Hampstead, Belsize Park, Swiss Cottage) from
Google News RSS, filters out anything already seen, and rebuilds index.html
as a static page suitable for GitHub Pages.

Styling follows the Brian Daily house style: white paper, Libre Caslon
Display masthead, DM Sans body, red accent, green section labels.

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

ITEMS_FILE = "items.json"    # full history: doubles as state + page data
HTML_FILE = "index.html"     # rebuilt fresh every run
MAX_ITEMS_PER_QUERY = 8
MAX_ITEMS_ON_PAGE = 60


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


# --- State ------------------------------------------------------------------

def load_items() -> list[dict]:
    if not os.path.exists(ITEMS_FILE):
        return []
    try:
        with open(ITEMS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [warn] could not read {ITEMS_FILE} ({e}); starting fresh")
        return []


def save_items(items: list[dict]) -> None:
    with open(ITEMS_FILE, "w") as f:
        json.dump(items, f, indent=2)


# --- Presentation helpers ---------------------------------------------------

# Map the raw search query onto a tidier section label.
AREA_LABELS = {
    "NW3 London": "NW3",
    "Hampstead London": "Hampstead",
    "Belsize Park London": "Belsize Park",
    "Swiss Cottage London": "Swiss Cottage",
    "Hampstead Heath": "The Heath",
}


def clean_title(title: str) -> tuple[str, str]:
    """Google News titles end in ' - Publisher'. Split that off."""
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        return head.strip(), tail.strip()
    return title.strip(), ""


def format_pub_date(raw: str) -> str:
    """Turn an RSS pubDate into e.g. 'Mon 27 July 2026'."""
    if not raw:
        return ""
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(raw, fmt).strftime("%a %d %B %Y")
        except ValueError:
            continue
    return raw


# --- HTML generation --------------------------------------------------------

CSS = """
:root {
  --paper: #fff;
  --ink: #11110f;
  --muted: #696966;
  --rule: #c9c9c4;
  --accent: #c72026;
  --green: #164b37;
  --serif: "Libre Caslon Display", Georgia, serif;
  --sans: "DM Sans", Arial, sans-serif;
  --gutter: clamp(20px, 5.6vw, 56px);
  --ease: cubic-bezier(.22, 1, .36, 1);
}
* { box-sizing: border-box; }
html {
  color-scheme: light;
  background: var(--paper);
  scroll-behavior: smooth;
}
body {
  margin: 0;
  color: var(--ink);
  background: var(--paper);
  font-family: var(--sans);
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; }
a, button { -webkit-tap-highlight-color: transparent; }

.shell {
  width: min(100%, 1060px);
  margin: 0 auto;
  padding: 0 var(--gutter);
}
.masthead {
  padding-top: clamp(26px, 6vw, 54px);
  text-align: center;
}
.brand {
  margin: 0;
  font-family: var(--serif);
  font-size: clamp(44px, 11.2vw, 100px);
  font-weight: 400;
  line-height: .86;
  letter-spacing: -.035em;
  white-space: nowrap;
}
.issue-line {
  margin: 18px 0 23px;
  color: #31312e;
  font-size: clamp(10px, 2.9vw, 14px);
  font-weight: 600;
  letter-spacing: .22em;
  text-transform: uppercase;
}
.issue-line .dot {
  padding: 0 .42em;
  color: var(--accent);
}
.strap {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  border-block: 1px solid var(--rule);
}
.strap div {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px 8px;
  color: var(--muted);
  font-size: clamp(10px, 2.6vw, 12px);
  font-weight: 600;
  letter-spacing: .16em;
  text-transform: uppercase;
}
.strap div + div { border-left: 1px solid var(--rule); }
.strap strong {
  color: var(--ink);
  font-weight: 700;
}

main { min-height: 60vh; }

.story {
  padding: 22px 0 24px;
  border-bottom: 1px solid var(--rule);
}
.story:first-of-type { padding-top: 28px; }
.story-index {
  display: inline-block;
  margin-right: 10px;
  color: var(--accent);
  font-family: var(--serif);
  font-size: clamp(30px, 8vw, 40px);
  line-height: .8;
  vertical-align: -.12em;
}
.section-label {
  color: var(--green);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.story h2 {
  margin: 10px 0 0;
  font-family: var(--serif);
  font-size: clamp(26px, 6.4vw, 40px);
  font-weight: 400;
  line-height: 1.02;
  letter-spacing: -.024em;
}
.story h2 a { text-decoration: none; }
.story h2 a:hover { text-decoration: underline; text-underline-offset: 4px; }
.story-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-top: 13px;
  color: #30302d;
  font-size: 13px;
  font-weight: 700;
}
.story-source {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.story-source::before {
  width: 7px;
  height: 7px;
  border: 2px solid var(--green);
  border-radius: 50%;
  content: "";
}
.story-date {
  color: var(--muted);
  font-weight: 600;
}
.source-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px 16px;
  margin-top: 14px;
  font-size: 12px;
  font-weight: 600;
}
.source-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  text-underline-offset: 3px;
}
.source-link::after {
  width: 7px;
  height: 7px;
  border-top: 1.5px solid currentColor;
  border-right: 1.5px solid currentColor;
  content: "";
  transform: rotate(45deg);
}
.source-link:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 34%, transparent);
  outline-offset: 3px;
}

.empty {
  padding: 40px 0;
  font-family: var(--serif);
  font-size: 22px;
}

.issue-footer {
  padding: 30px 0 12px;
  text-align: center;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .22em;
  text-transform: uppercase;
}
.site-footer {
  margin: 8px 0 44px;
  border-block: 1px solid var(--rule);
}
.site-footer p {
  margin: 0;
  padding: 18px 0;
  text-align: center;
  color: var(--muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .18em;
  text-transform: uppercase;
}

@media (min-width: 720px) {
  .strap { grid-template-columns: repeat(4, 1fr); }
  .story { padding: 26px 0 28px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: .01ms !important;
  }
}
"""

PAGE_SHELL = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#ffffff">
<meta name="description" content="NW3 News — a running digest of Hampstead, Belsize Park and Swiss Cottage news.">
<title>NW3 News &mdash; Hampstead briefing</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Libre+Caslon+Display&display=swap" rel="stylesheet">
<style>__CSS__</style>
</head>
<body>
<div class="shell">
  <header class="masthead">
    <p class="brand">NW3 NEWS</p>
    <p class="issue-line">Hampstead <span class="dot">&bull;</span> Belsize Park <span class="dot">&bull;</span> Swiss Cottage</p>
    <div class="strap">
      <div>Updated <strong>__UPDATED__</strong></div>
      <div>Stories <strong>__COUNT__</strong></div>
      <div>Sources <strong>Google News</strong></div>
      <div>Cadence <strong>Daily</strong></div>
    </div>
  </header>

  <main>
__ITEMS__
  </main>

  <p class="issue-footer">__FOOTER_DATE__</p>
  <footer class="site-footer">
    <p>Generated automatically by a GitHub Actions cron job</p>
  </footer>
</div>
</body>
</html>
"""

STORY_SHELL = """    <article class="story">
      <p class="section-label"><span class="story-index">__INDEX__</span>__AREA__</p>
      <h2><a href="__LINK__" target="_blank" rel="noopener noreferrer">__TITLE__</a></h2>
      <div class="story-meta">
        <span class="story-source">__SOURCE__</span>
        <span class="story-date">__DATE__</span>
      </div>
      <div class="source-list">
        <a class="source-link" href="__LINK__" target="_blank" rel="noopener noreferrer">Read the story</a>
      </div>
    </article>"""


def render_story(item: dict, index: int) -> str:
    title, publisher = clean_title(item["title"])
    source = item.get("source") or publisher or "Unknown source"
    area = AREA_LABELS.get(item.get("query", ""), item.get("query", ""))
    return (
        STORY_SHELL
        .replace("__INDEX__", f"{index:02d}")
        .replace("__AREA__", html.escape(area))
        .replace("__LINK__", html.escape(item["link"], quote=True))
        .replace("__TITLE__", html.escape(title))
        .replace("__SOURCE__", html.escape(source))
        .replace("__DATE__", html.escape(format_pub_date(item.get("pub_date", ""))))
    )


def render_html(items: list[dict]) -> str:
    items_sorted = sorted(items, key=lambda i: i.get("seen_at", ""), reverse=True)
    items_sorted = items_sorted[:MAX_ITEMS_ON_PAGE]

    if items_sorted:
        body = "\n".join(render_story(item, n) for n, item in enumerate(items_sorted, 1))
    else:
        body = '    <p class="empty">No stories collected yet.</p>'

    now = datetime.now(timezone.utc)
    return (
        PAGE_SHELL
        .replace("__CSS__", CSS)
        .replace("__ITEMS__", body)
        .replace("__UPDATED__", now.strftime("%d %b %Y, %H:%M UTC"))
        .replace("__COUNT__", str(len(items_sorted)))
        .replace("__FOOTER_DATE__", now.strftime("%A %d %B %Y"))
    )


def save_html(content: str) -> None:
    with open(HTML_FILE, "w") as f:
        f.write(content)


# --- Main run ---------------------------------------------------------------

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
    print(f"Rebuilt {HTML_FILE} ({len(existing)} item(s) in history).")


if __name__ == "__main__":
    run_once()
