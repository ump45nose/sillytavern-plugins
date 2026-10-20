// Headless helper for the pinned official MCP package. No token is printed.
// Its own SDK stores tokens-mcp.json under the runtime account's .plaud/.
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const root = process.argv[2];
if (!root) throw new Error("Pass the installed @plaud-ai/mcp package directory");
const pkg = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
if (pkg.name !== "@plaud-ai/mcp" || pkg.version !== "0.3.13") {
  throw new Error("OAuth helper requires the pinned official MCP 0.3.13");
}
const { getClient } = await import(pathToFileURL(join(root, "dist/chunk-KPVIF2OM.js")));
const { runOAuthCallback } = await import(pathToFileURL(join(root, "dist/chunk-LSO6O3TP.js")));
const client = getClient();
try {
  if (await client.auth.getAccessToken()) {
    await client.getCurrentUser();
    process.stdout.write(JSON.stringify({ status: "already_authenticated" }) + "\n");
    process.exit(0);
  }
  const { url, codeVerifier, state } = client.auth.createAuthorizationRequest();
  const result = await runOAuthCallback({
    port: 8199,
    expectedState: state,
    timeoutMs: 15 * 60 * 1000,
    onListening() {
      process.stdout.write(JSON.stringify({ status: "waiting_authorization", url, callback_port: 8199,
                                            expires_in_seconds: 900 }) + "\n");
    },
    async exchangeCode(code) {
      await client.auth.exchangeCode(code, codeVerifier, state);
    },
  });
  if (result.status !== "success") {
    process.stdout.write(JSON.stringify({ status: "authorization_failed", reason: result.status }) + "\n");
    process.exit(2);
  }
  await client.getCurrentUser();
  process.stdout.write(JSON.stringify({ status: "authenticated", account_verified: true }) + "\n");
} catch {
  // SDK exchange errors may include sensitive response bodies; do not print them.
  process.stdout.write(JSON.stringify({ status: "authorization_failed", reason: "upstream_or_credentials_error" }) + "\n");
  process.exitCode = 2;
}
