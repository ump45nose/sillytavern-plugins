from datetime import date
from tempfile import TemporaryDirectory
import unittest

from favsync.film_store import get_film, ingest_bilibili, list_films, set_downloaded
from favsync.film_watchlist import country_info, film_titles, release_info
from favsync.store import Store


class FilmWatchlistSmoke(unittest.TestCase):
    def test_title_and_release_examples(self):
        self.assertEqual(film_titles("《甲》与《乙》预告"), [("甲", "甲"), ("乙", "乙")])
        self.assertEqual(release_info("故事发生在 1698 年。上映日期：2026 年 10 月 14 日"),
                         ("2026-10-14", 2026))
        self.assertEqual(release_info("首播: 2027(未定)"), (None, 2027))

    def test_country_from_release_line_or_title(self):
        self.assertEqual(country_info("法国电影《甲》", "上映日期：2026-10-14 (德国)"), "德国")
        self.assertEqual(country_info("克罗地亚历史电影《乙》", "暂无上映时间"), "克罗地亚")
        self.assertEqual(country_info("《丙》", "播出周期: 2026年11月14日–2027年2月14日(韩国)"), "韩国")
        self.assertIsNone(country_info("《丁》全球版", "上映日期：2026-10-14 (全球)"))
        self.assertIsNone(country_info("《戊》", "上映日期：2026-10-14；主演：法国演员"))

        with TemporaryDirectory() as folder:
            store = Store(folder)
            try:
                ingest_bilibili(store.db, "personal", [
                    {"bvid": "BV1234567890", "title": "法国电影《甲》",
                     "intro": "上映日期：2026-10-14 (德国)"},
                    {"bvid": "BV1234567891", "title": "《丁》全球版",
                     "intro": "上映日期：2026-10-14 (全球)"},
                ])
                countries = {item["title"]: item["country"] for item in
                             list_films(store.db, date(2026, 9, 28))["items"]}
                self.assertEqual(countries, {"甲": "德国", "丁": None})
            finally:
                store.close()

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
