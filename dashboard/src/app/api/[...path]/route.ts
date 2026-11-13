import type { NextRequest } from "next/server";
import { backendUrl } from "@/lib/proxy";

// The browser talks only to this server. The backend address and the token stay here.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const TOKEN = process.env.API_TOKEN ?? "";
const MAX_BODY_BYTES = 4096;

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const url = backendUrl(BACKEND, path, request.nextUrl.search);
  if (url === null) return Response.json({ detail: "not found" }, { status: 404 });

  const headers = new Headers();
  for (const name of ["content-type", "accept"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (TOKEN) headers.set("authorization", `Bearer ${TOKEN}`);

  let body: string | undefined;
  if (request.method === "POST") {
    body = await request.text();
    if (body.length > MAX_BODY_BYTES) {
      return Response.json({ detail: "request too large" }, { status: 413 });
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers,
      body,
      signal: request.signal, // closes the upstream stream when the browser disconnects
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "the backend is not reachable" }, { status: 502 });
  }

  const out = new Headers();
  for (const name of ["content-type", "retry-after"]) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  out.set("cache-control", "no-cache, no-transform");
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;