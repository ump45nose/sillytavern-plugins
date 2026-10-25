// Seeds the disposable visual instance (127.0.0.1:32014) with deterministic synthetic data.
// Run after `node scripts/local-runtime.mjs reset-visual`. Never points at validation or production.
import assert from "node:assert/strict";
import fs from "node:fs";
import { launch, session, ready, urls, ports } from "../browser.mjs";
import { fixture } from "./fixture.mjs";

assert.equal(new URL(urls.visual).port, String(ports.visual), "Seeding is limited to the disposable visual instance");
const directory = "docs/design/rp-desktop/assets/";
const assets = Object.fromEntries(
  ["r-character.webp", "r-user-character.webp", "r-background.webp"].map((file) => [
    file,
    fs.readFileSync(directory + file).toString("base64"),
  ]),
);

const browser = await launch();
try {
  // Default session flags: helper/probe overrides would intercept settings saves.
  const { page, errors } = await session(browser);
  await page.setViewportSize({ width: 1496, height: 817 });
  await ready(page, urls.visual, { probe: true });
  const result = await page.evaluate(
    async ({ fixture, assets }) => {
      const c = SillyTavern.getContext();
      const h = workbench.host;
      const json = (body) => ({ method: "POST", headers: c.getRequestHeaders(), body: JSON.stringify(body) });
      const image = (file) =>
        new File([Uint8Array.from(atob(assets[file]), (ch) => ch.charCodeAt(0))], file, {
          type: "image/webp",
        });
      const upload = async (endpoint, fields, file, filename) => {
        const body = new FormData();
        for (const [key, value] of Object.entries(fields)) body.set(key, value);
        if (file) body.set("avatar", image(file), filename || file);
        const headers = { ...c.getRequestHeaders() };
        delete headers["Content-Type"];
        const response = await fetch(endpoint, { method: "POST", headers, body });
        if (!response.ok) throw new Error(`${endpoint}: ${response.status}`);
        return response.text();
      };

      // Characters (with avatars where the fixture provides one).
      for (const card of fixture.characters) {
        if (c.characters.some((x) => x.name === card.name)) continue;
        await upload(
          "/api/characters/create",
          {
            ch_name: card.name,
            description: card.description,
            personality: card.personality || "",
            scenario: card.scenario || "",
            first_mes: card.first_mes,
            creator_notes: "workbench-visual-fixture",
            tags: card.tags.join(","),
            fav: card.fav ? "true" : "false",
          },
          card.avatar,
        );
      }
      await c.getCharacters();

      // World books: built with the official entry factory so every default field exists.
      const wi = await import("/scripts/world-info.js");
      for (const book of fixture.worlds) {
        const data = { entries: {} };
        for (const entry of book.entries) Object.assign(wi.createWorldInfoEntry(book.name, data), entry);
        await c.saveWorldInfo(book.name, data, true);
      }
      await c.updateWorldInfoList();
      for (const book of fixture.worlds) if (book.enabled) await h.toggleBook(book.name, true);

      // Personas share uploaded avatar files; descriptions use the native settings shape.
      for (const persona of fixture.personas) {
        const file = await upload(
          "/api/avatars/upload",
          { overwrite_name: persona.file },
          "r-user-character.webp",
        );
        const id = JSON.parse(file).path || persona.file;
        c.powerUserSettings.personas[id] = persona.name;
        c.powerUserSettings.persona_descriptions[id] = {
          description: persona.description,
          title: persona.title,
          position: 0,
          depth: 2,
          role: 0,
          lorebook: "",
        };
      }

      // Presets: a copy of the active Chat Completion preset with a few deliberate differences.
      const manager = c.getPresetManager();
      for (const preset of fixture.presets) {
        if (manager.getAllPresets().includes(preset.name)) continue;
        await manager.savePreset(preset.name, {
          ...h.presetData(manager.getSelectedPresetName()),
          ...preset.values,
        });
      }

      // Connection profiles with manual model groups (an intentional workbench feature).
      const cm = c.extensionSettings.connectionManager;
      for (const profile of fixture.profiles) {
        if (!cm.profiles.some((p) => p.id === profile.id))
          cm.profiles.push({
            mode: "cc",
            api: "custom",
            "api-url": fixture.mockApi,
            ...profile.data,
            id: profile.id,
            name: profile.name,
          });
      }
      h.preference({ groups: Object.fromEntries(fixture.profiles.map((p) => [p.id, p.group])) });

      // Main chat with a fixed history; timestamps are constant so screenshots are stable.
      const actor = c.characters.find((x) => x.name === fixture.chat.character);
      const header = {
        user_name: fixture.chat.user,
        character_name: actor.name,
        create_date: fixture.chat.created,
        chat_metadata: {
          workbenchRP: { scene: fixture.chat.scene },
        },
      };
      const messages = fixture.chat.messages.map((m, i) => ({
        name: m.user ? fixture.chat.user : actor.name,
        is_user: !!m.user,
        is_system: false,
        send_date: fixture.chat.dates[i % fixture.chat.dates.length],
        mes: m.text,
        extra: {},
        swipes: [m.text],
        swipe_id: 0,
      }));
      const saved = await fetch(
        "/api/chats/save",
        json({
          ch_name: actor.name,
          file_name: fixture.chat.file,
          chat: [header, ...messages],
          avatar_url: actor.avatar,
          force: true,
        }),
      );
      if (!saved.ok) throw new Error("chat save failed " + saved.status);

      // RP presentation: character sprite and chat background, as the RP demo does.
      await upload("/api/sprites/upload", { name: actor.name, label: "neutral" }, "r-character.webp");
      await upload("/api/sprites/upload", { name: "workbench-visual-user", label: "neutral" }, "r-user-character.webp");
      const background = await upload(
        "/api/backgrounds/upload",
        {},
        "r-background.webp",
        "workbench-visual-sakura.webp",
      );

      await c.selectCharacterById(c.characters.indexOf(actor));
      await c.openCharacterChat(fixture.chat.file);
      const current = SillyTavern.getContext();
      const backgroundPath = "backgrounds/" + encodeURIComponent(background);
      current.chatMetadata.custom_background = `url("${backgroundPath}")`;
      current.chatMetadata.chat_backgrounds = [backgroundPath];
      // The stage reads sprites from the native expressions extension; the chat supplies them here.
      current.chatMetadata.workbenchRP = {
        ...current.chatMetadata.workbenchRP,
        characterSprite: "/characters/" + encodeURIComponent(actor.name) + "/neutral.webp",
        userSprite: "/characters/workbench-visual-user/neutral.webp",
      };
      await current.saveMetadata();

      (await import("/script.js")).setActiveCharacter(actor.avatar);
      current.powerUserSettings.auto_load_chat = true;
      const firstPersona = Object.keys(current.powerUserSettings.personas).find(
        (id) => current.powerUserSettings.personas[id] === fixture.personas[0].name,
      );
      if (firstPersona) await h.select("persona", firstPersona);
      h.preference({ layout: "novel", left: true });
      await h.persistSettings();
      return {
        chat: current.chatId,
        characters: current.characters.length,
        worlds: current.getWorldInfoNames(),
      };
    },
    { fixture, assets },
  );
  // Reload proves the state is persistent rather than session-only.
  await ready(page, urls.visual, { probe: true });
  const reopened = await page.evaluate(() => ({
    chat: SillyTavern.getContext().chatId,
    messages: SillyTavern.getContext().chat.length,
  }));
  assert.equal(reopened.chat, fixture.chat.file);
  assert.equal(reopened.messages, fixture.chat.messages.length);
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ ...result, reopened }, null, 2));
} finally {
  await browser.close();
}
