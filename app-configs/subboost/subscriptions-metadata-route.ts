import { timingSafeEqual } from "node:crypto";
import { decryptJsonObject } from "@local/lib/crypto";
import { prisma } from "@local/lib/prisma";

export const dynamic = "force-dynamic";

// Dedicated owner-scoped read capability. Never return subscription URLs, node
// snapshots, provider credentials, or the aggregate subscription-userinfo.
export async function GET(request: Request) {
  const token = process.env.SUBSCRIPTIONS_READ_TOKEN?.trim();
  const ownerId = process.env.SUBSCRIPTIONS_OWNER_ID?.trim();
  const supplied = request.headers.get("authorization") ?? "";
  const expected = Buffer.from(token ? `Bearer ${token}` : "");
  const suppliedBytes = Buffer.from(supplied);
  if (!token || !ownerId || suppliedBytes.length !== expected.length ||
      !timingSafeEqual(suppliedBytes, expected)) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const rows = await prisma.subscription.findMany({ where: { ownerId }, include: { autoUpdateState: true } });
  const items = [];
  for (const row of rows) {
    const config = decryptJsonObject(row.encryptedConfig);
    const sources = Array.isArray(config.sources) ? config.sources : [];
    for (const source of sources) {
      if (!source || typeof source !== "object" || source.type !== "url" || typeof source.id !== "string") continue;
      const userinfo: Record<string, number> = {};
      const info = source.subscriptionUserInfo;
      if (info && typeof info === "object") {
        for (const key of ["upload", "download", "total", "expire"]) {
          const value = info[key];
          if (typeof value === "number" && Number.isFinite(value) && value >= 0) userinfo[key] = value;
        }
      }
      items.push({
        id: `${row.id}:${source.id}`,
        name: typeof source.tag === "string" && source.tag.trim() ? source.tag.trim() : row.name,
        userinfo,
        observed_at: row.lastUpdatedAt?.toISOString() ?? null,
        stale: (row.autoUpdateState?.externalFailureCount ?? 0) > 0 || !!row.autoUpdateState?.disabledAt,
        valid_for_seconds: Math.min(86400, Math.max(900, (row.autoUpdateInterval ?? 1800) * 2)),
      });
    }
  }
  return Response.json({ items }, { headers: { "Cache-Control": "no-store" } });
}
