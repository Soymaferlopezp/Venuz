import { cookies } from "next/headers";

const ALLOWED_ROOTS = new Set([
  "analysis",
  "watchlists",
  "providers",
  "cycles",
]);

async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (!path.length || !ALLOWED_ROOTS.has(path[0])) {
    return Response.json({ detail: "Unsupported API path" }, { status: 404 });
  }
  const token = (await cookies()).get("venuz_access_token")?.value;
  const isPublicCycle = path[0] === "cycles";
  if (!token && !isPublicCycle) {
    return Response.json(
      { detail: "Authentication required" },
      { status: 401 },
    );
  }
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    return Response.json({ detail: "API is not configured" }, { status: 503 });
  }
  const incoming = new URL(request.url);
  const upstreamUrl =
    baseUrl.replace(/\/$/, "") +
    "/v1/" +
    path.map(encodeURIComponent).join("/") +
    incoming.search;
  const body = request.method === "POST" ? await request.text() : undefined;
  try {
    const upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers: {
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body || undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") ?? "application/json",
      },
    });
  } catch {
    return Response.json(
      { detail: { state: "error", message: "API is waking or unavailable" } },
      { status: 503 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
