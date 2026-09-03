"use client";

import { useEffect, useState } from "react";

import {
  StateNotice,
  type ViewState,
} from "@/components/analysis/state-notice";
import type { ProviderStatus } from "@/lib/api-contracts";
import { venuzFetch, VenuzApiError } from "@/lib/venuz-api";

export function ProvidersClient() {
  const [value, setValue] = useState<ProviderStatus | null>(null);
  const [state, setState] = useState<ViewState>("loading");
  useEffect(() => {
    void venuzFetch<ProviderStatus>("providers/status")
      .then((response) => {
        setValue(response);
        setState("loading");
      })
      .catch((error: unknown) => {
        setState(
          error instanceof VenuzApiError && error.status === 401
            ? "unauthenticated"
            : "error",
        );
      });
  }, []);
  if (!value) return <StateNotice state={state} />;
  const remaining =
    value.alpha_vantage_budget.request_limit -
    value.alpha_vantage_budget.request_count;
  const providers = [
    [
      "Alpaca Market Data",
      value.alpaca,
      "Assets, quotes, daily bars, and exchange calendar",
    ],
    ["SEC EDGAR", value.sec_edgar, "Company Facts and Submissions"],
    [
      "Alpha Vantage",
      value.alpha_vantage,
      "Consensus estimates and revisions only",
    ],
    [
      "Supabase",
      value.supabase,
      "Persistent state, RLS, cache, budget, and audit",
    ],
  ];
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2">
        {providers.map(([name, providerState, purpose]) => (
          <article
            key={name}
            className="rounded-2xl border border-slate-200 bg-white p-6"
          >
            <p className="text-sm text-slate-500">{purpose}</p>
            <h2 className="mt-2 text-xl font-semibold">{name}</h2>
            <p className="mt-5 rounded-xl bg-slate-50 p-3 text-sm font-medium text-slate-700">
              {providerState}
            </p>
          </article>
        ))}
      </div>
      <div
        role="note"
        className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-950"
      >
        Alpha Vantage: {remaining}/{value.alpha_vantage_budget.request_limit}{" "}
        requests available for {value.alpha_vantage_budget.budget_date}.{" "}
        {value.note}
      </div>
    </>
  );
}
