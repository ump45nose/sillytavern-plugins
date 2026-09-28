from datetime import date
from tempfile import TemporaryDirectory
import unittest

from favsync.film_store import get_film, ingest_bilibili, list_films, set_downloaded
from favsync.film_watchlist import film_titles, release_info
from favsync.store import Store


class FilmWatchlistSmoke(unittest.TestCase):
    def test_title_and_release_examples(self):
        self.assertEqual(film_titles("《甲》与《乙》预告"), [("甲", "甲"), ("乙", "乙")])
        self.assertEqual(release_info("故事发生在 1698 年。上映日期：2026 年 10 月 14 日"),
                         ("2026-10-14", 2026))
        self.assertEqual(release_info("首播: 2027(未定)"), (None, 2027))

    def test_rescan_keeps_downloaded_and_merges_same_year(self):
        videos = [
            {"bvid": "BV1234567890", "title": "电影《甲》预告", "intro": "上映日期: 2026-10-14"},
            {"bvid": "BV1234567891", "title": "《甲》正式预告", "intro": "首播: 2026-10-15"},
        ]
        with TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                ingest_bilibili(store.db, "personal", videos)
                first = list_films(store.db, date(2026, 9, 28))["items"]
                self.assertEqual(len(first), 1)
                self.assertEqual(len(first[0]["sources"]), 2)
                self.assertFalse(first[0]["released"])
                set_downloaded(store.db, first[0]["id"], True, date(2026, 9, 28))
                ingest_bilibili(store.db, "personal", videos)
                current = get_film(store.db, first[0]["id"], date(2026, 10, 14))
                self.assertTrue(current["downloaded"])
                self.assertTrue(current["released"])
                ingest_bilibili(store.db, "personal", videos[:1])
                current = get_film(store.db, first[0]["id"], date(2026, 10, 14))
                self.assertEqual(sum(source["active"] for source in current["sources"]), 1)
                self.assertTrue(current["downloaded"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
