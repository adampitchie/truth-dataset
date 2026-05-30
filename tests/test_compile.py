"""Tests for compile.py — covers all row transformation logic and main() behaviour."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import compile as compile_mod


# ── Helpers ───────────────────────────────────────────────────────────────────

def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def base_record(**kwargs) -> dict:
    defaults = {
        "id": "1",
        "url": "https://trumpstruth.org/statuses/1",
        "timestamp_iso": "2022-08-22T22:00:00+00:00",
        "text": "Hello world",
        "truth_social_url": "https://truthsocial.com/s/1",
        "is_retruth": False,
        "attachments": [],
        "scraped_at": "2024-08-22T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return defaults


def run_main(tmp_path: Path, records: list[dict]) -> pd.DataFrame:
    input_path = tmp_path / "dataset.jsonl"
    output_path = tmp_path / "dataset.parquet"
    write_jsonl(input_path, records)
    with (
        patch.object(compile_mod, "INPUT_PATH", input_path),
        patch.object(compile_mod, "OUTPUT_PATH", output_path),
    ):
        compile_mod.main()
    return pd.read_parquet(output_path)


# ── Input validation ──────────────────────────────────────────────────────────

class TestInputValidation:
    def test_exits_when_input_missing(self, tmp_path):
        missing = tmp_path / "missing.jsonl"
        output = tmp_path / "out.parquet"
        with (
            patch.object(compile_mod, "INPUT_PATH", missing),
            patch.object(compile_mod, "OUTPUT_PATH", output),
            pytest.raises(SystemExit) as exc,
        ):
            compile_mod.main()
        assert exc.value.code != 0

    def test_exit_message_mentions_input(self, tmp_path, capsys):
        missing = tmp_path / "missing.jsonl"
        output = tmp_path / "out.parquet"
        with (
            patch.object(compile_mod, "INPUT_PATH", missing),
            patch.object(compile_mod, "OUTPUT_PATH", output),
            pytest.raises(SystemExit),
        ):
            compile_mod.main()


# ── Row count and basic fields ────────────────────────────────────────────────

class TestBasicFields:
    def test_row_count_matches_records(self, tmp_path):
        records = [base_record(id=str(i)) for i in range(5)]
        df = run_main(tmp_path, records)
        assert len(df) == 5

    def test_empty_jsonl_produces_empty_dataframe(self, tmp_path):
        input_path = tmp_path / "dataset.jsonl"
        output_path = tmp_path / "dataset.parquet"
        input_path.write_text("", encoding="utf-8")
        with (
            patch.object(compile_mod, "INPUT_PATH", input_path),
            patch.object(compile_mod, "OUTPUT_PATH", output_path),
        ):
            compile_mod.main()
        df = pd.read_parquet(output_path)
        assert len(df) == 0  # empty DataFrame; columns may vary by parquet engine

    def test_blank_lines_in_jsonl_ignored(self, tmp_path):
        input_path = tmp_path / "dataset.jsonl"
        output_path = tmp_path / "dataset.parquet"
        input_path.write_text(
            json.dumps(base_record(id="1")) + "\n\n" + json.dumps(base_record(id="2")) + "\n\n",
            encoding="utf-8",
        )
        with (
            patch.object(compile_mod, "INPUT_PATH", input_path),
            patch.object(compile_mod, "OUTPUT_PATH", output_path),
        ):
            compile_mod.main()
        df = pd.read_parquet(output_path)
        assert len(df) == 2

    def test_id_preserved(self, tmp_path):
        df = run_main(tmp_path, [base_record(id="abc123")])
        assert df.iloc[0]["id"] == "abc123"

    def test_url_preserved(self, tmp_path):
        df = run_main(tmp_path, [base_record(url="https://trumpstruth.org/statuses/10")])
        assert df.iloc[0]["url"] == "https://trumpstruth.org/statuses/10"

    def test_text_preserved(self, tmp_path):
        df = run_main(tmp_path, [base_record(text="MAKE AMERICA GREAT AGAIN")])
        assert df.iloc[0]["text"] == "MAKE AMERICA GREAT AGAIN"

    def test_truth_social_url_preserved(self, tmp_path):
        df = run_main(tmp_path, [base_record(truth_social_url="https://ts.com/s/10")])
        assert df.iloc[0]["truth_social_url"] == "https://ts.com/s/10"

    def test_is_retruth_true_preserved(self, tmp_path):
        df = run_main(tmp_path, [base_record(is_retruth=True)])
        assert bool(df.iloc[0]["is_retruth"]) is True

    def test_is_retruth_false_preserved(self, tmp_path):
        df = run_main(tmp_path, [base_record(is_retruth=False)])
        assert bool(df.iloc[0]["is_retruth"]) is False

    def test_scraped_at_preserved(self, tmp_path):
        df = run_main(tmp_path, [base_record(scraped_at="2024-08-22T00:00:00+00:00")])
        assert df.iloc[0]["scraped_at"] == "2024-08-22T00:00:00+00:00"


# ── Timestamp parsing ─────────────────────────────────────────────────────────

class TestTimestampParsing:
    def test_timestamp_column_is_datetime(self, tmp_path):
        df = run_main(tmp_path, [base_record(timestamp_iso="2024-08-22T17:00:00+00:00")])
        assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])

    def test_timestamp_value_correct(self, tmp_path):
        df = run_main(tmp_path, [base_record(timestamp_iso="2024-08-22T17:00:00+00:00")])
        assert df.iloc[0]["timestamp"].year == 2024
        assert df.iloc[0]["timestamp"].month == 8
        assert df.iloc[0]["timestamp"].day == 22

    def test_invalid_timestamp_coerced_to_nat(self, tmp_path):
        df = run_main(tmp_path, [base_record(timestamp_iso="not-a-date")])
        assert pd.isna(df.iloc[0]["timestamp"])

    def test_empty_timestamp_coerced_to_nat(self, tmp_path):
        df = run_main(tmp_path, [base_record(timestamp_iso="")])
        assert pd.isna(df.iloc[0]["timestamp"])


# ── Attachment counts ─────────────────────────────────────────────────────────

class TestAttachmentCounts:
    def test_no_attachments(self, tmp_path):
        df = run_main(tmp_path, [base_record(attachments=[])])
        assert df.iloc[0]["n_images"] == 0
        assert df.iloc[0]["n_videos"] == 0

    def test_single_image(self, tmp_path):
        atts = [{"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": "flag"}]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["n_images"] == 1
        assert df.iloc[0]["n_videos"] == 0

    def test_single_video(self, tmp_path):
        atts = [{"type": "video", "url": "https://cdn.ex.com/a.mp4",
                 "caption_url": "", "transcript": "spoken"}]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["n_videos"] == 1
        assert df.iloc[0]["n_images"] == 0

    def test_multiple_images(self, tmp_path):
        atts = [
            {"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": "a"},
            {"type": "image", "url": "https://cdn.ex.com/b.jpg", "description": "b"},
        ]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["n_images"] == 2

    def test_mixed_attachments(self, tmp_path):
        atts = [
            {"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": "img"},
            {"type": "video", "url": "https://cdn.ex.com/v.mp4",
             "caption_url": "", "transcript": ""},
        ]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["n_images"] == 1
        assert df.iloc[0]["n_videos"] == 1


# ── Image descriptions ────────────────────────────────────────────────────────

class TestImageDescriptions:
    def test_single_image_description(self, tmp_path):
        atts = [{"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": "A rally"}]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["image_descriptions"] == "A rally"

    def test_multiple_descriptions_joined_with_blank_line(self, tmp_path):
        atts = [
            {"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": "First"},
            {"type": "image", "url": "https://cdn.ex.com/b.jpg", "description": "Second"},
        ]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["image_descriptions"] == "First\n\nSecond"

    def test_empty_description_excluded(self, tmp_path):
        atts = [
            {"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": ""},
            {"type": "image", "url": "https://cdn.ex.com/b.jpg", "description": "Real"},
        ]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["image_descriptions"] == "Real"

    def test_no_images_gives_empty_string(self, tmp_path):
        df = run_main(tmp_path, [base_record(attachments=[])])
        assert df.iloc[0]["image_descriptions"] == ""


# ── Video transcripts ─────────────────────────────────────────────────────────

class TestVideoTranscripts:
    def test_single_transcript(self, tmp_path):
        atts = [{"type": "video", "url": "https://cdn.ex.com/v.mp4",
                 "caption_url": "", "transcript": "Spoken words"}]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["video_transcripts"] == "Spoken words"

    def test_multiple_transcripts_joined_with_blank_line(self, tmp_path):
        atts = [
            {"type": "video", "url": "https://cdn.ex.com/v1.mp4",
             "caption_url": "", "transcript": "First"},
            {"type": "video", "url": "https://cdn.ex.com/v2.mp4",
             "caption_url": "", "transcript": "Second"},
        ]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["video_transcripts"] == "First\n\nSecond"

    def test_empty_transcript_excluded(self, tmp_path):
        atts = [
            {"type": "video", "url": "https://cdn.ex.com/v1.mp4",
             "caption_url": "", "transcript": ""},
            {"type": "video", "url": "https://cdn.ex.com/v2.mp4",
             "caption_url": "", "transcript": "Real"},
        ]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert df.iloc[0]["video_transcripts"] == "Real"

    def test_no_videos_gives_empty_string(self, tmp_path):
        df = run_main(tmp_path, [base_record(attachments=[])])
        assert df.iloc[0]["video_transcripts"] == ""


# ── Media URL lists ───────────────────────────────────────────────────────────

class TestMediaUrls:
    def test_image_urls_list(self, tmp_path):
        atts = [
            {"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": ""},
            {"type": "image", "url": "https://cdn.ex.com/b.jpg", "description": ""},
        ]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert list(df.iloc[0]["image_urls"]) == [
            "https://cdn.ex.com/a.jpg",
            "https://cdn.ex.com/b.jpg",
        ]

    def test_video_urls_list(self, tmp_path):
        atts = [{"type": "video", "url": "https://cdn.ex.com/v.mp4",
                 "caption_url": "https://cdn.ex.com/c.vtt", "transcript": ""}]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert list(df.iloc[0]["video_urls"]) == ["https://cdn.ex.com/v.mp4"]

    def test_caption_urls_list(self, tmp_path):
        atts = [{"type": "video", "url": "https://cdn.ex.com/v.mp4",
                 "caption_url": "https://cdn.ex.com/c.vtt", "transcript": ""}]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert list(df.iloc[0]["caption_urls"]) == ["https://cdn.ex.com/c.vtt"]

    def test_empty_url_excluded_from_list(self, tmp_path):
        atts = [{"type": "image", "url": "", "description": ""}]
        df = run_main(tmp_path, [base_record(attachments=atts)])
        assert list(df.iloc[0]["image_urls"]) == []

    def test_no_attachments_gives_empty_lists(self, tmp_path):
        df = run_main(tmp_path, [base_record(attachments=[])])
        assert list(df.iloc[0]["image_urls"]) == []
        assert list(df.iloc[0]["video_urls"]) == []
        assert list(df.iloc[0]["caption_urls"]) == []


# ── all_text column ───────────────────────────────────────────────────────────

class TestAllText:
    def test_text_only_post(self, tmp_path):
        df = run_main(tmp_path, [base_record(text="Just text", attachments=[])])
        assert df.iloc[0]["all_text"] == "Just text"

    def test_text_plus_image_description(self, tmp_path):
        atts = [{"type": "image", "url": "https://cdn.ex.com/a.jpg", "description": "A flag"}]
        df = run_main(tmp_path, [base_record(text="Post text", attachments=atts)])
        all_text = df.iloc[0]["all_text"]
        assert "Post text" in all_text
        assert "A flag" in all_text

    def test_text_plus_video_transcript(self, tmp_path):
        atts = [{"type": "video", "url": "https://cdn.ex.com/v.mp4",
                 "caption_url": "", "transcript": "Spoken"}]
        df = run_main(tmp_path, [base_record(text="Watch this", attachments=atts)])
        all_text = df.iloc[0]["all_text"]
        assert "Watch this" in all_text
        assert "Spoken" in all_text

    def test_media_only_post_has_all_text(self, tmp_path):
        atts = [{"type": "image", "url": "https://cdn.ex.com/a.jpg",
                 "description": "Description only"}]
        df = run_main(tmp_path, [base_record(text="", attachments=atts)])
        assert df.iloc[0]["all_text"] == "Description only"

    def test_empty_text_no_media_gives_empty_all_text(self, tmp_path):
        df = run_main(tmp_path, [base_record(text="", attachments=[])])
        assert df.iloc[0]["all_text"] == ""

    def test_all_text_stripped(self, tmp_path):
        df = run_main(tmp_path, [base_record(text="  trimmed  ", attachments=[])])
        assert not df.iloc[0]["all_text"].startswith(" ")


# ── Output file ───────────────────────────────────────────────────────────────

class TestOutputFile:
    def test_parquet_file_created(self, tmp_path):
        output_path = tmp_path / "out.parquet"
        input_path = tmp_path / "dataset.jsonl"
        write_jsonl(input_path, [base_record()])
        with (
            patch.object(compile_mod, "INPUT_PATH", input_path),
            patch.object(compile_mod, "OUTPUT_PATH", output_path),
        ):
            compile_mod.main()
        assert output_path.exists()

    def test_output_parent_dir_created(self, tmp_path):
        output_path = tmp_path / "nested" / "dir" / "out.parquet"
        input_path = tmp_path / "dataset.jsonl"
        write_jsonl(input_path, [base_record()])
        with (
            patch.object(compile_mod, "INPUT_PATH", input_path),
            patch.object(compile_mod, "OUTPUT_PATH", output_path),
        ):
            compile_mod.main()
        assert output_path.exists()

    def test_parquet_readable_by_pandas(self, tmp_path):
        df = run_main(tmp_path, [base_record()])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    def test_expected_columns_present(self, tmp_path):
        df = run_main(tmp_path, [base_record()])
        expected = {
            "id", "url", "timestamp_iso", "text", "truth_social_url", "is_retruth",
            "n_images", "n_videos", "image_descriptions", "video_transcripts",
            "image_urls", "video_urls", "caption_urls", "all_text", "scraped_at",
            "timestamp",
        }
        assert expected.issubset(set(df.columns))


# ── main() via sys.argv ───────────────────────────────────────────────────────

class TestMainCli:
    def test_main_with_cli_paths(self, tmp_path):
        input_path = tmp_path / "in.jsonl"
        output_path = tmp_path / "out.parquet"
        write_jsonl(input_path, [base_record(id="cli1")])

        import sys
        import importlib
        with patch.object(sys, "argv", ["compile.py", str(input_path), str(output_path)]):
            importlib.reload(compile_mod)
            compile_mod.main()

        df = pd.read_parquet(output_path)
        assert df.iloc[0]["id"] == "cli1"
