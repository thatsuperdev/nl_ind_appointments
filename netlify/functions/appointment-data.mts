import type { Context } from "@netlify/functions";
import { getStore } from "@netlify/blobs";

const STORE_NAME = "slots-data";
const KEY = "slots.json";

// Netlify sets these automatically at runtime — no config needed.
const ALLOWED_HOSTS = [process.env.URL, process.env.DEPLOY_URL, process.env.DEPLOY_PRIME_URL]
  .filter(Boolean)
  .map((u) => new URL(u as string).hostname)
  .concat(["localhost", "127.0.0.1"]);

// Lets the hourly freshness watchdog (a plain curl, no browser Origin/Referer)
// through without opening the feed up to anyone else who just curls the URL.
const WATCHDOG_SECRET = process.env.FRESHNESS_WATCHDOG_SECRET;

function isAllowedRequest(req: Request): boolean {
  if (WATCHDOG_SECRET && req.headers.get("x-freshness-check") === WATCHDOG_SECRET) {
    return true;
  }
  const origin = req.headers.get("origin") ?? req.headers.get("referer");
  if (!origin) return false;
  try {
    return ALLOWED_HOSTS.includes(new URL(origin).hostname);
  } catch {
    return false;
  }
}

export default async (req: Request, _context: Context) => {
  if (!isAllowedRequest(req)) {
    return new Response(JSON.stringify({ error: "Forbidden" }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });
  }

  const store = getStore(STORE_NAME);
  const data = await store.get(KEY);

  if (data === null) {
    return new Response(JSON.stringify({ error: "slots.json not found in blob store" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(data, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=0, must-revalidate",
    },
  });
};
