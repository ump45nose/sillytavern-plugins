// Builds the workbench-sync server plug-in (linked into the local SillyTavern checkout) and the
// VS Code extension, packed as a .vsix without vsce.
import { build } from "esbuild";
import { zipSync, strToU8 } from "fflate";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const plugin = path.join(root, "server/workbench-sync/dist");
await build({
  entryPoints: [path.join(root, "server/workbench-sync/src/index.ts")],
  outfile: path.join(plugin, "index.mjs"),
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node18",
  legalComments: "eof",
  // yaml resolves to CommonJS on node; the ESM bundle gives it a require.
  banner: {
    js: 'import { createRequire } from "node:module"; const require = createRequire(import.meta.url);',
  },
  logLevel: "warning",
});
// Only instances with enableServerPlugins load it (validation and visual); baseline stays official.
const plugins = path.join(root, "upstream/SillyTavern/plugins");
if (fs.existsSync(plugins)) {
  const link = path.join(plugins, "workbench-sync");
  if (fs.lstatSync(link, { throwIfNoEntry: false })) {
    if (!fs.lstatSync(link).isSymbolicLink())
      throw new Error(`${link} exists and is not a link; refusing to replace it.`);
    if (fs.readlinkSync(link) !== plugin) fs.unlinkSync(link);
  }
  if (!fs.existsSync(link)) fs.symlinkSync(plugin, link, "dir");
}

const ide = path.join(root, "ide/vscode"),
  manifest = JSON.parse(fs.readFileSync(path.join(ide, "package.json"), "utf8"));
const bundle = await build({
  entryPoints: [path.join(ide, "src/extension.ts")],
  bundle: true,
  format: "cjs",
  platform: "node",
  target: "node18",
  external: ["vscode"],
  write: false,
  logLevel: "warning",
});
const escape = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const vsixManifest = `<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="${manifest.name}" Version="${manifest.version}" Publisher="${manifest.publisher}" />
    <DisplayName>${escape(manifest.displayName)}</DisplayName>
    <Description xml:space="preserve">${escape(manifest.description)}</Description>
    <Categories>${manifest.categories.join(",")}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="${manifest.engines.vscode}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace" />
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="" />
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
`;
const contentTypes = `<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension=".json" ContentType="application/json" /><Default Extension=".js" ContentType="application/javascript" /><Default Extension=".vsixmanifest" ContentType="text/xml" /></Types>
`;
const out = path.join(ide, "dist");
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, "extension.js"), bundle.outputFiles[0].contents);
const vsix = path.join(out, `${manifest.name}-${manifest.version}.vsix`);
fs.writeFileSync(
  vsix,
  zipSync({
    "[Content_Types].xml": strToU8(contentTypes),
    "extension.vsixmanifest": strToU8(vsixManifest),
    "extension/package.json": strToU8(JSON.stringify(manifest, null, 2)),
    "extension/dist/extension.js": bundle.outputFiles[0].contents,
  }),
);
console.log(`Built server/workbench-sync/dist/index.mjs and ${path.relative(root, vsix)}`);
