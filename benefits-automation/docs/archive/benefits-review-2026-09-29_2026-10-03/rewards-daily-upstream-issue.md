### Version / environment

Microsoft-Rewards-Script 4.3.2, Linux container, existing authenticated desktop session, current Rewards dashboard (2026-09-29).

### Observed behavior

Daily Set URL-reward requests were acknowledged, but the dashboard's Daily activities counter remained 0/3. This is distinct from a missing login or failing snapshot: normal authenticated dashboard navigation worked.

The Daily activities section was collapsed (`aria-expanded=false`; its content was under a hidden-until-found ancestor). Expanding the section and clicking its visible offer links through the dashboard changed the counter progressively to 1/3, 2/3 and ultimately 3/3. A subsequent independent read-only dashboard reload confirmed 3/3. Some counter updates were delayed, so one immediate reload was insufficient.

### Expected behavior / suggested fix

Use the dashboard's visible daily-card navigation when the generic reportActivity path acknowledges without credit, and verify the daily progress counter after each activity. Do not treat an acknowledged server action as proof of credit. Skip already-completed cards and bound the read-only polling; do not repeatedly submit an unconfirmed offer.

In the local adapter, `workers.doDailySet` is disabled to avoid two daily executors. A separate adapter expands the Daily activities disclosure, opens each unfinished visible Bing/Rewards card once, then reloads the dashboard to verify `aria-valuenow` / `aria-valuemax`. The local scheduled path now independently verifies 3/3 and skips it when complete.

This is evidence from one account/day, not a claim that every future quiz/poll only requires opening its link. No account identifiers, credentials, or private browsing artifacts are included.
