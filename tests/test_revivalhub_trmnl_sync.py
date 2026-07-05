import datetime as dt
import unittest

from src.revivalhub_trmnl_sync import POSTER_IMG_BASE, find_next_screening


class FindNextScreeningTests(unittest.TestCase):
    def test_uses_top_level_film_catalog_poster_when_screening_has_tmdb_id_only(self):
        showtime = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
        source = {
            "venues": [{"id": "receaYS3GjcnaPXRk", "name": "Aero Theatre"}],
            "films": [
                {
                    "tmdbId": "3114",
                    "title": "The Searchers",
                    "posterPath": "jLBmgW0epNzJ1N9uzaVCjbyT94v.jpg",
                }
            ],
            "screenings": [
                {
                    "venue": "receaYS3GjcnaPXRk",
                    "screening_times": [showtime.isoformat()],
                    "films": [{"name": "The Searchers", "tmdb_id": 3114}],
                    "ticket_urls": [
                        "https://www.americancinematheque.com/now-showing/the-searchers/"
                    ],
                }
            ],
        }

        screening = find_next_screening(
            source=source,
            theatre="Aero Theatre",
            timezone="America/Los_Angeles",
            lookahead_hours=2,
        )

        self.assertIsNotNone(screening)
        self.assertEqual(
            screening.poster_url,
            f"{POSTER_IMG_BASE}/jLBmgW0epNzJ1N9uzaVCjbyT94v_400x600.jpg",
        )


if __name__ == "__main__":
    unittest.main()
