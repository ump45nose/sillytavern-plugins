import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";

const { outputFiles } = await build({
  entryPoints: [new URL("../src/ui/speakerColors.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  write: false,
});
const { speakerCss, speakerKey } = await import(
  "data:text/javascript;base64," + Buffer.from(outputFiles[0].text).toString("base64")
);

test("no colors, no stylesheet", () => {
  assert.equal(speakerCss({}, [{ id: "a.png", name: "A" }], []), "");
});

test("characters match by name, personas by their avatar", () => {
  const css = speakerCss(
    { [speakerKey("character", "a.png")]: "#112233", [speakerKey("persona", "u 1.png")]: "#fff700" },
    [{ id: "a.png", name: "Alice" }],
    [{ id: "u 1.png" }],
  );
  assert.match(css, /\.mes\[is_user="false"\]\[ch_name="Alice"\] \.mes_text q\{--wb-speaker:#112233/);
  assert.ok(css.includes('.mes[is_user="true"]:has(.avatar img:is([src*="Avatars/u 1.png"],[src*="file=u%201.png"])) .mes_text q{--wb-speaker:#fff700'));
  // Light and dark themes clamp the lightness so pale colors stay readable.
  assert.match(css, /min\(l,0\.55\)/);
  assert.match(css, /\[data-wb-theme="dark"\].*max\(l,0\.75\)/);
});

test("names are quoted safely and invalid colors are skipped", () => {
  const css = speakerCss(
    { [speakerKey("character", "a.png")]: "#abcdef", [speakerKey("character", "b.png")]: "red;}" },
    [
      { id: "a.png", name: 'He said "hi"\\' },
      { id: "b.png", name: "B" },
    ],
    [],
  );
  assert.ok(css.includes('[ch_name="He said \\"hi\\"\\\\"]'));
  assert.ok(!css.includes('ch_name="B"'));
});
