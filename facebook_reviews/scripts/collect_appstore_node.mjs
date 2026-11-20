import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, "..", "checkpoints", "appstore_pages");
const APP_ID = "284882215";
const TARGET = 500;
const GAP_MS = 900;

fs.mkdirSync(OUT, { recursive: true });

async function fetchPage(offset) {
  const url =
    `https://apps.apple.com/api/apps/v1/catalog/kr/apps/${APP_ID}/reviews` +
    `?platform=web&l=ko-KR&offset=${offset}&limit=10&sort=recent`;
  for (let attempt = 1; attempt <= 4; attempt++) {
    const res = await fetch(url, {
      headers: {
        Accept: "application/json",
        Origin: "https://apps.apple.com",
        Referer: `https://apps.apple.com/kr/app/facebook/id${APP_ID}`,
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
      },
    });
    const text = await res.text();
    if (res.status === 429 || res.status >= 500) {
      await new Promise((r) => setTimeout(r, GAP_MS * attempt * 2));
      continue;
    }
    return { status: res.status, text };
  }
  return { status: 0, text: "" };
}

function normalize(payload, offset) {
  const reviews = [];
  for (const item of payload.data || []) {
    const a = item.attributes || {};
    const body = a.review || "";
    const title = a.title || "";
    if (!String(body).trim() && !String(title).trim()) continue;
    reviews.push({
      id: String(item.id || ""),
      date: a.date || "",
      rating: a.rating ?? "",
      title,
      body,
      is_edited: !!a.isEdited,
      version: a.version || a.userVersion || "",
      voteSum: a.voteSum ?? "",
    });
  }
  let next_offset = null;
  const nxt = payload.next || "";
  if (String(nxt).includes("offset=")) {
    next_offset = Number(String(nxt).split("offset=")[1].split("&")[0]);
  } else if (reviews.length) {
    next_offset = offset + 10;
  }
  return {
    app_id: APP_ID,
    offset,
    count: reviews.length,
    next_offset,
    sort: "most_recent",
    country: "kr",
    reviews,
    source_url: `https://apps.apple.com/kr/app/facebook/id${APP_ID}?see-all=reviews&sort=recent`,
  };
}

function uniqueCount() {
  const ids = new Set();
  for (const f of fs.readdirSync(OUT).filter((x) => x.endsWith(".json"))) {
    const d = JSON.parse(fs.readFileSync(path.join(OUT, f), "utf8"));
    for (const r of d.reviews || []) ids.add(String(r.id));
  }
  return ids.size;
}

let offset = 0;
while (uniqueCount() < TARGET && offset <= 10000) {
  const file = path.join(OUT, `offset_${String(offset).padStart(4, "0")}.json`);
  if (fs.existsSync(file)) {
    const d = JSON.parse(fs.readFileSync(file, "utf8"));
    if ((d.reviews || []).length) {
      offset = d.next_offset ?? offset + 10;
      continue;
    }
  }
  const { status, text } = await fetchPage(offset);
  if (status !== 200) {
    console.error("stop", { offset, status, body: text.slice(0, 200) });
    fs.writeFileSync(
      path.join(OUT, `_error_offset_${offset}.json`),
      JSON.stringify({ offset, status, body: text.slice(0, 500) }, null, 2)
    );
    break;
  }
  const page = normalize(JSON.parse(text), offset);
  fs.writeFileSync(file, JSON.stringify(page, null, 2), "utf8");
  console.log(`saved offset=${offset} n=${page.count} unique=${uniqueCount()}`);
  if (!page.reviews.length) break;
  offset = page.next_offset ?? offset + 10;
  await new Promise((r) => setTimeout(r, GAP_MS));
}
console.log("done unique=", uniqueCount());
