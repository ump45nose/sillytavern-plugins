import fs from "node:fs";
import http from "node:http";
import crypto from "node:crypto";
// LAN entry for phone acceptance: basic auth with the local .env test credentials, then a plain
// proxy to the 127.0.0.1 instance.
// Usage: node scripts/lan-proxy.mjs [lan-ip=0.0.0.0] [lan-port=32124] [local-port=32014] [env-file=.env]
const [lanIp = "0.0.0.0", lanPort = "32124", localPort = "32014", envFile = ".env"] = process.argv.slice(2);
const env = Object.fromEntries(
  fs
    .readFileSync(envFile, "utf8")
    .split("\n")
    .filter((l) => l.includes("="))
    .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
);
if (!env.WB_USERNAME || !env.WB_PASSWORD) throw new Error("credentials missing");
const expected = Buffer.from("Basic " + Buffer.from(`${env.WB_USERNAME}:${env.WB_PASSWORD}`).toString("base64"));
const authorized = (header = "") => {
  const given = Buffer.from(header);
  return given.length === expected.length && crypto.timingSafeEqual(given, expected);
};
http
  .createServer((req, res) => {
    if (!authorized(req.headers.authorization)) {
      res.writeHead(401, { "WWW-Authenticate": 'Basic realm="workbench-visual"', "Content-Type": "text/plain" });
      return res.end("Unauthorized");
    }
    const headers = { ...req.headers, host: `127.0.0.1:${localPort}` };
    for (const key of ["origin", "referer"])
      if (headers[key]) headers[key] = headers[key].replace(/\/\/[^/]+/, `//127.0.0.1:${localPort}`);
    const upstream = http.request({ host: "127.0.0.1", port: localPort, method: req.method, path: req.url, headers }, (reply) => {
      res.writeHead(reply.statusCode, reply.headers);
      reply.pipe(res);
    });
    upstream.on("error", () => res.destroy());
    req.pipe(upstream);
  })
  .listen(Number(lanPort), lanIp, () => console.log(`http://${lanIp}:${lanPort} -> 127.0.0.1:${localPort} (basic auth)`));
