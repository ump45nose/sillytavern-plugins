import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

/** The parts of a user's directory list (SillyTavern's USER_DIRECTORY_TEMPLATE) this plug-in reads. */
export interface Directories {
  root: string;
  worlds: string;
  characters: string;
  chats: string;
  groups: string;
  groupChats: string;
  openAI_Settings: string;
}

/**
 * SillyTavern's own root. The plug-in is loaded through a symlink, so its own URL points into the
 * workbench checkout; server.js (argv[1]) or the working directory locate the server instead.
 */
function serverRoot() {
  const candidates = [process.argv[1] && path.dirname(fs.realpathSync(process.argv[1])), process.cwd()];
  const root = candidates.find((dir) => dir && fs.existsSync(path.join(dir, "src/character-card-parser.js")));
  if (!root) throw new Error("workbench-sync: SillyTavern server directory not found.");
  return root;
}

interface Host {
  readCard: (image: Buffer) => string;
  writeCard: (image: Buffer, data: string) => Buffer;
  getConfigValue: (key: string, fallback: unknown) => unknown;
}
let host: Promise<Host> | undefined;
export function st() {
  return (host ??= (async () => {
    const root = serverRoot(),
      load = (file: string) => import(pathToFileURL(path.join(root, file)).href);
    const [card, util] = await Promise.all([load("src/character-card-parser.js"), load("src/util.js")]);
    return { readCard: card.read, writeCard: card.write, getConfigValue: util.getConfigValue };
  })());
}

/** Writes through a temporary file in the same directory, so readers never see half a file. */
export async function writeAtomic(file: string, data: string | Buffer) {
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.${process.pid}.${Date.now()}.wbsync`);
  await fs.promises.writeFile(temp, data);
  try {
    await fs.promises.rename(temp, file);
  } catch (error) {
    await fs.promises.rm(temp, { force: true });
    throw error;
  }
}

/** The first line of a file, read in chunks so a long chat is not loaded whole. */
export async function firstLine(file: string) {
  const handle = await fs.promises.open(file, "r");
  try {
    const chunks: Buffer[] = [];
    const buffer = Buffer.alloc(65536);
    for (let position = 0; ; ) {
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, position);
      if (!bytesRead) break;
      const slice = buffer.subarray(0, bytesRead),
        end = slice.indexOf(10);
      chunks.push(Buffer.from(end >= 0 ? slice.subarray(0, end) : slice));
      if (end >= 0) break;
      position += bytesRead;
    }
    return Buffer.concat(chunks).toString("utf8");
  } finally {
    await handle.close();
  }
}
