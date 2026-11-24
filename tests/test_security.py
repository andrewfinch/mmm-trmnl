"""Regression checks for untrusted URLs and secret-safe error reporting."""

import datetime as dt
import unittest
from unittest import mock

import requests

from src.revivalhub_trmnl_sync import (
    POSTER_IMG_BASE, TMDB_IMG_BASE, Screening, _is_https_url,
    _poster_url_from_value, _verify_poster_url, build_trmnl_payload,
    fetch_payload, main,
)


class URLSecurityTests(unittest.TestCase):
    def test_rejects_unsafe_or_ambiguous_links(self):
        for url in (
            None, 42, "http://example.com/", "javascript:alert(1)",
            "https://user:password@example.com/", "https://example.com:8080/",
            "https://example.com:invalid/", "https://[invalid/",
            "https://example.com/\nsecret", 'https://example.com/" onerror="alert(1)',
            "https://example.com\\@localhost/",
        ):
            with self.subTest(url=url):
                self.assertFalse(_is_https_url(url))

    def test_allows_https_ticket_query_parameters(self):
        self.assertTrue(_is_https_url("https://tickets.example.com/show?id=123&time=7"))

    def test_blocks_untrusted_posters_without_making_requests(self):
        with mock.patch("src.revivalhub_trmnl_sync.requests.head") as head:
            for url in (
                "http://169.254.169.254/latest/meta-data/",
                "https://localhost/poster.jpg", "https://127.0.0.1/poster.jpg",
                "https://image.tmdb.org.attacker.example/t/p/w500/poster.jpg",
                "https://image.tmdb.org@attacker.example/t/p/w500/poster.jpg",
                POSTER_IMG_BASE + "/../other-bucket/poster.jpg",
                POSTER_IMG_BASE + "/%2e%2e/poster.jpg",
                POSTER_IMG_BASE + "/poster.jpg?redirect=https://localhost/",
            ):
                with self.subTest(url=url):
                    self.assertIsNone(_verify_poster_url(url))
                    self.assertIsNone(_poster_url_from_value(url))
            head.assert_not_called()

    def test_poster_redirect_is_not_followed_and_tmdb_fallback_works(self):
        bucket_url = POSTER_IMG_BASE + "/abc123_400x600.jpg"
        tmdb_url = TMDB_IMG_BASE + "/abc123.jpg"
        with mock.patch("src.revivalhub_trmnl_sync.requests.head") as head:
            head.side_effect = [mock.Mock(status_code=302), mock.Mock(status_code=200)]
            self.assertEqual(_verify_poster_url(bucket_url), tmdb_url)
            self.assertEqual(head.call_args_list, [
                mock.call(bucket_url, timeout=15, allow_redirects=False),
                mock.call(tmdb_url, timeout=15, allow_redirects=False),
            ])

    def test_payload_filters_urls_even_without_poster_verification(self):
        screening = Screening(
            theatre="Aero", title="Film", when=dt.datetime.now(dt.timezone.utc),
            timezone="UTC", poster_url="https://localhost/image.jpg",
            ticket_url="javascript:alert(1)",
        )
        payload = build_trmnl_payload(screening)
        self.assertIsNone(payload["poster_url"])
        self.assertIsNone(payload["ticket_url"])


class FeedSecurityTests(unittest.TestCase):
    def test_rejects_http_source_before_request(self):
        with mock.patch("src.revivalhub_trmnl_sync.requests.get") as get:
            with self.assertRaises(ValueError):
                fetch_payload("http://example.com/feed", "Aero", "UTC", 96, False)
            get.assert_not_called()

    def test_source_redirect_cannot_downgrade_https(self):
        with mock.patch("src.revivalhub_trmnl_sync.requests.get") as get:
            get.return_value.status_code = 302
            with self.assertRaises(ValueError):
                fetch_payload("https://example.com/feed", "Aero", "UTC", 96, False)
            get.assert_called_once_with(
                "https://example.com/feed", timeout=30, allow_redirects=False,
            )
            get.return_value.json.assert_not_called()

    def test_fetch_success_preserves_screening_payload(self):
        source = {
            "title": "The Searchers", "theatre": "Aero",
            "showtime": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(),
            "poster_url": TMDB_IMG_BASE + "/poster.jpg",
            "ticket_url": "https://tickets.example.com/the-searchers/",
        }
        with mock.patch("src.revivalhub_trmnl_sync.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = source
            payload = fetch_payload(
                "https://example.com/feed", "Aero", "UTC", 96, False,
                verify_poster=False,
            )
        self.assertEqual(payload["title"], "The Searchers")
        self.assertEqual(payload["poster_url"], source["poster_url"])
        self.assertEqual(payload["ticket_url"], source["ticket_url"])

    def test_failed_fetch_does_not_log_secret_url_or_write_payload(self):
        secret_url = "https://example.com/feed?token=private-token-value"
        for error in (requests.ConnectionError(secret_url), ValueError(secret_url)):
            with self.subTest(error=type(error).__name__):
                with mock.patch("src.revivalhub_trmnl_sync.requests.get", side_effect=error):
                    with mock.patch("src.revivalhub_trmnl_sync.Path.write_text") as write:
                        with self.assertLogs(level="DEBUG") as captured:
                            code = main([
                                "--revivalhub-url", secret_url, "--theatre", "Aero",
                                "--payload-path", "payload.json", "--verbose",
                            ])
                self.assertEqual(code, 1)
                write.assert_not_called()
                output = "\n".join(captured.output)
                self.assertNotIn(secret_url, output)
                self.assertNotIn("private-token-value", output)


if __name__ == "__main__":
    unittest.main()
