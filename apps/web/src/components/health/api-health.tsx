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
const WAKING_DELAY_MS = 1800;
const REQUEST_TIMEOUT_MS = 12000;

function isSafeHealthPayload(
  value: unknown,
): value is { status: "ok"; trading_mode: "paper" } {
  if (typeof value !== "object" || value === null) return false;
  const payload = value as Record<string, unknown>;
  return payload.status === "ok" && payload.trading_mode === "paper";
}

export function ApiHealth() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const wakingTimer = window.setTimeout(
      () => setState({ kind: "waking" }),
      WAKING_DELAY_MS,
    );
    const abortTimer = window.setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT_MS,
    );

    void fetch(`${API_BASE_URL}/health`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Health endpoint unavailable");
        const payload: unknown = await response.json();
        if (!isSafeHealthPayload(payload))
          throw new Error("Unsafe health response");
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
        window.clearTimeout(wakingTimer);
        window.clearTimeout(abortTimer);
      });

    return () => {
      controller.abort();
      window.clearTimeout(wakingTimer);
      window.clearTimeout(abortTimer);
    };
  }, [attempt]);

  if (state.kind === "loading") {
    return (
      <div
        role="status"
        className="rounded-2xl border border-slate-200 bg-slate-50 p-5 text-slate-700"
      >
        <LoaderCircle aria-hidden="true" className="mb-3 size-5 animate-spin" />
        <p className="font-medium">Comprobando API…</p>
        <p className="mt-1 text-sm text-slate-500">
          Validando el contrato de salud.
        </p>
      </div>
    );
  }

  if (state.kind === "waking") {
    return (
      <div
        role="status"
        className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950"
      >
        <Server aria-hidden="true" className="mb-3 size-5" />
        <p className="font-medium">Render está despertando</p>
        <p className="mt-1 text-sm text-amber-800">
          El servicio gratuito puede tardar unos segundos. Seguimos esperando.
        </p>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div
        role="alert"
        className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-950"
      >
        <CircleAlert aria-hidden="true" className="mb-3 size-5" />
        <p className="font-medium">API no disponible</p>
        <p className="mt-1 text-sm text-red-800">
          No se habilita ninguna acción. Revisa el backend o inténtalo otra vez.
        </p>
        <button
          type="button"
          onClick={() => {
            setState({ kind: "loading" });
            setAttempt((current) => current + 1);
          }}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold hover:bg-red-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-900"
        >
          <RefreshCw aria-hidden="true" className="size-4" />
          Reintentar
        </button>
      </div>
    );
  }

  return (
    <div
      role="status"
      className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-emerald-950"
    >
      <ShieldCheck aria-hidden="true" className="mb-3 size-5" />
      <p className="font-medium">API operativa · modo paper</p>
      <p className="mt-1 text-sm text-emerald-800">
        Contrato verificado a las {state.checkedAt}. No se exponen credenciales.
      </p>
    </div>
  );
}
