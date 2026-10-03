"""不接触真实下载器的最小候选选择冒烟检查。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


source = Path(__file__).resolve().parents[1] / "plugins.v2" / "filmwatchlist" / "selection.py"
spec = spec_from_file_location("filmwatchlist_selection", source)
selection = module_from_spec(spec)
spec.loader.exec_module(selection)


assert selection.quality_key("Film.2160p.BluRay.REMUX.mkv") > selection.quality_key("Film.1080p.BluRay.REMUX.mkv")
assert selection.quality_key("Film.1080p.BluRay.REMUX.mkv") > selection.quality_key("Film.2160p.WEB-DL.mkv")
assert selection.quality_key("Film.2160p.BluRay.x265.mkv") > selection.quality_key("Film.2160p.WEB-DL.mkv")
assert selection.inspect_files("Film.2160p.REMUX", ["Film.mkv"])[0]
assert not selection.inspect_files("Film.2160p.ISO", ["Film.iso"])[0]
assert not selection.inspect_files("Film.2160p.BluRay", ["BDMV/STREAM/00001.m2ts"])[0]
assert not selection.inspect_files("Film.1080p.WEB-DL", ["Film.nfo"])[0]
assert selection.inspect_files("Show.S01.1080p", ["Show.S01E01.mkv", "Show.S01E02.mkv"], {1, 2})[0]
assert not selection.inspect_files("Show.S01.1080p", ["Show.S01E01.mkv"], {1, 2})[0]
print("selection smoke: OK")
