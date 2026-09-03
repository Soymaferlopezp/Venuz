import type { ApiErrorBody } from "@/lib/api-contracts";

export class VenuzApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly state: string,
    message: string,
  ) {
    super(message);
  }
}

export async function venuzFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch("/api/venuz/" + path.replace(/^\//, ""), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = {};
    }
    const detail = body.detail;
    const state =
      typeof detail === "object" && detail?.state
        ? detail.state
        : response.status === 401
          ? "unauthenticated"
          : "error";
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail?.message
          ? detail.message
          : "Venuz API request failed";
    throw new VenuzApiError(response.status, state, message);
  }
  return (await response.json()) as T;
}

export function money(value: string | null): string {
  if (value === null) return "Unavailable";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

export function timestamp(value: string | null): string {
  if (value === null) return "Not available";
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}
