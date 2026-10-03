from __future__ import annotations

import re
import unicodedata
from rapidfuzz.fuzz import partial_ratio, ratio
from .models import Candidate, MediaItem

THEME = re.compile(r"\b(main theme|theme song|official theme|main titles?|opening|end credits|ending theme|op\s*1|ed\s*1)\b|主题曲|主題曲|片头曲|片尾曲", re.I)
NEGATIVE = {"cover": 30, "remix": 35, "live": 20, "karaoke": 40, "trailer": 35, "reaction": 50, "playlist": 30, "翻唱": 35, "混剪": 35, "现场": 20, "伴奏": 35}

def normalize(text: str | None) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", text or "").casefold()).split())

def score_candidate(candidate: Candidate, item: MediaItem, consensus: int = 1) -> int:
    if candidate.exact:
        candidate.score = 100
        candidate.metadata["score_details"] = {candidate.metadata.get('identity_kind','exact_identity'): 100}
        return 100
    evidence = candidate.title + " " + str(candidate.metadata.get("album_title") or "")
    titles = [normalize(t) for t in [item.name, item.original_title, *item.aliases] if t]
    date_evidence=normalize(evidence)
    for title in sorted(titles,key=len,reverse=True):date_evidence=date_evidence.replace(title,' ')
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", date_evidence))
    if candidate.year is None and len(years) == 1:
        candidate.year = int(next(iter(years)))
    movie = bool(re.search(r"\b(movie|film|motion picture)\b|电影|電影", evidence, re.I))
    series = bool(re.search(r"\b(tv|television|series)\b|电视剧|電視劇", evidence, re.I))
    if not candidate.media_type and movie != series:
        candidate.media_type = "Movie" if movie else "Series"
    conflict = bool(item.year and candidate.year and abs(item.year-candidate.year) > 1)
    conflict |= bool(candidate.media_type and candidate.media_type.casefold() != item.item_type.casefold())
    seasons = re.findall(r'\b(?:season\s*|s)(\d{1,2})\b', evidence, re.I)
    expected_season = re.search(r'\b(?:season\s*|s)(\d{1,2})\b', item.name+' '+(item.original_title or ''), re.I)
    if seasons and item.item_type == 'Series':
        conflict |= any(int(s) != (int(expected_season.group(1)) if expected_season else 1) for s in seasons)
    similarity = max((partial_ratio(normalize(evidence), t) for t in titles), default=0)
    association = round(similarity * .40)
    theme = bool(THEME.search(evidence)) or (candidate.provider=='televisiontunes' and bool(candidate.metadata.get('curated_source')))
    channel = str(candidate.metadata.get("channel") or "")
    trusted = bool(candidate.metadata.get("channel_verified") or candidate.metadata.get("curated_source"))
    details = {"association": association, "theme": 25 if theme else 0,
               "provenance": 15 if trusted else (10 if channel.endswith(" - Topic") else 0),
               "duration": 10 if candidate.duration and 30 <= candidate.duration <= 600 else 0,
               "consensus": min(10, max(0, consensus-1)*5)}
    penalty = 0
    lowered = normalize(candidate.title)
    for title in sorted(titles, key=len, reverse=True):
        lowered = lowered.replace(title, " ")
    for term, value in NEGATIVE.items():
        match = re.search(r"\b"+re.escape(term)+r"\b", lowered) if term.isascii() else term in lowered
        if match:
            penalty += value
    details["penalty"] = -penalty
    candidate.score = 0 if conflict else max(0, min(100, sum(details.values())))
    candidate.metadata.update(score_details=details, automatic_eligible=theme and association >= 34 and not conflict,
                              rejection="identity_conflict" if conflict else ("missing_theme_semantics" if not theme else None))
    return candidate.score

def score_all(candidates: list[Candidate], item: MediaItem) -> list[Candidate]:
    unique = {}
    for candidate in candidates:
        previous = unique.get(candidate.source_url)
        if previous is None or (candidate.exact and not previous.exact):
            unique[candidate.source_url] = candidate
    values = list(unique.values())
    for candidate in values:
        providers = {c.provider for c in values if ratio(normalize(c.title), normalize(candidate.title)) >= 85}
        score_candidate(candidate, item, len(providers))
    exact_order={'animethemes':0,'themerrdb':1,'plex_tv':2}
    return sorted(values, key=lambda c: (-int(c.exact),-c.score,exact_order.get(c.provider,9)))
