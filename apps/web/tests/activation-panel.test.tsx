import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivationPanel } from "@/components/cycles/activation-panel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ActivationPanel", () => {
  it("joins the one shared cycle and shows safe state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          cycle_id: "12345678-cycle",
          state: "blocked",
          data_freshness: "cached",
          blocked_reasons: ["Market is closed"],
        }),
      }),
    );
    render(<ActivationPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Activate Venuz" }));
    await act(async () => Promise.resolve());
    expect(screen.getByText("Trade blocked")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Market is closed");
    expect(screen.getByText(/cached/)).toBeInTheDocument();
  });

  it("reports activation failure honestly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    render(<ActivationPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Activate Venuz" }));
    await act(async () => Promise.resolve());
    expect(screen.getByRole("alert")).toHaveTextContent("could not start");
  });
});
