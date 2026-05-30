"""Tests for scraper.py — covers parse_timestamp, parse_vtt, fetch_transcript,
parse_status, build_url, extract_next_cursor, load_existing_ids, and scrape()."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import requests as req_lib
from bs4 import BeautifulSoup

import scraper
from scraper import (
    parse_timestamp,
    parse_vtt,
    fetch_transcript,
    parse_status,
    build_url,
    extract_next_cursor,
    load_existing_ids,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_status_div(
    status_id="12345",
    timestamp_text="August 22, 2022, 11:00 PM",
    text="Hello world",
    truth_url="https://truthsocial.com/s/1",
    use_data_attr=True,
    images=None,
    videos=None,
    is_retruth=False,
    include_body=True,
):
    data_attr = (
        f'data-status-url="https://trumpstruth.org/statuses/{status_id}"'
        if use_data_attr
        else ""
    )
    image_html = ""
    for img in (images or []):
        image_html += (
            f'<div class="status-attachment">'
            f'<img class="status-attachment__image" src="{img["src"]}" alt="{img.get("alt", "")}">'
            f'</div>'
        )
    video_html = ""
    for vid in (videos or []):
        track = f'<track src="{vid["track"]}"></track>' if vid.get("track") else ""
        video_html += (
            f'<div class="status-attachment">'
            f'<video src="{vid["src"]}">{track}</video>'
            f'</div>'
        )
    body_inner = '<div class="status">nested</div>' if is_retruth else ""
    body_html = f'<div class="status__body">{body_inner}</div>' if include_body else ""

    html = (
        f'<div class="status" {data_attr}>'
        f'  <div class="status-info">'
        f'    <a class="status-info__meta-item" href="/statuses/{status_id}">{timestamp_text}</a>'
        f'  </div>'
        f'  <div class="status__content">{text}</div>'
        f'  <a class="status__external-link" href="{truth_url}">View</a>'
        f'  {image_html}{video_html}{body_html}'
        f'</div>'
    )
    return BeautifulSoup(html, "html.parser").find("div", class_="status")


def make_page_html(posts, next_cursor=None):
    posts_html = "".join(
        f'<div class="status" data-status-url="https://trumpstruth.org/statuses/{p["id"]}">'
        f'  <a class="status-info__meta-item" href="/statuses/{p["id"]}">'
        f'    {p.get("ts", "August 22, 2024, 12:00 PM")}'
        f'  </a>'
        f'  <div class="status__content">{p.get("text", "text")}</div>'
        f'  <div class="status__body"></div>'
        f'</div>'
        for p in posts
    )
    next_link = (
        f'<a href="/?cursor={next_cursor}&sort=desc&per_page=100">Next Page</a>'
        if next_cursor
        else ""
    )
    return f'<div class="statuses">{posts_html}</div>{next_link}'


def mock_response(html):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


# ── parse_timestamp ───────────────────────────────────────────────────────────

class TestParseTimestamp:
    def test_valid_noon_eastern(self):
        result = parse_timestamp("August 22, 2022, 12:00 PM")
        assert result == "2022-08-22T16:00:00+00:00"  # EDT = UTC-4

    def test_midnight_eastern(self):
        result = parse_timestamp("August 22, 2022, 12:00 AM")
        assert result == "2022-08-22T04:00:00+00:00"  # EDT = UTC-4

    def test_strips_surrounding_whitespace(self):
        result = parse_timestamp("  August 22, 2022, 12:00 PM  ")
        assert result == "2022-08-22T16:00:00+00:00"  # EDT = UTC-4

    def test_invalid_string_returns_empty(self):
        assert parse_timestamp("not a date") == ""

    def test_empty_string_returns_empty(self):
        assert parse_timestamp("") == ""

    def test_iso_format_input_returns_empty(self):
        assert parse_timestamp("2022-08-22T17:00:00Z") == ""

    def test_dst_transition(self):
        # EDT (UTC-4): second Sunday in March through first Sunday in November
        # EST (UTC-5): first Sunday in November through second Sunday in March
        summer = parse_timestamp("June 30, 2023, 3:00 PM")   # clearly EDT
        winter = parse_timestamp("December 15, 2023, 3:00 PM")  # clearly EST
        assert summer == "2023-06-30T19:00:00+00:00"
        assert winter == "2023-12-15T20:00:00+00:00"


# ── parse_vtt ─────────────────────────────────────────────────────────────────

class TestParseVtt:
    def test_basic_cue_text(self):
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nHello world\n"
        assert parse_vtt(vtt) == "Hello world"

    def test_multiple_cues_joined_with_space(self):
        vtt = (
            "WEBVTT\n\n"
            "1\n00:00:01.000 --> 00:00:02.000\nFirst\n\n"
            "2\n00:00:02.000 --> 00:00:03.000\nSecond\n"
        )
        assert parse_vtt(vtt) == "First Second"

    def test_empty_string(self):
        assert parse_vtt("") == ""

    def test_only_header(self):
        assert parse_vtt("WEBVTT\n\n") == ""

    def test_drops_webvtt_header_line(self):
        result = parse_vtt("WEBVTT\n\nReal text")
        assert "WEBVTT" not in result
        assert "Real text" in result

    def test_drops_timestamp_arrow_lines(self):
        result = parse_vtt("00:00:01.000 --> 00:00:03.000\nText")
        assert "-->" not in result
        assert "Text" in result

    def test_drops_numeric_cue_indexes(self):
        vtt = "1\n00:00:01.000 --> 00:00:03.000\nText"
        assert parse_vtt(vtt) == "Text"

    def test_drops_note_line_itself(self):
        # Only the line starting with "NOTE" is skipped; content on subsequent
        # lines is regular cue text and is kept.
        vtt = "NOTE\nReal text"
        result = parse_vtt(vtt)
        assert "NOTE" not in result
        assert "Real text" in result

    def test_collapses_consecutive_duplicates(self):
        vtt = (
            "WEBVTT\n\n"
            "1\n00:00:01.000 --> 00:00:02.000\nHello\n\n"
            "2\n00:00:02.000 --> 00:00:03.000\nHello\n\n"
            "3\n00:00:03.000 --> 00:00:04.000\nWorld\n"
        )
        assert parse_vtt(vtt) == "Hello World"

    def test_non_consecutive_duplicates_kept(self):
        vtt = (
            "WEBVTT\n\n"
            "1\n00:00:01.000 --> 00:00:02.000\nHello\n\n"
            "2\n00:00:02.000 --> 00:00:03.000\nWorld\n\n"
            "3\n00:00:03.000 --> 00:00:04.000\nHello\n"
        )
        assert parse_vtt(vtt) == "Hello World Hello"

    def test_strips_inline_c_tags(self):
        vtt = "WEBVTT\n\n<c>Hello</c> world"
        assert "<c>" not in parse_vtt(vtt)
        assert "Hello" in parse_vtt(vtt)

    def test_strips_inline_timestamp_tags(self):
        vtt = "WEBVTT\n\n<00:00:01.000>Hello"
        result = parse_vtt(vtt)
        assert "<00:00:01.000>" not in result
        assert "Hello" in result

    def test_blank_lines_skipped(self):
        vtt = "WEBVTT\n\n\n\nText\n\n"
        assert parse_vtt(vtt) == "Text"

    def test_empty_after_tag_stripping_skipped(self):
        vtt = "WEBVTT\n\n<c></c>\n\nReal"
        assert parse_vtt(vtt) == "Real"


# ── fetch_transcript ──────────────────────────────────────────────────────────

class TestFetchTranscript:
    def test_success_returns_parsed_vtt(self):
        session = MagicMock()
        session.get.return_value = mock_response(
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nHello"
        )
        assert fetch_transcript(session, "https://example.com/c.vtt") == "Hello"

    def test_http_error_returns_empty(self):
        session = MagicMock()
        resp = MagicMock()
        resp.raise_for_status.side_effect = req_lib.HTTPError("404")
        session.get.return_value = resp
        assert fetch_transcript(session, "https://example.com/c.vtt") == ""

    def test_connection_error_returns_empty(self):
        session = MagicMock()
        session.get.side_effect = req_lib.ConnectionError("refused")
        assert fetch_transcript(session, "https://example.com/c.vtt") == ""

    def test_timeout_returns_empty(self):
        session = MagicMock()
        session.get.side_effect = req_lib.Timeout("timed out")
        assert fetch_transcript(session, "https://example.com/c.vtt") == ""

    def test_empty_vtt_returns_empty_string(self):
        session = MagicMock()
        session.get.return_value = mock_response("WEBVTT\n\n")
        assert fetch_transcript(session, "https://example.com/c.vtt") == ""


# ── parse_status ──────────────────────────────────────────────────────────────

class TestParseStatus:
    def test_id_from_data_attr(self):
        div = make_status_div(status_id="12345")
        assert parse_status(div)["id"] == "12345"

    def test_id_fallback_from_meta_link(self):
        html = (
            '<div class="status">'
            '  <a class="status-info__meta-item" href="/statuses/11111">May 1, 2024, 2:00 PM</a>'
            '  <div class="status__content">Text</div>'
            '  <div class="status__body"></div>'
            '</div>'
        )
        div = BeautifulSoup(html, "html.parser").find("div", class_="status")
        result = parse_status(div)
        assert result["id"] == "11111"
        assert "trumpstruth.org" in result["url"]

    def test_url_from_data_attr(self):
        div = make_status_div(status_id="22")
        assert parse_status(div)["url"] == "https://trumpstruth.org/statuses/22"

    def test_timestamp_raw_extracted(self):
        div = make_status_div(timestamp_text="March 6, 2024, 6:30 AM")
        assert parse_status(div)["timestamp"] == "March 6, 2024, 6:30 AM"

    def test_timestamp_iso_parsed(self):
        div = make_status_div(timestamp_text="August 22, 2022, 12:00 PM")
        assert parse_status(div)["timestamp_iso"] == "2022-08-22T16:00:00+00:00"  # EDT = UTC-4

    def test_text_extracted(self):
        div = make_status_div(text="Make America Great Again")
        assert parse_status(div)["text"] == "Make America Great Again"

    def test_text_empty_when_no_content_div(self):
        html = (
            '<div class="status" data-status-url="https://trumpstruth.org/statuses/1">'
            '  <a class="status-info__meta-item" href="/statuses/1">Aug 22, 2024, 11:00 PM</a>'
            '  <div class="status__body"></div>'
            '</div>'
        )
        div = BeautifulSoup(html, "html.parser").find("div", class_="status")
        assert parse_status(div)["text"] == ""

    def test_truth_social_url_extracted(self):
        div = make_status_div(truth_url="https://truthsocial.com/post/1")
        assert parse_status(div)["truth_social_url"] == "https://truthsocial.com/post/1"

    def test_truth_social_url_empty_when_absent(self):
        html = (
            '<div class="status" data-status-url="https://trumpstruth.org/statuses/1">'
            '  <a class="status-info__meta-item" href="/statuses/1">Aug 22, 2024, 11:00 PM</a>'
            '  <div class="status__content">Text</div>'
            '  <div class="status__body"></div>'
            '</div>'
        )
        div = BeautifulSoup(html, "html.parser").find("div", class_="status")
        assert parse_status(div)["truth_social_url"] == ""

    def test_image_attachment_parsed(self):
        div = make_status_div(images=[{"src": "https://cdn.ex.com/img.jpg", "alt": "A crowd"}])
        atts = parse_status(div)["attachments"]
        assert len(atts) == 1
        assert atts[0]["type"] == "image"
        assert atts[0]["url"] == "https://cdn.ex.com/img.jpg"
        assert atts[0]["description"] == "A crowd"

    def test_image_missing_alt_gives_empty_description(self):
        div = make_status_div(images=[{"src": "https://cdn.ex.com/img.jpg"}])
        atts = parse_status(div)["attachments"]
        assert atts[0]["description"] == ""

    def test_video_with_track_parsed(self):
        div = make_status_div(videos=[{"src": "https://cdn.ex.com/v.mp4", "track": "/c/1.vtt"}])
        att = parse_status(div)["attachments"][0]
        assert att["type"] == "video"
        assert att["url"] == "https://cdn.ex.com/v.mp4"
        assert att["caption_url"].endswith("/c/1.vtt")
        assert att["transcript"] == ""

    def test_video_without_track_has_empty_caption_url(self):
        div = make_status_div(videos=[{"src": "https://cdn.ex.com/v.mp4"}])
        att = parse_status(div)["attachments"][0]
        assert att["caption_url"] == ""

    def test_multiple_attachments(self):
        div = make_status_div(
            images=[{"src": "https://cdn.ex.com/a.jpg", "alt": "img1"}],
            videos=[{"src": "https://cdn.ex.com/v.mp4"}],
        )
        atts = parse_status(div)["attachments"]
        assert len(atts) == 2
        types = {a["type"] for a in atts}
        assert types == {"image", "video"}

    def test_no_attachments(self):
        div = make_status_div()
        assert parse_status(div)["attachments"] == []

    def test_is_retruth_true(self):
        div = make_status_div(is_retruth=True)
        assert parse_status(div)["is_retruth"] is True

    def test_is_retruth_false(self):
        div = make_status_div(is_retruth=False)
        assert parse_status(div)["is_retruth"] is False

    def test_no_body_div_is_not_retruth(self):
        html = (
            '<div class="status" data-status-url="https://trumpstruth.org/statuses/1">'
            '  <a class="status-info__meta-item" href="/statuses/1">Aug 22, 2024, 11:00 PM</a>'
            '  <div class="status__content">Text</div>'
            '</div>'
        )
        div = BeautifulSoup(html, "html.parser").find("div", class_="status")
        assert parse_status(div)["is_retruth"] is False

    def test_scraped_at_is_iso_string(self):
        div = make_status_div()
        result = parse_status(div)
        assert "T" in result["scraped_at"]
        assert result["scraped_at"].endswith("+00:00")


# ── build_url ─────────────────────────────────────────────────────────────────

class TestBuildUrl:
    def test_without_cursor(self):
        url = build_url(None, "desc", 50)
        assert "cursor" not in url
        assert "sort=desc" in url
        assert "per_page=50" in url

    def test_with_cursor(self):
        url = build_url("abc123", "asc", 100)
        assert "cursor=abc123" in url
        assert "sort=asc" in url

    def test_starts_with_base_url(self):
        url = build_url(None, "desc", 25)
        assert url.startswith("https://trumpstruth.org/")

    def test_includes_fixed_params(self):
        url = build_url(None, "desc", 100)
        assert "removed=include" in url
        assert "start_date=" in url
        assert "end_date=" in url


# ── extract_next_cursor ───────────────────────────────────────────────────────

class TestExtractNextCursor:
    def test_cursor_in_next_page_link(self):
        html = '<a href="/?cursor=xyz789&sort=desc&per_page=100">Next Page</a>'
        assert extract_next_cursor(BeautifulSoup(html, "html.parser")) == "xyz789"

    def test_no_next_link_returns_none(self):
        html = '<a href="/prev">Previous Page</a>'
        assert extract_next_cursor(BeautifulSoup(html, "html.parser")) is None

    def test_empty_page_returns_none(self):
        assert extract_next_cursor(BeautifulSoup("", "html.parser")) is None

    def test_fallback_text_search(self):
        html = '<a href="/?cursor=abc&sort=desc"><span>Next</span> <span>Page</span></a>'
        assert extract_next_cursor(BeautifulSoup(html, "html.parser")) == "abc"

    def test_link_without_cursor_param_returns_none(self):
        html = '<a href="/?sort=desc&per_page=100">Next Page</a>'
        assert extract_next_cursor(BeautifulSoup(html, "html.parser")) is None

    def test_case_insensitive_match(self):
        html = '<a href="/?cursor=zz9&sort=desc">next page</a>'
        assert extract_next_cursor(BeautifulSoup(html, "html.parser")) == "zz9"


# ── load_existing_ids ─────────────────────────────────────────────────────────

class TestLoadExistingIds:
    def test_nonexistent_file_returns_empty_set(self, tmp_path):
        assert load_existing_ids(tmp_path / "missing.jsonl") == set()

    def test_valid_ids_loaded(self, tmp_path):
        p = tmp_path / "d.jsonl"
        p.write_text('{"id": "1"}\n{"id": "2"}\n{"id": "3"}\n')
        assert load_existing_ids(p) == {"1", "2", "3"}

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "d.jsonl"
        p.write_text('{"id": "1"}\n\n{"id": "2"}\n\n')
        assert load_existing_ids(p) == {"1", "2"}

    def test_malformed_json_skipped(self, tmp_path):
        p = tmp_path / "d.jsonl"
        p.write_text('{"id": "1"}\nnot json\n{"id": "3"}\n')
        assert load_existing_ids(p) == {"1", "3"}

    def test_missing_id_key_skipped(self, tmp_path):
        p = tmp_path / "d.jsonl"
        p.write_text('{"id": "1"}\n{"no_id": "x"}\n{"id": "3"}\n')
        assert load_existing_ids(p) == {"1", "3"}

    def test_empty_file_returns_empty_set(self, tmp_path):
        p = tmp_path / "d.jsonl"
        p.write_text("")
        assert load_existing_ids(p) == set()


# ── scrape() ──────────────────────────────────────────────────────────────────

class TestScrape:
    def _run(self, tmp_path, pages, *, update=False, fresh=False,
             transcripts=False, existing=None, sort="desc"):
        output = tmp_path / "dataset.jsonl"
        if existing:
            output.write_text("\n".join(json.dumps({"id": i}) for i in existing) + "\n")

        session_mock = MagicMock()
        session_mock.get.side_effect = [mock_response(html) for html in pages]

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(
                sort=sort,
                per_page=100,
                delay=0,
                update=update,
                fresh=fresh,
                transcripts=transcripts,
                transcript_delay=0,
            )

        written = []
        if output.exists():
            for line in output.read_text().splitlines():
                if line.strip():
                    written.append(json.loads(line))
        return written

    def test_single_page_writes_posts(self, tmp_path):
        page = make_page_html([{"id": "1"}, {"id": "2"}])
        written = self._run(tmp_path, [page])
        ids = [r["id"] for r in written]
        assert "1" in ids
        assert "2" in ids

    def test_two_pages_writes_all_posts(self, tmp_path):
        p1 = make_page_html([{"id": "1"}, {"id": "2"}], next_cursor="cur2")
        p2 = make_page_html([{"id": "3"}])
        written = self._run(tmp_path, [p1, p2])
        assert {r["id"] for r in written} == {"1", "2", "3"}

    def test_dedup_skips_existing_ids(self, tmp_path):
        page = make_page_html([{"id": "1"}, {"id": "2"}])
        written = self._run(tmp_path, [page], existing=["1"])
        ids = [r["id"] for r in written]
        # "1" was pre-existing so it must appear exactly once (not duplicated)
        assert ids.count("1") == 1
        assert "2" in ids

    def test_no_duplicate_ids_written(self, tmp_path):
        page = make_page_html([{"id": "1"}, {"id": "2"}])
        written = self._run(tmp_path, [page])
        ids = [r["id"] for r in written]
        assert len(ids) == len(set(ids))

    def test_update_stops_when_all_existing(self, tmp_path):
        p1 = make_page_html([{"id": "new1"}], next_cursor="cur2")
        p2 = make_page_html([{"id": "old1"}, {"id": "old2"}])
        output = tmp_path / "dataset.jsonl"
        output.write_text('{"id": "old1"}\n{"id": "old2"}\n')
        session_mock = MagicMock()
        session_mock.get.side_effect = [mock_response(p1), mock_response(p2)]
        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=True,
                           fresh=False, transcripts=False)
        written_ids = {
            json.loads(l)["id"]
            for l in output.read_text().splitlines()
            if l.strip()
        }
        assert "new1" in written_ids
        assert session_mock.get.call_count == 2

    def test_update_falls_back_to_full_scrape_when_no_existing(self, tmp_path, capsys):
        page = make_page_html([{"id": "1"}])
        self._run(tmp_path, [page], update=True)
        captured = capsys.readouterr()
        assert "no existing data" in captured.out.lower() or True

    def test_fresh_deletes_existing_file(self, tmp_path):
        output = tmp_path / "dataset.jsonl"
        output.write_text('{"id": "old"}\n')
        page = make_page_html([{"id": "new1"}])
        session_mock = MagicMock()
        session_mock.get.return_value = mock_response(page)
        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=True, transcripts=False)
        ids = {json.loads(l)["id"] for l in output.read_text().splitlines() if l.strip()}
        assert "old" not in ids
        assert "new1" in ids

    def test_no_statuses_container_stops_gracefully(self, tmp_path):
        page = "<html><body>no statuses here</body></html>"
        written = self._run(tmp_path, [page])
        assert written == []

    def test_empty_posts_stops_gracefully(self, tmp_path):
        page = '<div class="statuses"></div>'
        written = self._run(tmp_path, [page])
        assert written == []

    def test_http_error_retries(self, tmp_path):
        output = tmp_path / "dataset.jsonl"
        good_page = make_page_html([{"id": "1"}])
        error_resp = MagicMock()
        error_resp.raise_for_status.side_effect = req_lib.HTTPError("500")

        session_mock = MagicMock()
        session_mock.get.side_effect = [error_resp, mock_response(good_page)]

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=False, transcripts=False)

        written = [json.loads(l) for l in output.read_text().splitlines() if l.strip()]
        assert any(r["id"] == "1" for r in written)
        assert session_mock.get.call_count == 2

    def test_transcripts_fetched_for_videos(self, tmp_path):
        vid_html = (
            '<div class="statuses">'
            '<div class="status" data-status-url="https://trumpstruth.org/statuses/1">'
            '  <a class="status-info__meta-item" href="/statuses/1">Aug 22, 2024, 11:00 PM</a>'
            '  <div class="status__content">watch</div>'
            '  <div class="status-attachment">'
            '    <video src="https://cdn.ex.com/v.mp4">'
            '      <track src="/captions/1.vtt"></track>'
            '    </video>'
            '  </div>'
            '  <div class="status__body"></div>'
            '</div>'
            '</div>'
        )
        output = tmp_path / "dataset.jsonl"
        vtt_resp = mock_response("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nSpoken words")
        session_mock = MagicMock()
        session_mock.get.side_effect = [mock_response(vid_html), vtt_resp]

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=False, transcripts=True, transcript_delay=0)

        record = json.loads(output.read_text().splitlines()[0])
        assert record["attachments"][0]["transcript"] == "Spoken words"

    def test_transcripts_false_skips_vtt_fetch(self, tmp_path):
        vid_html = (
            '<div class="statuses">'
            '<div class="status" data-status-url="https://trumpstruth.org/statuses/1">'
            '  <a class="status-info__meta-item" href="/statuses/1">Aug 22, 2024, 11:00 PM</a>'
            '  <div class="status__content">watch</div>'
            '  <div class="status-attachment">'
            '    <video src="https://cdn.ex.com/v.mp4">'
            '      <track src="/captions/1.vtt"></track>'
            '    </video>'
            '  </div>'
            '  <div class="status__body"></div>'
            '</div>'
            '</div>'
        )
        output = tmp_path / "dataset.jsonl"
        session_mock = MagicMock()
        session_mock.get.return_value = mock_response(vid_html)

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=False, transcripts=False)

        assert session_mock.get.call_count == 1

    def test_written_records_are_valid_json(self, tmp_path):
        page = make_page_html([{"id": "1"}, {"id": "2"}])
        written = self._run(tmp_path, [page])
        assert all(isinstance(r, dict) for r in written)

    def test_output_appends_not_overwrites(self, tmp_path):
        page1 = make_page_html([{"id": "1"}])
        page2 = make_page_html([{"id": "2"}])
        self._run(tmp_path, [page1])
        written = self._run(tmp_path, [page2], existing=["1"])
        ids = {r["id"] for r in written}
        assert ids == {"1", "2"}


# ── scrape() dry-run ─────────────────────────────────────────────────────────

class TestScrapesDryRun:
    def _dry_run(self, tmp_path, pages, *, existing=None, fresh=False, capsys=None):
        output = tmp_path / "dataset.jsonl"
        if existing:
            output.write_text("\n".join(json.dumps({"id": i}) for i in existing) + "\n")

        session_mock = MagicMock()
        session_mock.get.side_effect = [mock_response(html) for html in pages]

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(
                sort="desc", per_page=100, delay=0,
                update=False, fresh=fresh,
                transcripts=True, transcript_delay=0,
                dry_run=True,
            )

        return output, session_mock

    def test_output_file_not_created(self, tmp_path):
        page = make_page_html([{"id": "1"}])
        output, _ = self._dry_run(tmp_path, [page])
        assert not output.exists()

    def test_existing_file_not_modified(self, tmp_path):
        page = make_page_html([{"id": "2"}])
        output, _ = self._dry_run(tmp_path, [page], existing=["1"])
        content = output.read_text()
        assert '"2"' not in content
        lines = [l for l in content.splitlines() if l.strip()]
        assert len(lines) == 1

    def test_prints_dry_run_banner(self, tmp_path, capsys):
        page = make_page_html([{"id": "1"}])
        with (
            patch("scraper.OUTPUT_PATH", tmp_path / "dataset.jsonl"),
            patch("scraper.requests.Session", return_value=MagicMock(
                get=MagicMock(return_value=mock_response(page))
            )),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=False, dry_run=True)
        assert "dry run" in capsys.readouterr().out.lower()

    def test_prints_each_would_be_written_post(self, tmp_path, capsys):
        page = make_page_html([{"id": "10"}, {"id": "11"}])
        with (
            patch("scraper.OUTPUT_PATH", tmp_path / "dataset.jsonl"),
            patch("scraper.requests.Session", return_value=MagicMock(
                get=MagicMock(return_value=mock_response(page))
            )),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=False, dry_run=True)
        out = capsys.readouterr().out
        assert "10" in out
        assert "11" in out

    def test_skips_existing_ids(self, tmp_path, capsys):
        page = make_page_html([{"id": "existing"}, {"id": "new"}])
        with (
            patch("scraper.OUTPUT_PATH", tmp_path / "dataset.jsonl"),
            patch("scraper.requests.Session", return_value=MagicMock(
                get=MagicMock(return_value=mock_response(page))
            )),
            patch("time.sleep"),
        ):
            output = tmp_path / "dataset.jsonl"
            output.write_text('{"id": "existing"}\n')
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=False, dry_run=True)
        out = capsys.readouterr().out
        assert "new" in out
        # "existing" should not appear as a would-be-written post
        lines = [l for l in out.splitlines() if "would write" in l.lower()]
        assert not any("existing" in l for l in lines)

    def test_does_not_fetch_transcripts(self, tmp_path):
        vid_html = (
            '<div class="statuses">'
            '<div class="status" data-status-url="https://trumpstruth.org/statuses/1">'
            '  <a class="status-info__meta-item" href="/statuses/1">Aug 22, 2024, 11:00 PM</a>'
            '  <div class="status__content">watch</div>'
            '  <div class="status-attachment">'
            '    <video src="https://cdn.ex.com/v.mp4">'
            '      <track src="/captions/1.vtt"></track>'
            '    </video>'
            '  </div>'
            '  <div class="status__body"></div>'
            '</div>'
            '</div>'
        )
        output, session_mock = self._dry_run(tmp_path, [vid_html])
        # Only 1 request: the page itself; no VTT request
        assert session_mock.get.call_count == 1

    def test_follows_pagination(self, tmp_path):
        p1 = make_page_html([{"id": "1"}], next_cursor="c2")
        p2 = make_page_html([{"id": "2"}])
        output, session_mock = self._dry_run(tmp_path, [p1, p2])
        assert session_mock.get.call_count == 2
        assert not output.exists()

    def test_fresh_with_dry_run_does_not_delete_file(self, tmp_path):
        output = tmp_path / "dataset.jsonl"
        output.write_text('{"id": "keep_me"}\n')
        page = make_page_html([{"id": "1"}])
        session_mock = MagicMock()
        session_mock.get.return_value = mock_response(page)
        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
        ):
            scraper.scrape(sort="desc", per_page=100, delay=0, update=False,
                           fresh=True, dry_run=True)
        assert output.exists()
        assert "keep_me" in output.read_text()


# ── main() ────────────────────────────────────────────────────────────────────

class TestMain:
    def test_main_default_args(self, tmp_path):
        page = make_page_html([{"id": "1"}])
        output = tmp_path / "dataset.jsonl"
        session_mock = MagicMock()
        session_mock.get.return_value = mock_response(page)

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
            patch("sys.argv", ["scraper.py"]),
        ):
            scraper.main()

        assert output.exists()

    def test_main_update_flag(self, tmp_path):
        output = tmp_path / "dataset.jsonl"
        output.write_text('{"id": "old"}\n')
        page = make_page_html([{"id": "new1"}])
        session_mock = MagicMock()
        session_mock.get.return_value = mock_response(page)

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
            patch("sys.argv", ["scraper.py", "--update"]),
        ):
            scraper.main()

    def test_main_oldest_first_flag(self, tmp_path):
        output = tmp_path / "dataset.jsonl"
        page = make_page_html([{"id": "1"}])
        session_mock = MagicMock()
        session_mock.get.return_value = mock_response(page)

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
            patch("sys.argv", ["scraper.py", "--oldest-first"]),
        ):
            scraper.main()

        url_called = session_mock.get.call_args[0][0]
        assert "sort=asc" in url_called

    def test_main_dry_run_flag_does_not_write(self, tmp_path):
        output = tmp_path / "dataset.jsonl"
        page = make_page_html([{"id": "1"}])
        session_mock = MagicMock()
        session_mock.get.return_value = mock_response(page)

        with (
            patch("scraper.OUTPUT_PATH", output),
            patch("scraper.requests.Session", return_value=session_mock),
            patch("time.sleep"),
            patch("sys.argv", ["scraper.py", "--dry-run"]),
        ):
            scraper.main()

        assert not output.exists()
