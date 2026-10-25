import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";

// Minimal SillyTavern context: enough for the slice builders.
const st = {
  chat: [],
  characters: [{ avatar: "a.png", name: "Alice", data: { tags: [] } }],
  characterId: "0",
  chatId: "Alice - 1.jsonl",
  groups: [],
  onlineStatus: "Valid",
  mainApi: "openai",
  extensionSettings: { workbench: {}, connectionManager: { profiles: [], selectedProfile: "" } },
  powerUserSettings: { personas: {} },
  getPresetManager: () => ({ getAllPresets: () => [], getSelectedPresetName: () => "" }),
  getWorldInfoNames: () => [],
  getThumbnailUrl: (kind, id) => `${kind}/${id}`,
  saveSettingsDebounced() {},
};
globalThis.document = { getElementById: () => null };
globalThis.window = { SillyTavern: { getContext: () => st } };
const { outputFiles } = await build({
  entryPoints: [new URL("../src/host/core.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  write: false,
});
const { HostCore, messagePreview } = await import(
  "data:text/javascript;base64," + Buffer.from(outputFiles[0].text).toString("base64")
);
const message = (mes, is_user = false) => ({ name: is_user ? "You" : "Alice", is_user, mes, send_date: 1 });

test("slices are cached until invalidated, and dependents go stale with them", () => {
  const host = new HostCore();
  const session = host.slice("session"),
    resources = host.slice("resources");
  assert.equal(host.slice("session"), session);
  assert.equal(session.character.name, "Alice");
  host.invalidate("characters");
  assert.notEqual(host.slice("session"), session, "session embeds the active character");
  assert.equal(host.slice("resources"), resources);
  host.invalidate("prefs");
  assert.notEqual(host.slice("resources"), resources, "connection grouping reads prefs");
});

test("slice subscribers only hear their own slices; global subscribers hear everything", () => {
  const host = new HostCore();
  const heard = { session: 0, chat: 0, all: 0 };
  host.subscribeSlice("session", () => heard.session++);
  host.subscribeSlice("chat", () => heard.chat++);
  host.subscribe(() => heard.all++);
  host.invalidate("chat");
  assert.deepEqual(heard, { session: 0, chat: 1, all: 1 });
  host.invalidate("characters");
  assert.deepEqual(heard, { session: 1, chat: 1, all: 2 });
  host.refresh();
  assert.deepEqual(heard, { session: 2, chat: 2, all: 3 });
});

test("updateMessage re-indexes one floor and appends new ones without rebuilding the rest", () => {
  const host = new HostCore();
  st.chat = [message("<p>Hello   there</p>"), message("hi", true)];
  const first = host.slice("chat");
  assert.equal(first[0].preview, "Hello there");
  st.chat[1] = message("edited", true);
  st.chat.push(message("reply"));
  host.updateMessage(1);
  const next = host.slice("chat");
  assert.notEqual(next, first);
  assert.equal(next[0], first[0], "untouched floors keep their identity");
  assert.equal(next[1].preview, "edited");
  assert.equal(next[2].preview, "reply");
  st.chat.splice(0, 1);
  host.updateMessage(0);
  assert.equal(host.slice("chat").length, 2, "a shorter chat falls back to a full rebuild");
});

test("snapshot assembles the slices and keeps identity until something changes", () => {
  const host = new HostCore();
  const snap = host.snapshot();
  assert.equal(host.snapshot(), snap);
  assert.equal(snap.messages, host.slice("chat"));
  assert.equal(snap.chatName, "Alice - 1");
  host.invalidate("chat");
  assert.notEqual(host.snapshot(), snap);
  assert.equal(host.snapshot().characters, snap.characters);
});

test("previews strip markup and collapse whitespace", () => {
  assert.equal(messagePreview("<b>a</b>\n\n  b"), "a b");
  assert.equal(messagePreview(undefined), "");
  assert.equal(messagePreview("x".repeat(200)).length, 120);
});
