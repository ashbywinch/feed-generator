"""FR-1: Feedly OPML dual parser — exclusion blacklist + raw topic material."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class OPMLMissingError(FileNotFoundError):
    pass


def parse_opml(path: Path) -> tuple[set[str], list[dict[str, Any]]]:
    """Returns (known_domains, feeds).

    known_domains feeds the L1 blacklist; feeds (folder/title/url) are the
    topic-model seed material. URL-shaped category names are junk and never
    treated as topics. Fail fast: a missing/unparseable OPML aborts — the
    hardcoded fallback list from the reference code is rejected (it silently
    voids the zero-duplication guarantee).
    """
    if not path.exists():
        raise OPMLMissingError(f"OPML not found: {path} — export from https://feedly.com/i/opml")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise OPMLMissingError(f"unparseable OPML {path}: {exc}") from exc

    body = root.find("body")
    feeds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat in body.findall("outline") if body is not None else []:
        folder = cat.get("text") or cat.get("title") or "Uncategorized"
        if re.match(r"^https?://", folder):
            # Mis-imported subscription: the URL became a folder name. Its
            # feeds are STILL subscribed — keep them blacklisted, just don't
            # let the URL-shaped name become a topic hint.
            folder = "Uncategorized"
        for f in cat.findall(".//outline"):
            url = f.get("xmlUrl")
            if not url or url in seen:
                continue
            seen.add(url)
            feeds.append({"folder": folder, "title": f.get("title") or f.get("text") or url, "url": url})

    known_domains: set[str] = set()
    for f in feeds:
        host = urlparse(f["url"]).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        known_domains.add(host)
    return known_domains, feeds
