import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PortfolioMenu } from "../PortfolioMenu";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    getPortfolioHoldings: vi.fn(),
  },
}));

function renderMenu() {
  return render(
    <MemoryRouter>
      <PortfolioMenu collapsed={false} />
    </MemoryRouter>,
  );
}

const READY = {
  connected: true,
  profile: "alpaca-paper",
  is_paper: true,
  holdings: [
    { symbol: "AAPL", name: "", quantity: 100, average_cost: 150, current_price: 175.5,
      market_value: 17550, unrealized_pnl: 2550, pnl_percent: 17.0, side: "long" },
    { symbol: "TSLA", name: "", quantity: 10, average_cost: 300, current_price: 245,
      market_value: 2450, unrealized_pnl: -550, pnl_percent: -18.33, side: "long" },
    { symbol: "MISS", name: "", quantity: 5, average_cost: null, current_price: 12,
      market_value: 60, unrealized_pnl: null, pnl_percent: null, side: "long" },
  ],
  summary: { market_value: 20060, cost_basis: 18000, unrealized_pnl: 2000,
             pnl_percent: 11.11, cash: 5000 },
  error: null,
};

describe("PortfolioMenu", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("renders the toggle button", () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue({ ...READY, holdings: [] });
    renderMenu();
    expect(screen.getByText(/portfolio/i)).toBeInTheDocument();
  });

  it("shows loading then holdings when opened", async () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue(READY);
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /portfolio/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.getByText("TSLA")).toBeInTheDocument();
  });

  it("renders positive P&L in green and negative in red", async () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue(READY);
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /portfolio/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    const aaplPnl = screen.getByText("+17.00%");
    expect((aaplPnl as HTMLElement).className).toMatch(/green|success|text-up/i);
    const tslaPnl = screen.getByText("-18.33%");
    expect((tslaPnl as HTMLElement).className).toMatch(/red|danger|text-down/i);
  });

  it("renders — for missing pnl_percent", async () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue(READY);
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /portfolio/i }));
    await waitFor(() => expect(screen.getByText("MISS")).toBeInTheDocument());
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows manage-portfolio CTA when connected=false (no holdings yet)", async () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue({
      connected: false, profile: null, is_paper: null, holdings: [],
      summary: { market_value: 0, cost_basis: 0, unrealized_pnl: 0, pnl_percent: null, cash: null },
      error: "no holdings yet",
    });
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /portfolio/i }));
    await waitFor(() => expect(screen.getByText(/manage holdings/i)).toBeInTheDocument());
  });

  it("shows empty state when connected with no holdings", async () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue({ ...READY, holdings: [] });
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /portfolio/i }));
    await waitFor(() => expect(screen.getByText(/no positions/i)).toBeInTheDocument());
  });

  it("shows error + retry when fetch rejects", async () => {
    vi.mocked(api.getPortfolioHoldings).mockRejectedValue(new Error("network down"));
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /portfolio/i }));
    await waitFor(() => expect(screen.getByText(/failed to load/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("refetches on refresh click", async () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue(READY);
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /portfolio/i }));
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    const callsBefore = vi.mocked(api.getPortfolioHoldings).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => expect(vi.mocked(api.getPortfolioHoldings).mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("closes popover on outside click", async () => {
    vi.mocked(api.getPortfolioHoldings).mockResolvedValue(READY);
    renderMenu();
    const btn = screen.getByRole("button", { name: /portfolio/i });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(screen.queryByText("AAPL")).not.toBeInTheDocument());
  });
});
