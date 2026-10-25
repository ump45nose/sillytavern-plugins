// Decides whether a workbench selector targets isolated workbench UI ("layer"),
// native DOM ("bridge"), or cannot be told apart ("both").
// Observed audit hits win; otherwise the selector text is read against where
// each class/id was seen in the DOM (audit.tokens).

/** Splits a complex selector into compounds at top-level combinators. */
export function compounds(selector) {
  const out = [];
  let depth = 0,
    current = "";
  for (let i = 0; i < selector.length; i++) {
    const c = selector[i];
    if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") depth--;
    if (depth === 0 && /[\s>+~]/.test(c)) {
      if (current) out.push(current);
      current = "";
      continue;
    }
    current += c;
  }
  if (current) out.push(current);
  return out;
}

/** Class and id tokens that identify the element itself (negations and :has() excluded). */
function identity(compound) {
  const plain = compound.replace(/:(not|has)\((?:[^()]|\([^()]*\))*\)/g, "");
  return plain.match(/[.#][\w-]+/g) || [];
}

const ROOT = /^(\.wb-ui|#wb-root|#wb-layout-root)$/;
// Lease containers: `.wb-native-settings-slot page-<id>` and friends hold native controls.
const LEASE = /^\.(wb-native-(embedded|settings-slot|slot|select-slot)|page-[\w-]+)$/;

export function createClassifier(audit) {
  // "in"/"out" only when every observed element agrees; unseen tokens are guessed by prefix.
  const where = (token) => {
    const seen = audit.tokens[token];
    if (seen) return seen.in && !seen.out ? "in" : seen.out && !seen.in ? "out" : "mixed";
    if (token.startsWith("#")) return token.startsWith("#wb-") ? "guess-in" : "out";
    return /^\.(wb-|is-|has-|lucide)/.test(token) ? "guess-in" : "out";
  };
  const own = (token) => /^[.#]wb-/.test(token);
  /** Text-only decision, exported separately so it can be measured against observed hits. */
  const infer = (selector) => {
    const parts = compounds(selector).filter((c) => !/^(body|html|:root)\b/.test(c));
    if (!parts.length) return "bridge";
    let state = "unknown";
    for (const [index, compound] of parts.entries()) {
      const subject = index === parts.length - 1;
      const tokens = identity(compound);
      if (tokens.some((t) => ROOT.test(t))) {
        state = "in";
        continue;
      }
      // Descendants of a lease container are native controls.
      if (!subject && tokens.some((t) => LEASE.test(t))) {
        state = "out";
        continue;
      }
      // Workbench tokens decide the compound; native tokens only speak when none is present.
      const mine = tokens.filter(own).map(where);
      const theirs = tokens.filter((t) => !own(t)).map(where);
      const mixedIs = /:is\(/.test(compound) && mine.length && theirs.includes("out");
      if (mixedIs) return "both";
      if (mine.includes("in"))
        state = "in"; // only ever observed inside isolated UI
      else if (mine.includes("out")) state = "out";
      else if (mine.includes("guess-in")) state = state === "unknown" ? "in" : state;
      else if (theirs.includes("out")) state = "out";
    }
    return state === "in" ? "layer" : state === "out" ? "bridge" : "both";
  };
  const classify = (selector) => {
    const hit = audit.plugin[selector];
    if (hit && hit.in && !hit.out) return "layer";
    if (hit && hit.out && !hit.in) return "bridge";
    if (hit && hit.in && hit.out) return "both";
    return infer(selector);
  };
  return { classify, infer };
}
