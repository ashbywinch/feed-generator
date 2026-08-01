"""OPML dual parser: blacklist completeness + fail-fast."""

from pathlib import Path

import pytest

from signalflow.opml import OPMLMissingError, parse_opml

OPML = """<?xml version="1.0"?>
<opml version="1.0"><head/><body>
<outline text="Tech">
  <outline text="A" xmlUrl="https://www.example.com/feed"/>
  <outline text="B" xmlUrl="https://www.Example.com/rss"/>
</outline>
<outline text="http://junk.url/feed">
  <outline text="J" xmlUrl="https://junk.url/rss"/>
</outline>
<outline text="Cats">
  <outline text="C" xmlUrl="https://blog.example.org/feed"/>
</outline>
</body></opml>"""


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "feedly.opml"
    p.write_text(OPML)
    return p


def test_blacklist_and_folder_extraction(tmp_path):
    domains, feeds = parse_opml(_write(tmp_path))
    # www stripped, hosts lowercased by the parser
    assert domains == {"example.com", "blog.example.org", "junk.url"}
    assert len(feeds) == 4


def test_hosts_are_lowercased(tmp_path):
    p = tmp_path / "feedly.opml"
    p.write_text(
        '<opml version="1.0"><body><outline text="A"><outline xmlUrl="https://WWW.Example.COM/rss"/></outline></body></opml>'
    )
    domains, _ = parse_opml(p)
    assert domains == {"example.com"}


def test_url_shaped_category_feeds_still_blacklisted(tmp_path):
    _, feeds = parse_opml(_write(tmp_path))
    junk = [f for f in feeds if f["url"] == "https://junk.url/rss"]
    assert junk and junk[0]["folder"] == "Uncategorized"  # no URL-shaped topic hint


def test_duplicate_feeds_collapsed(tmp_path):
    p = tmp_path / "feedly.opml"
    p.write_text(
        """<opml version="1.0"><body>
<outline text="A"><outline text="a" xmlUrl="https://x.example/feed"/></outline>
<outline text="B"><outline text="b" xmlUrl="https://x.example/feed"/></outline>
</body></opml>"""
    )
    domains, feeds = parse_opml(p)
    assert len(feeds) == 1
    assert domains == {"x.example"}


def test_missing_opml_fails_fast(tmp_path):
    with pytest.raises(OPMLMissingError):
        parse_opml(tmp_path / "nope.opml")


def test_unparseable_opml_fails_fast(tmp_path):
    p = tmp_path / "bad.opml"
    p.write_text("this is not xml")
    with pytest.raises(OPMLMissingError):
        parse_opml(p)
