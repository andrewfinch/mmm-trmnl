import datetime as dt
import unittest
from unittest import mock

from src.revivalhub_trmnl_sync import (
    POSTER_IMG_BASE,
    TMDB_IMG_BASE,
    _tmdb_fallback_url,
    _verify_poster_url,
    find_next_screening,
)


def _source(screening_overrides=None, films=None):
    showtime = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    screening = {
        "venue": "receaYS3GjcnaPXRk",
        "screening_times": [showtime.isoformat()],
        "films": [{"name": "The Searchers", "tmdb_id": 3114}],
        "ticket_urls": [
            "https://www.americancinematheque.com/now-showing/the-searchers/"
        ],
    }
    screening.update(screening_overrides or {})
    return {
        "venues": [{"id": "receaYS3GjcnaPXRk", "name": "Aero Theatre"}],
        "films": films
        if films is not None
        else [
            {
                "tmdbId": "3114",
                "title": "The Searchers",
                "posterPath": "jLBmgW0epNzJ1N9uzaVCjbyT94v.jpg",
            }
        ],
        "screenings": [screening],
    }


def _find(source):
    return find_next_screening(
        source=source,
        theatre="Aero Theatre",
        timezone="America/Los_Angeles",
        lookahead_hours=2,
    )


class FindNextScreeningTests(unittest.TestCase):
    def test_uses_top_level_film_catalog_poster_when_screening_has_tmdb_id_only(self):
        screening = _find(_source())

        self.assertIsNotNone(screening)
        self.assertEqual(screening.title, "The Searchers")
        self.assertEqual(
            screening.poster_url,
            f"{POSTER_IMG_BASE}/jLBmgW0epNzJ1N9uzaVCjbyT94v_400x600.jpg",
        )

    def test_overrides_mislinked_film_using_ticket_slug(self):
        # Real-world case: the Aero's "Babylon in 70mm" screening was linked to
        # a 2022 Korean film also titled "Boogie Nights". The slug plus the
        # entry's directors/year should re-resolve to Chazelle's Babylon, not
        # the 1980 Franco Rosso Babylon.
        source = _source(
            screening_overrides={
                "films": [
                    {
                        "name": "Boogie Nights",
                        "year": 2022,
                        "directors": "Damien Chazelle",
                        "tmdb_id": 940164,
                    }
                ],
                "ticket_urls": [
                    "https://www.americancinematheque.com/now-showing/babylon-in-70mm-07-08-2026/"
                ],
            },
            films=[
                {
                    "tmdbId": "940164",
                    "title": "Boogie Nights",
                    "releaseDate": "2022-04-28",
                    "directors": "Kim Gyeong-yeop",
                    "posterPath": "tqWggxBF0vlVqHXMnqJeZXOU6WE.jpg",
                },
                {
                    "tmdbId": "57082",
                    "title": "Babylon",
                    "releaseDate": "1980-11-07",
                    "directors": "Franco Rosso",
                    "posterPath": "sbh5cwdoZ5TPE4JDO0Z7HGLa4IX.jpg",
                },
                {
                    "tmdbId": "615777",
                    "title": "Babylon",
                    "releaseDate": "2022-12-22",
                    "directors": "Damien Chazelle",
                    "posterPath": "wjOHjWCUE0YzDiEzKv8AfqHj3ir.jpg",
                },
            ],
        )

        screening = _find(source)

        self.assertIsNotNone(screening)
        self.assertEqual(screening.title, "Babylon")
        self.assertEqual(
            screening.poster_url,
            f"{POSTER_IMG_BASE}/wjOHjWCUE0YzDiEzKv8AfqHj3ir_400x600.jpg",
        )

    def test_keeps_linked_film_for_series_page_slugs(self):
        # Series/program slugs don't name the film; short catalog titles that
        # happen to appear in the slug must not hijack the screening.
        source = _source(
            screening_overrides={
                "films": [
                    {"name": "Star Spangled to Death", "tmdb_id": 86280}
                ],
                "ticket_urls": [
                    "https://www.lafilmforum.org/schedule/spring-2026/filmforum-50-program-16"
                ],
            },
            films=[
                {
                    "tmdbId": "86280",
                    "title": "Star Spangled to Death",
                    "posterPath": "1SshlLXCfFgqX9iJLtwPuAYh4Bx.jpg",
                },
                {"tmdbId": "999", "title": "Program", "posterPath": "x.jpg"},
            ],
        )

        screening = _find(source)

        self.assertIsNotNone(screening)
        self.assertEqual(screening.title, "Star Spangled to Death")
        self.assertEqual(
            screening.poster_url,
            f"{POSTER_IMG_BASE}/1SshlLXCfFgqX9iJLtwPuAYh4Bx_400x600.jpg",
        )

    def test_keeps_linked_film_when_no_ticket_url(self):
        source = _source(screening_overrides={"ticket_urls": []})

        screening = _find(source)

        self.assertIsNotNone(screening)
        self.assertEqual(screening.title, "The Searchers")


class PosterVerificationTests(unittest.TestCase):
    def test_tmdb_fallback_url_from_bucket_url(self):
        self.assertEqual(
            _tmdb_fallback_url(f"{POSTER_IMG_BASE}/abc123_400x600.jpg"),
            f"{TMDB_IMG_BASE}/abc123.jpg",
        )

    def test_tmdb_fallback_url_ignores_foreign_urls(self):
        self.assertIsNone(_tmdb_fallback_url("https://example.com/poster.jpg"))

    def test_verify_poster_falls_back_to_tmdb_when_bucket_403s(self):
        bucket_url = f"{POSTER_IMG_BASE}/abc123_400x600.jpg"
        tmdb_url = f"{TMDB_IMG_BASE}/abc123.jpg"

        def fake_head(url, **kwargs):
            response = mock.Mock()
            response.status_code = 200 if url == tmdb_url else 403
            return response

        with mock.patch("src.revivalhub_trmnl_sync.requests.head", side_effect=fake_head):
            self.assertEqual(_verify_poster_url(bucket_url), tmdb_url)

    def test_verify_poster_returns_none_when_all_candidates_fail(self):
        bucket_url = f"{POSTER_IMG_BASE}/abc123_400x600.jpg"

        def fake_head(url, **kwargs):
            response = mock.Mock()
            response.status_code = 403
            return response

        with mock.patch("src.revivalhub_trmnl_sync.requests.head", side_effect=fake_head):
            self.assertIsNone(_verify_poster_url(bucket_url))

    def test_verify_poster_keeps_bucket_url_when_it_serves(self):
        bucket_url = f"{POSTER_IMG_BASE}/abc123_400x600.jpg"

        def fake_head(url, **kwargs):
            response = mock.Mock()
            response.status_code = 200
            return response

        with mock.patch("src.revivalhub_trmnl_sync.requests.head", side_effect=fake_head):
            self.assertEqual(_verify_poster_url(bucket_url), bucket_url)


if __name__ == "__main__":
    unittest.main()
