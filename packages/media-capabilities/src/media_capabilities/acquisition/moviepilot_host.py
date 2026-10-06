"""MoviePilot composition boundary. Host imports are deferred to method calls."""
from copy import copy
from dataclasses import asdict
import hashlib
import re

from .evidence import magnet_evidence, torrent_evidence
from .models import MediaIdentity, ResourceCandidate, SourcePage
from .policies import inspect_target, subtitle_evidence
from .public_index import MediaQuery
from .quality_selection import MediaCandidate
from .selection import normalize_title
from .media_types import normalize_media_type


class MoviePilotIdentity:
    def __init__(self):
        self.native = {}

    def identify(self, request):
        from app.chain.media import MediaChain
        from app.schemas.types import MediaType
        chain = MediaChain()
        types = {"movie": MediaType.MOVIE, "tv": MediaType.TV}
        if request.tmdb_id:
            values = [chain.recognize_media(mtype=types[request.media_type], tmdbid=request.tmdb_id)]
        elif request.imdb_id:
            from app.modules.themoviedb.tmdbv3api import Find
            found = Find().find_by_imdb_id(request.imdb_id) or {}
            values = [chain.recognize_media(mtype=types[t], tmdbid=row['id'])
                      for t in ([request.media_type] if request.media_type else types)
                      for row in found.get('movie_results' if t == 'movie' else 'tv_results', [])]
        else:
            _, values = chain.search(f"{request.title} ({request.year})" if request.year else request.title)
            values = values or []
        results, suggestions = {}, {}
        for value in values:
            if not value:
                continue
            kind = normalize_media_type(value.type)
            if request.media_type and kind != request.media_type:
                continue
            if request.year and str(value.year) != str(request.year):
                continue
            names = tuple(dict.fromkeys(str(n) for n in
                (value.title, getattr(value, "original_title", None), *(getattr(value, "names", None) or [])) if n))
            if request.title and normalize_title(request.title) not in {normalize_title(n) for n in names}:
                if not request.tmdb_id and not request.imdb_id and getattr(value, 'tmdb_id', None):
                    suggestion = MediaIdentity(value.title, kind, value.tmdb_id,
                        getattr(value, 'imdb_id', None), int(value.year) if str(value.year).isdigit() else None,
                        names, exact_match=False)
                    suggestions[(kind, value.tmdb_id)] = suggestion
                continue
            if not request.tmdb_id and not request.imdb_id:
                value = chain.recognize_media(mtype=types[kind], tmdbid=value.tmdb_id,
                                             doubanid=getattr(value, "douban_id", None))
            if not value or (request.imdb_id and getattr(value, "imdb_id", None)
                             and value.imdb_id != request.imdb_id):
                continue
            names = tuple(dict.fromkeys(str(n) for n in
                (value.title, getattr(value, 'original_title', None), *(getattr(value, 'names', None) or [])) if n))
            if request.title and normalize_title(request.title) not in {normalize_title(n) for n in names}:
                continue
            raw = getattr(value, "tmdb_info", None) or {}
            episodes = tuple(sorted((int(s), int(e)) for s, rows in (value.seasons or {}).items()
                                    if int(s) > 0 for e in rows)) if kind == "tv" else ()
            ended = raw.get("status") == "Ended"
            if request.scope == "series" and kind == "tv":
                declared_seasons, declared_episodes = raw.get("number_of_seasons"), raw.get("number_of_episodes")
                if not ended or not declared_seasons or not declared_episodes \
                        or len({s for s, _ in episodes}) != int(declared_seasons) \
                        or len(episodes) != int(declared_episodes):
                    raise ValueError("整剧需已完结，且所有正季及集数能够完整核实")
            identity = MediaIdentity(value.title, kind, value.tmdb_id,
                getattr(value, "imdb_id", None), int(value.year) if str(value.year).isdigit() else None,
                names, episodes, ended)
            key = (kind, identity.tmdb_id or identity.imdb_id)
            if not key[1]:
                continue
            results[key] = identity
            self.native[key] = value
        return list(results.values()) if results else list(suggestions.values())[:20]

    def context_media(self, identity, target):
        value = copy(self.native[(identity.media_type, identity.tmdb_id or identity.imdb_id)])
        value.season = next(iter(target.expected))[0] if target.scope in ("season", "episode") else None
        return value


class MTeamAdapter:
    source_id = "mteam"
    public_source = False

    def __init__(self, settings, identities):
        self.settings, self.identities = settings, identities

    def search(self, target, cursor=None):
        from app.chain.search import SearchChain
        media = target.media
        # One native site query; no all-site aggregation or per-release TMDB lookups.
        query = f"{media.title} {media.year}" if media.media_type != "tv" and media.year else media.title
        page = int(cursor) if cursor is not None else 0
        if page < 0 or page > 11:
            raise ValueError('站点分页越界')
        rows = SearchChain().search_by_title(query, sites=[self.settings.site_id], page=page) or []
        candidates = []
        for context in rows:
            torrent = getattr(context, "torrent_info", None)
            if not torrent or torrent.site != self.settings.site_id:
                continue
            try:
                if media.media_type and torrent.category and normalize_media_type(torrent.category) != media.media_type:
                    continue
            except ValueError:
                continue
            native_media = getattr(context, "media_info", None)
            if media.tmdb_id and native_media and getattr(native_media, "tmdb_id", None):
                if normalize_media_type(native_media.type) != media.media_type or str(native_media.tmdb_id) != str(media.tmdb_id):
                    continue
            else:
                prefix = re.split(r"(?i)\b(?:19\d{2}|20\d{2}|S\d{1,3}|2160p|1080p|720p)\b", torrent.title, maxsplit=1)[0]
                meta = getattr(context, 'meta_info', None)
                release_names = (prefix, *(getattr(meta, key, None) for key in ('name', 'cn_name', 'en_name')))
                if not {normalize_title(n) for n in release_names if n}.intersection(
                        normalize_title(n) for n in (media.title, *media.aliases)):
                    continue
                years = re.findall(r"\b(?:19|20)\d{2}\b", torrent.title)
                if media.media_type != "tv" and media.year and years and str(media.year) not in years:
                    continue
            identifier = hashlib.sha256(f"{torrent.site}:{torrent.page_url or torrent.title}".encode()).hexdigest()
            candidates.append(ResourceCandidate(identifier, self.source_id, torrent.title,
                int(torrent.size) if getattr(torrent, "size", None) else None,
                int(getattr(torrent, "seeders", 0) or 0),
                subtitle_evidence(torrent.title + " " + str(getattr(torrent, "description", "") or "")), context))
        return SourcePage("OK" if candidates else "NO_RESULTS", candidates,
                          str(page + 1) if rows and page < 11 else None)

    def resolve(self, candidate, target):
        from app.chain.download import DownloadChain
        context = copy(candidate.native)
        content, _, _ = DownloadChain().download_torrent(context.torrent_info, source="MediaAcquisition")
        evidence = torrent_evidence(content, candidate.title)
        inspect_target(candidate.title, evidence.files, target)
        context.media_info = self.identities.context_media(target.media, target)
        subs = subtitle_evidence(files=evidence.files)
        if not subs.chinese:
            subs = candidate.subtitles
        return [MediaCandidate("pt", candidate.title, evidence.video_bytes, evidence.total_bytes,
            candidate.candidate_id, info_hash=evidence.info_hash, torrent_content=content,
            context=context, files=evidence.files,
            evidence={"subtitles": asdict(subs), "seeders": candidate.seeders})]

    def health(self):
        from app.db.site_oper import SiteOper
        site = SiteOper().get(self.settings.site_id)
        return {"status": "OK" if site else "UNAVAILABLE"}


class Mini4KAdapter:
    source_id = "mini4k"
    public_source = True

    def __init__(self, settings, indexer_factory, p115_factory):
        self.settings = settings
        self.indexer_factory, self.p115_factory = indexer_factory, p115_factory

    def search(self, target, cursor=None):
        media = target.media
        page = self.indexer_factory().search(MediaQuery(title=media.title, aliases=media.aliases[:3],
            year=media.year, media_type=media.media_type, tmdb_id=media.tmdb_id, imdb_id=media.imdb_id,
            season=(getattr(target, 'season', None) or next((s for s, _ in target.expected), None))
                if target.scope in ("season", "episode") else None), cursor)
        candidates = [ResourceCandidate(c.candidate_id, self.source_id, c.title, c.size_bytes,
            subtitles=subtitle_evidence(c.quality_text), native=c) for c in page.candidates]
        return SourcePage(page.status.value, candidates, page.next_cursor, page.reason)

    def resolve(self, candidate, target):
        if not self.settings.p115_route_enabled:
            raise ValueError("115 公网下载路由未启用")
        resolved = self.indexer_factory().resolve(candidate.candidate_id)
        if resolved.status.value != "OK":
            raise ValueError("Mini4K 解析状态：" + resolved.status.value +
                             ("；" + resolved.reason if resolved.reason else ""))
        results, seen_hashes = [], set()
        for link in sorted(resolved.links, key=lambda item: item.kind != 'torrent'):
            if link.kind in ("torrent", "magnet"):
                if link.info_hash and link.info_hash in seen_hashes:
                    continue
                try:
                    ev = torrent_evidence(link.torrent_bytes, candidate.title) if link.kind == "torrent" \
                         else magnet_evidence(link.value, candidate.title, timeout=25)
                    if ev.private:
                        continue
                    inspect_target(candidate.title, ev.files, target)
                except ValueError:
                    continue
                seen_hashes.add(ev.info_hash)
                magnet = next((item.value for item in resolved.links if item.kind == 'magnet'
                               and item.info_hash == ev.info_hash), None)
                results.append(MediaCandidate("public_bt", candidate.title, ev.video_bytes, ev.total_bytes,
                    candidate.candidate_id, info_hash=ev.info_hash,
                    link=magnet or (link.value if link.kind == "magnet" else f"magnet:?xt=urn:btih:{ev.info_hash}"),
                    files=ev.files, evidence={"subtitles": asdict(subtitle_evidence(files=ev.files)
                        if subtitle_evidence(files=ev.files).chinese else candidate.subtitles),
                        "target_path": self.p115_factory().target_path(target.media.media_type)}))
            elif link.kind == "115_share" and self.settings.share_115_enabled and target.scope != "series":
                adapter = self.p115_factory()
                ev = adapter.preview_share(link.value, candidate.title)
                inspect_target(candidate.title, ev.files, target)
                # A one-way share identity is enough for deduplication; never save its code.
                from .public_index import Mini4KIndexer
                results.append(MediaCandidate("115_share", candidate.title, ev.video_bytes, ev.total_bytes,
                    candidate.candidate_id, link=link.value, files=ev.files, file_ids=ev.root_ids,
                    evidence={"root_names": list(ev.root_names), "share_key": Mini4KIndexer._link_selector(link.value),
                        "target_path": adapter.target_path(target.media.media_type),
                        "subtitles": asdict(candidate.subtitles)}))
        if not results:
            raise ValueError("Mini4K 没有满足目标范围的公开 BT 或已启用分享")
        return results

    def health(self):
        return asdict(self.indexer_factory().health())


class MoviePilotDownloadAdapter:
    def __init__(self, p115_factory, authorize):
        self.p115_factory, self.guard_submission = p115_factory, authorize

    def submit(self, candidate, target):
        if candidate.source == "pt":
            from app.chain.download import DownloadChain
            download_hash, _ = DownloadChain().download_single(candidate.context,
                torrent_content=candidate.torrent_content, source="MediaAcquisition",
                username="MediaAcquisition", return_detail=True)
            return {"status": "submitted", "download_hash": download_hash} if download_hash else {"status": "pending"}
        adapter = self.p115_factory({'media_type': target.media.media_type,
            'target_path': candidate.evidence.get('target_path')})
        kind = target.media.media_type
        adapter.validate_target(kind)
        if candidate.source == "public_bt":
            accepted = bool(adapter.offline_task(candidate.info_hash)) or adapter.submit_magnet(candidate.link, kind)
        else:
            from .p115_task_adapter import ShareEvidence
            ev = ShareEvidence(candidate.files, candidate.video_bytes, candidate.total_bytes,
                               candidate.file_ids, tuple(candidate.evidence["root_names"]))
            if adapter.cloud_items(kind, ev.root_names):
                # Existing names alone are insufficient proof that this copy is ours.
                return {"status": "pending", "reason": "目标已有同名文件，需要核实分享转存回执"}
            accepted = adapter.submit_share(candidate.link, kind, ev)
        return {"status": "submitted" if accepted else "pending"}

    def status(self, record):
        if record.get("route") == "pt":
            from app.chain.download import DownloadChain
            rows = DownloadChain().list_torrents(hashs=[record.get("download_hash") or record.get("info_hash")],
                                                 include_all_tags=True)
            if rows:
                row = rows[0]
                progress = row.get("progress") if isinstance(row, dict) else getattr(row, "progress", None)
                return {"status": "submitted", "phase": "submitted",
                        "download_hash": record.get("download_hash") or record.get("info_hash"),
                        **({"progress": progress} if isinstance(progress, (int, float)) else {})}
        elif record.get("route") == "public_bt":
            row = self.p115_factory(record).offline_task(record["info_hash"])
            if row:
                status = int(row.get("status", 0))
                return {"status": "failed" if status == 1 else "completed" if status == 2 else "submitted",
                        "phase": "submitted", "progress": row.get("percentDone", row.get("percent", 0))}
        # A successful share submission already supplies its receipt. Merely observing
        # same-named files cannot upgrade an uncertain transfer to a confirmed receipt.
        return {}
