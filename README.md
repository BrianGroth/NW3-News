# NW3-News
An automated news digest for the NW3 area of London (Hampstead, Belsize Park, Swiss Cottage). A GitHub Actions workflow runs on a daily schedule (cron), executing a Python script that fetches recent local news via Google News RSS feeds, filters out stories already seen, and regenerates index.html with the full running list — newest first.

The workflow (defined in .github/workflows/nw3-digest.yml) checks out the repo, runs nw3_digest.py, then commits the updated index.html and items.json back to main. items.json holds the full history of items found so far, which is what lets the script tell new stories apart from ones it's already reported.

The index.html is served directly as a GitHub Pages site, creating a self-updating homepage of NW3 news with no server or always-on machine required.

View it at http://briangroth.github.io/NW3-News
