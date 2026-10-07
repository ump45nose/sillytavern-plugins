"""Emby adapter: favorites, exact STRM identity, and per-user state migration."""
from pathlib import Path
import os
import hashlib
import tempfile
import time
import xml.etree.ElementTree as ET

import httpx

from .models import MediaUnit, stable_id


class LibraryPending(ValueError):
    """A scan/refresh is asynchronous; keep the migration stage pending."""


class EmbyTransport:
    def __init__(self, url: str, token: str, timeout=30):
        base = url.rstrip("/")
        if not base.endswith("/emby"):
            base += "/emby"
        self.client = httpx.Client(base_url=base, headers={"X-Emby-Token": token}, timeout=timeout)

    def close(self):
        self.client.close()

    def get(self, path, **params):
        return self.client.get(path, params=params).raise_for_status().json()

    def items(self, user, **params):
        return self._items(f"/Users/{user}/Items", **params)

    def global_items(self, **params):
        """Include secondary versions; callers must verify user visibility."""
        return self._items("/Items", **params)

    def _items(self, path, **params):
        result, start = [], 0
        while True:
            payload = self.get(path, StartIndex=start, Limit=200,
                               Fields="Path,ProviderIds,MediaSources,RunTimeTicks,Studios", **params)
            rows = payload.get("Items", [])
            result.extend(rows)
            start += len(rows)
            if start >= int(payload.get("TotalRecordCount", start)):
                return result
            if not rows or start > 200000:
                raise RuntimeError("Emby 分页未完成")

    def item(self, user, item_id):
        return self.get(f"/Users/{user}/Items/{item_id}")

    def state(self, user, item_id):
        data = self.item(user, item_id).get("UserData", {})
        return {"Played": bool(data.get("Played")), "IsFavorite": bool(data.get("IsFavorite"))}

    def set_state(self, user, item_id, state):
        for field, endpoint in (("Played", "PlayedItems"), ("IsFavorite", "FavoriteItems")):
            method = "POST" if state[field] else "DELETE"
            self.client.request(method, f"/Users/{user}/{endpoint}/{item_id}").raise_for_status()

    def refresh_item(self, item_id):
        self.client.post(f"/Items/{item_id}/Refresh", params={
            "MetadataRefreshMode": "FullRefresh", "ImageRefreshMode": "Default",
            "ReplaceAllMetadata": False, "ReplaceAllImages": False, "Recursive": False},
            json={"ReplaceThumbnailImages": False}).raise_for_status()

    def refresh(self):
        self.client.post("/Library/Refresh").raise_for_status()


class EmbyLibrary:
    def __init__(self, transport, expected_episodes, mappings=None):
        self.http, self.expected = transport, expected_episodes
        self.mappings = mappings or []
        self.server_id = None

    def _map(self, value, *, reverse=False):
        path = Path(value)
        for mapping in sorted(self.mappings, key=lambda m: len(m["local" if reverse else "emby"]), reverse=True):
            source = Path(mapping["local" if reverse else "emby"])
            target = Path(mapping["emby" if reverse else "local"])
            if path.is_relative_to(source):
                return str(target / path.relative_to(source))
        return str(path)

    def _row(self, raw):
        path = raw.get("Path") or ""
        return {"item_id": str(raw["Id"]), "path": self._map(path) if path else "",
                "episode": raw.get("IndexNumber") if raw.get("Type") == "Episode" else None,
                "studios": [str(row.get("Name") or "") for row in (raw.get("Studios") or []) if row.get("Name")]}

    def discover(self, users, *, unit_keys=None, resolve_episodes=True):
        if self.server_id is None:
            self.server_id = str(self.http.get("/System/Info")["Id"])
        units = {}
        for user in users:
            favorites = self.http.items(user, Recursive=True, Filters="IsFavorite",
                                        IncludeItemTypes="Movie,Series,Season,Episode")
            for favorite in favorites:
                if favorite["Type"] == "Movie":
                    contexts = [(favorite, None, None)]
                elif favorite["Type"] == "Series":
                    seasons = self.http.get(f"/Shows/{favorite['Id']}/Seasons", UserId=user)["Items"]
                    contexts = [(favorite, s, int(s["IndexNumber"])) for s in seasons
                                if int(s.get("IndexNumber") or 0) > 0]
                else:
                    series_id = favorite.get("SeriesId")
                    series = self.http.item(user, series_id)
                    season_number = int(favorite.get("ParentIndexNumber") if favorite["Type"] == "Episode"
                                        else favorite.get("IndexNumber"))
                    seasons = self.http.get(f"/Shows/{series_id}/Seasons", UserId=user)["Items"]
                    season = next((s for s in seasons if s.get("IndexNumber") == season_number), None)
                    if not season:
                        raise ValueError("收藏的目标季未找到")
                    contexts = [(series, season, season_number)]
                for parent, season, number in contexts:
                    kind = "movie" if number is None else "tv"
                    providers = {str(k).lower(): str(v) for k, v in (parent.get("ProviderIds") or {}).items()}
                    key = stable_id([self.server_id, kind, providers or parent["Id"], number])
                    if unit_keys is not None and key not in unit_keys:
                        continue
                    if key not in units:
                        raw_items = [parent] if kind == "movie" else self.http.items(
                            user, ParentId=season["Id"], Recursive=True, IncludeItemTypes="Episode",
                            IsMissing=False, IsVirtualItem=False)
                        # Cloud items must not become new local archive tasks.
                        raw_items = [row for row in raw_items if not str(row.get("Path", "")).lower().endswith(".strm")]
                        if not raw_items:
                            continue
                        expected = sorted(self.expected(providers, number)) if kind == "tv" and resolve_episodes else []
                        unit = MediaUnit(key, kind, parent.get("Name", "Media"), providers, number,
                                         expected, [self._row(row) for row in raw_items], [],
                                         float(parent.get("RunTimeTicks") or 0) / 10000000 or None)
                        unit.items[0]["parents"] = {"series": str(parent["Id"]),
                                                    "season": str(season["Id"])} if season else {}
                        units[key] = unit
                    if key in units and user not in units[key].favored_by:
                        units[key].favored_by.append(user)
        return list(units.values())

    def capture_states(self, unit, users):
        result = {}
        for user in users:
            result[user] = {str(row["item_id"]): self.http.state(user, row["item_id"]) for row in unit.items}
            for item_id in unit.items[0].get("parents", {}).values():
                result[user][item_id] = self.http.state(user, item_id)
        return result

    def _targets(self, job, artifacts, user, *, refresh=True):
        kind = job["unit"]["kind"]
        rows = self.http.items(user, Recursive=True, IncludeItemTypes="Movie" if kind == "movie" else "Episode")
        global_by_path = {}
        mapping = {}
        source = {row.get("episode"): row for row in job["unit"]["items"]}
        for artifact in artifacts:
            expected_path = self._map(artifact["path"], reverse=True)
            matches = [row for row in rows if str(row.get("Path")) == expected_path]
            visible = matches[0] if len(matches) == 1 else None
            if not matches:
                # Emby collapses movie versions in user enumeration. Resolve the
                # exact file globally, then require its own opaque source ID in
                # a visible user's item; provider ID alone is never sufficient.
                if expected_path not in global_by_path:
                    global_by_path[expected_path] = self.http.global_items(Recursive=True, Path=expected_path,
                        IncludeItemTypes="Movie" if kind == "movie" else "Episode")
                candidates = [row for row in global_by_path[expected_path] if str(row.get("Path")) == expected_path]
                if len(candidates) == 1:
                    own_sources = {s.get("Id") for s in candidates[0].get("MediaSources", [])
                                   if s.get("Id") and s.get("Type") == "Default"}
                    visible = next((row for row in rows if any(s.get("Id") in own_sources
                        for s in row.get("MediaSources", []))), None)
                    if visible is None:
                        # List responses may omit grouped sources even when
                        # MediaSources is requested. Detail responses include
                        # them. Restrict detail reads to matching movie IDs or
                        # the exact series/season/episode context.
                        for row in rows:
                            if kind == "movie":
                                ids = {str(k).lower(): str(v) for k, v in (row.get("ProviderIds") or {}).items()}
                                identity = job["unit"]["provider_ids"]
                                common = set(ids) & set(identity)
                                possible = bool(common) and all(ids[k] == identity[k] for k in common)
                            else:
                                possible = row.get("SeriesId") == candidates[0].get("SeriesId") and \
                                    row.get("IndexNumber") == artifact.get("episode") and \
                                    row.get("ParentIndexNumber") == job["unit"]["season"]
                            if possible:
                                detail = self.http.item(user, row["Id"])
                                if any(s.get("Id") in own_sources for s in detail.get("MediaSources", [])):
                                    visible = detail
                                    break
                    if visible:
                        matches = candidates
            if len(matches) != 1:
                raise LibraryPending("云端 STRM 条目尚未唯一入库")
            target = matches[0]
            job.setdefault("library_targets", {}).setdefault(user, {})[artifact["path"]] = {
                "target": str(target["Id"]), "visible_item": str(visible["Id"])}
            if kind == "tv" and (target.get("IndexNumber") != artifact["episode"] or
                                  target.get("ParentIndexNumber") != job["unit"]["season"]):
                raise ValueError("目标 STRM 集序不匹配")
            parent_raw = target if kind == "movie" else self.http.item(user, target["SeriesId"])
            providers = {str(k).lower(): str(v) for k, v in (parent_raw.get("ProviderIds") or {}).items()}
            identity = job["unit"]["provider_ids"]
            common = set(identity) & set(providers)
            if not common or any(identity[k] != providers[k] for k in common):
                # Re-read the known identity NFO for an already scanned item.
                if refresh:
                    self.http.refresh_item(str(target["Id"]))
                raise LibraryPending("目标 STRM 媒体标识等待媒体库刷新")
            original = source[artifact.get("episode")]
            mapping[original["item_id"]] = str(target["Id"])
            parents = original.get("parents") or job["unit"]["items"][0].get("parents", {})
            if parents:
                mapping[parents["series"]] = str(target["SeriesId"])
                mapping[parents["season"]] = str(target["SeasonId"])
        return mapping

    def _publish_identity(self, job, artifacts, checkpoint):
        """Publish known identity beside owned STRM files, without scraping."""
        unit = job["unit"]
        providers = {k: v for k, v in unit["provider_ids"].items() if k in {"tmdb", "imdb", "tvdb"}}
        if not providers:
            raise ValueError("源媒体没有可确认的媒体标识")
        def identity(root):
            ET.SubElement(root, "title").text = unit["title"]
            for index, (kind, value) in enumerate(providers.items()):
                ET.SubElement(root, "uniqueid", type=kind, default="true" if index == 0 else "false").text = value
                ET.SubElement(root, kind + "id").text = value
            return root
        rows = []
        if unit["kind"] == "tv":
            rows.append((Path(artifacts[0]["path"]).parent / "tvshow.nfo", identity(ET.Element("tvshow"))))
        for artifact in artifacts:
            root = identity(ET.Element("movie")) if unit["kind"] == "movie" else ET.Element("episodedetails")
            if unit["kind"] == "tv":
                ET.SubElement(root, "season").text = str(unit["season"])
                ET.SubElement(root, "episode").text = str(artifact["episode"])
            rows.append((Path(artifact["path"]).with_suffix(".nfo"), root))
        for path, root in rows:
            if path.is_symlink():
                raise ValueError("媒体标识文件不能是符号链接")
            previous = None
            if path.exists():
                previous = path.read_bytes()
                existing = ET.fromstring(previous)
                if existing.tag != root.tag:
                    raise ValueError("已有 NFO 类型不匹配")
                ids = {str(node.get("type") or "").lower(): node.text for node in existing.findall("uniqueid")}
                ids.update({k: existing.findtext(k + "id") for k in providers if existing.findtext(k + "id")})
                if root.tag == "episodedetails":
                    if existing.findtext("season") != str(unit["season"]) or existing.findtext("episode") != root.findtext("episode"):
                        raise ValueError("已有 NFO 集序不匹配")
                    continue
                if any(ids.get(k) and ids[k] != v for k, v in providers.items()):
                    raise ValueError("已有 NFO 的媒体标识不匹配，保留并等待人工核实")
                if any(ids.get(k) == v for k, v in providers.items()):
                    continue
                if any(ids.get(k) for k in {"tmdb", "imdb", "tvdb"}):
                    raise ValueError("已有 NFO 的媒体标识无法与源媒体核对")
                # Emby may have already written an unidentified NFO for our
                # validated STRM. Preserve its fields and add known source IDs.
                for node in root:
                    if node.tag == "title":
                        title = existing.find("title")
                        if title is None:
                            existing.append(node)
                        elif not title.text or title.text in {path.parent.name, path.stem}:
                            title.text = node.text
                    elif node.tag == "uniqueid":
                        existing.append(node)
                    elif existing.find(node.tag) is None:
                        existing.append(node)
                    else:
                        existing.find(node.tag).text = node.text
                root = existing
            payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            receipt = {"state": "intent", "sha256": hashlib.sha256(payload).hexdigest(),
                       "previous_sha256": hashlib.sha256(previous).hexdigest() if previous else None}
            job.setdefault("identity_files", {})[str(path)] = receipt
            checkpoint()
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".mediaarchive-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                if previous is None:
                    os.chmod(temporary, 0o644)
                    os.link(temporary, path)
                else:
                    if path.is_symlink() or path.read_bytes() != previous:
                        raise ValueError("NFO 已被其他进程修改，等待重试")
                    os.chmod(temporary, path.stat().st_mode & 0o777)
                    os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            receipt["state"] = "published"
            checkpoint()

    def migrate(self, job, artifacts, checkpoint):
        self._publish_identity(job, artifacts, checkpoint)
        self.http.refresh()
        # A scan is asynchronous; a missing target keeps this stage pending.
        for user, states in job["user_states"].items():
            deadline, refresh = time.monotonic() + 120, True
            while True:
                try:
                    mapping = self._targets(job, artifacts, user, refresh=refresh)
                    break
                except LibraryPending:
                    if time.monotonic() >= deadline:
                        raise
                    refresh = False
                    time.sleep(3)
            receipts = job.setdefault("migration_receipts", {}).setdefault(user, {})
            parents = set(job["unit"]["items"][0].get("parents", {}).values())
            # Marking a parent watched/unwatched can cascade to child episodes.
            for original in sorted(states, key=lambda key: key not in parents):
                state = states[original]
                target = mapping[original]
                if receipts.get(original, {}).get("target") == target:
                    continue
                if self.http.state(user, target) != state:
                    self.http.set_state(user, target, state)
                if self.http.state(user, target) != state:
                    raise ValueError("已看/收藏状态回读不一致")
                receipts[original] = {"target": target, "state": state}
                checkpoint()

    def verify_migration(self, job, artifacts):
        for user, states in job["user_states"].items():
            mapping = self._targets(job, artifacts, user)
            receipts = job.get("migration_receipts", {}).get(user, {})
            for original, state in states.items():
                # A confirmed migration stays confirmed when a user subsequently
                # changes their cloud item's watch/favorite state.
                receipt = receipts.get(original)
                if not receipt or receipt["target"] != mapping[original] or receipt["state"] != state:
                    raise ValueError("缺少已回读确认的用户状态迁移回执")
