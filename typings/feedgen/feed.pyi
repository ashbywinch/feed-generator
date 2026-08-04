"""Minimal type stubs for feedgen (no published types).

Covers the surface the project uses: digest.py (FR-7) and weekly_feed.py
(per-topic feeds) — FeedGenerator metadata, entries, and rss_file output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

class FeedEntry:
    def id(self, id: str | None = None) -> str | None: ...
    def title(self, title: str | None = None) -> str | None: ...
    def link(self, href: str | None = None, rel: str = "alternate", **kwargs: Any) -> list[Any] | None: ...
    def description(self, description: str | None = None, isSummary: bool = False) -> str | None: ...  # noqa: N803
    def content(  # noqa: N803
        self, content: str | None = None, src: str | None = None, type: str | None = None
    ) -> dict[str, Any] | None: ...
    def pubDate(self, pubDate: datetime | None = None) -> datetime | None: ...  # noqa: N802,N803

class FeedGenerator:
    def id(self, id: str | None = None) -> str | None: ...
    def title(self, title: str | None = None) -> str | None: ...
    def author(self, author: dict[str, str] | None = None, **kwargs: Any) -> None: ...
    def link(self, href: str | None = None, rel: str = "alternate", **kwargs: Any) -> list[Any] | None: ...
    def description(self, description: str | None = None) -> str | None: ...
    def add_entry(self, feedEntry: FeedEntry | None = None, order: str = "prepend") -> FeedEntry: ...  # noqa: N803
    def rss_file(
        self,
        filename: Any,
        extensions: bool = True,
        pretty: bool = False,
        encoding: str = "UTF-8",
        xml_declaration: bool = True,
    ) -> None: ...
