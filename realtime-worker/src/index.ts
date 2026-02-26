import { DurableObject } from "cloudflare:workers";

export interface Env {
  ROOM: DurableObjectNamespace;
  ALLOWED_ORIGIN?: string;
}

function bad(msg: string, status = 400): Response {
  return new Response(msg, { status });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") return new Response("ok");

    const m = url.pathname.match(/^\/room\/([A-Za-z0-9_-]{4,20})$/);
    if (!m) return bad("Not found", 404);
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") return bad("Expected websocket", 426);

    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "*";
    if (allowed !== "*" && origin !== allowed) return bad("Forbidden", 403);

    const code = m[1].toUpperCase();
    const id = env.ROOM.idFromName(code);
    const stub = env.ROOM.get(id);
    return stub.fetch(request);
  }
};

export class RoomDO extends DurableObject<Env> {
  private host: WebSocket | null = null;
  private join: WebSocket | null = null;

  async fetch(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") return bad("Expected websocket", 426);
    const url = new URL(request.url);
    const room = (url.pathname.split("/").pop() || "").toUpperCase();
    const role = this.host ? (this.join ? "spectator" : "join") : "host";
    if (role === "spectator") return bad("Room is full", 409);

    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    server.accept();

    if (role === "host") this.host = server;
    else this.join = server;

    server.addEventListener("message", (evt: MessageEvent) => {
      const target = role === "host" ? this.join : this.host;
      if (!target) return;
      const payload = typeof evt.data === "string" ? evt.data : String(evt.data);
      try { target.send(payload); } catch {}
    });

    const cleanup = () => {
      if (role === "host" && this.host === server) this.host = null;
      if (role === "join" && this.join === server) this.join = null;
      const peer = role === "host" ? this.join : this.host;
      if (peer) {
        try { peer.send(JSON.stringify({ t: "peer", state: "left" })); } catch {}
      }
    };

    server.addEventListener("close", cleanup);
    server.addEventListener("error", cleanup);

    try {
      server.send(JSON.stringify({ t: "ready", role, room }));
      if (this.host && this.join) {
        try { this.host.send(JSON.stringify({ t: "peer", state: "joined" })); } catch {}
        try { this.join.send(JSON.stringify({ t: "peer", state: "joined" })); } catch {}
      }
    } catch {
      cleanup();
    }

    return new Response(null, { status: 101, webSocket: client });
  }
}
