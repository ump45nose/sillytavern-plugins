# Movie query calibration: Gladiator (2000)

The live comparison evaluated 11 query variants on six sources: YouTube,
Bilibili, NetEase, QQ Music, Archive and TelevisionTunes (66 queries). Variants
included `theme`, `main title`, `main theme`, `main`, `music`, `soundtrack`, a
year-qualified theme query, `end credits`, and localized theme/OST/ending words.
Provider-ID resolvers were not treated as free-text search engines.

Titles, albums and performer evidence were inspected. Same-name rap songs and
game soundtracks were rejected; arrangements, covers and long compilations were
separated. These are metadata labels, not listening approval. Query utility is:
40 points for work precision in the first three results, 25 for clean versions,
25 for likely-original recordings, and up to 10 for related results in the first
ten. Top-k=3 then favors new result identities and preserves both original and
localized title queries when both performed well.

| Source | Adopted movie templates, in execution order | Observed behavior |
| --- | --- | --- |
| YouTube | `{local} 原声`; `{title} main title`; `{local} 主题曲` | Each selected query had three related results in its first three. Broad `music` returned long compilations. |
| Bilibili | `{local} 主题曲` | Only this measured query qualified. Later checks were unstable; request failures are not evidence that the words are irrelevant. |
| NetEase | `{local} 片尾曲`; `{title} main theme`; `{title} main title` | Localized queries found Hans Zimmer/Lisa Gerrard recordings; English queries add arrangement choices. `music` returned unrelated rap and `end credits` returned other works. |
| QQ Music | `{local} 主题曲`; `{title} soundtrack`; `{title} theme` | Localized/OST queries found the movie album; short `theme` adds alternate versions. `main title` and `end credits` were much less precise. |
| Archive | Keep the conservative licensed-audio route | No qualified movie theme in the sample; broad `music` found an unrelated same-name recording. |
| TelevisionTunes | Keep the existing series resolver | No matching movie audio in the sample; do not extrapolate that to series coverage. |

The selected movie profiles live in `emby_theme_worker/query_policy.py` and are
used source-by-source and round-by-round. An explicit keyword or identified theme
track may add a query, within the four-query ceiling. Network concurrency remains
two and the search budget remains 180 seconds. Series/anime opening queries and
automatic adoption thresholds are unchanged. One film is an initial calibration;
the twelve-title listening set is still needed to evaluate broader quality.

The experiment also exposed absent optional cookie files preventing downloads,
and Bilibili flat-playlist entries with no titles. Missing optional cookies now
use anonymous access without sharing another platform's cookies. Bilibili falls
back to its search metadata API for untitled entries, and rejected API responses
are errors rather than empty candidate lists. YouTube and a NetEase original
recording downloaded and decoded during the checks; the tested QQ version did
not download, and Bilibili remained unstable.

Reproduce on the private Worker environment with the repository script:

```sh
docker exec -i emby-theme-worker python - --item EMBY_ID --output /data/reports/query-results.json < scripts/query_benchmark.py
```

The reviewed labeling rubric is intentionally restricted to Gladiator (2000).
Use `--search-only`, `--sources`, and repeated `--query-template` arguments for
bounded checks. It does not write media files or production provider-health state,
and it saves source hashes rather than signed download addresses.
