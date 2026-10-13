# Retired container schedules

These original wrappers depended on the removed Docker scripts directory and
are retained only as historical source. Their six recurring schedules were
restored on 2026-10-06 using the working implementations in `hermes/`: audits
at the former stop times, startup repair at the former start times. The trusted
profile entrypoints and manifest point to those current implementations.
Persistent services use the canonical boot plan and Docker restart policies.
Deploying source alone does not modify the Hermes scheduler database.
