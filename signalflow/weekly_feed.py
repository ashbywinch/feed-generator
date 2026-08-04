"""Per-topic weekly RSS feeds (FR-9 digest, per topic) + topic background pages.

Each topic's feed entry renders OUR selection verdict, not the article:
  - description: the why-it-matters summary (the pick's `reason`; falls back
    to the observed event, then the thesis) — what the reader needs to know
    before clicking.
  - content: that summary, then a link to the topic's long-read background
    page (the area story), then a clickable preview snippet of the article
    (the item's own summary, truncated) linking to the original.
Entry id = the article URL (Feedly de-dupes on id), pubDate = pick time.

Pure rendering — no network, no LLM. The spike CLI (spikes/build_feeds.py)
wires paths; this module only knows layouts it is told.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from feedgen.feed import FeedGenerator

SNIPPET_LIMIT = 400  # preview snippet cap (chars); the clickable article preview

RADAR_SVG = (
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M2 12a10 10 0 0 1 20 0"/><path d="M6 12a6 6 0 0 1 12 0"/>'
    '<path d="M10 12a2 2 0 0 1 4 0"/><circle cx="12" cy="12" r=".5" fill="currentColor" stroke="none"/>'
    "</svg>"
)

# SVG favicon data URI (URL-encoded; raw <>/# in href breaks parsing)
FAVICON_URI = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23000'"
    "%20stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpath d='M2 12a10 10 0 0 1 20 0'/%3E%3Cpath d='M6 12a6 6 0 0 1 12 0'/%3E"
    "%3Cpath d='M10 12a2 2 0 0 1 4 0'/%3E%3Ccircle cx='12' cy='12' r='.5' fill='%23000' stroke='none'/%3E"
    "%3C/svg%3E"
)

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """Tags removed, whitespace collapsed — the plain text of an item summary."""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text or "")).strip()


def _format_date(iso: str | None) -> str:
    """ISO datetime -> compact human date like 'Aug 3, 2026' or '—' if absent."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return "—"
    return dt.strftime("%b %-d, %Y")


def why_summary(pick: dict[str, Any]) -> str:
    """Our summary of why the article is important: reason, else event, else thesis."""
    for key in ("reason", "empirical_event", "thesis"):
        value = pick.get(key)
        if value:
            return str(value)
    return ""


def snippet_text(summary: str, limit: int = SNIPPET_LIMIT) -> str:
    """Plain-text preview: strip HTML, truncate at a word boundary."""
    text = strip_html(summary)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def load_snippet_map(feeds_path: Path) -> dict[str, str]:
    """url -> latest item summary from the shared feed cache (weekly_feeds.jsonl).

    Latest line per crawl_root wins; items without a summary are skipped.
    """
    out: dict[str, str] = {}
    if not feeds_path.exists():
        return out
    for line in feeds_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            print(f"      WARNING: {feeds_path.name}: skipping corrupt line: {line[:60]!r}")
            continue
        for item in entry.get("items") or []:
            summary = item.get("summary")
            if summary and item.get("url"):
                out[item["url"]] = str(summary)
    return out


def pick_snippet(pick: dict[str, Any], snippet_map: dict[str, str], limit: int = SNIPPET_LIMIT) -> str:
    """The clickable preview text: the article's own summary, else its title."""
    summary = snippet_map.get(pick["url"])
    if summary:
        return snippet_text(summary, limit=limit)
    return snippet_text(pick.get("title", ""), limit=limit)


def _pub_date(pick: dict[str, Any]) -> datetime | None:
    raw = pick.get("picked_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _entry_body(pick: dict[str, Any], topic_name: str, story_url: str, snippet: str) -> str:
    esc = html.escape
    summary = esc(why_summary(pick))
    return (
        f"<p>{summary}</p>"
        f'<p><a href="{esc(story_url)}">Topic background: {esc(topic_name)} &rarr;</a></p>'
        f'<p><a href="{esc(pick["url"])}">{esc(snippet)}</a></p>'
    )


def build_topic_feed(
    *,
    slug: str,
    topic_name: str,
    picks: list[dict[str, Any]],
    story: dict[str, Any],
    feed_url: str,
    story_url: str,
    out_path: Path,
    snippet_map: dict[str, str] | None = None,
) -> int:
    """Build one topic's RSS feed from its picks. Returns the entry count.

    story is only used for its existence/recency here (the long-read link is
    story_url); the page itself is rendered by render_story_html.
    """
    del slug, story  # metadata only; feed identity is feed_url
    snippets = snippet_map if snippet_map is not None else {}
    fg = FeedGenerator()
    fg.id(feed_url)
    fg.title(f"SignalFlow — {topic_name}")
    fg.link(href=story_url, rel="alternate")
    fg.description(f"Weekly curated selection for {topic_name} — why each article matters.")

    for pick in picks:
        fe = fg.add_entry()
        fe.id(pick["url"])  # stable source URL: Feedly de-dupes on id
        fe.title(pick.get("title", ""))
        fe.link(href=pick["url"])
        fe.description(why_summary(pick))
        fe.content(
            _entry_body(pick, topic_name, story_url, pick_snippet(pick, snippets)),
            type="CDATA",
        )
        pub = _pub_date(pick)
        if pub is not None:
            fe.pubDate(pub)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    fg.rss_file(str(tmp), pretty=True)
    tmp.replace(out_path)  # atomic: a failed build never publishes a partial feed
    return len(picks)


# --- topic background page --------------------------------------------------


_STORY_CSS = (
    "<style>"
    "body{font-family:system-ui,-apple-system,sans-serif;max-width:46rem;margin:2rem auto;"
    "padding:0 1rem;line-height:1.55;color:#1a1a1a}"
    "h1{font-size:1.6rem} h2{margin-top:2rem;font-size:1.15rem} "
    "li{margin:.35rem 0} .meta{color:#666;font-size:.85rem}"
    "</style>"
)


def render_story_html(story: dict[str, Any], topic_name: str) -> str:
    """Standalone HTML page for the topic background long read (the area story)."""
    esc = html.escape
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>{esc(topic_name)} — SignalFlow topic background</title>",
        _STORY_CSS,
        "</head><body>",
        f"<h1>{esc(topic_name)}</h1>",
        f"<p class='meta'>Version {story.get('version', 0)} · updated {esc(str(story.get('updated_at', ''))[:10])}</p>",
    ]
    overview = story.get("overview", "")
    if overview:
        parts.append("<h2>Overview</h2>")
        for para in str(overview).split("\n\n"):
            if para.strip():
                parts.append(f"<p>{esc(para)}</p>")
    angles = story.get("angles", {})
    if isinstance(angles, dict) and angles:
        parts.append("<h2>Subareas</h2>")
        for subarea in sorted(angles):
            items = angles[subarea]
            if not isinstance(items, list):
                continue  # corrupt section: skip rendering, eval gates flag it
            parts.append(f"<h3>{esc(str(subarea))}</h3><ul>")
            parts.extend(f"<li>{esc(str(a))}</li>" for a in items)
            parts.append("</ul>")
    questions = story.get("open_questions", [])
    if questions:
        parts.append("<h2>Open questions</h2><ul>")
        parts.extend(f"<li>{esc(str(q))}</li>" for q in questions)
        parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)


# --- site builder -----------------------------------------------------------


def _site_urls(base_url: str, slug: str) -> tuple[str, str]:
    root = base_url.rstrip("/")
    return f"{root}/feeds/{slug}.xml", f"{root}/topics/{slug}/"


def render_index(
    *,
    picks_dir: Path,
    stories_dir: Path,
    site_dir: Path,
    base_url: str,
    built_topics: list[tuple[str, int]],
) -> str:
    """Render the site's landing page (index.html) — blog-like topic cards.

    Each topic with picks + a story gets a card: the story overview as a
    blurb, the latest picks with why-relevant notes, and links to the
    background page and RSS feed. The page includes a toolbar with a home
    icon and a login/user-dropdown area populated by JS.
    """
    esc = html.escape
    cards: list[str] = []
    for slug, _count in built_topics:
        picks_path = picks_dir / f"{slug}.json"
        story_path = stories_dir / f"{slug}.json"
        try:
            payload = json.loads(picks_path.read_text(encoding="utf-8"))
            story = json.loads(story_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        topic_name = str(payload.get("topic") or slug)
        picks = payload.get("picks") or []
        blurb = (story.get("overview") or "")[:400]
        if len(blurb) >= 400:
            last_space = blurb.rfind(" ")
            blurb = blurb[:last_space] + " …" if last_space > 300 else blurb + " …"
        feed_url, story_url = _site_urls(base_url, slug)
        pick_items = "".join(
            f'<li><a class="pick-title" href="{esc(p.get("url", ""))}">'
            f"{esc(p.get('title', ''))}</a>"
            f'<span class="pick-source"> — {esc(p.get("source") or p.get("domain") or "")}'
            f" ({_format_date(p.get('published'))})</span>"
            f'<p class="pick-reason">{esc(p.get("reason", ""))}</p></li>'
            for p in picks[:5]
            if p.get("url")
        )
        cards.append(
            f"<article>"
            f"<hgroup><h2>{esc(topic_name)}</h2>"
            f'<p class="topic-blurb">{esc(blurb)}</p></hgroup>'
            f'<div class="topic-links">'
            f'<a href="{esc(story_url)}">Read the background →</a>'
            f'<a href="{esc(feed_url)}">RSS feed →</a>'
            f"</div>"
            f"<ul>{pick_items}</ul>"
            f"</article>"
        )
    cards_html = "\n".join(cards) if cards else "<p>No topics yet — the nightly pipeline hasn't run.</p>"
    tooltip_js = (
        "<script>"
        "(async function(){"
        "const r=await fetch('/admin/auth/status');"
        "const d=await r.json();"
        "const a=document.getElementById('login-area');"
        "if(d.logged_in){"
        "a.innerHTML='<details class=dropdown><summary>'+"
        "d.email.replace(/&/g,'&amp;').replace(/</g,'&lt;')+' ▾</summary>"
        '<ul><li><a href="/admin/">Admin</a></li>'
        '<li><a href="/admin/auth/logout">Logout</a></li></ul></details>'
        "}else{"
        "a.innerHTML='<a href=\"/admin/auth/login\">Login</a>'"
        "}})()</script>"
    )
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>SignalFlow — Outside Discovery</title>"
        f'<link rel="icon" href="{FAVICON_URI}">'
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">'
        "<style>"
        "body>header nav{display:flex;align-items:center;justify-content:space-between}"
        "body>header nav svg{display:block;vertical-align:middle}"
        "body>header nav a[aria-label=Home]{font-size:1.3rem;text-decoration:none;line-height:0}"
        "#login-area{display:flex;align-items:center;gap:.5rem}"
        "#login-area details[open] ul{position:absolute;right:0;min-width:10rem;"
        "background:var(--pico-card-background-color);"
        "border:1px solid var(--pico-muted-border-color);"
        "border-radius:var(--pico-border-radius);padding:.25rem 0;z-index:10}"
        "#login-area details[open] ul li{padding:0;margin:0}"
        "#login-area details[open] ul li a{display:block;padding:.35rem .75rem;text-decoration:none}"
        "main article{margin-bottom:2rem}"
        ".topic-links{display:flex;gap:1rem;font-size:.85rem;margin:.5rem 0 1rem}"
        "article .pick-reason{color:var(--pico-muted-color);font-size:.9rem;margin:.1rem 0 0}"
        "article .pick-source{color:var(--pico-muted-color);font-size:.8rem}"
        "article .pick-title{font-weight:600}"
        "article ul{list-style:none;padding:0;margin-top:.5rem}"
        "article ul li{margin-bottom:1rem;padding-bottom:.5rem;border-bottom:1px solid var(--pico-muted-border-color)}"
        "article ul li:last-child{border-bottom:none}"
        "</style></head><body>"
        '<header><nav class="container">'
        f'<a href="/" aria-label="Home">{RADAR_SVG}</a>'
        '<div id="login-area"><a href="/admin/auth/login">Login</a></div>'
        "</nav></header>"
        '<main class="container"><h1>SignalFlow</h1>'
        '<p class="site-subtitle">Outside discovery — weekly curated commentary from the frontiers.</p>'
        f"{cards_html}</main>"
        "<footer class='container'><p>Powered by SignalFlow · "
        '<a href="/admin/">Admin</a></p></footer>'
        f"{tooltip_js}</body></html>"
    )


def build_site(
    *,
    picks_dir: Path,
    stories_dir: Path,
    feeds_path: Path,
    site_dir: Path,
    base_url: str,
) -> list[tuple[str, int]]:
    """Build every topic's feed + background page into the static site layout.

    Iterates the per-topic picks files (spikes/state/picks/{slug}.json); a
    topic is built only when it has BOTH picks (non-empty) and a story — the
    feed body links the story page, so a missing story means no feed. Returns
    [(slug, entry_count)] for the topics built.
    """
    snippets = load_snippet_map(feeds_path)
    built: list[tuple[str, int]] = []
    for picks_path in sorted(picks_dir.glob("*.json")):
        try:
            payload = json.loads(picks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"      WARNING: {picks_path.name}: corrupt picks file skipped ({exc})")
            continue  # corrupt picks: skip, the runner will regenerate
        if not isinstance(payload, dict):
            print(f"      WARNING: {picks_path.name}: unexpected payload shape — skipped")
            continue
        slug = str(payload.get("slug") or picks_path.stem)
        topic_name = str(payload.get("topic") or slug)
        picks = payload.get("picks") or []
        if not picks:
            continue  # a quiet week yields no feed (an empty feed helps no one)
        story_path = stories_dir / f"{slug}.json"
        if not story_path.exists():
            print(f"      WARNING: {slug} has {len(picks)} picks but no story file — feed skipped (state error)")
            continue  # no background long read -> the feed body would dangle
        try:
            story = json.loads(story_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"      WARNING: {story_path.name}: corrupt story file skipped ({exc})")
            continue
        if not isinstance(story, dict):
            print(f"      WARNING: {story_path.name}: unexpected payload shape — skipped")
            continue
        feed_url, story_url = _site_urls(base_url, slug)
        feed_out = site_dir / "feeds" / f"{slug}.xml"
        page_out = site_dir / "topics" / slug / "index.html"
        n = build_topic_feed(
            slug=slug,
            topic_name=topic_name,
            picks=picks,
            story=story,
            feed_url=feed_url,
            story_url=story_url,
            out_path=feed_out,
            snippet_map=snippets,
        )
        page_out.parent.mkdir(parents=True, exist_ok=True)
        page_tmp = page_out.with_suffix(".html.tmp")
        page_tmp.write_text(render_story_html(story, topic_name), encoding="utf-8")
        page_tmp.replace(page_out)  # atomic, same as the feed: never publish a truncated page
        built.append((slug, n))

    # Render the landing page index.html from the topics just built
    index_html = render_index(
        picks_dir=picks_dir,
        stories_dir=stories_dir,
        site_dir=site_dir,
        base_url=base_url,
        built_topics=built,
    )
    index_out = site_dir / "index.html"
    site_dir.mkdir(parents=True, exist_ok=True)
    index_tmp = index_out.with_suffix(".html.tmp")
    index_tmp.write_text(index_html, encoding="utf-8")
    index_tmp.replace(index_out)
    print(f"      index -> site/index.html ({len(built)} topics)")
    return built
