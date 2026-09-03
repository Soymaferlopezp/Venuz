import Link from "next/link";

export type ViewState =
  | "loading"
  | "empty"
  | "stale"
  | "insufficient"
  | "provider_exhausted"
  | "unauthenticated"
  | "error";

const copy: Record<ViewState, { title: string; detail: string }> = {
  loading: {
    title: "Loading analysis",
    detail: "The API may need a moment to wake on the free hosting tier.",
  },
  empty: {
    title: "No persisted analysis yet",
    detail: "Run a scan to create an evidence-backed watchlist.",
  },
  stale: {
    title: "Data is stale - NO TRADE",
    detail: "Refresh provider inputs before relying on this analysis.",
  },
  insufficient: {
    title: "Insufficient evidence - NO TRADE",
    detail:
      "One or more deterministic criteria lacks the required observations.",
  },
  provider_exhausted: {
    title: "Provider budget exhausted - NO TRADE",
    detail:
      "Cached results remain visible. New estimate requests resume with the next daily budget.",
  },
  unauthenticated: {
    title: "Sign in required",
    detail: "Venuz data is isolated per authenticated operator.",
  },
  error: {
    title: "Analysis unavailable - NO TRADE",
    detail: "The API or a required provider did not return a valid response.",
  },
};

export function StateNotice({ state }: { state: ViewState }) {
  const message = copy[state];
  return (
    <div
      role={
        state === "error" || state === "provider_exhausted" ? "alert" : "status"
      }
      aria-live="polite"
      className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-amber-950"
    >
      <h2 className="font-semibold">{message.title}</h2>
      <p className="mt-2 text-sm">{message.detail}</p>
      {state === "unauthenticated" ? (
        <Link
          href="/sign-in"
          className="mt-4 inline-block font-semibold underline"
        >
          Open sign in
        </Link>
      ) : null}
    </div>
  );
}
