import json
import tempfile
import unittest
from datetime import date, datetime
from html import escape
from pathlib import Path
from unittest import mock

import collect_notices
from collect_notices import (
    BOARDS,
    KST,
    BlockedHTMLError,
    MalformedHTMLError,
    PageCapExceeded,
    build_post_url,
    collect_board,
    cutoff_for,
    parse_date,
    parse_notice_page,
    refresh_notices,
)


def row(seq, title, post_date, board_id="3202", pinned=False):
    row_class = ' class="noti_tit_a"' if pinned else ""
    number = '<em class="notice2">고정</em>' if pinned else seq
    return f"""
    <tr{row_class}>
      <td data-table="number">{number}</td>
      <td data-table="subject">
        <a id="subject_{seq}" href="#contents" title="{escape(title)}"
           onclick="javascript:goView('{board_id}','{board_id}','{seq}', '0', 'null', 'W', '1', 'N', '')">{escape(title)}</a>
      </td>
      <td data-table="write">작성자</td>
      <td data-table="date">{post_date}</td>
    </tr>
    """


def page(rows, board_id="3202", next_page=None):
    pagination = ""
    if next_page:
        menu = "0209" if board_id == "3202" else "0201"
        pagination = (
            '<div class="pagination"><span class="apage">1</span>'
            f'<a href="/boardCnts/list.do?type=main&page={next_page}&m={menu}'
            f'&searchType=S&s=in_hyoseong&boardID={board_id}">다음</a></div>'
        )
    return (
        "<!doctype html><html><body>"
        '<table class="bbsList"><tbody>'
        + "".join(rows)
        + "</tbody></table>"
        + pagination
        + "</body></html>"
    )


def board(board_id="3202"):
    return next(item for item in BOARDS if item.board_id == board_id)


EVIDENCE_DIR = (
    Path(__file__).resolve().parents[1]
    / ".superloopy"
    / "sessions"
    / "school-notices"
    / "evidence"
)


class ParseTests(unittest.TestCase):
    @unittest.skipUnless(EVIDENCE_DIR.is_dir(), "provided evidence HTML is absent")
    def test_provided_live_evidence_pages_parse(self):
        today = date(2026, 11, 5)
        cutoff = cutoff_for(today)
        expected = {
            "3202": (
                "34311516",
                "2026-11-04",
                "https://in-hyoseong.icehs.kr/boardCnts/updateCnt.do"
                "?boardID=3202&viewBoardID=3202&boardSeq=34311516&lev=0"
                "&action=view&searchType=S&statusYN=W&page=1"
                "&m=0209&s=in_hyoseong",
            ),
            "3215": (
                "34310558",
                "2026-11-03",
                "https://in-hyoseong.icehs.kr/boardCnts/updateCnt.do"
                "?boardID=3215&viewBoardID=3215&boardSeq=34310558&lev=0"
                "&action=view&searchType=S&statusYN=W&page=1"
                "&m=0201&s=in_hyoseong",
            ),
        }
        for board_id, (seq, post_date, expected_url) in expected.items():
            html = (EVIDENCE_DIR / f"board-{board_id}-page1.html").read_text(
                encoding="utf-8"
            )
            notices = parse_notice_page(html, board(board_id), cutoff, today)
            by_id = {notice["id"]: notice for notice in notices}
            self.assertIn(f"{board_id}:{seq}", by_id)
            self.assertEqual(by_id[f"{board_id}:{seq}"]["date"], post_date)
            self.assertEqual(by_id[f"{board_id}:{seq}"]["url"], expected_url)

    def test_parse_page_uses_subject_id_go_view_args_and_row_date(self):
        html = page(
            [
                row("30238698", "오래된 고정글", "2022-12-23", pinned=True),
                row("34311516", "2027학년도 입학설명회 안내", "2026-11-04"),
            ]
        )

        notices = parse_notice_page(
            html, board(), cutoff_date=date(2025, 11, 5), today=date(2026, 11, 5)
        )

        self.assertEqual(len(notices), 1)
        notice = notices[0]
        self.assertEqual(notice["id"], "3202:34311516")
        self.assertEqual(notice["board_id"], "3202")
        self.assertEqual(notice["category"], "notice")
        self.assertEqual(notice["title"], "2027학년도 입학설명회 안내")
        self.assertEqual(notice["date"], "2026-11-04")
        self.assertEqual(
            notice["url"],
            "https://in-hyoseong.icehs.kr/boardCnts/updateCnt.do"
            "?boardID=3202&viewBoardID=3202&boardSeq=34311516&lev=0"
            "&action=view&searchType=S&statusYN=W&page=1"
            "&m=0209&s=in_hyoseong",
        )

    def test_go_view_args_parses_double_quoted_arguments(self):
        args = collect_notices._go_view_args(
            'javascript:goView("3202","3202","34311516", "0", "null", "W", '
            '"1", "N", "")'
        )
        self.assertEqual(
            args,
            ["3202", "3202", "34311516", "0", "null", "W", "1", "N", ""],
        )

    def test_pinned_marker_and_class_date_fallback_are_recognized(self):
        html = """
        <html><body><table class="bbsList"><tbody>
          <tr>
            <td data-table="number"><em class="notice2">고정</em></td>
            <td data-table="subject">
              <a id="subject_34311516" href="#contents" title="최근 고정글"
                 onclick="goView('3202','3202','34311516','0','null','W','1','N','')">최근 고정글</a>
            </td>
            <td class="date">2026-11-04</td>
          </tr>
        </tbody></table></body></html>
        """
        result = collect_notices._parse_page(
            html, board(), date(2025, 11, 5), date(2026, 11, 5), 1
        )
        self.assertEqual([notice["id"] for notice in result.notices], ["3202:34311516"])
        self.assertFalse(result.has_relevant_regular)

    def test_cutoff_is_previous_calendar_year_same_month_day_inclusive(self):
        today = date(2026, 11, 5)
        cutoff = cutoff_for(today)
        self.assertEqual(cutoff, date(2025, 11, 5))

        html = page(
            [
                row("1", "cutoff day", "2025-11-05"),
                row("2", "day before", "2025-11-04"),
                row("3", "today", "2026-11-05"),
                row("4", "tomorrow", "2026-11-06"),
            ]
        )
        notices = parse_notice_page(html, board(), cutoff, today)

        self.assertEqual([notice["id"] for notice in notices], ["3202:1", "3202:3"])

    def test_cutoff_clamps_leap_day(self):
        self.assertEqual(cutoff_for(date(2028, 2, 29)), date(2027, 2, 28))

    def test_parse_date_accepts_common_source_formats(self):
        self.assertEqual(parse_date("2026-11-04"), date(2026, 11, 4))
        self.assertEqual(parse_date("2026.11.04"), date(2026, 11, 4))
        self.assertEqual(parse_date("2026/11/04"), date(2026, 11, 4))
        self.assertEqual(parse_date("2026. 11. 4."), date(2026, 11, 4))

    def test_parse_date_rejects_invalid_dates(self):
        with self.assertRaises(ValueError):
            parse_date("2026-02-30")
        with self.assertRaises(ValueError):
            parse_date("not a date")

    def test_malformed_html_without_bbslist_raises(self):
        with self.assertRaises(MalformedHTMLError):
            parse_notice_page(
                "<html><body><p>no table</p></body></html>",
                board(),
                date(2025, 11, 5),
                date(2026, 11, 5),
            )

    def test_blocked_html_raises_explicit_error(self):
        with self.assertRaises(BlockedHTMLError):
            parse_notice_page(
                "<html><body>Access Denied - 비정상적인 접근이 차단되었습니다.</body></html>",
                board(),
                date(2025, 11, 5),
                date(2026, 11, 5),
            )

    def test_build_post_url_is_https_individual_view_url(self):
        self.assertEqual(
            build_post_url("3215", "3215", "34310558", "0", "0201"),
            "https://in-hyoseong.icehs.kr/boardCnts/updateCnt.do"
            "?boardID=3215&viewBoardID=3215&boardSeq=34310558&lev=0"
            "&action=view&searchType=S&statusYN=W&page=1"
            "&m=0201&s=in_hyoseong",
        )


class CollectBoardTests(unittest.TestCase):
    def test_old_pinned_rows_do_not_stop_pagination(self):
        responses = {
            1: page(
                [
                    row("30238698", "오래된 고정글", "2022-12-23", pinned=True),
                    row("20", "page one recent", "2026-10-20"),
                ],
                next_page=2,
            ),
            2: page([row("19", "page two recent", "2025-11-05")]),
        }
        calls = []

        def fetch(url, timeout):
            calls.append((url, timeout))
            return responses[len(calls)]

        with mock.patch.object(collect_notices.time, "sleep") as sleep:
            notices = collect_board(
                board(),
                date(2025, 11, 5),
                date(2026, 11, 5),
                fetch=fetch,
                timeout=7,
                max_pages=40,
                delay=0.25,
            )

        self.assertEqual([notice["id"] for notice in notices], ["3202:20", "3202:19"])
        self.assertEqual(len(calls), 2)
        self.assertIn("page=2", calls[1][0])
        self.assertEqual(calls[0][1], 7)
        sleep.assert_called_once_with(0.25)

    def test_page_with_only_old_regular_rows_stops_even_with_next_link(self):
        html = page(
            [
                row("30238698", "오래된 고정글", "2022-12-23", pinned=True),
                row("1", "old regular", "2024-01-01"),
            ],
            next_page=2,
        )

        def fetch(url, timeout):
            return html

        with mock.patch.object(collect_notices.time, "sleep"):
            notices = collect_board(
                board(),
                date(2025, 11, 5),
                date(2026, 11, 5),
                fetch=fetch,
                max_pages=40,
            )

        self.assertEqual(notices, [])

    def test_duplicate_ids_across_pages_are_removed(self):
        responses = {
            1: page([row("10", "recent", "2026-10-20")], next_page=2),
            2: page([row("10", "recent duplicate", "2026-10-20")]),
        }
        calls = []

        def fetch(url, timeout):
            calls.append(url)
            return responses[len(calls)]

        with mock.patch.object(collect_notices.time, "sleep"):
            notices = collect_board(
                board(),
                date(2025, 11, 5),
                date(2026, 11, 5),
                fetch=fetch,
                max_pages=40,
            )

        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["title"], "recent")

    def test_page_cap_exceeded_raises_explicit_error(self):
        html = page([row("10", "recent", "2026-10-20")], next_page=2)

        def fetch(url, timeout):
            return html

        with mock.patch.object(collect_notices.time, "sleep"):
            with self.assertRaises(PageCapExceeded):
                collect_board(
                    board(),
                    date(2025, 11, 5),
                    date(2026, 11, 5),
                    fetch=fetch,
                    max_pages=1,
                )


class RefreshTests(unittest.TestCase):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=KST)

    def good_fetch(self, board_id, post_date="2026-11-04", seq=None):
        html = page(
            [row(seq or ("34311516" if board_id == "3202" else "34310558"), f"{board_id} title", post_date, board_id=board_id)],
            board_id=board_id,
        )
        return html

    def test_success_writes_parent_schema_sources_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "notices.json"

            def fetch(url, timeout):
                if "boardID=3215" in url:
                    return self.good_fetch("3215")
                return self.good_fetch("3202")

            with mock.patch.object(collect_notices.time, "sleep"):
                ok, document = refresh_notices(
                    output, fetch=fetch, now=self.now, max_pages=5, timeout=3
                )
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(ok)
        self.assertEqual(written, document)
        self.assertEqual(document["status"], "ok")
        self.assertIsNone(document["error"])
        self.assertEqual(document["updated_at"], "2026-11-05T12:00:00+09:00")
        self.assertEqual(document["last_attempt_at"], "2026-11-05T12:00:00+09:00")
        self.assertEqual(
            document["sources"],
            [
                {
                    "category": "notice",
                    "board_id": "3202",
                    "name": "공지사항",
                    "url": "https://in-hyoseong.icehs.kr/boardCnts/list.do?boardID=3202&m=0209&s=in_hyoseong",
                },
                {
                    "category": "letter",
                    "board_id": "3215",
                    "name": "가정통신문",
                    "url": "https://in-hyoseong.icehs.kr/boardCnts/list.do?boardID=3215&m=0201&s=in_hyoseong",
                },
            ],
        )
        self.assertEqual({notice["id"] for notice in document["notices"]}, {"3202:34311516", "3215:34310558"})

    def test_failure_preserves_previous_notices_and_updated_at(self):
        previous = {
            "updated_at": "2026-11-04T18:17:00+09:00",
            "last_attempt_at": "2026-11-04T18:17:00+09:00",
            "status": "ok",
            "error": None,
            "sources": [],
            "notices": [
                {
                    "id": "3202:1",
                    "board_id": "3202",
                    "category": "notice",
                    "title": "retained",
                    "date": "2026-11-04",
                    "url": "https://example.invalid/retained",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "notices.json"
            output.write_text(json.dumps(previous), encoding="utf-8")

            def fetch(url, timeout):
                if "boardID=3215" in url:
                    raise OSError("network down")
                return self.good_fetch("3202")

            with mock.patch.object(collect_notices.time, "sleep"):
                ok, document = refresh_notices(
                    output, fetch=fetch, now=self.now, max_pages=5, timeout=3
                )
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(ok)
        self.assertEqual(written, document)
        self.assertEqual(document["status"], "error")
        self.assertIn("network down", document["error"])
        self.assertEqual(document["updated_at"], previous["updated_at"])
        self.assertEqual(document["notices"], previous["notices"])
        self.assertEqual(document["last_attempt_at"], "2026-11-05T12:00:00+09:00")

    def test_initial_failure_writes_empty_error_document_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "notices.json"

            def fetch(url, timeout):
                raise OSError("network down")

            ok, document = refresh_notices(
                output, fetch=fetch, now=self.now, max_pages=5, timeout=3
            )
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(ok)
        self.assertEqual(written, document)
        self.assertEqual(document["status"], "error")
        self.assertIsNone(document["updated_at"])
        self.assertEqual(document["notices"], [])
        self.assertIsNotNone(document["error"])

    def test_corrupt_previous_file_does_not_break_failure_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "notices.json"
            output.write_text("{not json", encoding="utf-8")

            def fetch(url, timeout):
                raise OSError("network down")

            ok, document = refresh_notices(
                output, fetch=fetch, now=self.now, max_pages=5, timeout=3
            )
            written = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(ok)
        self.assertEqual(written, document)
        self.assertEqual(document["status"], "error")
        self.assertIsNone(document["updated_at"])
        self.assertEqual(document["notices"], [])


if __name__ == "__main__":
    unittest.main()
