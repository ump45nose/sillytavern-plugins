# Token Monitor adapters

`usage-monitor/` preserves the existing independently running Usage Monitor MCP
adapter. It was moved out of the retired Personal Data Hub without changing
its data sources, interfaces, OAuth, container or schedule. Token Monitor itself
continues in its existing upstream checkout and production deployment.

The Mac account adapter targets the verified installed 0.75.0 source, identified
by `prepare.py` hashes; it does not patch the older NAS agent. Run
`python3 prepare.py SOURCE EMPTY_DESTINATION`, then
`python3 apply-app.py ORIGINAL_APP PREPARED_SOURCE OUTPUT_APP`. Verify and sign the
candidate with the original signing policy before replacing the installed app.
Keep the original app and private data in a separate backup; neither belongs in Git.

The adapter serves authenticated account operations on a random IPv4 loopback
port. `local-account-control.json` in the app's user-data directory contains only
the private process token, port and protocol version; provider credentials remain
in Token Monitor. The file is removed on exit. Hub only uses this local interface
and the existing NAS quota synchronization. An upstream app replacement needs
the adapter reapplied; clients detect missing/incompatible capability explicitly.
