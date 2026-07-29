#!/usr/bin/env python3
"""
NW3 News Digest Agent
----------------------
Collects recent NW3-area news (Hampstead, Belsize Park, Swiss Cottage) and
rebuilds index.html in the Brian Daily house style, ready for GitHub Pages.

Two kinds of source are used:

  * Google News RSS search feeds  - broad NW3 coverage, headline only.
  * Publisher RSS feeds           - fewer hits, but carry real summary prose,
                                    which fills the "Executive brief" block.

Designed to be run once per invocation (e.g. by a GitHub Actions cron
schedule) rather than looping forever with a sleep() call.
"""

import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# --- Config ---------------------------------------------------------------

# Google News search feeds: wide coverage, no summary text.
QUERIES = [
    "NW3 London",
    "Hampstead London",
    "Belsize Park London",
    "Swiss Cottage London",
    "Hampstead Heath",
]

# Publisher feeds: real summary prose. Items are kept only if they mention
# one of KEYWORDS. Add more feeds here - anything that fails is skipped with
# a warning, so a bad URL cannot break the run.
PUBLISHER_FEEDS = [
    ("ianVisits", "https://www.ianvisits.co.uk/articles/feed/"),
    # ("HamHigh", "https://www.hamhigh.co.uk/rss/"),
    # ("MyLondon", "https://www.mylondon.news/?service=rss"),
]

KEYWORDS = [
    "nw3", "hampstead", "belsize", "swiss cottage",
    "the heath", "kenwood", "primrose hill",
]

ITEMS_FILE = "items.json"    # full history: doubles as state + page data
HTML_FILE = "index.html"     # rebuilt fresh every run
MAX_ITEMS_PER_FEED = 10
MAX_ITEMS_ON_PAGE = 45

AREA_LABELS = {
    "NW3 London": "NW3",
    "Hampstead London": "Hampstead",
    "Belsize Park London": "Belsize Park",
    "Swiss Cottage London": "Swiss Cottage",
    "Hampstead Heath": "The Heath",
}


# --- Fetching ---------------------------------------------------------------

def get_feed(url: str) -> ET.Element | None:
    """Fetch and parse an RSS feed, returning None on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [warn] fetch failed for {url}: {e}")
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        print(f"  [warn] parse failed for {url}: {e}")
        return None


def strip_html(raw: str) -> str:
    """Reduce an RSS description to plain text."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def fetch_google_news(query: str) -> list[dict]:
    """Google News search feed. Headline, publisher and date only."""
    encoded = urllib.parse.quote(query)
    url = (f"https://news.google.com/rss/search?q={encoded}"
           "&hl=en-GB&gl=GB&ceid=GB:en")
    root = get_feed(url)
    if root is None:
        return []

    items = []
    for node in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        if not (title and link):
            continue
        items.append({
            "title": title,
            "link": link,
            "pub_date": (node.findtext("pubDate") or "").strip(),
            "source": (node.findtext("source") or "").strip(),
            "brief": "",                       # no prose in this feed
            "area": AREA_LABELS.get(query, query),
            "seen_at": datetime.now(timezone.utc).isoformat(),
        })
    return items


def fetch_publisher(name: str, url: str) -> list[dict]:
    """Publisher feed. Carries real summary prose; filtered by KEYWORDS."""
    root = get_feed(url)
    if root is None:
        return []

    items = []
    for node in root.findall(".//item")[:40]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        if not (title and link):
            continue

        brief = strip_html(node.findtext("description") or "")
        haystack = f"{title} {brief}".lower()
        matched = next((k for k in KEYWORDS if k in haystack), None)
        if not matched:
            continue

        items.append({
            "title": title,
            "link": link,
            "pub_date": (node.findtext("pubDate") or "").strip(),
            "source": name,
            "brief": brief[:400],
            "area": matched.title() if matched != "nw3" else "NW3",
            "seen_at": datetime.now(timezone.utc).isoformat(),
        })
        if len(items) >= MAX_ITEMS_PER_FEED:
            break
    return items


# --- State ------------------------------------------------------------------

def load_items() -> list[dict]:
    if not os.path.exists(ITEMS_FILE):
        return []
    try:
        with open(ITEMS_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [warn] could not read {ITEMS_FILE} ({e}); starting fresh")
        return []


def save_items(items: list[dict]) -> None:
    with open(ITEMS_FILE, "w") as f:
        json.dump(items, f, indent=2)


# --- Presentation helpers ---------------------------------------------------

def clean_title(title: str) -> tuple[str, str]:
    """Google News titles end in ' - Publisher'. Split that off."""
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        return head.strip(), tail.strip()
    return title.strip(), ""


def parse_pub(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def pretty_date(raw: str) -> str:
    dt = parse_pub(raw)
    return dt.strftime("%a %d %B %Y") if dt else ""


def seen_date(item: dict) -> str:
    """The UTC date on which this item was first collected."""
    try:
        return datetime.fromisoformat(item["seen_at"]).date().isoformat()
    except (KeyError, ValueError):
        return ""


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
html { color-scheme: light; scroll-behavior: smooth; background: var(--paper); }
body {
  margin: 0;
  color: var(--ink);
  background: var(--paper);
  font-family: var(--sans);
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; }
button, a { -webkit-tap-highlight-color: transparent; }

.shell { width: min(100%, 1060px); margin: 0 auto; padding: 0 var(--gutter); }

.masthead { padding-top: clamp(26px, 6vw, 54px); text-align: center; }
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
.issue-line .dot { padding: 0 .42em; color: var(--accent); }

.date-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-block: 1px solid var(--rule);
  background: color-mix(in srgb, var(--paper) 94%, transparent);
  backdrop-filter: blur(12px);
}
.date-tab {
  position: relative;
  min-height: 58px;
  border: 0;
  padding: 8px 6px;
  color: var(--muted);
  background: transparent;
  font: 500 clamp(12px, 3.2vw, 16px)/1.1 var(--sans);
  cursor: pointer;
}
.date-tab::after {
  position: absolute;
  right: 17%;
  bottom: -1px;
  left: 17%;
  height: 4px;
  background: var(--accent);
  content: "";
  opacity: 0;
  transform: scaleX(.45);
  transition: opacity 180ms ease, transform 280ms var(--ease);
}
.date-tab[aria-selected="true"] { color: var(--ink); font-weight: 700; }
.date-tab[aria-selected="true"]::after { opacity: 1; transform: scaleX(1); }
.date-tab:focus-visible, .source-link:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 34%, transparent);
  outline-offset: -3px;
}

main { min-height: 60vh; }

.morning { margin-top: 28px; border-block: 2px solid var(--ink); }
.morning-title {
  margin: 0;
  padding: 11px 0 9px;
  border-bottom: 1px solid var(--rule);
  color: var(--green);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.morning-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.morning-fact {
  min-width: 0;
  padding: 13px 10px 12px 0;
  border-bottom: 1px solid var(--rule);
  font-family: var(--serif);
  font-size: clamp(19px, 5.3vw, 24px);
  line-height: 1.1;
}
.morning-fact:nth-child(even) { padding-left: 14px; border-left: 1px solid var(--rule); }
.morning-fact small {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-family: var(--sans);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
}

.briefing { animation: reveal 460ms var(--ease) both; }
.briefing[hidden] { display: none; }
@keyframes reveal {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

.story { padding: 24px 0 27px; border-bottom: 1px solid var(--rule); }
.story:first-of-type { padding-top: 30px; }
.story-index {
  display: inline-block;
  margin-right: 10px;
  color: var(--accent);
  font-family: var(--serif);
  font-size: clamp(35px, 10vw, 48px);
  line-height: .8;
  vertical-align: -.12em;
}
.section-label {
  margin: 0;
  color: var(--green);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.story h2 {
  margin: 10px 0 0;
  font-family: var(--serif);
  font-size: clamp(30px, 8.4vw, 48px);
  font-weight: 400;
  line-height: .99;
  letter-spacing: -.028em;
}
.story h2 a { text-decoration: none; }
.story h2 a:hover { text-decoration: underline; text-underline-offset: 4px; }
.story-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-top: 14px;
  color: #30302d;
  font-size: 13px;
  font-weight: 700;
}
.story-location { display: inline-flex; align-items: center; gap: 7px; }
.story-location::before {
  width: 7px;
  height: 7px;
  border: 2px solid var(--green);
  border-radius: 50%;
  content: "";
}
.action-label {
  padding: 4px 8px 3px;
  border: 1px solid var(--accent);
  color: var(--accent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.story-date { color: var(--muted); font-weight: 600; }
.story-body {
  margin-top: 14px;
  font-size: clamp(18px, 5vw, 20px);
  line-height: 1.5;
}
.story-body p { margin: 0 0 9px; }
.story-body strong { font-weight: 700; }

.source-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px 16px;
  margin-top: 15px;
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

.empty { padding: 44px 0; font-family: var(--serif); font-size: 22px; }

.issue-footer {
  padding: 30px 0 12px;
  text-align: center;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .22em;
  text-transform: uppercase;
}
.site-footer { margin: 8px 0 44px; border-block: 1px solid var(--rule); }
.site-footer p {
  margin: 0;
  padding: 20px 0;
  text-align: center;
  color: var(--muted);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .2em;
  text-transform: uppercase;
}

@media (min-width: 720px) {
  .morning {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: stretch;
  }
  .morning-title {
    display: flex;
    align-items: center;
    min-width: 145px;
    border-right: 1px solid var(--rule);
    border-bottom: 0;
    padding-right: 24px;
  }
  .morning-facts { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .morning-fact {
    display: block;
    padding: 12px 14px;
    border-right: 1px solid var(--rule);
    border-bottom: 0;
    font-size: 17px;
  }
  .morning-fact:nth-child(even) { border-left: 0; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: .01ms !important;
    transition-duration: .01ms !important;
  }
}
"""

JS = """
const tabs = Array.from(document.querySelectorAll(".date-tab"));
function select(day) {
  tabs.forEach(tab => {
    const on = tab.dataset.day === day;
    tab.setAttribute("aria-selected", on ? "true" : "false");
    const panel = document.getElementById(tab.dataset.day);
    if (panel) panel.hidden = !on;
  });
}
tabs.forEach(tab => tab.addEventListener("click", () => select(tab.dataset.day)));
"""

PAGE_SHELL = """<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#ffffff">
<meta name="description" content="NW3 News - a daily Hampstead, Belsize Park and Swiss Cottage briefing.">
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
    <p class="issue-line">London <span class="dot">&bull;</span> __ISSUE_DATE__</p>
    <nav class="date-nav" aria-label="Choose briefing date" role="tablist">
__TABS__
    </nav>
  </header>

  <main>
    <section class="morning" aria-label="Digest summary">
      <p class="morning-title">This edition</p>
      <div class="morning-facts">
__FACTS__
      </div>
    </section>

__PANELS__
  </main>

  <p class="issue-footer">__FOOTER_DATE__</p>
  <footer class="site-footer">
    <p>Generated automatically by a GitHub Actions cron job</p>
  </footer>
</div>
<script>__JS__</script>
</body>
</html>
"""

TAB = ('      <button class="date-tab" id="tab-__ID__" role="tab" '
       'aria-controls="__ID__" aria-selected="__SELECTED__" '
       'data-day="__ID__">__LABEL__</button>')

PANEL = """    <section class="briefing" id="__ID__" role="tabpanel" aria-labelledby="tab-__ID__"__HIDDEN__>
__STORIES__
    </section>"""

STORY = """      <article class="story">
        <p class="section-label"><span class="story-index">__INDEX__</span>__AREA__</p>
        <h2><a href="__LINK__" target="_blank" rel="noopener noreferrer">__TITLE__</a></h2>
        <div class="story-meta">
          <span class="story-location">__AREA__</span>
          <span class="action-label">__SOURCE__</span>
          <span class="story-date">__DATE__</span>
        </div>
__BODY__
        <div class="source-list">
          <a class="source-link" href="__LINK__" target="_blank" rel="noopener noreferrer">Read the story</a>
        </div>
      </article>"""

BODY = ('        <div class="story-body">\n'
        '          <p><strong>Executive brief:</strong> __BRIEF__</p>\n'
        '        </div>')

FACT = '        <div class="morning-fact">__VALUE__<small>__LABEL__</small></div>'


def render_story(item: dict, index: int) -> str:
    title, publisher = clean_title(item["title"])
    source = item.get("source") or publisher or "Unknown"
    brief = (item.get("brief") or "").strip()
    body = BODY.replace("__BRIEF__", html.escape(brief)) if brief else ""

    return (
        STORY
        .replace("__INDEX__", f"{index:02d}")
        .replace("__LINK__", html.escape(item["link"], quote=True))
        .replace("__TITLE__", html.escape(title))
        .replace("__AREA__", html.escape(item.get("area", "NW3")))
        .replace("__SOURCE__", html.escape(source))
        .replace("__DATE__", html.escape(pretty_date(item.get("pub_date", ""))))
        .replace("__BODY__", body)
    )


def render_html(items: list[dict]) -> str:
    items_sorted = sorted(items, key=lambda i: i.get("seen_at", ""), reverse=True)
    items_sorted = items_sorted[:MAX_ITEMS_ON_PAGE]

    now = datetime.now(timezone.utc)
    today = now.date()
    days = [
        ("today", f"Today {today.strftime('%-d %B')}", today.isoformat()),
        ("yesterday", "Yesterday", (today - timedelta(days=1)).isoformat()),
        ("day-before", "Earlier", None),
    ]
    recent = {d[2] for d in days[:2]}

    buckets: dict[str, list[dict]] = {d[0]: [] for d in days}
    for item in items_sorted:
        stamp = seen_date(item)
        if stamp == days[0][2]:
            buckets["today"].append(item)
        elif stamp == days[1][2]:
            buckets["yesterday"].append(item)
        else:
            buckets["day-before"].append(item)

    # Open on the first tab that actually has stories.
    active = next((d[0] for d in days if buckets[d[0]]), "today")

    tabs, panels = [], []
    for day_id, label, _ in days:
        tabs.append(
            TAB.replace("__ID__", day_id)
               .replace("__LABEL__", label)
               .replace("__SELECTED__", "true" if day_id == active else "false")
        )
        group = buckets[day_id]
        if group:
            stories = "\n".join(
                render_story(item, n) for n, item in enumerate(group, 1)
            )
        else:
            stories = '      <p class="empty">Nothing collected for this day.</p>'
        panels.append(
            PANEL.replace("__ID__", day_id)
                 .replace("__STORIES__", stories)
                 .replace("__HIDDEN__", "" if day_id == active else " hidden")
        )

    with_brief = sum(1 for i in items_sorted if (i.get("brief") or "").strip())
    facts = [
        (str(len(buckets["today"])), "New today"),
        (str(len(items)), "Tracked overall"),
        (str(with_brief), "With summaries"),
        (now.strftime("%H:%M"), "Updated (UTC)"),
    ]
    facts_html = "\n".join(
        FACT.replace("__VALUE__", html.escape(v)).replace("__LABEL__", html.escape(l))
        for v, l in facts
    )

    return (
        PAGE_SHELL
        .replace("__CSS__", CSS)
        .replace("__JS__", JS)
        .replace("__TABS__", "\n".join(tabs))
        .replace("__PANELS__", "\n\n".join(panels))
        .replace("__FACTS__", facts_html)
        .replace("__ISSUE_DATE__", now.strftime("%A %-d %B %Y"))
        .replace("__FOOTER_DATE__", now.strftime("%A %-d %B %Y"))
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
        print(f"Checking Google News: {query}")
        for item in fetch_google_news(query):
            if item["link"] not in seen_links:
                new_items.append(item)
                seen_links.add(item["link"])

    for name, url in PUBLISHER_FEEDS:
        print(f"Checking publisher: {name}")
        for item in fetch_publisher(name, url):
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
