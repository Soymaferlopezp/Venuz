"use client";

import { useEffect, useState } from "react";

import {
  StateNotice,
  type ViewState,
} from "@/components/analysis/state-notice";
import { StatusPill } from "@/components/analysis/status-pill";
import type { CompanyThesis, RatioCluster } from "@/lib/api-contracts";
import { money, timestamp, venuzFetch, VenuzApiError } from "@/lib/venuz-api";

function stateFor(error: unknown): ViewState {
  if (error instanceof VenuzApiError) {
    if (error.status === 401) return "unauthenticated";
    if (error.status === 404) return "empty";
    if (error.state === "provider_exhausted") return "provider_exhausted";
  }
  return "error";
}

function RatioPanel({ cluster }: { cluster: RatioCluster }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6">
      <h2 className="text-xl font-semibold">
        {cluster.ratio_type.toUpperCase()} observations
      </h2>
      <p className="mt-2 text-sm text-slate-600">
        Cluster median {cluster.median ?? "unavailable"} - {cluster.confidence}{" "}
        confidence
      </p>
      <ul className="mt-5 space-y-2">
        {cluster.observations.map((item) => (
          <li
            key={item.period_end}
            className="flex flex-wrap justify-between gap-2 border-b border-slate-100 pb-2 text-sm"
          >
            <span>
              {item.period_end} - {item.value ?? "invalid"}
            </span>
            <span
              className={item.included ? "text-emerald-700" : "text-red-700"}
            >
              {item.reason}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function CompanyClient({ symbol }: { symbol: string }) {
  const [thesis, setThesis] = useState<CompanyThesis | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [running, setRunning] = useState(false);
  useEffect(() => {
    let active = true;
    void venuzFetch<CompanyThesis>("analysis/" + symbol + "/latest")
      .then((value) => {
        if (!active) return;
        setThesis(value);
        setViewState(
          value.data_state === "stale"
            ? "stale"
            : value.data_state === "insufficient"
              ? "insufficient"
              : "loading",
        );
      })
      .catch((error: unknown) => {
        if (active) setViewState(stateFor(error));
      });
    return () => {
      active = false;
    };
  }, [symbol]);

  async function analyze() {
    setRunning(true);
    setViewState("loading");
    try {
      const value = await venuzFetch<CompanyThesis>("analysis/" + symbol, {
        method: "POST",
        body: JSON.stringify({ mode: "provider" }),
      });
      setThesis(value);
      setViewState(value.data_state === "fresh" ? "loading" : value.data_state);
    } catch (error) {
      setViewState(stateFor(error));
    } finally {
      setRunning(false);
    }
  }

  if (!thesis) {
    return (
      <main className="mx-auto max-w-7xl px-6 py-12 lg:px-10">
        <StateNotice state={viewState} />
        {viewState === "empty" ? (
          <button
            type="button"
            onClick={analyze}
            disabled={running}
            className="mt-5 rounded-full bg-emerald-800 px-5 py-3 font-semibold text-white"
          >
            {running ? "Analyzing..." : "Analyze " + symbol}
          </button>
        ) : null}
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-12 lg:px-10">
      {viewState !== "loading" ? <StateNotice state={viewState} /> : null}
      <div className="mt-6 flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Reproducible thesis - {thesis.company.ticker}
          </p>
          <h1 className="mt-3 text-4xl font-semibold">{thesis.company.name}</h1>
          <p className="mt-3 text-slate-600">
            Updated {timestamp(thesis.generated_at)} - freshness{" "}
            {thesis.data_state}
          </p>
        </div>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-xs font-semibold uppercase text-amber-800">
            Quarterly frozen range
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {money(thesis.valuation.floor)} to {money(thesis.valuation.ceiling)}
          </p>
          <p className="mt-1 text-xs text-amber-900">
            Report {thesis.valuation.report_date ?? "unavailable"} - frozen{" "}
            {timestamp(thesis.valuation.frozen_at)}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={analyze}
        disabled={running}
        className="mt-6 rounded-full border border-emerald-800 px-5 py-2 font-semibold text-emerald-900"
      >
        {running ? "Refreshing..." : "Refresh provider data"}
      </button>

      <section aria-labelledby="financials-title" className="mt-10">
        <h2 id="financials-title" className="text-2xl font-semibold">
          Four-year fundamentals
        </h2>
        <div className="mt-5 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">
              Four fiscal years of normalized SEC values in US dollars
            </caption>
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
              <tr>
                {[
                  "Year",
                  "Revenue",
                  "Net income",
                  "Operating cash flow",
                  "Capital expenditures",
                  "Total assets",
                  "Total liabilities",
                  "Debt",
                ].map((label) => (
                  <th key={label} scope="col" className="px-4 py-3 font-medium">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {thesis.financial_years.map((year) => {
                return (
                  <tr
                    key={year.period.end}
                    className="border-b border-slate-100 last:border-0"
                  >
                    <th scope="row" className="px-4 py-3">
                      {year.period.fiscal_year}
                    </th>
                    <td className="px-4 py-3">{money(year.revenue)}</td>
                    <td className="px-4 py-3">{money(year.net_income)}</td>
                    <td className="px-4 py-3">
                      {money(year.operating_cash_flow)}
                    </td>
                    <td className="px-4 py-3">
                      {money(year.capital_expenditures)}
                    </td>
                    <td className="px-4 py-3">{money(year.total_assets)}</td>
                    <td className="px-4 py-3">
                      {money(year.total_liabilities)}
                    </td>
                    <td className="px-4 py-3">{money(year.total_debt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="criteria-title" className="mt-10">
        <h2 id="criteria-title" className="text-2xl font-semibold">
          Seven criteria
        </h2>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {thesis.criteria.map((criterion) => (
            <article
              key={criterion.criterion}
              className="rounded-2xl border border-slate-200 bg-white p-5"
            >
              <div className="flex justify-between gap-4">
                <h3 className="font-semibold">
                  {criterion.criterion.replaceAll("_", " ")}
                </h3>
                <StatusPill status={criterion.status} />
              </div>
              <p className="mt-4 text-sm font-medium">{criterion.reason}</p>
              <p className="mt-2 text-sm text-slate-600">{criterion.formula}</p>
              <pre className="mt-4 overflow-x-auto rounded-xl bg-slate-50 p-3 text-xs">
                {JSON.stringify(criterion.values, null, 2)}
              </pre>
              <p className="mt-3 text-xs text-slate-500">
                Evidence: {criterion.evidence_ids.join(", ") || "missing"}
              </p>
            </article>
          ))}
        </div>
      </section>

      <div className="mt-10 grid gap-5 lg:grid-cols-2">
        <RatioPanel cluster={thesis.pe_cluster} />
        <RatioPanel cluster={thesis.pfcf_cluster} />
      </div>
      <section className="mt-10 rounded-2xl bg-slate-950 p-6 text-white">
        <h2 className="text-xl font-semibold">Deterministic result</h2>
        <p className="mt-5 text-4xl font-semibold">
          {thesis.eligibility === "eligible" ? "ELIGIBLE" : "NO TRADE"}
        </p>
        <p className="mt-4 text-slate-300">
          {thesis.no_trade_reasons.join(" | ") || "All analysis gates passed."}
        </p>
      </section>

      <section aria-labelledby="evidence-title" className="mt-10">
        <h2 id="evidence-title" className="text-2xl font-semibold">
          Evidence timeline
        </h2>
        <ol className="mt-5 grid gap-4 md:grid-cols-3">
          {thesis.evidence.map((item) => (
            <li
              key={item.evidence_id}
              className="rounded-2xl border border-slate-200 bg-white p-5"
            >
              <p className="text-xs font-semibold uppercase text-emerald-800">
                {item.provenance.provider}
              </p>
              <h3 className="mt-2 font-semibold">{item.title}</h3>
              <p className="mt-3 text-sm">
                Source as of {timestamp(item.provenance.source_as_of)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Fetched {timestamp(item.provenance.fetched_at)}
              </p>
              <a
                href={item.provenance.source_url}
                rel="noreferrer"
                target="_blank"
                className="mt-4 inline-block text-sm font-semibold text-emerald-800 underline"
              >
                Open source
              </a>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
