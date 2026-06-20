import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Plus, RefreshCw, Save, Trash2, Wallet, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api, type Holding, type PortfolioHoldings } from "@/lib/api";
import { cn } from "@/lib/utils";

interface EditableRow {
  symbol: string;
  name: string;
  quantity: string; // string while editing, parsed on save
  average_cost: string;
  // pristine snapshot fields used to detect dirty rows
  _pristine_symbol?: string;
  _pristine_qty?: string;
  _pristine_cost?: string;
  _pristine_name?: string;
  _isNew?: boolean;
}

function holdingToRow(h: Holding): EditableRow {
  return {
    symbol: h.symbol,
    name: h.name ?? "",
    quantity: String(h.quantity),
    average_cost: h.average_cost !== null ? String(h.average_cost) : "",
    _pristine_symbol: h.symbol,
    _pristine_qty: String(h.quantity),
    _pristine_cost: h.average_cost !== null ? String(h.average_cost) : "",
    _pristine_name: h.name ?? "",
  };
}

function isDirty(row: EditableRow): boolean {
  if (row._isNew) return true;
  return (
    row.symbol !== row._pristine_symbol ||
    row.quantity !== row._pristine_qty ||
    row.average_cost !== row._pristine_cost ||
    row.name !== row._pristine_name
  );
}

export function Portfolio() {
  const { t } = useTranslation();
  const [data, setData] = useState<PortfolioHoldings | null>(null);
  const [rows, setRows] = useState<EditableRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async (force = true) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getPortfolioHoldings(undefined, force);
      setData(result);
      setRows(result.holdings.map(holdingToRow));
    } catch (e) {
      setError((e as Error).message || "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const dirtyCount = useMemo(() => rows.filter(isDirty).length, [rows]);

  const updateRow = (idx: number, patch: Partial<EditableRow>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRow = () => {
    setRows((prev) => [
      ...prev,
      {
        symbol: "",
        name: "",
        quantity: "",
        average_cost: "",
        _isNew: true,
      },
    ]);
  };

  const deleteRow = async (idx: number) => {
    const row = rows[idx];
    if (row._isNew) {
      // not yet persisted, just drop locally
      setRows((prev) => prev.filter((_, i) => i !== idx));
      return;
    }
    const symbol = row._pristine_symbol || row.symbol;
    if (!window.confirm(t("portfolio.confirmDelete", { symbol }))) return;
    try {
      await api.deleteHolding(symbol);
      setRows((prev) => prev.filter((_, i) => i !== idx));
      toast.success(t("portfolio.saved"));
    } catch (e) {
      toast.error(`${t("portfolio.saveFailed")}: ${(e as Error).message}`);
    }
  };

  const validateRow = (row: EditableRow): string | null => {
    const sym = row.symbol.trim();
    if (!sym) return t("portfolio.symbolRequired");
    const qty = Number(row.quantity);
    if (!Number.isFinite(qty) || qty <= 0) return t("portfolio.qtyMustBePositive");
    const cost = Number(row.average_cost);
    if (!Number.isFinite(cost) || cost < 0) return t("portfolio.costNonNegative");
    return null;
  };

  const saveAll = async () => {
    // Validate all dirty rows
    for (const row of rows) {
      if (!isDirty(row)) continue;
      const err = validateRow(row);
      if (err) {
        toast.error(`${row.symbol || "(empty)"}: ${err}`);
        return;
      }
    }
    setSaving(true);
    try {
      const payload = rows.map((r) => ({
        symbol: r.symbol.trim().toUpperCase(),
        quantity: Number(r.quantity),
        average_cost: Number(r.average_cost),
        name: r.name.trim(),
      }));
      await api.replaceHoldings(payload);
      toast.success(t("portfolio.saved"));
      await refresh();
    } catch (e) {
      toast.error(`${t("portfolio.saveFailed")}: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <Link
            to="/"
            className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3 w-3" />
            Home
          </Link>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Wallet className="h-6 w-6 text-primary" />
            {t("portfolio.title")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("portfolio.subtitle")}</p>
          {data && data.profile && (
            <p className="mt-1 text-xs text-muted-foreground">
              source: <span className="font-mono">{data.profile}</span>
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => refresh(true)}
          disabled={loading}
          className="rounded-md border p-2 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          aria-label="refresh"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/30 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">{t("portfolio.tableSymbol")}</th>
              <th className="px-3 py-2 text-left">{t("portfolio.tableName")}</th>
              <th className="px-3 py-2 text-right">{t("portfolio.tableQuantity")}</th>
              <th className="px-3 py-2 text-right">{t("portfolio.tableAvgCost")}</th>
              <th className="w-16 px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-xs text-muted-foreground">
                  {t("portfolio.noHoldings")}
                </td>
              </tr>
            )}
            {rows.map((row, idx) => {
              const dirty = isDirty(row);
              return (
                <tr
                  key={`${idx}-${row._pristine_symbol ?? row.symbol}`}
                  className={cn("border-b last:border-0", dirty && "bg-amber-500/5")}
                >
                  <td className="px-2 py-1.5">
                    <input
                      value={row.symbol}
                      onChange={(e) => updateRow(idx, { symbol: e.target.value.toUpperCase() })}
                      placeholder="AAPL"
                      className="w-24 rounded border bg-background px-2 py-1 font-mono text-sm uppercase outline-none focus:border-primary"
                      readOnly={!row._isNew}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      value={row.name}
                      onChange={(e) => updateRow(idx, { name: e.target.value })}
                      placeholder=""
                      className="w-full rounded border bg-background px-2 py-1 text-sm outline-none focus:border-primary"
                    />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <input
                      type="number"
                      step="any"
                      value={row.quantity}
                      onChange={(e) => updateRow(idx, { quantity: e.target.value })}
                      className="w-24 rounded border bg-background px-2 py-1 text-right text-sm tabular-nums outline-none focus:border-primary"
                    />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <input
                      type="number"
                      step="any"
                      value={row.average_cost}
                      onChange={(e) => updateRow(idx, { average_cost: e.target.value })}
                      className="w-28 rounded border bg-background px-2 py-1 text-right text-sm tabular-nums outline-none focus:border-primary"
                    />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => deleteRow(idx)}
                      className="rounded p-1 text-muted-foreground hover:bg-red-500/10 hover:text-red-600"
                      aria-label={t("portfolio.deleteRow")}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={addRow}
          className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("portfolio.addRow")}
        </button>
        <div className="flex items-center gap-2">
          {dirtyCount > 0 && (
            <button
              type="button"
              onClick={() => refresh(true)}
              disabled={saving}
              className="text-xs text-muted-foreground hover:underline"
            >
              {t("portfolio.discardChanges")}
            </button>
          )}
          <button
            type="button"
            onClick={saveAll}
            disabled={saving || dirtyCount === 0}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {t("portfolio.saveAll")} {dirtyCount > 0 && `(${dirtyCount})`}
          </button>
        </div>
      </div>
    </div>
  );
}
