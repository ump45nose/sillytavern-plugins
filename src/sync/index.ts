/**
 * Readable files for SillyTavern resources, shared by the workbench-sync server plug-in and the
 * tests. Pure: no DOM, no Node. Every codec round-trips: rendering a resource and writing the files
 * back gives the same resource.
 */
export { SyncError, splitFront, parseYaml, fileStem, uniqueNames, sameData, type Data } from "./text";
export { worldCodec } from "./world";
export { characterCodec, mirrorCard } from "./character";
export { presetCodec } from "./preset";
export { profileCodec, profileNames, personaCodec, personaNames } from "./settings";
export { outlineCodec } from "./outline";
export { tableCodec, type SyncTable } from "./database";
