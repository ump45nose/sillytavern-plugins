# NAS host settings

`99-tailscale-forwarding.conf` is installed as
`/etc/sysctl.d/99-tailscale-forwarding.conf`. It makes the existing Tailscale
subnet router's forwarding settings persistent. The existing native IPv6
disable policy and the advertised `192.168.31.0/24` route remain in place.

The NAS has no UPS. On 2026-10-13, the unused NUT server and monitor were
disabled and `/etc/nut/nut.conf` was changed from `MODE=netserver` to
`MODE=none`. Device definitions, identities and credentials were retained.
Configuring a UPS later requires selecting its actual device or network
server, setting the appropriate mode and enabling the corresponding units.

Private repair backups are kept in
`/home/yuwk/.local/state/incident-diagnostics/2026-10-13/repairs`.

`shellcrash-journal.conf` is installed as
`/etc/systemd/system/shellcrash.service.d/20-journal.conf`. ShellCrash emits
warnings to the existing bounded persistent journal rather than discarding
stdout. Its local YAML keeps `log-level: warning`; request-by-request traffic
logging is not enabled. The existing root service identity, resolver,
proxy selection and routing are retained.

Docker's resolver forwards to the host ShellCrash listener first, then the
existing two public resolvers. No resolver loop was found. The historical
1024-query backlog has not recurred after reboot; its original request source
is still unknown. Enabling warning logs exposed current failures forwarding
UDP queries to `1.1.1.1:53` and `8.8.8.8:53` through the selected VLESS node.
`shellcrash-dns.cfg` switches those two external DNS upstreams to the same
providers' HTTPS endpoints. Domestic/bootstrap resolvers, DNS routing and
the existing ECS parameters remain unchanged. Merge only `dns_fallback` into
the private ShellCrash config, regenerate or reload the effective config,
and keep node credentials out of this repository. No Docker daemon or
unrelated container restart is needed.

DNS-over-HTTPS and its proxy routing are described in the
[Mihomo DNS documentation](https://wiki.metacubex.one/config/dns/).

Forwarding settings follow the
[Tailscale subnet-router documentation](https://tailscale.com/docs/features/subnet-routers#enable-ip-forwarding).
