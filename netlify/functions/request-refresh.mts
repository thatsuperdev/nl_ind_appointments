import type { Context } from "@netlify/functions";
import { getStore } from "@netlify/blobs";
import { isAllowedRequest, jsonResponse } from "./lib/access.mts";

const STORE_NAME = "slots-data";
const DATA_KEY = "slots.json";
const STATE_KEY = "refresh-request.json";
const STALE_AFTER_MS = 20 * 60 * 1000;
const REQUEST_COOLDOWN_MS = 5 * 60 * 1000;
const RELEASE_WINDOW_MINUTES = 60;

function localAmsterdamTime(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Amsterdam",
    weekday: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return {
    weekday: value("weekday"),
    day: Number(value("day")),
    minutes: Number(value("hour")) * 60 + Number(value("minute")),
  };
}

function refreshReasons(generatedAt: string | undefined, now = new Date()): string[] {
  const reasons: string[] = [];
  if (!generatedAt || Number.isNaN(Date.parse(generatedAt)) || now.getTime() - Date.parse(generatedAt) > STALE_AFTER_MS) {
    reasons.push("cache-stale");
  }
  const local = localAmsterdamTime(now);
  const nearRelease = Math.abs(local.minutes - 9 * 60) <= RELEASE_WINDOW_MINUTES;
  if (nearRelease && (local.day === 1 || local.weekday === "Thu")) {
    reasons.push("embassy-release-window");
  }
  return reasons;
}

export default async (req: Request, _context: Context) => {
  if (req.method !== "POST") return jsonResponse({ error: "Method not allowed" }, 405);
  if (!isAllowedRequest(req)) return jsonResponse({ error: "Forbidden" }, 403);

  const token = process.env.GITHUB_WORKFLOW_TOKEN;
  if (!token) {
    return jsonResponse({ error: "Refresh is not configured" }, 503);
  }

  const store = getStore(STORE_NAME);
  const cached = await store.get(DATA_KEY);
  const data = cached ? JSON.parse(cached) : {};
  const reasons = refreshReasons(data.generated_at);
  if (reasons.length === 0) {
    return jsonResponse({ requested: false, reason: "cache-fresh", generated_at: data.generated_at });
  }

  const previousStateRaw = await store.get(STATE_KEY);
  const previousState = previousStateRaw ? JSON.parse(previousStateRaw) : {};
  const lastRequested = Date.parse(previousState.requested_at ?? "");
  if (Number.isFinite(lastRequested) && Date.now() - lastRequested < REQUEST_COOLDOWN_MS) {
    return jsonResponse({
      requested: false,
      reason: "refresh-cooldown",
      requested_at: previousState.requested_at,
      workflow_url: previousState.workflow_url,
    });
  }

  const repository = process.env.GITHUB_REPOSITORY ?? "thatsuperdev/nl_ind_appointments";
  const workflow = process.env.GITHUB_WORKFLOW_FILE ?? "update-slots-quick.yml";
  const ref = process.env.GITHUB_WORKFLOW_REF ?? "main";
  const workflowUrl = `https://github.com/${repository}/actions/workflows/${workflow}`;
  const dispatch = await fetch(
    `https://api.github.com/repos/${repository}/actions/workflows/${encodeURIComponent(workflow)}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref }),
    },
  );
  if (!dispatch.ok) {
    return jsonResponse({ error: "Could not start refresh workflow", status: dispatch.status }, 502);
  }

  const state = { requested_at: new Date().toISOString(), reasons, workflow_url: workflowUrl };
  await store.set(STATE_KEY, JSON.stringify(state));
  return jsonResponse({ requested: true, reasons, workflow_url: workflowUrl });
};
