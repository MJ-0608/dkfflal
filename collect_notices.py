#!/usr/bin/env python3
"""Bounded collector for Hyoseong school notices and family letters."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from bs4 import BeautifulSoup

BASE_URL = "https://in-hyoseong.icehs.kr"
SITE_SUFFIX = "in_hyoseong"
KST = timezone(timedelta(hours=9))
DEFAULT_OUTPUT = Path("notices.json")
DEFAULT_MAX_PAGES = 40
DEFAULT_TIMEOUT = 20.0
DELAY_SECONDS = 0.25

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 HyoseongNoticeCollector/1.0"
)

_DATE_RE = re.compile(r"^(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\.?$")
_SUBJECT_ID_RE = re.compile(r"^subject_(\d+)$")
_GOVIEW_RE = re.compile(r"goView\s*\((.*?)\)", re.S)
_QUOTED_ARG_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")
_PAGE_RE = re.compile(r"[?&]page=(\d+)")
_BLOCK_MARKERS = (
    "access denied",
    "access forbidden",
    "request blocked",
    "too many requests",
    "cloudflare",
    "captcha",
    "forbidden",
    "비정상적인 접근",
    "접근이 차단",
    "서비스 이용이 제한",
    "잘못된 접근",
)


@dataclass(frozen=True)
class Board:
    board_id: str
    category: str
    name: str
    menu: str
    list_url: str


@dataclass
class _PageResult:
    notices: list[dict[str, Any]]
    has_relevant_regular: bool
    has_more: bool


BOARDS: tuple[Board, ...] = (
    Board(
        board_id="3202",
        category="notice",
        name="공지사항",
        menu="0209",
        list_url=f"{BASE_URL}/boardCnts/list.do?boardID=3202&m=0209&s={SITE_SUFFIX}",
    ),
    Board(
        board_id="3215",
        category="letter",
        name="가정통신문",
        menu="0201",
        list_url=f"{BASE_URL}/boardCnts/list.do?boardID=3215&m=0201&s={SITE_SUFFIX}",
    ),
)


class CollectorError(Exception):
    """Base class for expected collector failures."""


class FetchError(CollectorError):
    """The remote board could not be fetched."""


class BlockedHTMLError(CollectorError):
    """The remote site returned a block or anti-bot page."""


class MalformedHTMLError(CollectorError):
    """The fetched page is not a recognizable board list."""


class PageCapExceeded(CollectorError):
    """The page cap was reached while earlier pages still pointed forward."""


def _now_kst() -> datetime:
    return datetime.now(KST)


def parse_date(value: str) -> date:
    match = _DATE_RE.match(value.strip())
    if not match:
        raise ValueError(f"unsupported date: {value!r}")
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def cutoff_for(today: date) -> date:
    """Return the same month/day one calendar year before today, inclusive."""
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        # Feb 29 in a leap year maps to Feb 28 in the previous common year.
        return date(today.year - 1, today.month, 28)


def _resolve_board(value: Board | Mapping[str, Any] | str) -> Board:
    if isinstance(value, Board):
        return value
    if isinstance(value, str):
        for board in BOARDS:
            if board.board_id == value:
                return board
        raise ValueError(f"unknown board: {value}")
    return Board(
        board_id=str(value["board_id"]),
        category=str(value["category"]),
        name=str(value["name"]),
        menu=str(value["menu"]),
        list_url=str(value.get("list_url") or ""),
    )


def build_list_url(board: Board, page: int) -> str:
    parts = [f"boardID={board.board_id}", f"m={board.menu}", f"s={SITE_SUFFIX}"]
    if page > 1:
        parts.append(f"page={page}")
    return f"{BASE_URL}/boardCnts/list.do?{'&'.join(parts)}"


def _default_menu(board_id: str) -> str:
    for board in BOARDS:
        if board.board_id == board_id:
            return board.menu
    return ""


def build_post_url(
    board_id: str,
    view_board_id: str,
    board_seq: str,
    lev: str,
    menu: str | None = None,
    status_yn: str = "W",
    page: str = "1",
    include_site_suffix: bool = True,
) -> str:
    parts = [
        f"boardID={board_id}",
        f"viewBoardID={view_board_id}",
        f"boardSeq={board_seq}",
        f"lev={lev}",
        "action=view",
        "searchType=S",
        f"statusYN={status_yn}",
        f"page={page}",
        f"m={menu or _default_menu(board_id)}",
    ]
    if include_site_suffix:
        parts.append(f"s={SITE_SUFFIX}")
    return f"{BASE_URL}/boardCnts/updateCnt.do?{'&'.join(parts)}"


def sources_document() -> list[dict[str, str]]:
    return [
        {
            "category": board.category,
            "board_id": board.board_id,
            "name": board.name,
            "url": board.list_url,
        }
        for board in BOARDS
    ]


def _looks_blocked(html: str) -> bool:
    lowered = html.casefold()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _go_view_args(onclick: str) -> list[str]:
    match = _GOVIEW_RE.search(onclick or "")
    if not match:
        return []
    raw = match.group(1)
    args = [
        quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
        for quoted in _QUOTED_ARG_RE.finditer(raw)
    ]
    if args:
        return args
    return [part.strip().strip("'\"") for part in raw.split(",") if part.strip()]


def _class_has(value: Any, needle: str) -> bool:
    if isinstance(value, (list, tuple, set)):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value)
    return needle in text.lower()


def _is_pinned(row: Any) -> bool:
    classes = row.get("class") or []
    if any("noti" in str(class_name).lower() for class_name in classes):
        return True
    number_cell = row.find("td", attrs={"data-table": "number"})
    if number_cell is not None:
        notice_mark = number_cell.find(
            "em", class_=lambda value: _class_has(value, "notice")
        )
        if notice_mark is not None:
            return True
    return False


def _extract_date(row: Any) -> str:
    date_cell = row.find("td", attrs={"data-table": "date"})
    if date_cell is None:
        date_cell = row.find("td", class_=lambda value: _class_has(value, "date"))
    if date_cell is None:
        raise MalformedHTMLError("notice row is missing its date cell")
    return date_cell.get_text(" ", strip=True)


def _extract_subject_anchor(row: Any) -> Any:
    subject_cell = row.find("td", attrs={"data-table": "subject"})
    search_root = subject_cell if subject_cell is not None else row
    anchor = search_root.find("a", id=_SUBJECT_ID_RE)
    if anchor is None and subject_cell is not None:
        raise MalformedHTMLError("notice row is missing its subject anchor")
    return anchor


def _has_more_pages(soup: BeautifulSoup, current_page: int) -> bool:
    pagination = soup.select_one(".pagination") or soup.select_one(".paging")
    anchors = pagination.find_all("a") if pagination is not None else soup.find_all("a")
    for anchor in anchors:
        classes = [str(item).lower() for item in (anchor.get("class") or [])]
        if "btn_next" in classes:
            return True
        href = anchor.get("href") or ""
        match = _PAGE_RE.search(href)
        if match and int(match.group(1)) > current_page:
            return True
    return False


def _parse_page(
    html: str,
    board: Board,
    cutoff_date: date,
    today: date,
    current_page: int = 1,
) -> _PageResult:
    if not isinstance(html, str) or not html.strip():
        raise MalformedHTMLError("empty HTML response")

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.bbsList")
    if table is None:
        if _looks_blocked(html):
            raise BlockedHTMLError("blocked HTML response")
        raise MalformedHTMLError("table.bbsList is missing")

    tbody = table.find("tbody")
    rows = (tbody if tbody is not None else table).find_all("tr", recursive=False)
    notices: list[dict[str, Any]] = []
    seen: set[str] = set()
    has_relevant_regular = False

    for row in rows:
        if row.find("th") is not None and row.find("td") is None:
            continue

        anchor = _extract_subject_anchor(row)
        if anchor is None:
            if row.find("td") is not None:
                raise MalformedHTMLError("notice row has no subject link")
            continue

        anchor_id = anchor.get("id") or ""
        id_match = _SUBJECT_ID_RE.match(anchor_id)
        onclick_args = _go_view_args(anchor.get("onclick") or "")
        seq = id_match.group(1) if id_match else (onclick_args[2] if len(onclick_args) > 2 else "")
        if not seq.isdigit():
            raise MalformedHTMLError("notice row has no usable subject ID")

        row_board_id = onclick_args[0] if onclick_args and onclick_args[0].isdigit() else board.board_id
        if row_board_id != board.board_id:
            raise MalformedHTMLError(
                f"board ID mismatch: expected {board.board_id}, found {row_board_id}"
            )
        view_board_id = (
            onclick_args[1] if len(onclick_args) > 1 and onclick_args[1].isdigit() else board.board_id
        )
        lev = onclick_args[3] if len(onclick_args) > 3 and onclick_args[3] else "0"
        status_yn = onclick_args[5] if len(onclick_args) > 5 and onclick_args[5] else "W"
        page_arg = onclick_args[6] if len(onclick_args) > 6 and onclick_args[6] else "1"
        menu_arg = onclick_args[9] if len(onclick_args) > 9 and onclick_args[9] else ""
        menu = menu_arg or board.menu

        title = (anchor.get("title") or "").strip()
        if not title:
            title = anchor.get_text(" ", strip=True)
        if not title:
            raise MalformedHTMLError("notice row has an empty title")

        try:
            post_date = parse_date(_extract_date(row))
        except ValueError as exc:
            raise MalformedHTMLError(f"invalid notice date: {exc}") from exc

        in_range = cutoff_date <= post_date <= today
        if in_range and not _is_pinned(row):
            has_relevant_regular = True
        if not in_range:
            continue

        notice_id = f"{board.board_id}:{seq}"
        if notice_id in seen:
            continue
        seen.add(notice_id)
        notices.append(
            {
                "id": notice_id,
                "board_id": board.board_id,
                "category": board.category,
                "title": title,
                "date": post_date.isoformat(),
                "url": build_post_url(
                    board.board_id,
                    view_board_id,
                    seq,
                    lev,
                    menu,
                    status_yn,
                    page_arg,
                    include_site_suffix=not menu_arg,
                ),
            }
        )

    return _PageResult(
        notices=notices,
        has_relevant_regular=has_relevant_regular,
        has_more=_has_more_pages(soup, current_page),
    )


def parse_notice_page(
    html: str,
    board: Board | Mapping[str, Any] | str,
    cutoff_date: date | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Parse one board page and return notices inside the inclusive cutoff."""
    resolved = _resolve_board(board)
    if today is None:
        today = _now_kst().date()
    if cutoff_date is None:
        cutoff_date = cutoff_for(today)
    return _parse_page(html, resolved, cutoff_date, today).notices


def fetch_html(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise FetchError(f"HTTP {status} for {url}")
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"network error for {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FetchError(f"timed out fetching {url}") from exc

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedHTMLError("HTML response is not valid UTF-8") from exc


def _invoke_fetch(fetch: Callable[..., str], url: str, timeout: float) -> str:
    try:
        return fetch(url, timeout)
    except TypeError:
        return fetch(url)


def _dedupe_and_sort(notices: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for notice in notices:
        notice_id = str(notice.get("id", ""))
        if notice_id in seen:
            continue
        seen.add(notice_id)
        unique.append(notice)
    unique.sort(key=lambda item: item.get("date", ""), reverse=True)
    return unique


def collect_board(
    board: Board | Mapping[str, Any] | str,
    cutoff_date: date,
    today: date,
    fetch: Callable[..., str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_pages: int = DEFAULT_MAX_PAGES,
    delay: float = DELAY_SECONDS,
) -> list[dict[str, Any]]:
    """Collect one board sequentially until it leaves the date window."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    resolved = _resolve_board(board)
    fetch_fn = fetch or fetch_html
    collected: list[dict[str, Any]] = []

    for page_number in range(1, max_pages + 1):
        if page_number > 1 and delay > 0:
            time.sleep(delay)
        url = build_list_url(resolved, page_number)
        try:
            html = _invoke_fetch(fetch_fn, url, timeout)
            result = _parse_page(html, resolved, cutoff_date, today, page_number)
        except (BlockedHTMLError, MalformedHTMLError, FetchError) as exc:
            raise exc.__class__(
                f"{resolved.name} ({resolved.board_id}) page {page_number}: {exc}"
            ) from exc
        except Exception as exc:
            raise FetchError(
                f"{resolved.name} ({resolved.board_id}) page {page_number}: {exc}"
            ) from exc

        collected.extend(result.notices)
        if not result.has_relevant_regular or not result.has_more:
            break
        if page_number == max_pages:
            raise PageCapExceeded(
                f"{resolved.name} ({resolved.board_id}) page cap exceeded "
                f"(max_pages={max_pages})"
            )

    return _dedupe_and_sort(collected)


def _load_previous(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if "updated_at" not in data or not isinstance(data.get("notices"), list):
        return None
    return data


def write_document_atomic(path: str | os.PathLike[str], document: Mapping[str, Any]) -> None:
    """Write JSON through a same-directory temporary file and atomic replace."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _timestamp(now: datetime) -> str:
    return now.astimezone(KST).isoformat(timespec="seconds")


def refresh_notices(
    output_path: str | os.PathLike[str] = DEFAULT_OUTPUT,
    fetch: Callable[..., str] | None = None,
    now: datetime | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout: float = DEFAULT_TIMEOUT,
    delay: float = DELAY_SECONDS,
) -> tuple[bool, dict[str, Any]]:
    """Refresh both boards atomically; retain the last good snapshot on failure."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    destination = Path(output_path)
    current = now or _now_kst()
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    current = current.astimezone(KST)
    attempted_at = _timestamp(current)
    today = current.date()
    cutoff_date = cutoff_for(today)
    previous = _load_previous(destination)
    fetch_fn = fetch or fetch_html

    try:
        notices: list[dict[str, Any]] = []
        for index, board in enumerate(BOARDS):
            if index > 0 and delay > 0:
                time.sleep(delay)
            notices.extend(
                collect_board(
                    board,
                    cutoff_date,
                    today,
                    fetch=fetch_fn,
                    timeout=timeout,
                    max_pages=max_pages,
                    delay=delay,
                )
            )
        document: dict[str, Any] = {
            "updated_at": attempted_at,
            "last_attempt_at": attempted_at,
            "status": "ok",
            "error": None,
            "sources": sources_document(),
            "notices": _dedupe_and_sort(notices),
        }
        write_document_atomic(destination, document)
        return True, document
    except Exception as exc:
        if previous is not None:
            notices = previous.get("notices") if isinstance(previous.get("notices"), list) else []
            updated_at = previous.get("updated_at")
        else:
            notices = []
            updated_at = None
        sources = sources_document()

        message = str(exc).strip() or exc.__class__.__name__
        if len(message) > 300:
            message = message[:297] + "..."
        document = {
            "updated_at": updated_at,
            "last_attempt_at": attempted_at,
            "status": "error",
            "error": message,
            "sources": sources,
            "notices": notices,
        }
        write_document_atomic(destination, document)
        return False, document


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Hyoseong school notices and family letters."
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="output JSON path")
    parser.add_argument(
        "--max-pages",
        type=_positive_int,
        default=DEFAULT_MAX_PAGES,
        help="maximum pages per board (default: 40)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT,
        help="request timeout in seconds (default: 20)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ok, document = refresh_notices(
            args.output,
            max_pages=args.max_pages,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"notice collection failed: {exc}", file=sys.stderr)
        return 1

    if not ok:
        print(f"notice collection failed: {document.get('error')}", file=sys.stderr)
        return 1

    print(f"collected {len(document['notices'])} notices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
