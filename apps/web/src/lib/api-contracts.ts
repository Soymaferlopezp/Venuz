// Shared DTO contract mirrored from the FastAPI OpenAPI schemas.
export type Status = "green" | "yellow" | "red" | "insufficient";
export type ValuationStatus =
  | "strong_green"
  | "green"
  | "yellow"
  | "red"
  | "insufficient";
export type DataState =
  | "fresh"
  | "stale"
  | "insufficient"
  | "provider_exhausted"
  | "error";

export interface Provenance {
  provider: string;
  source_url: string;
  fetched_at: string;
  source_as_of: string;
  cache_key: string | null;
  fresh_until: string | null;
}

export interface Evidence {
  evidence_id: string;
  title: string;
  provenance: Provenance;
}

export interface Criterion {
  criterion: string;
  status: Status;
  formula: string;
  reason: string;
  values: Record<string, string | number | boolean | null>;
  evidence_ids: string[];
}

export interface RatioObservation {
  ratio_type: "pe" | "pfcf";
  period_end: string;
  value: string | null;
  included: boolean;
  reason: string | null;
  source_url: string;
}

export interface RatioCluster {
  ratio_type: string;
  observations: RatioObservation[];
  median: string | null;
  confidence: "high" | "medium" | "low" | "insufficient";
}

export interface ValuationRange {
  current_price: string;
  estimated_price_pe: string | null;
  estimated_price_pfcf: string | null;
  floor: string | null;
  ceiling: string | null;
  green_price: string | null;
  strong_green_price: string | null;
  status: ValuationStatus;
  confidence: "high" | "medium" | "low" | "insufficient";
  automatic_action_eligible: boolean;
  report_date: string | null;
  frozen_at: string | null;
  refresh_eligible_at: string | null;
}

export interface CompanyThesis {
  company: {
    ticker: string;
    name: string;
    exchange: string;
    sector: { slug: string; name: string; prioritized: boolean };
    cik: string | null;
  };
  generated_at: string;
  eligibility: "eligible" | "no_trade";
  criteria: Criterion[];
  pe_cluster: RatioCluster;
  pfcf_cluster: RatioCluster;
  valuation: ValuationRange;
  evidence: Evidence[];
  no_trade_reasons: string[];
  data_state: DataState;
  fresh_until: string | null;
  earnings_state: string;
  financial_years: Array<{
    period: {
      fiscal_year: number;
      fiscal_period: string;
      start: string | null;
      end: string;
      filed_at: string | null;
    };
    revenue: string;
    net_income: string;
    operating_cash_flow: string;
    capital_expenditures: string;
    total_assets: string;
    total_liabilities: string;
    total_debt: string;
  }>;
  forward_estimates: {
    comparable_period: string;
    consensus_eps: string | null;
    previous_consensus_eps: string | null;
    prior_year_eps: string | null;
    provenance: Provenance;
  } | null;
  market: {
    price: string;
    bid: string;
    ask: string;
    average_daily_dollar_volume: string | null;
    observed_at: string;
    provenance: Provenance;
  } | null;
}

export interface WatchlistResponse {
  items: CompanyThesis[];
}

export interface ProviderStatus {
  alpaca: string;
  sec_edgar: string;
  alpha_vantage: string;
  supabase: string;
  alpha_vantage_budget: {
    provider: string;
    budget_date: string;
    request_limit: number;
    request_count: number;
  };
  note: string;
}

export interface ApiErrorBody {
  detail?: string | { state?: DataState; message?: string };
}
