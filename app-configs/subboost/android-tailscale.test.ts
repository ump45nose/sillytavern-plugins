import { describe, expect, it } from "vitest";
import { dump, load } from "js-yaml";
import { applyAndroidTailscaleProfile } from "./android-tailscale";

const base = {
  mode: "rule",
  proxies: [{ name: "overseas", type: "trojan", server: "proxy.example", port: 443, password: "test" }],
  "proxy-groups": [
    { name: "auto", type: "url-test", proxies: ["overseas"], url: "https://example.com", interval: 300 },
    { name: "select", type: "select", proxies: ["auto", "overseas", "DIRECT"] },
  ],
  "rule-providers": { china: { type: "http", behavior: "domain", url: "https://example.com/cn.yaml" } },
  rules: ["IP-CIDR,192.168.0.0/16,DIRECT,no-resolve", "RULE-SET,china,DIRECT", "MATCH,select"],
  dns: {
    "enhanced-mode": "fake-ip", "respect-rules": true,
    nameserver: ["https://dns.example/dns-query"],
    "proxy-server-nameserver": ["1.1.1.1"],
    "fake-ip-filter": ["*.ts.net", "+.lan"],
    "nameserver-policy": { "+.example.cn": ["223.5.5.5"] },
  },
};

describe("Android Tailnet subscription overlay", () => {
  it("preserves public proxies, groups, providers and the original rule tail", () => {
    const result = load(applyAndroidTailscaleProfile(dump(base))) as typeof base;
    expect(result.proxies.slice(0, -1)).toEqual(base.proxies);
    expect(result["proxy-groups"]).toEqual(base["proxy-groups"]);
    expect(result["rule-providers"]).toEqual(base["rule-providers"]);
    expect(result.rules.slice(4)).toEqual(base.rules);
    expect(result.rules.slice(0, 4)).toEqual([
      "DOMAIN-SUFFIX,tail0292a9.ts.net,TAILNET",
      "IP-CIDR,100.64.0.0/10,TAILNET,no-resolve",
      "IP-CIDR6,fd7a:115c:a1e0::/48,TAILNET,no-resolve",
      "IP-CIDR,192.168.31.0/24,TAILNET,no-resolve",
    ]);
    expect(result.proxies.at(-1)).toEqual({
      name: "TAILNET", type: "tailscale", hostname: "xiaomi-14-pro-mihomo",
      "state-dir": "tailscale/android-mihomo", "accept-routes": true, ephemeral: false, udp: true,
    });
  });

  it("routes only Tailnet DNS to ts:// and retains public DNS settings", () => {
    const result = load(applyAndroidTailscaleProfile(dump(base))) as typeof base;
    expect(result.dns.nameserver).toEqual(base.dns.nameserver);
    expect(result.dns["proxy-server-nameserver"]).toEqual(base.dns["proxy-server-nameserver"]);
    expect(result.dns["nameserver-policy"]).toEqual({
      "+.tail0292a9.ts.net": ["ts://TAILNET"], "+.example.cn": ["223.5.5.5"],
    });
    expect(result.dns["fake-ip-filter"]).toEqual(["*.ts.net", "+.lan", "+.tail0292a9.ts.net"]);
  });

  it("excludes Tailnet from include-all groups without losing existing exclusions", () => {
    const input = { ...base, "proxy-groups": [
      { name: "all", type: "url-test", "include-all": true, "exclude-filter": "expire|quota" },
      { name: "all-proxies", type: "select", "include-all-proxies": true },
    ] };
    const result = load(applyAndroidTailscaleProfile(dump(input))) as typeof input;
    expect(result["proxy-groups"][0]["exclude-filter"]).toBe("(?:expire|quota)|^TAILNET$");
    expect(result["proxy-groups"][1]["exclude-filter"]).toBe("^TAILNET$");
  });

  it("fails on name conflicts rather than returning an ambiguous subscription", () => {
    const input = { ...base, "proxy-groups": [{ name: "TAILNET", type: "select", proxies: ["DIRECT"] }] };
    expect(() => applyAndroidTailscaleProfile(dump(input))).toThrow("reserved proxy name conflict");
  });

  it("fails when fake-IP whitelist semantics would override the Tailnet exclusion", () => {
    const input = { ...base, dns: { ...base.dns, "fake-ip-filter-mode": "whitelist" } };
    expect(() => applyAndroidTailscaleProfile(dump(input))).toThrow("requires a fake-IP blacklist");
  });
});
