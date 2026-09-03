import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProvidersPage from "@/app/providers/page";
import ScreenerPage from "@/app/screener/page";
import {
  StateNotice,
  type ViewState,
} from "@/components/analysis/state-notice";
import { StatusPill } from "@/components/analysis/status-pill";
import type { CompanyThesis } from "@/lib/api-contracts";

function thesis(symbol: string): CompanyThesis {
  return {
    company: {
      ticker: symbol,
      name: symbol + " Corp.",
      exchange: "NASDAQ",
      sector: { slug: "technology", name: "Technology", prioritized: true },
      cik: "0000000001",
    },
    generated_at: "2026-09-02T18:00:00Z",
    eligibility: "no_trade",
    criteria: [],
    pe_cluster: {
      ratio_type: "pe",
      observations: [],
      median: "20",
      confidence: "high",
    },
    pfcf_cluster: {
      ratio_type: "pfcf",
      observations: [],
      median: "18",
      confidence: "high",
    },
    valuation: {
      current_price: "100",
      estimated_price_pe: "110",
      estimated_price_pfcf: "120",
      floor: "110",
      ceiling: "120",
      green_price: "104.5",
      strong_green_price: "99",
      status: "green",
      confidence: "high",
      automatic_action_eligible: true,
      report_date: "2026-08-28",
      frozen_at: "2026-09-02T18:00:00Z",
      refresh_eligible_at: null,
    },
    evidence: [],
    no_trade_reasons: ["next_earnings_schedule_unavailable"],
    data_state: "fresh",
    fresh_until: "2026-09-02T18:01:00Z",
    earnings_state: "open",
    financial_years: [],
    forward_estimates: null,
    market: null,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("connected phase 2 analysis views", () => {
  it("renders a persisted ten-company watchlist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            items: [
              "AAPL",
              "MSFT",
              "NVDA",
              "GOOGL",
              "AMZN",
              "META",
              "AVGO",
              "LLY",
              "COST",
              "XOM",
            ].map(thesis),
          }),
          { status: 200 },
        ),
      ),
    );
    render(<ScreenerPage />);
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View thesis" })).toHaveLength(
      10,
    );
    expect(screen.getByText(/PAPER TRADING/)).toBeInTheDocument();
  });

  it("shows the persisted Alpha Vantage budget without secrets", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            alpaca: "configured_read_only",
            sec_edgar: "configured_cached",
            alpha_vantage: "configured_budgeted",
            supabase: "connected",
            alpha_vantage_budget: {
              provider: "alpha_vantage",
              budget_date: "2026-09-02",
              request_limit: 25,
              request_count: 4,
            },
            note: "Missing inputs produce NO_TRADE.",
          }),
          { status: 200 },
        ),
      ),
    );
    render(<ProvidersPage />);
    expect(
      await screen.findByText(/21\/25 requests available/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/secret/i)).not.toBeInTheDocument();
  });

  it("communicates every required operational state with text", () => {
    const states: ViewState[] = [
      "loading",
      "empty",
      "stale",
      "insufficient",
      "provider_exhausted",
      "unauthenticated",
      "error",
    ];
    for (const state of states) {
      const view = render(<StateNotice state={state} />);
      expect(within(view.container).getByRole("heading")).toBeInTheDocument();
      view.unmount();
    }
    render(<StatusPill status="strong_green" />);
    expect(screen.getByText("strong green")).toBeInTheDocument();
  });
});
