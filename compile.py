"""Convert data/dataset.jsonl into an analysis-friendly Parquet file.

Reads the canonical JSONL (one post per line), flattens the nested `attachments`
into convenience columns, and writes a typed, compressed Parquet file that loads
into pandas in milliseconds.

Derived columns added (these do NOT exist as such in the JSONL):
  n_images            — number of image attachments
  n_videos            — number of video attachments
  image_descriptions  — all image descriptions joined with blank lines
  video_transcripts   — all video transcripts joined with blank lines
  image_urls          — list of image file URLs (flattened from attachments)
  video_urls          — list of video file URLs (flattened from attachments)
  caption_urls        — list of video caption (VTT) URLs
  all_text            — post text + image descriptions + transcripts, joined
                        (one column for full-text search / NLP, covers media-only posts)
  timestamp           — timestamp_iso parsed to a real UTC datetime

The nested `attachments` array from the JSONL is flattened into the columns above,
so the Parquet is self-sufficient (no media information is lost).

Usage:
  python compile.py                 # data/dataset.jsonl -> data/dataset.parquet
  python compile.py in.jsonl out.parquet
"""

import json
import sys
from pathlib import Path

import pandas as pd

INPUT_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/dataset.jsonl")
OUTPUT_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/dataset.parquet")


def main():
    if not INPUT_PATH.exists():
        sys.exit(f"Input not found: {INPUT_PATH} — run the scraper first.")

    rows = []
    with INPUT_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            atts = r.get("attachments", [])
            images = [a for a in atts if a["type"] == "image"]
            videos = [a for a in atts if a["type"] == "video"]

            descriptions = [a.get("description", "") for a in images if a.get("description")]
            transcripts = [a.get("transcript", "") for a in videos if a.get("transcript")]

            rows.append({
                "id": r["id"],
                "url": r["url"],
                "timestamp_iso": r.get("timestamp_iso", ""),
                "text": r.get("text", ""),
                "truth_social_url": r.get("truth_social_url", ""),
                "is_retruth": r.get("is_retruth", False),
                "n_images": len(images),
                "n_videos": len(videos),
                "image_descriptions": "\n\n".join(descriptions),
                "video_transcripts": "\n\n".join(transcripts),
                # Media URLs preserved as lists so the Parquet is self-sufficient
                "image_urls": [a.get("url", "") for a in images if a.get("url")],
                "video_urls": [a.get("url", "") for a in videos if a.get("url")],
                "caption_urls": [a.get("caption_url", "") for a in videos if a.get("caption_url")],
                # One column with everything searchable (post + descriptions + transcripts)
                "all_text": "\n\n".join(
                    [r.get("text", "")] + descriptions + transcripts
                ).strip(),
                "scraped_at": r.get("scraped_at", ""),
            })

    df = pd.DataFrame(rows)
    ts_series = df["timestamp_iso"] if "timestamp_iso" in df.columns else pd.Series(dtype=str)
    df["timestamp"] = pd.to_datetime(ts_series, utc=True, errors="coerce")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PATH, compression="snappy", index=False)
    print(f"Wrote {OUTPUT_PATH} — {len(df):,} rows")


if __name__ == "__main__":
    main()
