"""Sin Chew tag-list adapter. It never needs login cookies or article bodies."""

from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit

from .domain import Article, SourceError
from .http import HttpClient, HttpError, NetworkError


def article_from_link(url: str, title: str, base_url: str) -> Article | None:
    absolute = urlsplit(urljoin(base_url, unescape(url)))
    expected_host = urlsplit(base_url).hostname
    if absolute.scheme != "https" or absolute.hostname != expected_host or absolute.username:
        return None
    path = absolute.path
    # Modern and legacy public article URL forms. Ignore navigation, ads and JS.
    modern = re.search(r"/news/\d{8}/[^/]+/(\d+)(?:/|$)", path)
    legacy = re.match(r"/\d{8}/[^/]+/?$", path)
    query_id = parse_qs(absolute.query).get("p", [""])[0]
    if modern:
        identity = "post:" + modern.group(1)
        query = ""
    elif query_id.isdigit():
        identity = "post:" + query_id
        path, query = "/", "p=" + query_id
    elif legacy:
        identity = "url:" + path.rstrip("/")
        query = ""
    else:
        return None
    title = " ".join(unescape(title).split())
    if not title:
        return None
    canonical = urlunsplit(("https", absolute.netloc, path, query, ""))
    return Article(identity, title[:1500], canonical)


class _ArticleLinks(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[Article] = []
        self.current = None
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip_depth += 1
        if tag == "a":
            if self.current:
                self._finish()
            self.current = {"url": attrs.get("href", ""), "title": attrs.get("title", ""), "text": [], "alt": ""}
        elif self.current and tag == "img" and attrs.get("alt"):
            self.current["alt"] = attrs["alt"]

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "a" and self.current:
            self._finish()

    def handle_data(self, data):
        if self.current and not self.skip_depth:
            self.current["text"].append(data)

    def _finish(self):
        item = self.current
        title = item["title"] or " ".join(item["text"]).strip() or item["alt"]
        article = article_from_link(item["url"], title, self.base_url)
        if article:
            self.links.append(article)
        self.current = None

    def close(self):
        super().close()
        if self.current:
            self._finish()


def _extract_json(value, base_url: str) -> list[Article]:
    if value is None:
        raise SourceError("Unexpected null tag response; site format may have changed.")
    if isinstance(value, str):
        return _extract_html(value, base_url)
    if isinstance(value, list):
        articles = []
        for item in value:
            articles.extend(_extract_json(item, base_url))
        return articles
    if isinstance(value, dict):
        url = value.get("url") or value.get("link") or value.get("permalink")
        title = value.get("title")
        if isinstance(title, dict):
            title = title.get("rendered")
        if isinstance(url, str) and isinstance(title, str):
            article = article_from_link(url, re.sub(r"<[^>]*>", "", title), base_url)
            if not article:
                raise SourceError("Tag response contained an invalid article link.")
            return [article]
        for key in ("html", "data", "posts", "content", "result"):
            if key in value:
                return _extract_json(value[key], base_url)
    raise SourceError("Unrecognized tag response; inspect the source format before changing the parser.")


def _extract_html(content: str, base_url: str) -> list[Article]:
    if not content.strip():
        return []
    parser = _ArticleLinks(base_url)
    parser.feed(content)
    parser.close()
    if not parser.links:
        raise SourceError("No article links found in a nonempty response; possible block page or site change.")
    return parser.links


def parse_page(body: bytes, base_url: str) -> list[Article]:
    try:
        content = body.decode("utf-8-sig")
        if content.lstrip().startswith(("{", "[", '"')):
            articles = _extract_json(json.loads(content), base_url)
        else:
            articles = _extract_html(content, base_url)
        # Image and headline anchors may link to the same article.
        by_id = {}
        for article in articles:
            if article.id not in by_id or len(article.title) > len(by_id[article.id].title):
                by_id[article.id] = article
        return list(by_id.values())
    except (ValueError, UnicodeError, RecursionError):
        raise SourceError("Tag response is not valid UTF-8, JSON or article HTML.") from None


class SinChewTagSource:
    def __init__(self, http: HttpClient, *, tag_id: int = 1495,
                 base_url: str = "https://www.sinchew.com.my", max_pages: int = 20,
                 baseline_pages: int = 2):
        self.http, self.tag_id, self.base_url = http, tag_id, base_url.rstrip("/")
        self.max_pages, self.baseline_pages = max_pages, baseline_pages

    @property
    def identity(self) -> str:
        return hashlib.sha256(f"sinchew-tag-v1:{self.base_url}:{self.tag_id}".encode()).hexdigest()

    def _page(self, number: int) -> list[Article]:
        endpoint = f"{self.base_url}/ajx-api/tag_posts/?cat={self.tag_id}&page={number}"
        try:
            response = self.http.request("GET", quote(endpoint, safe=":/?=&%"), headers={
                "User-Agent": "PersonalArticleAlerts/1.0", "Accept": "application/json,text/html",
                "Referer": self.base_url + "/",
            })
        except HttpError as exc:
            raise SourceError(f"Sin Chew returned HTTP {exc.status}. No login cookies are used; diagnose site access.") from None
        except NetworkError:
            raise SourceError("Sin Chew could not be reached after bounded retries.") from None
        articles = parse_page(response.body, self.base_url)
        if number == 1 and not articles:
            raise SourceError("The latest tag page is empty; refusing to treat this as a healthy check.")
        return articles

    def baseline(self) -> list[Article]:
        result = {}
        for number in range(1, self.baseline_pages + 1):
            page = self._page(number)
            if not page:
                break
            for article in page:
                result.setdefault(article.id, article)
        return list(result.values())

    def discover(self, known_ids: set[str]) -> list[Article]:
        discovered = {}
        page_signatures = set()
        for number in range(1, self.max_pages + 1):
            articles = self._page(number)
            if not articles:
                return list(discovered.values())
            signature = tuple(a.id for a in articles)
            if signature in page_signatures:
                raise SourceError("Pagination repeated a page; refusing to silently skip a backlog.")
            page_signatures.add(signature)
            for article in articles:
                discovered.setdefault(article.id, article)
            # A fully known page avoids treating one pinned old article as the frontier.
            if all(article.id in known_ids for article in articles):
                return list(discovered.values())
        raise SourceError("Backlog exceeds max_pages. Increase it and rerun; delivery history is preserved.")
