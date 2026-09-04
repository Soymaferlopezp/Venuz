"use client";

import { useEffect, useState } from "react";
import { ArrowUpRight, LoaderCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

type CycleMode = "stocks" | "options" | "mixed";
type PublicCycle = {
  cycle_id: string;
  state: string;
  mode: CycleMode;
  selected_asset_class: "stock" | "option" | null;
  options_capability_status: string;
  data_freshness: string;
  blocked_reasons: string[];
};

const labels: Record<string, string> = {
  queued: "Exploring",
  exploring: "Exploring",
  analyzing: "Analyzing",
  evaluating_trade: "Paper Trading",
  paper_order_submitted: "Paper Trading",
  monitoring: "Paper Trading",
  completed: "Completed",
  blocked: "Trade blocked",
  quota_exhausted: "Provider quota reached",
  provider_unavailable: "Provider unavailable",
  failed_safe: "Stopped safely",
};

export function ActivationPanel() {
  const [cycle, setCycle] = useState<PublicCycle | null>(null);
  const [mode, setMode] = useState<CycleMode>("stocks");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function activate() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/venuz/cycles/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!response.ok) throw new Error("Venuz could not start a safe cycle.");
      setCycle((await response.json()) as PublicCycle);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Venuz is unavailable.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (
      !cycle ||
      [
        "completed",
        "blocked",
        "quota_exhausted",
        "provider_unavailable",
        "failed_safe",
      ].includes(cycle.state)
    )
      return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`/api/venuz/cycles/${cycle.cycle_id}`);
      if (response.ok) setCycle((await response.json()) as PublicCycle);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [cycle]);

  return (
    <section
      aria-labelledby="activation-title"
      className="rounded-[2rem] border border-slate-800 bg-slate-950 p-6 text-white shadow-2xl sm:p-8"
    >
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-300">
        One global cycle
      </p>
      <h2 id="activation-title" className="mt-3 text-2xl font-semibold">
        {cycle ? labels[cycle.state] : "Ready when you are"}
      </h2>
      <fieldset className="mt-5" disabled={loading}>
        <legend className="sr-only">Trading mode</legend>
        <div className="grid grid-cols-3 gap-2">
          {(["stocks", "options", "mixed"] as const).map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={mode === item}
              onClick={() => setMode(item)}
              className={`rounded-full border px-3 py-2 text-xs font-semibold capitalize ${
                mode === item
                  ? "border-amber-300 bg-amber-300 text-slate-950"
                  : "border-slate-700 text-slate-300"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </fieldset>
      <p className="mt-3 text-sm leading-6 text-slate-300">
        {cycle
          ? "You are viewing the shared, auditable cycle. Repeated clicks never create visitor-specific orders."
          : "Join the current market cycle. Venuz reuses valid data and submits only to Alpaca Paper when every deterministic guard passes."}
      </p>
      {cycle && (
        <p className="mt-4 font-mono text-xs text-slate-400">
          Cycle {cycle.cycle_id.slice(0, 8)} · {cycle.data_freshness}
        </p>
      )}
      {cycle?.blocked_reasons.map((reason) => (
        <p
          key={reason}
          role="alert"
          className="mt-3 rounded-xl bg-amber-300/10 p-3 text-sm text-amber-200"
        >
          {reason}
        </p>
      ))}
      {error && (
        <p
          role="alert"
          className="mt-4 rounded-xl bg-red-400/10 p-3 text-sm text-red-200"
        >
          {error}
        </p>
      )}
      <Button
        onClick={activate}
        disabled={loading}
        className="mt-6 w-full rounded-full bg-amber-300 text-slate-950 hover:bg-amber-200"
      >
        {loading ? (
          <LoaderCircle aria-hidden="true" className="animate-spin" />
        ) : cycle ? (
          <RefreshCw aria-hidden="true" />
        ) : (
          <ArrowUpRight aria-hidden="true" />
        )}
        {loading
          ? "Joining cycle…"
          : cycle
            ? "Retry or rejoin"
            : "Activate Venuz"}
      </Button>
      <div className="mt-5 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-400">
        <a
          className="underline hover:text-white"
          href="https://github.com/Soymaferlopezp/Venuz"
          target="_blank"
          rel="noreferrer"
        >
          Open repository
        </a>
        <a className="underline hover:text-white" href="#setup">
          Setup instructions
        </a>
      </div>
    </section>
  );
}
