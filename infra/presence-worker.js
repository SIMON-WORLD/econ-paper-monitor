const ACTIVE_WINDOW_MS = 120000;

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "*";
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(origin) });
    }
    const url = new URL(request.url);
    if (url.pathname !== "/presence" || request.method !== "GET") {
      return new Response(JSON.stringify({ error: "not_found" }), { status: 404, headers: corsHeaders(origin) });
    }
    const clientId = (url.searchParams.get("client_id") || "").trim();
    if (!/^[a-zA-Z0-9_-]{16,80}$/.test(clientId)) {
      return new Response(JSON.stringify({ error: "invalid_client_id" }), { status: 400, headers: corsHeaders(origin) });
    }
    const site = (url.searchParams.get("site") || "default").trim();
    const windowMode = (url.searchParams.get("window") || "active").trim();
    if (!/^[a-z0-9-]{1,40}$/.test(site) || !["active", "day"].includes(windowMode)) {
      return new Response(JSON.stringify({ error: "invalid_scope" }), { status: 400, headers: corsHeaders(origin) });
    }
    const activeWindowMs = windowMode === "day" ? 86400000 : ACTIVE_WINDOW_MS;
    const roomId = env.PRESENCE_ROOM.idFromName(`${origin}:${site}:${windowMode}`);
    const room = env.PRESENCE_ROOM.get(roomId);
    return room.fetch(new Request("https://presence.internal/heartbeat", {
      method: "POST",
      headers: { "content-type": "application/json", "x-origin": origin },
      body: JSON.stringify({ clientId, activeWindowMs }),
    }));
  },
};

export class PresenceRoom {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const payload = await request.json();
    const now = Date.now();
    const entries = await this.state.storage.list({ prefix: "client:" });
    const stale = [];
    let online = 0;
    const clientKey = `client:${payload.clientId}`;
    for (const [key, timestamp] of entries) {
      if (now - Number(timestamp) > Number(payload.activeWindowMs || ACTIVE_WINDOW_MS)) stale.push(key);
      else online += 1;
    }
    if (stale.length) await this.state.storage.delete(stale);
    const isNewClient = !entries.has(clientKey) || stale.includes(clientKey);
    await this.state.storage.put(clientKey, now);
    if (isNewClient) online += 1;
    const origin = request.headers.get("x-origin") || "*";
    return new Response(JSON.stringify({ online }), {
      headers: corsHeaders(origin),
    });
  }
}
