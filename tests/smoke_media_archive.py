"""Small standalone smoke suite. No production downloads or deletions.

Run: PYTHONPATH=packages/media-capabilities/src python3 tests/smoke_media_archive.py
"""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

from media_capabilities.files import LocalFiles
from media_capabilities.emby import EmbyLibrary, EmbyTransport
from media_capabilities.makemkv import MakeMKVEngine
from media_capabilities.models import FileAsset, MediaUnit, TorrentSnapshot
from media_capabilities.moviepilot import MoviePilotDownloader
from media_capabilities.policies import seed_decision, select_titles
from media_capabilities.store import MemoryTaskStore


ROOT = Path(__file__).resolve().parents[1]


def load(name, directory):
    spec = importlib.util.spec_from_file_location(name, ROOT / "plugins.v2" / directory / "workflow.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ArchiveService = load("archive_smoke", "mediaarchive").ArchiveService
RemuxService = load("remux_smoke", "discremux").RemuxService


class Library:
    def __init__(self, units):
        self.units, self.migrated, self.fail = units, False, False

    def discover(self, users, **kwargs):
        return self.units

    def capture_states(self, unit, users):
        return {user: {row["item_id"]: {"Played": False, "IsFavorite": True}
                       for row in unit.items} for user in users}

    def migrate(self, job, artifacts, checkpoint):
        if self.fail:
            raise ValueError("fixture migration failure")
        self.migrated = True
        checkpoint()

    def verify_migration(self, job, artifacts):
        assert self.migrated


class Downloader:
    def __init__(self):
        self.removals = self.tags = 0
        self.ratio = 1

    def associate(self, unit, assets):
        return [TorrentSnapshot("qB", "a" * 40, "PT", [a.path for a in assets],
                                 86400, self.ratio, True)]

    def mark_retained(self, torrent):
        self.tags += 1

    def cleanup(self, job, checkpoint):
        job["deletion_intents"] = ["qB:" + "a" * 40]
        checkpoint()
        self.removals += 1
        return {"complete": True}

    def deletion_allowed(self, assets):
        return False


class Cloud:
    def __init__(self):
        self.objects, self.calls = {}, 0
        self.timeout = self.fail = False

    def find(self, asset, directory, name):
        return self.objects.get((directory, name))

    def upload(self, asset, directory, name):
        self.calls += 1
        receipt = {"id": self.calls, "size": asset.size, "sha1": asset.sha1,
                   "name": name, "path": directory + "/" + name, "pickcode": "fixture"}
        self.objects[directory, name] = receipt
        if self.timeout:
            self.timeout = False
            raise TimeoutError("fixture lost response")
        return receipt

    def verify(self, asset, receipt):
        if self.fail:
            raise ValueError("fixture cloud corruption")
        assert receipt["size"] == asset.size and receipt["sha1"] == asset.sha1


class Strm:
    def __init__(self):
        self.fail = False

    def publish(self, job):
        return [{"path": "/fixture.strm", "episode": a.get("episode")} for a in job["assets"]]

    def verify(self, artifacts):
        if self.fail:
            raise ValueError("fixture unplayable")


class Smoke(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.files = LocalFiles([str(self.root)], [str(self.output)])

    def tearDown(self):
        self.temp.cleanup()

    def archive(self, kind="movie", ratio=1):
        rows = []
        for episode in ([None] if kind == "movie" else [1, 2]):
            path = self.root / f"video-{episode}.mkv"
            path.write_bytes(b"fixture video payload")
            rows.append({"item_id": str(episode), "path": str(path), "episode": episode})
        unit = MediaUnit(kind, kind, "Smoke", season=1 if kind == "tv" else None,
                         expected_episodes=[1, 2] if kind == "tv" else [], items=rows,
                         favored_by=["user1", "user2"])
        store, library, downloader, cloud, strm = MemoryTaskStore(), Library([unit]), Downloader(), Cloud(), Strm()
        downloader.ratio = ratio
        options = {"users": ["user1", "user2"], "dry_run": False, "cleanup_enabled": True,
                   "movie_path": "/Media/Movie", "tv_path": "/Media/TV_Show"}
        service = ArchiveService(store, library, downloader, self.files, cloud, strm, None, options)
        return service, store, library, downloader, cloud, strm

    def test_archive_movie_season_and_lost_upload_response(self):
        for kind in ("movie", "tv"):
            with self.subTest(kind=kind):
                service, store, library, downloader, cloud, strm = self.archive(kind)
                cloud.timeout = True
                service.run(backfill=True)
                self.assertEqual(downloader.removals, 0)
                self.assertEqual(next(iter(store.read()["jobs"].values()))["stage"], "UPLOADING")
                resumed = ArchiveService(store, library, downloader, self.files, cloud, strm, None, service.options)
                resumed.run()
                job = next(iter(store.read()["jobs"].values()))
                self.assertEqual(job["stage"], "DONE")
                self.assertEqual(cloud.calls, 1 if kind == "movie" else 2)
                self.assertEqual(downloader.removals, 1)
                self.assertTrue(job["deletion_intents"])
                self.assertEqual(set(job["user_states"]), {"user1", "user2"})
                resumed.run(backfill=True)
                self.assertEqual(downloader.removals, 1)

    def test_validation_failures_keep_local(self):
        for failure in ("cloud", "strm", "library"):
            service, store, library, downloader, cloud, strm = self.archive()
            {"cloud": cloud, "strm": strm, "library": library}[failure].fail = True
            service.run(backfill=True)
            self.assertEqual(downloader.removals, 0)
            self.assertTrue((self.root / "video-None.mkv").exists())

    def test_baseline_preview_seed_rules_and_retention(self):
        torrent = TorrentSnapshot("qB", "hash", "PT", [], 29*86400, .9, True)
        self.assertEqual(seed_decision(torrent), (False, False))
        torrent.seeding_seconds = 31*86400
        self.assertEqual(seed_decision(torrent), (True, False))
        torrent.seeding_seconds, torrent.ratio = 86400, 2
        self.assertEqual(seed_decision(torrent), (True, True))
        torrent.ratio = float("nan")
        self.assertEqual(seed_decision(torrent), (False, False))
        service, store, library, downloader, cloud, strm = self.archive(ratio=2)
        service.run()
        self.assertFalse(store.read()["jobs"])
        service.options["dry_run"] = True
        service.run(backfill=True)
        self.assertEqual(cloud.calls, 0)
        self.assertEqual(downloader.tags, 0)
        service.options["dry_run"] = False
        service.run()
        self.assertEqual(downloader.tags, 1)
        self.assertTrue(next(iter(store.read()["jobs"].values()))["retained"])
        # A targeted run records the complete baseline and leaves other units alone.
        service, selected_store, selected_library, _, selected_cloud, _ = self.archive()
        selected_library.units.append(MediaUnit("other", "movie", "Other", items=[], favored_by=["user1"]))
        selected = selected_library.units[0].key
        service.run(backfill=True, unit_keys=[selected])
        self.assertEqual(len(selected_store.read()["jobs"]), 1)
        self.assertEqual(selected_cloud.calls, 1)
        self.assertIn("other", selected_store.read()["baseline"]["user1"])
        # Exercise the real cleanup adapter on a single temporary source file.
        path = self.root / "cleanup.mkv"
        path.write_bytes(b"temporary source")
        asset = self.files.capture([str(path)])[0]
        snapshot = TorrentSnapshot("qB", "cleanup", "PT", [str(path)], 86400, 1, True,
                                    matched_files=[str(path)], source_files=[asset.dump()])
        job = {"source": [asset.dump()], "torrents": [snapshot.dump()], "retained": []}
        recorded = []
        class Client:
            removed = False
            def torrents_delete(inner, **kwargs):
                self.assertEqual(kwargs["delete_files"], False)
                self.assertIn("qB:cleanup", recorded[-1]["deletion_intents"])
                inner.removed = True
            def torrents_info(inner, **kwargs): return [] if inner.removed else [{}]
        client = Client()
        adapter = MoviePilotDownloader(self.files)
        row = {"downloader": "qB", "raw": {"hash": "cleanup"}, "client": client, "files": [str(path)]}
        adapter._inventory = lambda **kwargs: []
        self.assertFalse(adapter.cleanup(job, lambda: recorded.append(deepcopy(job)))["complete"])
        self.assertTrue(path.exists())
        adapter._inventory = lambda **kwargs: [] if client.removed else [row]
        adapter._snapshot = lambda *args: snapshot
        self.assertTrue(adapter.cleanup(job, lambda: recorded.append(deepcopy(job)))["complete"])
        self.assertFalse(path.exists())

    def test_remux_ambiguity_manual_and_independent_queue(self):
        original = self.root / "disc.iso"
        original.write_bytes(b"source disc")
        produced = self.output / "fixture.mkv"
        produced.write_bytes(b"prepared video")
        asset = self.files.describe(self.files.capture([str(produced)]))[0]
        titles = [{"id": 0, "duration": 6000}, {"id": 1, "duration": 6100}]
        self.assertFalse(select_titles(titles, "movie")[0])
        class Engine:
            def inspect(self, source): return deepcopy(titles)
            def convert(self, job, progress): return [{"asset": asset.dump()}]
        service = RemuxService(MemoryTaskStore(), self.files, Engine(), Downloader(),
                               {"output_dir": str(self.output), "delete_original": True})
        pending = service.submit({"source": str(original), "title": "Disc"})
        service.process(pending)
        self.assertEqual(service.status(pending)["stage"], "MANUAL")
        second = service.submit({"source": str(original), "title": "Unique", "runtime_seconds": 5800})
        service.process(second)
        self.assertEqual(service.status(second)["stage"], "DONE")
        service.choose(pending, [{"id": 1}])
        service.process(pending)
        self.assertEqual(service.status(pending)["stage"], "DONE")
        self.assertTrue(original.exists())
        previous = service.status(pending)["outputs"][0]["path"]
        service.restart(pending)
        self.assertEqual(service.status(pending)["attempt"], 2)
        service.process(pending)
        self.assertEqual(service.status(pending)["stage"], "MANUAL")
        service.choose(pending, [{"id": 1}])
        service.process(pending)
        self.assertNotEqual(service.status(pending)["outputs"][0]["path"], previous)

    def test_real_ffprobe_and_makemkv_robot_parser(self):
        sample = self.root / "tiny.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=size=64x64:rate=2",
                        "-t", "1", "-c:v", "ffv1", str(sample)], check=True)
        self.assertEqual(self.files.inspect_media(str(sample))["streams"][0]["codec_name"], "ffv1")
        engine = MakeMKVEngine(self.files)
        engine._run = lambda *a, **k: ['TINFO:0,9,0,"1:30:00"', 'TINFO:0,8,0,"12"',
                                      'TINFO:0,11,0,"123456"', 'TINFO:0,26,0,"1,2,3"',
                                      'TINFO:0,27,0,"title_t00.mkv"',
                                      'SINFO:0,0,1,6201,"Video"']
        title = engine.inspect(str(sample.with_suffix(".iso")))[0]
        self.assertEqual((title["duration"], title["chapters"], title["segments"]), (5400, 12, "1,2,3"))
        self.assertEqual(len(title["streams"]), 1)
        nfo = sample.with_suffix(".nfo")
        nfo.write_text('<movie><title>tiny</title><plot>Keep metadata</plot></movie>')
        library = EmbyLibrary(None, None)
        job = {"unit": {"kind": "movie", "title": "Known movie", "provider_ids": {"tmdb": "123"}}}
        library._publish_identity(job, [{"path": str(sample)}], lambda: None)
        self.assertIn("Keep metadata", nfo.read_text())
        self.assertIn("<tmdbid>123</tmdbid>", nfo.read_text())
        calls = []
        class Client:
            def post(inner, path, **kwargs):
                calls.append((path, kwargs))
                return inner
            def raise_for_status(inner): return inner
        transport = EmbyTransport.__new__(EmbyTransport)
        transport.client = Client()
        transport.refresh_item("fixture")
        self.assertEqual(calls[0][1]["params"]["ImageRefreshMode"], "Default")
        target_path = str(sample.with_suffix(".strm"))
        class GroupedLibrary:
            def items(inner, *args, **kwargs):
                return [{"Id": "head", "Path": "/another-version.strm", "ProviderIds": {"Tmdb": "123"}}]
            def item(inner, user, item_id):
                return {"Id": "head", "MediaSources": [{"Id": "opaque-source", "Type": "Grouping"}]}
            def global_items(inner, **kwargs):
                return [{"Id": "version", "Path": target_path, "ProviderIds": {"Tmdb": "123"},
                         "MediaSources": [{"Id": "opaque-source", "Type": "Default"}]}]
        library.http = GroupedLibrary()
        job["unit"]["items"] = [{"item_id": "original", "episode": None}]
        self.assertEqual(library._targets(job, [{"path": target_path}], "user"), {"original": "version"})
        self.assertEqual(job["library_targets"]["user"][target_path]["visible_item"], "head")


if __name__ == "__main__":
    unittest.main(verbosity=2)
