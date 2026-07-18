import type { Context } from "@netlify/functions";
import { getStore } from "@netlify/blobs";
import { isAllowedRequest, jsonResponse } from "./lib/access.mts";

const STORE_NAME = "slots-data";
const KEY = "slots.json";

export default async (req: Request, _context: Context) => {
  if (!isAllowedRequest(req)) {
    return jsonResponse({ error: "Forbidden" }, 403);
  }

  const store = getStore(STORE_NAME);
  const data = await store.get(KEY);

  if (data === null) {
    return jsonResponse({ error: "slots.json not found in blob store" }, 404);
  }

  return new Response(data, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=0, must-revalidate",
    },
  });
};
