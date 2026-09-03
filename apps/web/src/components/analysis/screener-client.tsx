"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  StateNotice,
  type ViewState,
} from "@/components/analysis/state-notice";
import { StatusPill } from "@/components/analysis/status-pill";
import type { CompanyThesis, WatchlistResponse } from "@/lib/api-contracts";
import { money, timestamp, venuzFetch, VenuzApiError } from "@/lib/venuz-api";

function errorState(error: unknown): ViewState {
  if (error instanceof VenuzApiError) {
    if (error.status === 401) return "unauthenticated";
    if (error.state === "provider_exhausted") return "provider_exhausted";
  }
  return "error";
}

function dataState(items: CompanyThesis[]): ViewState {
  if (!items.length) return "empty";
  if (items.some((item) => item.data_state === "stale")) return "stale";
  if (items.some((item) => item.data_state === "insufficient"))
    return "insufficient";
  return "loading";
}

export function ScreenerClient() {
  const [items, setItems] = useState<CompanyThesis[]>([]);
  const [state, setState] = useState<ViewState>("loading");
  const [running, setRunning] = useState(false);
  useEffect(() => {
    let active = true;
    void venuzFetch<WatchlistResponse>("watchlists/latest")
      .then((response) => {
        if (!active) return;
        setItems(response.items);
        setState(dataState(response.items));
      })
      .catch((error: unknown) => {
        if (active) setState(errorState(error));
      });
    return () => {
      active = false;
    };
  }, []);

  async function runScan() {
    setRunning(true);
    setState("loading");
    try {
      const response = await venuzFetch<WatchlistResponse>(
        "watchlists/build?mode=provider",
        { method: "POST" },
      );
      setItems(response.items);
      setState(dataState(response.items));
    } catch (error) {
      setState(errorState(error));
    } finally {
      setRunning(false);
    }
  }

  const visibleState =
    items.length === 0 || state !== "loading" ? state : undefined;
  return (
    <main className="mx-auto max-w-7xl px-6 py-12 lg:px-10">
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Deterministic watchlist
          </p>
          <h1 className="mt-3 text-4xl font-semibold">
            Evidence before action.
          </h1>
          <p className="mt-4 max-w-2xl text-slate-600">
            The scan reads Alpaca, SEC EDGAR, and budgeted Alpha Vantage
            estimates, then persists every decision in Supabase.
          </p>
        </div>
        <button
          type="button"
          onClick={runScan}
          disabled={running}
          className="rounded-full bg-emerald-800 px-5 py-3 font-semibold text-white disabled:opacity-60"
        >
          {running ? "Running scan..." : "Run scan"}
        </button>
      </div>
      {visibleState ? (
        <div className="mt-8">
          <StateNotice state={visibleState} />
        </div>
      ) : null}
      {items.length ? (
        <div className="mt-8 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Persisted equity watchlist</caption>
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
              <tr>
                {[
                  "Ticker",
                  "Sector",
                  "Price",
                  "Frozen range",
                  "State",
                  "Updated",
                  "Action",
                ].map((label) => (
                  <th key={label} scope="col" className="px-5 py-4 font-medium">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.company.ticker}
                  className="border-b border-slate-100 last:border-0"
                >
                  <th scope="row" className="px-5 py-4 font-semibold">
                    {item.company.ticker}
                  </th>
                  <td className="px-5 py-4 text-slate-600">
                    {item.company.sector.name}
                  </td>
                  <td className="px-5 py-4">
                    {money(item.valuation.current_price)}
                  </td>
                  <td className="px-5 py-4">
                    {money(item.valuation.floor)} to{" "}
                    {money(item.valuation.ceiling)}
                  </td>
                  <td className="px-5 py-4">
                    <StatusPill status={item.valuation.status} />
                    {item.data_state !== "fresh" ? (
                      <span className="ml-2 text-xs text-amber-800">
                        {item.data_state}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-5 py-4 text-xs text-slate-500">
                    {timestamp(item.generated_at)}
                  </td>
                  <td className="px-5 py-4">
                    <Link
                      href={"/companies/" + item.company.ticker}
                      className="font-semibold text-emerald-800 underline"
                    >
                      View thesis
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </main>
  );
}
