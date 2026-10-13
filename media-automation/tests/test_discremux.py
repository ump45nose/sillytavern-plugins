"""REMUX publication and recovery on real temporary files, without subprocesses."""
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from media_capabilities.files import LocalFiles
from media_capabilities.makemkv import MakeMKVEngine
from media_capabilities.store import MemoryTaskStore


RemuxService = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                                "plugins.v2/discremux/workflow.py"))["RemuxService"]


def service_for(root, *, output="", delete_original=False):
    files = LocalFiles([str(root)], [output] if output else None)
    engine = MakeMKVEngine(files)
    calls = []

    def run(args, **kwargs):
        if "info" in args:
            return ['TINFO:0,9,0,"1:40:00"']
        calls.append(args)
        (Path(args[-1]) / "title.mkv").write_bytes(b"converted video")
        return []

    engine._run = run
    files.inspect_media = lambda path: {"format": {"duration": 6000},
                                       "streams": [{"codec_type": "video"}]}
    downloader = SimpleNamespace(deletion_allowed=lambda assets: True)
    service = RemuxService(MemoryTaskStore(), files, engine, downloader,
                           {"output_dir": output, "delete_original": delete_original})
    return service, calls


@pytest.mark.parametrize("source_kind", ["iso", "disc_folder", "bdmv"])
def test_default_publishes_in_source_folder_and_reuses_job(tmp_path, source_kind):
    movie = tmp_path / "Downloads/Movie/Film"
    movie.mkdir(parents=True)
    if source_kind == "iso":
        source = movie / "Film.iso"
        source.write_bytes(b"disc")
    else:
        bdmv = movie / "BDMV"
        bdmv.mkdir()
        (bdmv / "index.bdmv").write_bytes(b"disc index")
        (bdmv / "00000.m2ts").write_bytes(b"disc stream")
        source = movie if source_kind == "disc_folder" else bdmv
    service, calls = service_for(tmp_path)
    request = {"source": str(source), "title": "Film"}
    job_id = service.submit(request)
    service.process(job_id)
    job = service.status(job_id)
    assert job["stage"] == "DONE"
    assert job["outputs"][0]["path"] == str(movie / "Film.mkv")
    assert Path(calls[0][-1]).is_relative_to(movie / ".discremux")
    assert source.exists()
    assert service.submit(request) == job_id
    assert len(service.snapshot()["jobs"]) == 1

    # A new service can recover frozen paths after configuration changes.
    resumed, _ = service_for(tmp_path)
    resumed.store = service.store
    resumed.options["output_dir"] = str(tmp_path / "different")
    resumed.restart(job_id)
    resumed.process(job_id)
    restarted = resumed.status(job_id)
    assert restarted["stage"] == "DONE"
    assert Path(restarted["outputs"][0]["path"]).parent == movie
    assert restarted["outputs"][0]["path"] != job["outputs"][0]["path"]
    assert (movie / "Film.mkv").exists()


def test_iso_directly_in_allowed_root(tmp_path):
    source = tmp_path / "Film.iso"
    source.write_bytes(b"disc")
    service, _ = service_for(tmp_path)
    job_id = service.submit({"source": str(source), "title": "Film"})
    service.process(job_id)
    assert service.status(job_id)["stage"] == "DONE"
    assert service.status(job_id)["outputs"][0]["path"] == str(tmp_path / "Film.mkv")


def test_explicit_output_and_legacy_job_keep_task_directory(tmp_path):
    source = tmp_path / "Film.iso"
    source.write_bytes(b"disc")
    output = tmp_path / "Remux"
    service, _ = service_for(tmp_path, output=str(output))
    job_id = service.submit({"source": str(source), "title": "Film"})
    # Old persisted jobs have no in_place field and keep their publication layout.
    state = service.store.read()
    state["jobs"][job_id].pop("in_place")
    service.store.write(state)
    resumed, _ = service_for(tmp_path)
    resumed.store = service.store
    resumed.process(job_id)
    job = resumed.status(job_id)
    assert job["stage"] == "DONE"
    assert job["outputs"][0]["path"] == str(output / f"Film-{job_id[:10]}" / "Film.mkv")


def test_existing_different_mkv_is_preserved(tmp_path):
    source = tmp_path / "Film.iso"
    source.write_bytes(b"disc")
    target = tmp_path / "Film.mkv"
    target.write_bytes(b"existing version")
    service, _ = service_for(tmp_path, delete_original=True)
    job_id = service.submit({"source": str(source), "title": "Film"})
    service.process(job_id)
    job = service.status(job_id)
    assert job["stage"] == "FAILED"
    assert job["resume_stage"] == "COMMITTING"
    assert target.read_bytes() == b"existing version"
    assert source.exists()


def test_disc_cleanup_keeps_mkv_and_working_receipts(tmp_path):
    source = tmp_path / "Film"
    bdmv = source / "BDMV"
    bdmv.mkdir(parents=True)
    (bdmv / "index.bdmv").write_bytes(b"disc index")
    (bdmv / "00000.m2ts").write_bytes(b"disc stream")
    service, _ = service_for(tmp_path, delete_original=True)
    job_id = service.submit({"source": str(source), "title": "Film"})
    service.process(job_id)
    job = service.status(job_id)
    assert job["stage"] == "DONE"
    assert not bdmv.exists()
    assert (source / "Film.mkv").read_bytes() == b"converted video"
    assert (source / ".discremux" / job_id / "0/ready.json").exists()


def test_tv_outputs_keep_episode_names_in_place(tmp_path):
    source = tmp_path / "Show.iso"
    source.write_bytes(b"disc")
    service, _ = service_for(tmp_path)
    job_id = service.submit({"source": str(source), "title": "Show", "kind": "tv",
                             "season": 2, "episodes": [3]})
    service.process(job_id)
    assert service.status(job_id)["stage"] == "DONE"
    assert service.status(job_id)["outputs"][0]["path"] == str(tmp_path / "Show.S02E03.mkv")


def test_output_rejects_disc_internals_and_symlinks(tmp_path):
    source = tmp_path / "Film"
    (source / "BDMV").mkdir(parents=True)
    (source / "BDMV/index.bdmv").write_bytes(b"index")
    files = LocalFiles([str(tmp_path)])
    with pytest.raises(ValueError):
        files.validate_output(str(source), str(source / "BDMV"))
    with pytest.raises(ValueError):
        files.validate_output(str(source), str(tmp_path.parent / "outside"))
    target = tmp_path / "Remux"
    target.mkdir()
    symlink = tmp_path / "link"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        files.validate_output(str(source), str(symlink))
