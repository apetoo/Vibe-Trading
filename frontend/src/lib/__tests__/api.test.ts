import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../api";

describe("api.getPortfolioHoldings", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
  });
  afterEach(() => vi.restoreAllMocks());

  it("GETs /portfolio/holdings with no profile by default", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ connected: true, holdings: [] })),
    });
    await api.getPortfolioHoldings();
    const [url, init] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/portfolio/holdings");
    expect(init?.method).toBeUndefined();
  });

  it("appends profile_id when provided", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ connected: true, holdings: [] })),
    });
    await api.getPortfolioHoldings("futu-live");
    const url = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toBe("/portfolio/holdings?profile_id=futu-live");
  });

  it("appends force=1 when force=true (manual refresh bypasses backend cache)", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({ connected: true, holdings: [] })),
    });
    await api.getPortfolioHoldings(undefined, true);
    const url = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(url).toBe("/portfolio/holdings?force=1");
  });
});
