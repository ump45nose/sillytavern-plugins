from pathlib import PurePosixPath

import pytest

from media_capabilities.acquisition.adult import classify_adult, collection_path
from media_capabilities.acquisition.javdb_cli import JavDbCli, normalize_jav_number
from media_capabilities.acquisition.quality_selection import MediaCandidate
from media_capabilities.acquisition.upgrade import decide_upgrade, facts_from_library, is_4k


def probe(width=3840, height=2160, hdr=False):
    stream = {"codec_type": "video", "width": width, "height": height}
    if hdr:
        stream["color_transfer"] = "smpte2084"
    return {"streams": [stream], "format": {"duration": "6000"}}


def candidate(title, size, source="pt", cid="x", files=()):
    return MediaCandidate(source, title, size, size, cid, files=tuple(files))


def test_tiered_upgrade_reuses_existing_quality_hierarchy():
    current = facts_from_library("Film.2026.1080p.WEB-DL.mkv", 10_000, probe(1920, 1080))
    decision = decide_upgrade(current, [
        candidate("Film.2026.1080p.BluRay.mkv", 11_000),
        candidate("Film.2026.2160p.BluRay.mkv", 14_000, cid="best"),
    ])
    assert decision.upgrade is True
    assert decision.candidate_id == "best"


def test_same_tier_near_size_is_not_washed():
    current = facts_from_library("Film.2160p.WEB-DL.mkv", 10_000, probe())
    decision = decide_upgrade(current, [
        candidate("Film.2160p.WEB-DL.mkv", 10_800, source="public_bt"),
    ], near_size_ratio=0.10)
    assert decision.equivalent is True


def test_adult_strategy_uses_file_name_resolution_and_size():
    current = facts_from_library("ABC-123.mkv", 8_000, probe(1920, 1080))
    decision = decide_upgrade(current, [
        candidate("ABC-123", 8_400, "public_bt", files=("ABC-123.1080p.mkv",)),
        candidate("ABC-123", 15_000, "pt", cid="4k", files=("ABC-123.2160p.mkv",)),
    ], strategy="resolution_size")
    assert decision.upgrade is True
    assert decision.candidate_id == "4k"


def test_probe_4k_wins_over_unhelpful_filename():
    assert is_4k(probe(), "scene.mkv") is True
    assert is_4k(probe(1920, 1080), "scene.mkv") is False


@pytest.mark.parametrize("raw,expected", [
    ("abc-123", "ABC-123"),
    ("ABC00123", "ABC-00123"),
    ("fc2-ppv-1234567", "FC2-PPV-1234567"),
])
def test_normalize_jav_number(raw, expected):
    assert normalize_jav_number(raw) == expected


def test_adult_classification_and_collection_path():
    assert classify_adult("ABC-123", "/Adult/JAV/ABC-123/ABC-123.mkv") == "jav"
    assert classify_adult("Scene", "/Adult/Western/Vixen/Scene.mkv", ["Vixen"]) == "vixen"
    target = collection_path("/Adult/Western/Vixen/Scene.mkv", "/Adult/Western")
    assert PurePosixPath(target) == PurePosixPath("/Adult/Western/Collection/Vixen/Scene.mkv")


def test_javdb_cli_parses_stable_json_contract(monkeypatch):
    cli = JavDbCli("/usr/bin/javdb")
    monkeypatch.setattr(cli, "health", lambda: {"status": "OK"})
    class Result:
        returncode = 0
        stderr = b""
        stdout = (b'{"movie_id":"m1","magnets":['
                  b'{"hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","size":4096,'
                  b'"name":"ABC-123.2160p","hd":true,"cnsub":false}]}')
    monkeypatch.setattr("subprocess.run", lambda *a, **k: Result())
    rows = cli.magnets("ABC-123")
    assert rows[0].size_bytes == 4096 * 1024 * 1024
    assert rows[0].magnet.endswith("a" * 40)
