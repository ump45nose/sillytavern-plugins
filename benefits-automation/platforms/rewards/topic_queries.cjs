"use strict";
// Static GPL-3.0-or-later query catalog from the pinned Rewards dependency.
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const root = path.join(__dirname, "vendor/rewards-parser");
const name = "src/functions/bing-search-activity-queries.json";
const bytes = fs.readFileSync(path.join(root, name));
const expected = "72ce2d96f55ef6dbdc99ce1534fc83fae3d8cc9e46e68a00255abde863d8de94";
if (bytes.length > 65536 || crypto.createHash("sha256").update(bytes).digest("hex") !== expected)
  throw Error("search_topics_modified");
const normalize = value => String(value || "").normalize("NFKC")
  .replace(/[\u200b-\u200d\ufeff]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
const catalog = new Map();
for (const row of JSON.parse(bytes)) {
  const title = normalize(row.title);
  if (!title || !Array.isArray(row.queries) || row.queries.length < 1 || row.queries.length > 10 ||
      row.queries.some(q => typeof q !== "string" || !q.trim() || q.length > 300))
    throw Error("search_topics_invalid");
  const queries = Object.freeze([...row.queries]);
  if (catalog.has(title) && JSON.stringify(catalog.get(title)) !== JSON.stringify(queries))
    throw Error("search_topics_ambiguous");
  catalog.set(title, queries);
}
// Stable offer identifiers also work when the dashboard localizes the title.
const aliases = {
  creditreport: "Know your score", health: "Feeling symptoms?", recipe: "Learn to cook a new recipe",
  videogames: "Explore videogames", dictionary: "Expand your vocabulary", timezonedates: "What time is it?",
  financemarket: "How's the economy?", mattress: "Sleep better", beautyproducts: "Freshen up your routine",
  cellphoneplans: "Talk, text, save", cruises: "Set Sail", internetproviders: "Check options",
  bankaccounts: "Bank smarter", airportparking: "Park with ease", allinclusiveresorts: "Plan a quick getaway",
  concerttickets: "Catch the show", lyrics: "Search the lyrics of a song", rentalcars: "Drive your way",
  cars: "Hit the road", couponcodes: "Save more today", homeimprovement: "Upgrade your space",
  streamingservices: "Stream your favorites", flowerdelivery: "Send a smile", jobs: "Discover open job roles",
  restaurant: "Too tired to cook?", petsupplies: "Treat your pet", weather: "Prepare for the weather",
  creditcards: "Swipe smart", flight: "Plan a quick getaway",
  insurance: "Protect what matters", shopping: "Find Deals on Bing",
};
const QUERIES = Object.freeze(Object.fromEntries(Object.entries(aliases).map(([id, title]) => {
  const queries = catalog.get(normalize(title));
  if (!queries) throw Error("search_topic_alias_invalid");
  return [id, queries];
})));
function resolve(job) {
  for (const title of [job.title, job.metadata?.title]) {
    const queries = catalog.get(normalize(title));
    if (queries) return queries;
  }
  const id = String(job.offerId || "").toLowerCase();
  const key = Object.keys(QUERIES).find(k => id.includes("_" + k + "_"));
  return key ? QUERIES[key] : null;
}
module.exports = { QUERIES, resolve, normalize };
