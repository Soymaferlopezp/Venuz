import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiHealth } from "@/components/health/api-health";

describe("ApiHealth", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("shows loading and then a safe paper-ready state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ status: "ok", trading_mode: "paper" }),
      }),
    );
    render(<ApiHealth />);
    expect(screen.getByText("Comprobando API…")).toBeInTheDocument();
    await act(async () => Promise.resolve());
    expect(screen.getByText("API operativa · modo paper")).toBeInTheDocument();
  });

  it("identifies a sleeping Render service while the request is pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => undefined)),
    );
    render(<ApiHealth />);
    await act(async () => vi.advanceTimersByTimeAsync(1800));
    expect(screen.getByText("Render está despertando")).toBeInTheDocument();
  });

  it("fails closed for an invalid health response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ status: "ok", trading_mode: "live" }),
      }),
    );
    render(<ApiHealth />);
    await act(async () => Promise.resolve());
    expect(screen.getByRole("alert")).toHaveTextContent("API no disponible");
  });
});
