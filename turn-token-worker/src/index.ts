interface Env {
  ALLOWED_ORIGIN?: string;
  TURN_URLS?: string;
  STUN_URLS?: string;
  TOKEN_TTL_SECONDS?: string;
  TURN_USERNAME?: string;
  TURN_CREDENTIAL?: string;
  TURN_SHARED_SECRET?: string;
  TURN_USERNAME_PREFIX?: string;
}

function corsHeaders(origin: string) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin"
  };
}

function splitCsv(value: string | undefined): string[] {
  return (value || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

async function hmacSha1Base64(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-1" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  const bytes = new Uint8Array(sig);
  let raw = "";
  for (const b of bytes) raw += String.fromCharCode(b);
  return btoa(raw);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const reqOrigin = request.headers.get("Origin") || "";
    const allowedOrigin = env.ALLOWED_ORIGIN || "*";
    const allowAll = allowedOrigin === "*";

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(allowAll ? "*" : allowedOrigin) });
    }

    if (request.method !== "GET") {
      return new Response("Method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    if (url.pathname !== "/turn") {
      return new Response("Not found", { status: 404 });
    }

    if (!allowAll && reqOrigin !== allowedOrigin) {
      return new Response("Forbidden", { status: 403 });
    }

    const turnUrls = splitCsv(env.TURN_URLS);
    const stunUrls = splitCsv(env.STUN_URLS);

    if (!turnUrls.length) {
      return new Response(JSON.stringify({ error: "TURN_URLS is empty" }), {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders(allowAll ? "*" : allowedOrigin) }
      });
    }

    let username = (env.TURN_USERNAME || "").trim();
    let credential = (env.TURN_CREDENTIAL || "").trim();

    if (!username || !credential) {
      const sharedSecret = (env.TURN_SHARED_SECRET || "").trim();
      if (sharedSecret) {
        const ttl = Number.parseInt(env.TOKEN_TTL_SECONDS || "3600", 10);
        const expires = Math.floor(Date.now() / 1000) + (Number.isFinite(ttl) ? ttl : 3600);
        const prefix = (env.TURN_USERNAME_PREFIX || "ink-soccer").trim();
        username = `${expires}:${prefix}`;
        credential = await hmacSha1Base64(sharedSecret, username);
      }
    }

    if (!username || !credential) {
      return new Response(JSON.stringify({ error: "Set TURN_USERNAME + TURN_CREDENTIAL or TURN_SHARED_SECRET" }), {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders(allowAll ? "*" : allowedOrigin) }
      });
    }

    const iceServers: Array<{ urls: string[]; username?: string; credential?: string }> = [];
    if (stunUrls.length) iceServers.push({ urls: stunUrls });
    iceServers.push({ urls: turnUrls, username, credential });

    return new Response(JSON.stringify({ iceServers }), {
      headers: { "Content-Type": "application/json", ...corsHeaders(allowAll ? "*" : allowedOrigin) }
    });
  }
};
