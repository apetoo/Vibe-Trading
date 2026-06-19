import { useEffect, useRef, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { Wallet, RefreshCw, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { api, type PortfolioHoldings } from "@/lib/api";

type Status = "loading" | "ready" | "error";

function fmtMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function pnlClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  return v > 0 ? "text-green-600 dark:text-green-400" : v < 0 ? "text-red-600 dark:text-red-400" : "text-muted-foreground";
}

function pnlMoneyClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  return v > 0 ? "text-green-600 dark:text-green-400" : v < 0 ? "text-red-600 dark:text-red-400" : "text-muted-foreground";
}

export function PortfolioMenu({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<PortfolioHoldings | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const lastFetchAt = useRef<number>(0);

  const load = useCallback(async (force = false) => {
    // De-dup concurrent refreshes (double-click guard).
    if (inFlight) return;
    const stale = Date.now() - lastFetchAt.current > 60_000;
    if (!force && data && !stale) return;
    setInFlight(true);
    if (!data) setStatus("loading");
    try {
      const result = await api.getPortfolioHoldings();
      setData(result);
      setStatus("ready");
      lastFetchAt.current = Date.now();
    } catch {
      setStatus("error");
    } finally {
      setInFlight(false);
    }
  }, [data, inFlight]);

  // Initial load on mount.
  useEffect(() => {
    void load();
  }, [load]);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const onToggle = () => {
    const next = !open;
    setOpen(next);
    if (next) void load();
  };

  const label = collapsed ? null : (
    <span className="text-sm">{t("portfolio.title")}</span>
  );

  return (
    <div ref={containerRef} className="relative px-2 py-1">
      <button
        type="button"
        onClick={onToggle}
        aria-label={t("portfolio.title")}
        className={cn(
          "flex items-center rounded-md text-sm transition-colors w-full",
          collapsed ? "justify-center p-2" : "gap-3 px-3 py-2",
          "text-muted-foreground hover:bg-muted hover:text-foreground",
          open && "bg-muted text-foreground",
        )}
        title={collapsed ? t("portfolio.title") : undefined}
      >
        <Wallet className="h-4 w-4 shrink-0" aria-hidden="true" />
        {label}
        {!collapsed && <ChevronDown className={cn("h-3 w-3 ml-auto transition-transform", open && "rotate-180")} />}
      </button>

      {open && (
        <div className="absolute left-full top-0 ml-2 z-50 w-80 rounded-lg border bg-card shadow-lg">
          {/* Summary header */}
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-xs font-medium text-muted-foreground">{t("portfolio.title")}</span>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={inFlight}
              aria-label={t("portfolio.refresh")}
              className="p-1 text-muted-foreground hover:text-foreground rounded disabled:opacity-50"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", inFlight && "animate-spin")} />
            </button>
          </div>

          {status === "loading" && (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">{t("portfolio.loading")}</div>
          )}

          {status === "error" && (
            <div className="px-3 py-6 text-center">
              <p className="text-xs text-muted-foreground mb-2">{t("portfolio.error")}</p>
              <button
                type="button"
                onClick={() => void load(true)}
                className="text-xs text-primary hover:underline"
              >
                {t("portfolio.retry")}
              </button>
            </div>
          )}

          {status === "ready" && data && (
            <>
              {data.connected ? (
                <>
                  {/* Summary */}
                  <div className="px-3 py-2 border-b">
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">{t("portfolio.totalValue")}</span>
                      <span className="font-medium">{fmtMoney(data.summary.market_value)}</span>
                    </div>
                    <div className="flex justify-between text-xs mt-1">
                      <span className="text-muted-foreground">{t("portfolio.pnl")}</span>
                      <span className={cn("font-medium", pnlMoneyClass(data.summary.unrealized_pnl))}>
                        {fmtMoney(data.summary.unrealized_pnl)} ({fmtPct(data.summary.pnl_percent)})
                      </span>
                    </div>
                    {data.summary.cash !== null && (
                      <div className="flex justify-between text-xs mt-1">
                        <span className="text-muted-foreground">{t("portfolio.cash")}</span>
                        <span className="font-medium">{fmtMoney(data.summary.cash)}</span>
                      </div>
                    )}
                  </div>

                  {/* Holdings list */}
                  {data.holdings.length === 0 ? (
                    <div className="px-3 py-6 text-center text-xs text-muted-foreground">{t("portfolio.empty")}</div>
                  ) : (
                    <div className="max-h-80 overflow-auto">
                      {data.holdings.map((h) => (
                        <div key={h.symbol} className="px-3 py-2 border-b last:border-b-0 hover:bg-muted/50">
                          <div className="flex justify-between items-center">
                            <span className="text-xs font-medium">{h.symbol}</span>
                            <span className={cn("text-xs font-medium", pnlClass(h.pnl_percent))} data-pnl>
                              {fmtPct(h.pnl_percent)}
                            </span>
                          </div>
                          <div className="flex justify-between text-[11px] text-muted-foreground mt-0.5">
                            <span>{t("portfolio.quantity")}: {h.quantity}</span>
                            <span>{t("portfolio.price")}: {fmtMoney(h.current_price)}</span>
                          </div>
                          <div className="flex justify-between text-[11px] text-muted-foreground">
                            <span>{t("portfolio.cost")}: {fmtMoney(h.average_cost)}</span>
                            <span className={pnlMoneyClass(h.unrealized_pnl)}>
                              {t("portfolio.pnl")}: {fmtMoney(h.unrealized_pnl)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="px-3 py-6 text-center">
                  <p className="text-xs text-muted-foreground mb-2">{t("portfolio.disconnected")}</p>
                  <Link to="/settings" onClick={() => setOpen(false)} className="text-xs text-primary hover:underline">
                    {t("portfolio.connectCta")}
                  </Link>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
