import assert from "node:assert/strict";
import fs from "node:fs";
import { launch, session, ready, urls, artifacts } from "./browser.mjs";

// Explicitly configures the existing validation account. No model calls or service changes.
// Dedicated resources and chat metadata keep the user's existing cards/persona intact.
const name = "白芷 · RP立绘演示";
const chatName = "RP双立绘演示";
const marker = "workbench-rp-two-sprites-v1";
const directory = "docs/design/rp-desktop/assets/";
const assets = Object.fromEntries(["r-character.webp", "r-user-character.webp", "r-background.webp"].map(file => [file, fs.readFileSync(directory + file).toString("base64")]));
assert.equal(new URL(urls.validation).port, "32012", "Only the validation instance can be configured");

const browser = await launch();
try {
  const { page, errors } = await session(browser);
  await page.setViewportSize({ width:1496, height:817 });
  await ready(page, urls.validation, { probe:true });
  const initial = await page.evaluate(() => {
    const c = SillyTavern.getContext();
    return { persona:workbench.host.snapshot().current.persona, name:c.name1, expressions:JSON.stringify(c.extensionSettings.expressions) };
  });
  const configured = await page.evaluate(async ({ name, chatName, marker, assets }) => {
    const c = SillyTavern.getContext();
    if (workbench.host.snapshot().busy) throw new Error("Wait for the current generation to finish before configuring the demo");
    const image = file => new File([Uint8Array.from(atob(assets[file]), char => char.charCodeAt(0))], file, { type:"image/webp" });
    const upload = async (endpoint, fields, file, filename) => {
      const body = new FormData();
      for (const [key, value] of Object.entries(fields)) body.set(key, value);
      body.set("avatar", image(file), filename || file);
      const headers = { ...c.getRequestHeaders() }; delete headers["Content-Type"];
      const response = await fetch(endpoint, { method:"POST", headers, body });
      if (!response.ok) throw new Error(`${endpoint}: ${response.status}`);
      return response.text();
    };
    let actor = c.characters.find(item => item.name === name);
    if (actor) {
      // List entries are shallow; verify the full card before reusing a matching name.
      const response = await fetch("/api/characters/get", { method:"POST", headers:c.getRequestHeaders(), body:JSON.stringify({ avatar_url:actor.avatar }) });
      if (!response.ok) throw new Error("Demo character could not be inspected");
      const card = await response.json();
      if (card.creatorcomment !== marker && card.data?.creator_notes !== marker) throw new Error("Demo name is already used by a different character");
    }
    if (!actor) {
      await upload("/api/characters/create", {
        ch_name:name, description:"白芷，樱花小径上的旧友。此角色用于已确认 RP 布局的双立绘演示。",
        first_mes:"*夕阳穿过樱花，落在白芷手中的书页上。她抬起头，笑着走近。*\n\n\"你来了。沿着这条小径走走吧，我有一件事想告诉你。\"",
        creator_notes:marker,
      }, "r-character.webp");
      await c.getCharacters();
      actor = c.characters.find(item => item.name === name);
    }
    if (!actor) throw new Error("Demo character could not be loaded");
    await c.selectCharacterById(c.characters.indexOf(actor));
    let current = SillyTavern.getContext();
    if (current.chatId !== chatName) {
      const list = await fetch("/api/characters/chats", { method:"POST", headers:c.getRequestHeaders(), body:JSON.stringify({ avatar_url:actor.avatar, simple:true }) });
      if (!list.ok) throw new Error("Demo chats could not be listed");
      const chats = await list.json();
      if (Array.isArray(chats) && chats.some(chat => chat.file_id === chatName)) await current.openCharacterChat(chatName);
      else {
        // A new character's initial greeting is already the intended demo; otherwise use a new chat.
        if (current.chatMetadata.workbenchRP?.demo !== marker && current.chat.length > 1) await workbench.host.newChat();
        current = SillyTavern.getContext();
        await current.saveChat();
        await current.renameChat(current.chatId, chatName);
      }
    }
    current = SillyTavern.getContext();
    if (current.chatMetadata.workbenchRP && current.chatMetadata.workbenchRP.demo !== marker) throw new Error("Chat has another RP configuration; refusing to overwrite it");
    await upload("/api/sprites/upload", { name, label:"neutral" }, "r-character.webp");
    await upload("/api/sprites/upload", { name:name + "/user", label:"neutral" }, "r-user-character.webp");
    const background = await upload("/api/backgrounds/upload", {}, "r-background.webp", "workbench-rp-demo-sakura.webp");
    const sprite = async folder => {
      const response = await fetch("/api/sprites/get?name=" + encodeURIComponent(folder));
      if (!response.ok) throw new Error("Sprite list failed: " + response.status);
      const item = (await response.json()).find(sprite => sprite.label === "neutral");
      if (!item) throw new Error("Uploaded sprite not found");
      return item.path;
    };
    current.chatMetadata.workbenchRP = {
      ...current.chatMetadata.workbenchRP, demo:marker,
      characterSprite:await sprite(name), userSprite:await sprite(name + "/user"),
      scene:{ day:"12", location:"樱花小径", weather:"晴 · 微风", time:"16:40" },
    };
    const backgroundPath = "backgrounds/" + encodeURIComponent(background);
    current.chatMetadata.custom_background = `url("${backgroundPath}")`;
    current.chatMetadata.chat_backgrounds = [...new Set([...(current.chatMetadata.chat_backgrounds || []), backgroundPath])];
    await current.saveMetadata();
    // Make the saved demo open on refresh, using the same setting as native character selection.
    (await import("/script.js")).setActiveCharacter(actor.avatar);
    current.powerUserSettings.auto_load_chat = true;
    // The account already uses RP. Explicitly retain that mode without replacing its other preferences.
    workbench.host.preference({ layout:"rp" });
    await workbench.host.persistSettings();
    return { character:actor.name, chat:current.chatId, actorSprite:current.chatMetadata.workbenchRP.characterSprite, userSprite:current.chatMetadata.workbenchRP.userSprite };
  }, { name, chatName, marker, assets });

  // Reload is essential: this must be persistent configuration, not a screenshot-only session.
  await ready(page, urls.validation, { probe:true });
  await page.waitForFunction(() => document.querySelectorAll(".wb-rp-stage .is-sprite img").length === 2 && [...document.querySelectorAll(".wb-rp-stage .is-sprite img")].every(image => image.complete && image.naturalWidth > 0));
  await page.waitForTimeout(1200); // Let initial native panels and RP geometry finish their transitions.
  const verified = await page.evaluate(() => {
    const c = SillyTavern.getContext();
    return {
      character:c.characters[c.characterId]?.name, chat:c.chatId,
      sprites:[...document.querySelectorAll(".wb-rp-stage .is-sprite img")].map(image => ({ src:image.getAttribute("src"), width:image.naturalWidth, height:image.naturalHeight })),
      background:getComputedStyle(document.getElementById("bg1")).backgroundImage,
      persona:workbench.host.snapshot().current.persona, name:c.name1, expressions:JSON.stringify(c.extensionSettings.expressions),
    };
  });
  assert.equal(verified.character, name); assert.equal(verified.chat, chatName);
  assert.equal(verified.persona, initial.persona); assert.equal(verified.name, initial.name);
  assert.equal(verified.expressions, initial.expressions);
  assert.equal(verified.sprites.length, 2);
  assert.equal(verified.sprites[0].src, configured.actorSprite); assert.equal(verified.sprites[1].src, configured.userSprite);
  assert.match(verified.background, /workbench-rp-demo-sakura/);
  assert.deepEqual(errors, []);
  await page.screenshot({ path:artifacts + "/rp-demo-persistent.png" });
  console.log(JSON.stringify({ url:urls.validation, character:verified.character, chat:verified.chat, sprites:verified.sprites, reloadVerified:true, personaPreserved:true, expressionsPreserved:true, errors }, null, 2));
} finally {
  await browser.close();
}
