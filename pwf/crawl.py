"""Polite, resumable crawler for listing pages and report detail pages.

robots.txt permits everything on this host, so the concurrency and delay in
config.py are courtesy to a small club's server rather than a requirement.
Every response is cached gzipped in ``raw_pages`` so that re-parsing, rule
changes and re-analysis never cost another HTTP request.
"""
from __future__ import annotations

import asyncio
import gzip
import random
import sqlite3
from datetime import datetime

import httpx

from . import config as C
from .parse_index import max_report_id
from .parse_index import parse as parse_index
from .parse_report import is_missing


def _store(conn: sqlite3.Connection, url: str, kind: str, ref: str,
           status: int, html: str, missing: bool) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO raw_pages"
        " (url, kind, ref, http_status, is_missing, fetched_at, body)"
        " VALUES (?,?,?,?,?,?,?)",
        (url, kind, str(ref), status, int(missing),
         datetime.now().isoformat(timespec="seconds"),
         gzip.compress(html.encode("utf-8", "replace"))),
    )


def have(conn: sqlite3.Connection, kind: str | None = None) -> set[str]:
    q = "SELECT url FROM raw_pages"
    args: tuple = ()
    if kind:
        q += " WHERE kind=?"
        args = (kind,)
    return {r[0] for r in conn.execute(q, args)}


def load(conn: sqlite3.Connection, url: str) -> str | None:
    row = conn.execute("SELECT body FROM raw_pages WHERE url=?", (url,)).fetchone()
    if row is None or row[0] is None:
        return None
    return gzip.decompress(row[0]).decode("utf-8", "replace")


def iter_cached(conn: sqlite3.Connection, kind: str, include_missing: bool = False):
    q = "SELECT url, ref, body FROM raw_pages WHERE kind=?"
    if not include_missing:
        q += " AND is_missing=0"
    for url, ref, body in conn.execute(q, (kind,)):
        if body is None:
            continue
        yield url, ref, gzip.decompress(body).decode("utf-8", "replace")


async def _fetch(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> tuple[int, str]:
    """GET with retry/backoff. Returns (status, html); status 0 means gave up."""
    for attempt in range(C.MAX_RETRIES):
        async with sem:
            await asyncio.sleep(C.DELAY_SECONDS * (1 + random.random() * 0.5))
            try:
                r = await client.get(url)
            except (httpx.TimeoutException, httpx.TransportError):
                await asyncio.sleep(2 ** attempt)
                continue
        if r.status_code >= 500:
            await asyncio.sleep(2 ** attempt)
            continue
        return r.status_code, r.text
    return 0, ""


async def _run(conn, urls: list[tuple[str, str, str]], kind_label: str, progress) -> dict:
    """urls: list of (url, kind, ref)."""
    sem = asyncio.Semaphore(C.CONCURRENCY)
    stats = {"ok": 0, "missing": 0, "failed": 0}
    limits = httpx.Limits(max_connections=C.CONCURRENCY * 2)

    async with httpx.AsyncClient(
        headers={"User-Agent": C.USER_AGENT}, timeout=C.TIMEOUT,
        follow_redirects=True, limits=limits,
    ) as client:
        async def one(url, kind, ref):
            status, html = await _fetch(client, url, sem)
            if status == 0:
                stats["failed"] += 1
                return
            missing = kind == "report" and is_missing(html)
            stats["missing" if missing else "ok"] += 1
            _store(conn, url, kind, ref, status, html, missing)

        batch: list = []
        for i, (url, kind, ref) in enumerate(urls, 1):
            batch.append(one(url, kind, ref))
            if len(batch) >= 60:
                await asyncio.gather(*batch)
                conn.commit()
                batch = []
                progress(i, len(urls), stats, kind_label)
        if batch:
            await asyncio.gather(*batch)
            conn.commit()
        progress(len(urls), len(urls), stats, kind_label)

    # A run that mostly fails means something changed; surface it loudly.
    attempted = sum(stats.values())
    if attempted and stats["failed"] / attempted > 0.25:
        raise RuntimeError(
            f"{stats['failed']}/{attempted} requests failed - aborting rather "
            "than hammering the server. Check connectivity or the site layout."
        )
    return stats


def _default_progress(done, total, stats, label):
    pct = 100 * done / total if total else 100
    print(f"  [{label}] {done}/{total} ({pct:5.1f}%)  "
          f"ok={stats['ok']} missing={stats['missing']} failed={stats['failed']}",
          flush=True)


def crawl_index(conn, refresh: bool = False, limit: int | None = None,
                progress=_default_progress) -> dict:
    """Walk listing pages in blocks, stopping once a block yields no cards.

    The archive ends somewhere past offset 12,000; probing block by block avoids
    several hundred pointless requests past the end.
    """
    seen = set() if refresh else have(conn, "index")
    total = {"ok": 0, "missing": 0, "failed": 0}
    block, offset = 100, 0

    while offset <= 20000:
        urls = []
        for k in range(block):
            off = offset + k * C.INDEX_PAGE_SIZE
            urls.append((C.INDEX_URL.format(offset=off), "index", off))
            if limit and len(urls) >= limit:
                break

        todo = [u for u in urls if refresh or u[0] not in seen]
        if todo:
            stats = asyncio.run(_run(conn, todo, f"index@{offset}", progress))
            for k in total:
                total[k] += stats[k]

        # Stop when this whole block came back with no report cards.
        cards = 0
        for url, _kind, _ref in urls:
            html = load(conn, url)
            if html:
                cards += len(parse_index(html))
        if cards == 0:
            break

        offset += block * C.INDEX_PAGE_SIZE
        if limit:
            break

    return total


def discover_max_id(conn) -> int:
    """Highest report id seen anywhere in the cached index pages."""
    best = 0
    for _url, _ref, html in iter_cached(conn, "index"):
        m = max_report_id(html)
        if m:
            best = max(best, m)
    return best


def index_report_ids(conn) -> set[int]:
    ids: set[int] = set()
    for _url, _ref, html in iter_cached(conn, "index"):
        for row in parse_index(html):
            ids.add(row["report_id"])
    return ids


def crawl_reports(conn, max_id: int | None = None, refresh: bool = False,
                  limit: int | None = None, progress=_default_progress) -> dict:
    max_id = max_id or discover_max_id(conn)
    if not max_id:
        raise RuntimeError("No report ids found - run `pwf crawl --index` first.")
    seen = set() if refresh else have(conn, "report")
    urls = []
    for rid in range(2, max_id + 1):
        url = C.REPORT_URL.format(id=rid)
        if url in seen:
            continue
        urls.append((url, "report", rid))
        if limit and len(urls) >= limit:
            break
    if not urls:
        print("  [reports] nothing to do")
        return {"ok": 0, "missing": 0, "failed": 0}
    return asyncio.run(_run(conn, urls, "reports", progress))


def crawl_lakes(conn, slugs: list[str], refresh: bool = False,
                progress=_default_progress) -> dict:
    seen = set() if refresh else have(conn, "lake")
    urls = [(C.LAKE_URL.format(slug=s), "lake", s) for s in slugs]
    todo = [u for u in urls if u[0] not in seen]
    if not todo:
        print("  [lakes] nothing to do")
        return {"ok": 0, "missing": 0, "failed": 0}
    return asyncio.run(_run(conn, todo, "lakes", progress))
