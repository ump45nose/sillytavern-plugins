import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";

const { outputFiles } = await build({
  entryPoints: [new URL("../src/host/bus.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  write: false,
});
const { bus, guards } = await import(
  "data:text/javascript;base64," + Buffer.from(outputFiles[0].text).toString("base64")
);

test("bus delivers payloads to current handlers only", () => {
  const seen = [];
  const off = bus.on("rp-jump", (id) => seen.push(id));
  bus.emit("rp-jump", 3);
  off();
  bus.emit("rp-jump", 4);
  assert.deepEqual(seen, [3]);
});

test("a handler may unsubscribe while the event is being delivered", () => {
  const seen = [];
  const offA = bus.on("image-compose", () => {
    seen.push("a");
    offA();
  });
  const offB = bus.on("image-compose", () => seen.push("b"));
  bus.emit("image-compose");
  bus.emit("image-compose");
  offB();
  assert.deepEqual(seen, ["a", "b", "b"]);
});

test("guards run in order, stop at the first refusal and see the leave options", () => {
  const calls = [];
  const offA = guards.add((o) => (calls.push(["a", !!o.preserveDrafts]), true));
  const offB = guards.add(() => (calls.push(["b"]), false));
  const offC = guards.add(() => (calls.push(["c"]), true));
  assert.equal(guards.check({ preserveDrafts: true }), false);
  assert.deepEqual(calls, [["a", true], ["b"]]);
  offB();
  assert.equal(guards.check(), true);
  offA();
  offC();
});

test("one beforeunload listener serves every hold and leaves with the last one", () => {
  const listeners = new Set();
  globalThis.window = {
    addEventListener: (name, fn) => name === "beforeunload" && listeners.add(fn),
    removeEventListener: (name, fn) => name === "beforeunload" && listeners.delete(fn),
  };
  const unload = () => {
    const event = { prevented: false, preventDefault() { this.prevented = true; } };
    listeners.forEach((fn) => fn(event));
    return event.prevented;
  };
  let pending = false;
  const offA = guards.hold(() => pending),
    offB = guards.hold(() => false);
  assert.equal(listeners.size, 1);
  assert.equal(unload(), false);
  pending = true;
  assert.equal(unload(), true);
  offA();
  assert.equal(listeners.size, 1);
  assert.equal(unload(), false);
  offB();
  assert.equal(listeners.size, 0);
  delete globalThis.window;
});
