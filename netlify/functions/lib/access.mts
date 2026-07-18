const ALLOWED_HOSTS = [process.env.URL, process.env.DEPLOY_URL, process.env.DEPLOY_PRIME_URL]
  .filter(Boolean)
  .map((u) => new URL(u as string).hostname)
  .concat(["localhost", "127.0.0.1"]);

const WATCHDOG_SECRET = process.env.FRESHNESS_WATCHDOG_SECRET;

export function isAllowedRequest(req: Request): boolean {
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

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
