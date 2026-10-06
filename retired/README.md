# Retired container schedules

These wrappers depended on the removed Docker scripts directory. The six
profile jobs are paused with a reason in the private Hermes scheduler store.
Current persistent services are managed by `nas-container-boot`, Docker restart
policies, and their application schedules. These files are retained for review;
deploying the repository does not resume their jobs.
