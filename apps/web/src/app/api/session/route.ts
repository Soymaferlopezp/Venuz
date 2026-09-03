import { cookies } from "next/headers";

const COOKIE_NAME = "venuz_access_token";

function publicConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) return null;
  return { url: url.replace(/\/$/, ""), key };
}

export async function POST(request: Request) {
  const config = publicConfig();
  if (!config) {
    return Response.json(
      { detail: "Supabase Auth is not configured" },
      { status: 503 },
    );
  }
  const body = (await request.json()) as { email?: string; password?: string };
  if (!body.email || !body.password) {
    return Response.json(
      { detail: "Email and password are required" },
      { status: 422 },
    );
  }
  const response = await fetch(
    config.url + "/auth/v1/token?grant_type=password",
    {
      method: "POST",
      headers: { apikey: config.key, "Content-Type": "application/json" },
      body: JSON.stringify({ email: body.email, password: body.password }),
      cache: "no-store",
    },
  );
  const payload = (await response.json()) as {
    access_token?: string;
    expires_in?: number;
    msg?: string;
    error_description?: string;
  };
  if (!response.ok || !payload.access_token) {
    return Response.json(
      {
        detail:
          payload.error_description ?? payload.msg ?? "Invalid credentials",
      },
      { status: 401 },
    );
  }
  const store = await cookies();
  store.set(COOKIE_NAME, payload.access_token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: payload.expires_in ?? 3600,
  });
  return Response.json({ authenticated: true });
}

export async function GET() {
  const store = await cookies();
  return Response.json({
    authenticated: Boolean(store.get(COOKIE_NAME)?.value),
  });
}

export async function DELETE() {
  const store = await cookies();
  store.delete(COOKIE_NAME);
  return Response.json({ authenticated: false });
}
