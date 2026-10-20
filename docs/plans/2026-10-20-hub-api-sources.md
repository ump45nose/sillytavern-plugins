# Hub API NAS source and boot integration

Scope: register the new independently deployed hub-api in the NAS boot plan and later
add read-only usage-monitor HTTP in its existing source. Hub API itself lives outside
this aggregate repository at `/home/yuwk/src/personal-hub`.

This worktree owns only the hub-api boot-plan line, usage-monitor source and this plan.
Main has unrelated uncommitted boot cleanup; never copy or commit those edits.
Deploy only the added boot-plan line into the current deployed file, preserving its
other entries and the unrelated retired Tailscale cleanup.

Acceptance: boot --check adds no new unexplained differences; usage HTTP is read-only,
authenticated, reuses the existing business implementation and has meaningful tests.
Before rebuilding/restarting usage-monitor, notify the user. No other source is restarted.

Progress: boot registration prepared; usage-monitor implementation pending step 4.
