import { useSyncExternalStore } from "react";
import type { HostAdapter } from "../host/adapter";

/** The database plug-in's tables and status, re-rendered on every plug-in update. */
export function useDatabase(host: HostAdapter) {
  return useSyncExternalStore(host.database.subscribe, () => host.database.state);
}
