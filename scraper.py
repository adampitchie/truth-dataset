"""
Scraper for trumpstruth.org — cursor-paginated, server-side rendered HTML.

Output: data/dataset.jsonl (one JSON object per line, append-safe)

Fields per post:
  id             — archive ID (integer string from /statuses/<id>)
  url            — archive URL (https://trumpstruth.org/statuses/<id>)
  timestamp      — raw timestamp string from the page
  timestamp_iso  — ISO 8601 UTC (parsed from Eastern Time)
  text           — post body text (empty string if image/video only)
  truth_social_url — original Truth Social URL
  attachments    — list of attachment dicts:
                     image: {type, url, description}              — image description text
                     video: {type, url, caption_url, transcript}  — transcript from the VTT
  is_retruth     — True if this is a reblog/retruth of another account
  scraped_at     — UTC ISO 8601 when this record was written

Deduplication is ALWAYS on: any post ID already present in the output file is
skipped, so re-running never creates duplicates.

Usage:
  python scraper.py                  # full scrape of the whole archive (first run)
  python scraper.py --update         # incremental: fetch only new posts, then stop
  python scraper.py --fresh          # delete existing data and re-scrape everything
  python scraper.py --oldest-first   # full scrape, oldest first
  python scraper.py --per-page 100   # items per request (10/25/50/100)
  python scraper.py --delay 1.5      # seconds between requests (default 1.0)
  python scraper.py --dry-run        # report new posts without writing to disk

Typical workflow:
  python scraper.py                  # once, to build the initial dataset
  python scraper.py --update         # every day after, to pull in new posts
  python scraper.py --update --dry-run  # preview what --update would write
"""

import argparse
import contextlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs, urljoin

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

BASE_URL = "https://trumpstruth.org"
EASTERN = ZoneInfo("America/New_York")
OUTPUT_PATH = Path("data/dataset.jsonl")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; research-scraper/1.0; "
        "+https://github.com/adampitchie/truth-dataset)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_timestamp(raw: str) -> str:
    """Parse 'May 30, 2026, 12:46 AM' (Eastern) → ISO 8601 UTC."""
    try:
        dt_eastern = datetime.strptime(raw.strip(), "%B %d, %Y, %I:%M %p")
        dt_eastern = dt_eastern.replace(tzinfo=EASTERN)
        return dt_eastern.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ""


def parse_vtt(vtt_text: str) -> str:
    """Extract spoken text from a WEBVTT caption file into one transcript string.

    Drops the WEBVTT header, NOTE blocks, cue indexes, and timestamp lines;
    keeps cue text, collapses consecutive duplicate lines, and joins with spaces.
    """
    lines = []
    for raw in vtt_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if "-->" in line:  # timestamp cue line
            continue
        if line.isdigit():  # cue index
            continue
        # Strip inline VTT tags like <c>, <00:00:01.000>
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue
        if lines and lines[-1] == line:  # collapse repeated captions
            continue
        lines.append(line)
    return " ".join(lines)


def fetch_transcript(session: requests.Session, vtt_url: str) -> str:
    """Fetch and parse a VTT caption file. Returns '' on any failure."""
    try:
        resp = session.get(vtt_url, timeout=30)
        resp.raise_for_status()
        return parse_vtt(resp.text)
    except requests.RequestException:
        return ""


def parse_status(div) -> dict:
    """Extract all fields from a div.status BeautifulSoup element."""
    # --- ID and archive URL ---
    status_url = (div.get("data-status-url") or "").strip()
    status_id = status_url.rstrip("/").split("/")[-1] if status_url else ""

    # Fallback: find the meta link that points to /statuses/<id>
    if not status_id:
        for a in div.select("a.status-info__meta-item"):
            href = a.get("href", "")
            m = re.search(r"/statuses/(\d+)", href)
            if m:
                status_id = m.group(1)
                status_url = urljoin(BASE_URL, href)
                break

    # --- Timestamp ---
    timestamp_raw = ""
    timestamp_iso = ""
    for a in div.select("a.status-info__meta-item"):
        href = a.get("href", "")
        if "/statuses/" in href:
            timestamp_raw = a.get_text(strip=True)
            timestamp_iso = parse_timestamp(timestamp_raw)
            break

    # --- Text ---
    content_div = div.find("div", class_="status__content")
    text = content_div.get_text(separator="\n", strip=True) if content_div else ""

    # --- Original Truth Social URL ---
    ext_link = div.find("a", class_="status__external-link")
    truth_social_url = ext_link["href"] if ext_link else ""

    # --- Attachments ---
    attachments = []
    for att_div in div.select("div.status-attachment"):
        img = att_div.find("img", class_="status-attachment__image")
        video = att_div.find("video")
        if img:
            attachments.append({
                "type": "image",
                "url": img.get("src", ""),
                # The img alt attribute holds the full image description
                # (identical to the detail page's "Image Description" block).
                "description": img.get("alt", ""),
            })
        elif video:
            src = video.get("src", "")
            # VTT caption track holds the video transcript (fetched separately)
            track = video.find("track")
            attachments.append({
                "type": "video",
                "url": src,
                "caption_url": urljoin(BASE_URL, track["src"]) if track else "",
                "transcript": "",  # filled in by fetch_transcript during scrape
            })

    # --- Is retruth (nested status = reblog) ---
    # A retruth has a nested div.status inside the body
    body_div = div.find("div", class_="status__body")
    nested = body_div.find("div", class_="status") if body_div else None
    is_retruth = nested is not None

    return {
        "id": status_id,
        "url": status_url,
        "timestamp": timestamp_raw,
        "timestamp_iso": timestamp_iso,
        "text": text,
        "truth_social_url": truth_social_url,
        "attachments": attachments,
        "is_retruth": is_retruth,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def build_url(cursor: Optional[str], sort: str, per_page: int) -> str:
    params = {
        "sort": sort,
        "per_page": per_page,
        "start_date": "",
        "end_date": "",
        "removed": "include",
    }
    if cursor:
        params["cursor"] = cursor
    return f"{BASE_URL}/?{urlencode(params)}"


def extract_next_cursor(soup: BeautifulSoup) -> Optional[str]:
    """Return the cursor value from the 'Next Page' link, or None if last page."""
    next_link = soup.find("a", string=re.compile(r"Next Page", re.I))
    if not next_link:
        # Try finding by class or broader text
        for a in soup.find_all("a"):
            if "Next Page" in a.get_text():
                next_link = a
                break
    if not next_link:
        return None

    href = next_link.get("href", "")
    qs = parse_qs(urlparse(href).query)
    cursors = qs.get("cursor")
    return cursors[0] if cursors else None


def load_existing_ids(path: Path) -> set[str]:
    ids = set()
    if not path.exists():
        return ids
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    return ids


def scrape(sort: str, per_page: int, delay: float, update: bool, fresh: bool,
           transcripts: bool = True, transcript_delay: float = 0.3,
           dry_run: bool = False):
    if dry_run:
        print("DRY RUN — nothing will be written to disk.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if fresh and OUTPUT_PATH.exists():
        if dry_run:
            print(f"DRY RUN — would delete {OUTPUT_PATH} and re-scrape from scratch.")
        else:
            OUTPUT_PATH.unlink()
            print("Fresh start: deleted existing output file.")

    # Dedup is always on: load every ID we already have so we never re-write one.
    existing_ids = load_existing_ids(OUTPUT_PATH)
    if existing_ids:
        print(f"{len(existing_ids):,} posts already in {OUTPUT_PATH}")

    # Incremental updates only make sense newest-first, and only if we already
    # have data to stop against. Fall back to a full scrape otherwise.
    if update:
        if not existing_ids:
            print("Update mode requested but no existing data — running full scrape.")
            update = False
        else:
            sort = "desc"  # new posts appear at the top in descending order

    session = requests.Session()
    session.headers.update(HEADERS)

    cursor = None
    page_num = 0
    total_written = 0
    total_skipped = 0

    ctx = contextlib.nullcontext() if dry_run else OUTPUT_PATH.open("a")
    with ctx as out_f:
        while True:
            page_num += 1
            url = build_url(cursor, sort, per_page)
            print(f"Page {page_num:>4} | {url[:120]}", flush=True)

            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  ERROR fetching page {page_num}: {e}")
                print("  Waiting 10s before retry...")
                time.sleep(10)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Each top-level div.status in div.statuses is a post
            statuses_container = soup.find("div", class_="statuses")
            if not statuses_container:
                print("  No .statuses container found — stopping.")
                break

            # Only direct children to avoid nested retruth divs
            posts = statuses_container.find_all("div", class_="status", recursive=False)
            if not posts:
                print("  No posts on page — done.")
                break

            page_written = 0
            page_skipped = 0
            page_transcripts = 0
            for div in posts:
                record = parse_status(div)
                if record["id"] in existing_ids:
                    page_skipped += 1
                    total_skipped += 1
                    continue
                # Fetch video transcripts (one small request per video).
                if transcripts and not dry_run:
                    for att in record["attachments"]:
                        if att["type"] == "video" and att.get("caption_url"):
                            att["transcript"] = fetch_transcript(session, att["caption_url"])
                            if att["transcript"]:
                                page_transcripts += 1
                            time.sleep(transcript_delay)
                if dry_run:
                    print(f"  DRY RUN would write: id={record['id']} ts={record['timestamp_iso']}")
                else:
                    out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out_f.flush()
                existing_ids.add(record["id"])
                page_written += 1
                total_written += 1

            print(
                f"         new {page_written}, already-have {page_skipped}, "
                f"transcripts {page_transcripts} | new this run: {total_written:,}"
            )

            # Incremental stop: once a whole page is posts we already have, we've
            # caught up to the archive — everything below is older and stored.
            if update and page_written == 0:
                print("Reached already-archived posts — incremental update complete.")
                break

            cursor = extract_next_cursor(soup)
            if not cursor:
                print("No next page cursor — scrape complete.")
                break

            time.sleep(delay)

    if total_written:
        print(f"\nDone. {total_written:,} new posts written to {OUTPUT_PATH}")
    else:
        print(f"\nDone. No new posts — {OUTPUT_PATH} already up to date.")


def main():
    parser = argparse.ArgumentParser(description="Scrape trumpstruth.org to JSONL")
    parser.add_argument(
        "--update", action="store_true",
        help="Incremental mode: fetch only posts newer than what's stored, then stop",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Delete the existing output file and re-scrape the whole archive",
    )
    parser.add_argument(
        "--oldest-first", action="store_true",
        help="Full scrape ordered oldest-first (ignored in --update mode)",
    )
    parser.add_argument(
        "--per-page", type=int, default=100, choices=[10, 25, 50, 100],
        help="Posts per page request (default: 100)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds to wait between page requests (default: 1.0)",
    )
    parser.add_argument(
        "--no-transcripts", action="store_true",
        help="Skip fetching video transcripts (faster; videos keep caption_url only)",
    )
    parser.add_argument(
        "--transcript-delay", type=float, default=0.3,
        help="Seconds to wait between transcript (VTT) requests (default: 0.3)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and report new posts without writing anything to disk",
    )
    args = parser.parse_args()

    sort = "asc" if args.oldest_first else "desc"
    scrape(
        sort=sort,
        per_page=args.per_page,
        delay=args.delay,
        update=args.update,
        fresh=args.fresh,
        transcripts=not args.no_transcripts,
        transcript_delay=args.transcript_delay,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
