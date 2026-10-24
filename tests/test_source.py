import json
from pathlib import Path
import unittest

from article_alerts.domain import SourceError
from article_alerts.http import HttpError, Response
from article_alerts.source import SinChewTagSource, article_from_link, parse_page
from tests.helpers import ScriptedHttp, article


BASE = "https://www.sinchew.com.my"


def page(*ids):
    return Response(json.dumps([{"title": f"新闻 {n}", "url": article(n).url} for n in ids]).encode())


class SourceTests(unittest.TestCase):
    def test_html_links_titles_tracking_and_duplicate_image_anchors(self):
        body = (Path(__file__).parent / "fixtures/tag-page.html").read_bytes()
        articles = parse_page(body, BASE)
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].title, "新诈骗警报 & 提醒")
        self.assertEqual(articles[0].id, "post:7990499")
        self.assertNotIn("?", articles[0].url)
        self.assertNotIn("#", articles[1].url)

    def test_json_list_and_wrapped_html(self):
        self.assertEqual(parse_page(page(10).body, BASE)[0].id, "post:10")
        html = '<a href="/?p=12">Title</a>'
        wrapped = json.dumps({"data": {"html": html}}).encode()
        self.assertEqual(parse_page(wrapped, BASE)[0].id, "post:12")

    def test_wordpress_style_title(self):
        value = [{"link": article(9).url, "title": {"rendered": "<b>Title</b> &amp; text"}}]
        self.assertEqual(parse_page(json.dumps(value).encode(), BASE)[0].title, "Title & text")

    def test_public_legacy_link_supported(self):
        self.assertIsNotNone(article_from_link("/20261024/test-story", "Title", BASE))

    def test_external_and_non_article_links_ignored(self):
        for url in ["https://evil.example/?p=5", "javascript:alert(1)", "/tag/诈骗", "http://www.sinchew.com.my/?p=5"]:
            with self.subTest(url=url):
                self.assertIsNone(article_from_link(url, "Title", BASE))

    def test_block_page_and_unknown_json_never_mean_no_news(self):
        for body in [b"<html>Access denied</html>", b'{"status":"blocked"}', b'{"data":null}', b'[{bad]', b'\xff']:
            with self.subTest(body=body):
                with self.assertRaises(SourceError):
                    parse_page(body, BASE)

    def test_first_page_empty_is_a_failure(self):
        source = SinChewTagSource(ScriptedHttp(Response(b"[]")))
        with self.assertRaises(SourceError):
            source.baseline()

    def test_403_is_explicit_and_contains_no_cookie_requirement(self):
        source = SinChewTagSource(ScriptedHttp(HttpError(403)))
        with self.assertRaisesRegex(SourceError, "HTTP 403"):
            source.baseline()

    def test_catchup_scans_beyond_first_page_and_pinned_old_item(self):
        http = ScriptedHttp(page(1, 5, 4), page(3, 2), page(2, 1))
        source = SinChewTagSource(http)
        found = source.discover({"post:1", "post:2"})
        self.assertEqual({a.id for a in found}, {"post:1", "post:2", "post:3", "post:4", "post:5"})
        self.assertEqual(len(http.calls), 3)
        self.assertIn("page=1", http.calls[0][1])
        self.assertNotIn("Cookie", http.calls[0][2])

    def test_known_frontier_stops_network_reads(self):
        http = ScriptedHttp(page(2, 1))
        SinChewTagSource(http).discover({"post:1", "post:2"})
        self.assertEqual(len(http.calls), 1)

    def test_empty_later_page_is_end_of_list(self):
        found = SinChewTagSource(ScriptedHttp(page(3, 2), Response(b"[]"))).discover({"post:1"})
        self.assertEqual(len(found), 2)

    def test_pagination_cap_does_not_silently_truncate(self):
        source = SinChewTagSource(ScriptedHttp(page(5), page(4)), max_pages=2)
        with self.assertRaisesRegex(SourceError, "max_pages"):
            source.discover({"post:1"})

    def test_repeated_page_is_failure(self):
        source = SinChewTagSource(ScriptedHttp(page(5, 4), page(5, 4)))
        with self.assertRaisesRegex(SourceError, "repeated"):
            source.discover({"post:1"})

    def test_identity_is_stable_but_changes_with_tag(self):
        http = ScriptedHttp()
        self.assertEqual(SinChewTagSource(http).identity, SinChewTagSource(http).identity)
        self.assertNotEqual(SinChewTagSource(http).identity, SinChewTagSource(http, tag_id=999).identity)
