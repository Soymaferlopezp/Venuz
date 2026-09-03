"use client";
import {
  CircleAlert,
  LoaderCircle,
  RefreshCw,
  Server,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
type HealthState =
  | { kind: "loading" }
  | { kind: "waking" }
  | { kind: "ready"; checkedAt: string }
  | { kind: "error" };
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
function safe(
  value: unknown,
): value is { status: "ok"; trading_mode: "paper" } {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>).status === "ok" &&
    (value as Record<string, unknown>).trading_mode === "paper"
  );
}
export function ApiHealth() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const waking = window.setTimeout(() => setState({ kind: "waking" }), 1800);
    const abort = window.setTimeout(() => controller.abort(), 12000);
    void fetch(`${API_BASE_URL}/health`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        const payload: unknown = await response.json();
        if (!safe(payload)) throw new Error();
        setState({
          kind: "ready",
          checkedAt: new Date().toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          }),
        });
      })
      .catch(() => setState({ kind: "error" }))
      .finally(() => {
        clearTimeout(waking);
        clearTimeout(abort);
      });
    return () => {
      controller.abort();
      clearTimeout(waking);
      clearTimeout(abort);
    };
  }, [attempt]);
  if (state.kind === "loading")
    return (
      <div role="status" className="rounded-2xl bg-slate-50 p-5">
        <LoaderCircle className="mb-3 size-5 animate-spin" />
        <p className="font-medium">Checking API…</p>
        <p className="text-sm text-slate-500">
          Validating the Paper-only contract.
        </p>
      </div>
    );
  if (state.kind === "waking")
    return (
      <div role="status" className="rounded-2xl bg-amber-50 p-5">
        <Server className="mb-3 size-5" />
        <p className="font-medium">Render is waking up</p>
        <p className="text-sm">The free service may need a few seconds.</p>
      </div>
    );
  if (state.kind === "error")
    return (
      <div role="alert" className="rounded-2xl bg-red-50 p-5">
        <CircleAlert className="mb-3 size-5" />
        <p className="font-medium">API unavailable</p>
        <p className="text-sm">No action is enabled.</p>
        <button
          onClick={() => {
            setState({ kind: "loading" });
            setAttempt((value) => value + 1);
          }}
        >
          <RefreshCw className="inline size-4" /> Retry
        </button>
      </div>
    );
  return (
    <div role="status" className="rounded-2xl bg-emerald-50 p-5">
      <ShieldCheck className="mb-3 size-5" />
      <p className="font-medium">API ready · Paper mode</p>
      <p className="text-sm">
        Verified at {state.checkedAt}. No credentials are exposed.
      </p>
    </div>
  );
}
