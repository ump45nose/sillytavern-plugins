"""Shared resource inspection; consumers retain selection and failure policy."""
from dataclasses import asdict

from .evidence import magnet_evidence, magnet_hash, torrent_evidence
from .policies import inspect_target, subtitle_evidence
from .quality_selection import MediaCandidate
from .public_index import Mini4KIndexer


def pt_candidate(content, title, candidate_id, context, target, subtitles=None, seeders=0):
    evidence = torrent_evidence(content, title)
    inspect_target(title, evidence.files, target)
    subs = subtitle_evidence(files=evidence.files)
    if not subs.chinese and subtitles is not None:
        subs = subtitles
    return MediaCandidate('pt', title, evidence.video_bytes, evidence.total_bytes,
        candidate_id or evidence.info_hash, info_hash=evidence.info_hash,
        torrent_content=content, context=context, files=evidence.files,
        evidence={'subtitles': asdict(subs), 'seeders': seeders})


def public_candidates(links, candidate, target, p115_factory, *, share_enabled=False):
    """Inspect each BT hash once; report errors for the caller's pause policy."""
    results, errors, seen_hashes = [], [], set()
    for link in sorted(links, key=lambda item: item.kind != 'torrent'):
        try:
            if link.kind in ('torrent', 'magnet'):
                digest = link.info_hash or (magnet_hash(link.value) if link.kind == 'magnet' else '')
                if digest.lower() in seen_hashes:
                    continue
                ev = torrent_evidence(link.torrent_bytes, candidate.title) if link.kind == 'torrent' \
                    else magnet_evidence(link.value, candidate.title, timeout=25)
                if ev.private:
                    raise ValueError('private BT，禁止提交 115')
                inspect_target(candidate.title, ev.files, target)
                if ev.info_hash in seen_hashes:
                    continue
                seen_hashes.add(ev.info_hash)
                magnet = next((item.value for item in links if item.kind == 'magnet'
                               and (item.info_hash or '').lower() == ev.info_hash), None)
                subs = subtitle_evidence(files=ev.files)
                if not subs.chinese:
                    subs = candidate.subtitles
                results.append(MediaCandidate('public_bt', candidate.title, ev.video_bytes, ev.total_bytes,
                    candidate.candidate_id, info_hash=ev.info_hash,
                    link=magnet or (link.value if link.kind == 'magnet' else f'magnet:?xt=urn:btih:{ev.info_hash}'),
                    files=ev.files, evidence={'subtitles': asdict(subs)}))
            elif link.kind == '115_share' and share_enabled and target.scope != 'series':
                ev = p115_factory().preview_share(link.value, candidate.title)
                inspect_target(candidate.title, ev.files, target)
                results.append(MediaCandidate('115_share', candidate.title, ev.video_bytes, ev.total_bytes,
                    candidate.candidate_id, link=link.value, files=ev.files, file_ids=ev.root_ids,
                    evidence={'root_names': list(ev.root_names),
                        'share_key': Mini4KIndexer._link_selector(link.value),
                        'subtitles': asdict(candidate.subtitles)}))
        except Exception as exc:
            errors.append(exc)
    return results, errors
