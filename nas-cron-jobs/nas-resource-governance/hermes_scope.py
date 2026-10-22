"""Preserve Hermes named worker scopes; resource policy lives in systemd."""
import sys


def scoped_command(argv, *, mode="interactive", unit_name=None, memory_max=None):
    command = list(argv)
    if sys.platform != "linux" or mode != "gateway_worker":
        return command
    # Workers survive a gateway reload; the hermes user slice caps them all.
    if command and command[0].rsplit("/", 1)[-1] == "systemd-run":
        return command
    args = ["/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--collect"]
    if unit_name:
        args += ["--unit", unit_name]
    return [*args, "--", *command]
