#!/usr/bin/env python3
"""Verify a deployed profile using a private baseline; never print tokens or YAML."""
import argparse
import json
import os
import pathlib
import subprocess
import urllib.error
import urllib.request


def parse_yaml(data, container):
    code = "const fs=require('fs'),y=require('js-yaml');process.stdout.write(JSON.stringify(y.load(fs.readFileSync(0,'utf8'))));"
    result = subprocess.run(["docker", "exec", "-i", container, "node", "-e", code],
                            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return json.loads(result.stdout)


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


def verify(baseline, base_url, container):
    profile = json.loads((pathlib.Path(__file__).parent / "android-tailscale.json").read_text())
    rows = json.loads((baseline / "subscriptions.encrypted.json").read_text())
    assert len(rows) == 1, "Select the correct subscription before validating"
    url = base_url.rstrip("/") + "/api/subscriptions/" + rows[0]["token"] + "/config.yaml"
    mobile_url = url + "?profile=android-tailscale"
    status, normal, normal_headers = fetch(url)
    assert status == 200, "Normal subscription request failed"
    assert normal == (baseline / "subscription.before.yaml").read_bytes(), "Normal subscription changed"
    status, mobile, headers = fetch(mobile_url)
    assert status == 200, "Mobile subscription request failed"
    original = parse_yaml(normal, container)
    result = parse_yaml(mobile, container)
    expected_node = {"name": profile["name"], "type": "tailscale", "hostname": profile["hostname"],
                     "state-dir": profile["stateDir"], "accept-routes": True, "ephemeral": False, "udp": True}
    assert result["proxies"] == original["proxies"] + [expected_node], "Public proxies changed"
    expected_rules = ["DOMAIN-SUFFIX," + profile["tailnetDomain"] + "," + profile["name"],
                      "IP-CIDR,100.64.0.0/10," + profile["name"] + ",no-resolve",
                      "IP-CIDR6,fd7a:115c:a1e0::/48," + profile["name"] + ",no-resolve"]
    expected_rules += ["IP-CIDR," + subnet + "," + profile["name"] + ",no-resolve" for subnet in profile["homeSubnets"]]
    assert result["rules"] == expected_rules + original["rules"], "Rule precedence or existing rules changed"
    assert result["mode"] == "rule", "Phone profile requires rule mode"
    for key in original:
        if key not in ("proxies", "rules", "dns", "mode", "proxy-groups"):
            assert result[key] == original[key], "Unexpected top-level change: " + key
    expected_groups = json.loads(json.dumps(original.get("proxy-groups", [])))
    for group in expected_groups:
        if group.get("include-all") or group.get("include-all-proxies"):
            existing = group.get("exclude-filter")
            group["exclude-filter"] = ("(?:" + existing + ")|" if existing else "") + "^TAILNET$"
    assert result.get("proxy-groups", []) == expected_groups, "Proxy group candidates changed"
    expected_dns = json.loads(json.dumps(original.get("dns", {})))
    policy = expected_dns.get("nameserver-policy", {})
    for key in (profile["tailnetDomain"], "*." + profile["tailnetDomain"], "+." + profile["tailnetDomain"]):
        policy.pop(key, None)
    policy["+." + profile["tailnetDomain"]] = ["ts://" + profile["name"]]
    expected_dns["nameserver-policy"] = policy
    expected_dns["fake-ip-filter"] = list(dict.fromkeys(expected_dns.get("fake-ip-filter", []) + ["+." + profile["tailnetDomain"]]))
    assert result["dns"] == expected_dns, "Unexpected DNS change"
    for key in ("profile-update-interval", "subscription-userinfo", "cache-control", "content-type"):
        assert headers.get(key) == normal_headers.get(key), "Subscription header changed: " + key
    assert fetch(url + "?profile=unknown")[0] == 400, "Unknown profiles must fail"
    assert fetch(base_url.rstrip("/") + "/api/subscriptions/invalid-test-token/config.yaml?profile=android-tailscale")[0] == 404, "Invalid tokens must fail"
    for name, data in (("mobile-subscription.private.txt", (mobile_url + "\n").encode()),
                       ("mobile-config.private.yaml", mobile)):
        path = baseline / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
        os.chmod(path, 0o600)
    print("Verified: original subscription unchanged;", len(original["proxies"]),
          "public proxies;", len(original["rules"]), "original rules;",
          len(expected_rules), "Tailnet rules; DNS, groups, auth and update headers correct.")
    print("Private mobile import files:", baseline)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=pathlib.Path)
    parser.add_argument("--url", default="http://127.0.0.1:13000")
    parser.add_argument("--container", default="subboost-app-1")
    arguments = parser.parse_args()
    verify(arguments.baseline, arguments.url, arguments.container)
