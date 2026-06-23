import { useCallback, useEffect, useState } from 'react';
import { Network, Plus, Edit3, Check, X, ChevronDown, ChevronRight, Loader2, ExternalLink, FileText, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../lib/api';
import type {
  IndustryNode,
  IndustryNodeCreate,
  IndustryNodeUpdate,
  IndustryNodeFields,
  IndustryNodeDetailResponse,
  IndustryRelation,
  IndustryRelationCreate,
  RelationType,
  PendingReview,
} from '../types/industryChain';

// ─── Helpers ───────────────────────────────────────────────────────

/** Recursively walk node children to find a node by id */
function findNode(nodes: IndustryNode[], id: string): IndustryNode | undefined {
  for (const n of nodes) {
    if (n.id === id) return n;
  }
  return undefined;
}

/** Get children of a given parent */
function getChildren(nodes: IndustryNode[], parentId: string | null): IndustryNode[] {
  return nodes.filter((n) => n.parent_id === parentId);
}

/** Pretty-print a JSON field for read-only display */
function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v ?? '');
  }
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  annual_report: '年报',
  prospectus: '招股书',
  exchange_announcement: '交易所公告',
  broker_report: '券商研报',
};

// ─── Node Tree Sub-component ───────────────────────────────────────

function TreeNode({
  node,
  nodes,
  depth,
  selectedId,
  onSelect,
  expandedIds,
  onToggle,
}: {
  node: IndustryNode;
  nodes: IndustryNode[];
  depth: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  expandedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  const children = getChildren(nodes, node.id);
  const isExpanded = expandedIds.has(node.id);
  const isSelected = selectedId === node.id;

  const typeColors: Record<string, string> = {
    chain: 'text-blue-600 dark:text-blue-400',
    sector: 'text-emerald-600 dark:text-emerald-400',
    product: 'text-purple-600 dark:text-purple-400',
    company: 'text-amber-600 dark:text-amber-400',
    external: 'text-orange-600 dark:text-orange-400',
  };

  return (
    <>
      <button
        className={`w-full flex items-center gap-1 px-2 py-1.5 text-sm rounded-md transition-colors hover:bg-accent/50 ${
          isSelected ? 'bg-accent font-medium' : ''
        }`}
        style={{ paddingLeft: `${12 + depth * 16}px` }}
        onClick={() => onSelect(node.id)}
      >
        {children.length > 0 ? (
          <span
            className="shrink-0 cursor-pointer p-0.5 rounded hover:bg-muted"
            onClick={(e) => {
              e.stopPropagation();
              onToggle(node.id);
            }}
          >
            {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </span>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <span className={`text-[10px] uppercase tracking-wider font-semibold ${typeColors[node.type] ?? 'text-muted-foreground'}`}>
          {node.type}
        </span>
        <span className="truncate">{node.name}</span>
      </button>
      {isExpanded && children.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          nodes={nodes}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
          expandedIds={expandedIds}
          onToggle={onToggle}
        />
      ))}
    </>
  );
}

// ─── Read-only field row helpers ───────────────────────────────────

function FieldRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="grid grid-cols-[120px_1fr] gap-2 py-1.5 text-sm">
      <span className="text-xs font-medium text-muted-foreground pt-0.5">{label}</span>
      <span className="whitespace-pre-wrap leading-relaxed">{value}</span>
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (!value || (typeof value === 'object' && Object.keys(value as object).length === 0)) return null;
  return (
    <div className="py-1.5">
      <div className="text-xs font-medium text-muted-foreground mb-1">{label}</div>
      <pre className="text-xs bg-muted/50 dark:bg-muted/30 rounded-md p-3 overflow-x-auto whitespace-pre-wrap leading-relaxed">
        {prettyJson(value)}
      </pre>
    </div>
  );
}

function DetailView({
  detail,
  relations,
  onDeleteRelation,
}: {
  detail: IndustryNodeDetailResponse;
  relations: IndustryRelation[];
  onDeleteRelation?: (relationId: string) => void;
}) {
  const { t } = useTranslation();
  const f = detail.fields;
  const isCompany = detail.node.type === 'company';
  const validationLabels: Record<string, string> = {
    unverified: t('industryChain.validationUnverified'),
    verified: t('industryChain.validationVerified'),
    pending: t('industryChain.validationPending'),
  };
  const relationTypeLabels: Record<string, string> = {
    supplier: t('industryChain.relUpstream'),
    customer: t('industryChain.relDownstream'),
    substitute: t('industryChain.relSubstitute'),
    related: t('industryChain.relRelated'),
    certified_by: t('industryChain.relCertifiedBy'),
    segment_of: t('industryChain.relBusinessLines'),
  };

  const hasMarket =
    !!(f?.market_size || f?.growth_rate || f?.chain_position || f?.localization || f?.gross_margin);
  const hasStock = !!(
    f?.financials && Object.keys(f.financials).length > 0
  ) || !!(f?.operating_metrics && Object.keys(f.operating_metrics).length > 0) ||
    !!(f?.customer_structure && Object.keys(f.customer_structure).length > 0);

  return (
    <div className="space-y-5">
      {/* Validation badge */}
      {f?.validation_status && (
        <div className="flex items-center gap-2">
          <span className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded ${
            f.validation_status === 'verified'
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
              : f.validation_status === 'pending'
                ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                : 'bg-muted text-muted-foreground'
          }`}>
            {validationLabels[f.validation_status] ?? f.validation_status}
          </span>
          {detail.snapshot_at && (
            <span className="text-xs text-muted-foreground">
              {new Date(detail.snapshot_at).toLocaleDateString()}
            </span>
          )}
        </div>
      )}

      {/* Overview */}
      {(f?.summary || f?.narrative) && (
        <section>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            {t('industryChain.sectionOverview')}
          </h3>
          {f?.summary && <p className="text-sm font-medium mb-2">{f.summary}</p>}
          {f?.narrative && <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">{f.narrative}</p>}
        </section>
      )}

      {/* Supply Relations */}
      <section>
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
          {t('industryChain.sectionRelations')}
        </h3>
        {relations.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('industryChain.noRelations')}</p>
        ) : (
          (() => {
            const groupOrder: RelationType[] = ['supplier', 'customer', 'substitute', 'related', 'certified_by', 'segment_of'];
            const grouped = new Map<RelationType, IndustryRelation[]>();
            for (const r of relations) {
              const list = grouped.get(r.relation_type) || [];
              list.push(r);
              grouped.set(r.relation_type, list);
            }
            return groupOrder.map((type) => {
              const items = grouped.get(type);
              if (!items || items.length === 0) return null;
              return (
                <div key={type} className="mb-3 last:mb-0">
                  <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
                    {relationTypeLabels[type]}
                  </h4>
                  <div className="divide-y divide-border/60">
                    {items.map((r) => (
                      <div key={r.relation_id} className="flex items-center justify-between py-1.5">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-sm truncate">{r.other_name}</span>
                          {r.note && (
                            <span className="text-xs text-muted-foreground truncate hidden sm:inline">— {r.note}</span>
                          )}
                        </div>
                        {onDeleteRelation && (
                          <button
                            className="shrink-0 p-1 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                            onClick={() => {
                              if (window.confirm(t('industryChain.confirmDeleteRelation'))) {
                                onDeleteRelation(r.relation_id);
                              }
                            }}
                            title={t('common.delete')}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            });
          })()
        )}
      </section>

      {/* Market & position */}
      {hasMarket && (
        <section>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            {t('industryChain.sectionMarket')}
          </h3>
          <div className="divide-y divide-border/60">
            <FieldRow label={t('industryChain.fieldMarketSize')} value={f?.market_size ?? ''} />
            <FieldRow label={t('industryChain.fieldGrowthRate')} value={f?.growth_rate ?? ''} />
            <FieldRow label={t('industryChain.fieldChainPosition')} value={f?.chain_position ?? ''} />
            <FieldRow label={t('industryChain.fieldLocalization')} value={f?.localization ?? ''} />
            <FieldRow label={t('industryChain.fieldGrossMargin')} value={f?.gross_margin ?? ''} />
          </div>
        </section>
      )}

      {/* Tech trend */}
      {f?.tech_trend && (
        <section>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            {t('industryChain.sectionTech')}
          </h3>
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{f.tech_trend}</p>
        </section>
      )}

      {/* Macro drivers */}
      {f?.macro_drivers && f.macro_drivers.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            {t('industryChain.sectionMacro')}
          </h3>
          <ul className="space-y-1.5">
            {f.macro_drivers.map((d, i) => (
              <li key={i} className="text-sm flex gap-2">
                <span className="text-primary shrink-0">•</span>
                <span className="leading-relaxed">{d}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Stock-only fundamentals */}
      {isCompany && hasStock && (
        <section>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            {t('industryChain.sectionStock')}
          </h3>
          <div className="space-y-2">
            <JsonBlock label={t('industryChain.fieldFinancials')} value={f?.financials} />
            <JsonBlock label={t('industryChain.fieldOperatingMetrics')} value={f?.operating_metrics} />
            <JsonBlock label={t('industryChain.fieldCustomerStructure')} value={f?.customer_structure} />
          </div>
        </section>
      )}

      {/* Sources */}
      {detail.sources.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            {t('industryChain.sectionSources')} ({detail.sources.length})
          </h3>
          <div className="space-y-2">
            {detail.sources.map((s, i) => (
              <div key={i} className="flex items-start gap-2 p-2 rounded-md bg-muted/40 dark:bg-muted/20">
                <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {SOURCE_TYPE_LABELS[s.source_type] ?? s.source_type}
                    </span>
                    {s.title && <span className="text-sm font-medium">{s.title}</span>}
                    {s.publisher && <span className="text-xs text-muted-foreground">{s.publisher}</span>}
                    {s.published_date && <span className="text-xs text-muted-foreground">{s.published_date}</span>}
                  </div>
                  {s.cited_text && (
                    <p className="text-xs text-muted-foreground mt-1 italic line-clamp-2">{s.cited_text}</p>
                  )}
                  {s.url && (
                    <a href={s.url} target="_blank" rel="noreferrer" className="text-xs text-primary hover:underline mt-1 inline-flex items-center gap-0.5">
                      <ExternalLink className="h-3 w-3" />
                      {t('industryChain.viewSource')}
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ─── Edit form for rich fields ─────────────────────────────────────

function RichFieldsEditor({
  fields,
  onChange,
}: {
  fields: IndustryNodeFields;
  onChange: (next: IndustryNodeFields) => void;
}) {
  const { t } = useTranslation();
  const set = (patch: Partial<IndustryNodeFields>) => onChange({ ...fields, ...patch });

  const macroText = Array.isArray(fields.macro_drivers)
    ? fields.macro_drivers.join('\n')
    : (fields.macro_drivers as unknown as string) ?? '';

  const [finText, setFinText] = useState('');
  const [opText, setOpText] = useState('');
  const [custText, setCustText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    setFinText(prettyJson(fields.financials));
    setOpText(prettyJson(fields.operating_metrics));
    setCustText(prettyJson(fields.customer_structure));
    setJsonError(null);
  }, [fields.financials, fields.operating_metrics, fields.customer_structure]);

  const syncJson = (which: 'financials' | 'operating_metrics' | 'customer_structure', text: string) => {
    if (which === 'financials') setFinText(text);
    if (which === 'operating_metrics') setOpText(text);
    if (which === 'customer_structure') setCustText(text);
    if (!text.trim()) {
      set({ [which]: {} } as Partial<IndustryNodeFields>);
      setJsonError(null);
      return;
    }
    try {
      const parsed = JSON.parse(text);
      set({ [which]: parsed } as Partial<IndustryNodeFields>);
      setJsonError(null);
    } catch {
      setJsonError(`${which}: ${t('industryChain.jsonInvalid')}`);
    }
  };

  const textCls = 'w-full min-h-[60px] px-3 py-2 rounded-md border border-input bg-background text-sm resize-y';
  const labelCls = 'block text-xs font-medium text-muted-foreground mb-1';

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
        {t('industryChain.editRichFields')}
      </h4>

      <div>
        <label className={labelCls}>{t('industryChain.fieldNarrative')}</label>
        <textarea className={textCls} value={fields.narrative ?? ''} onChange={(e) => set({ narrative: e.target.value })} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>{t('industryChain.fieldMarketSize')}</label>
          <textarea className={textCls} value={fields.market_size ?? ''} onChange={(e) => set({ market_size: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>{t('industryChain.fieldGrowthRate')}</label>
          <textarea className={textCls} value={fields.growth_rate ?? ''} onChange={(e) => set({ growth_rate: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>{t('industryChain.fieldChainPosition')}</label>
          <textarea className={textCls} value={fields.chain_position ?? ''} onChange={(e) => set({ chain_position: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>{t('industryChain.fieldLocalization')}</label>
          <textarea className={textCls} value={fields.localization ?? ''} onChange={(e) => set({ localization: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>{t('industryChain.fieldGrossMargin')}</label>
          <textarea className={textCls} value={fields.gross_margin ?? ''} onChange={(e) => set({ gross_margin: e.target.value })} />
        </div>
        <div>
          <label className={labelCls}>{t('industryChain.fieldValidationStatus')}</label>
          <select
            className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
            value={fields.validation_status ?? 'unverified'}
            onChange={(e) => set({ validation_status: e.target.value })}
          >
            <option value="unverified">{t('industryChain.validationUnverified')}</option>
            <option value="verified">{t('industryChain.validationVerified')}</option>
            <option value="pending">{t('industryChain.validationPending')}</option>
          </select>
        </div>
      </div>

      <div>
        <label className={labelCls}>{t('industryChain.fieldTechTrend')}</label>
        <textarea className={textCls} value={fields.tech_trend ?? ''} onChange={(e) => set({ tech_trend: e.target.value })} />
      </div>

      <div>
        <label className={labelCls}>{t('industryChain.fieldMacroDrivers')}</label>
        <textarea
          className={textCls}
          placeholder={t('industryChain.macroDriversPlaceholder')}
          value={macroText}
          onChange={(e) => set({ macro_drivers: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean) })}
        />
      </div>

      <div>
        <label className={labelCls}>{t('industryChain.fieldFinancials')}</label>
        <textarea className={`${textCls} font-mono text-xs`} value={finText} onChange={(e) => syncJson('financials', e.target.value)} />
      </div>
      <div>
        <label className={labelCls}>{t('industryChain.fieldOperatingMetrics')}</label>
        <textarea className={`${textCls} font-mono text-xs`} value={opText} onChange={(e) => syncJson('operating_metrics', e.target.value)} />
      </div>
      <div>
        <label className={labelCls}>{t('industryChain.fieldCustomerStructure')}</label>
        <textarea className={`${textCls} font-mono text-xs`} value={custText} onChange={(e) => syncJson('customer_structure', e.target.value)} />
      </div>

      {jsonError && (
        <p className="text-xs text-destructive">{jsonError}</p>
      )}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────

export default function IndustryChain() {
  const { t } = useTranslation();

  // Data state
  const [nodes, setNodes] = useState<IndustryNode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail state
  const [detail, setDetail] = useState<IndustryNodeDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Relations state
  const [relations, setRelations] = useState<IndustryRelation[]>([]);

  // Editor state
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editType, setEditType] = useState<IndustryNode['type']>('unknown');
  const [editDescription, setEditDescription] = useState('');
  const [editFields, setEditFields] = useState<IndustryNodeFields>({});
  const [editJsonError, setEditJsonError] = useState<string | null>(null);

  // Add-relation form state
  const [newRelationType, setNewRelationType] = useState<RelationType>('supplier');
  const [newRelationTarget, setNewRelationTarget] = useState('');
  const [newRelationNote, setNewRelationNote] = useState('');

  // New node form state
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<IndustryNode['type']>('sector');
  const [newDescription, setNewDescription] = useState('');

  // Pending reviews state
  const [reviews, setReviews] = useState<PendingReview[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'tree' | 'reviews'>('tree');

  // ─── Data fetching ──────────────────────────────────────────────

  const fetchTree = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getIndustryChainTree();
      setNodes(res.tree.nodes);
      // Expand root level by default
      const rootIds = new Set<string>();
      res.tree.nodes.filter((n: IndustryNode) => n.parent_id === null).forEach((n: IndustryNode) => rootIds.add(n.id));
      setExpandedIds(rootIds);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load industry chain');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchReviews = useCallback(async () => {
    try {
      setReviewsLoading(true);
      const res = await api.getPendingReviews();
      setReviews(res.reviews);
    } catch {
      // Silently fail – reviews are secondary
    } finally {
      setReviewsLoading(false);
    }
  }, []);

  const fetchDetail = useCallback(async (id: string) => {
    try {
      setDetailLoading(true);
      const d = await api.getIndustryNodeDetail(id);
      setDetail(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load node detail');
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const fetchRelations = useCallback(async (id: string) => {
    try {
      const res = await api.getIndustryNodeRelations(id);
      setRelations(res.relations);
    } catch {
      setRelations([]);
    }
  }, []);

  useEffect(() => {
    fetchTree();
    fetchReviews();
  }, [fetchTree, fetchReviews]);

  // ─── Selection ──────────────────────────────────────────────────

  const selectedNode = selectedId ? findNode(nodes, selectedId) : undefined;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setEditing(false);
    setShowAddForm(false);
    const node = findNode(nodes, id);
    if (node) {
      setEditName(node.name);
      setEditType(node.type);
      setEditDescription(node.description ?? '');
    }
    fetchDetail(id);
    fetchRelations(id);
  }, [nodes, fetchDetail, fetchRelations]);

  const handleToggle = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const startEditing = () => {
    if (!detail) return;
    setEditFields({ ...detail.fields });
    setEditJsonError(null);
    setEditing(true);
  };

  // ─── CRUD operations ────────────────────────────────────────────

  const handleSaveEdit = async () => {
    if (!selectedId) return;
    if (editJsonError) {
      setError(editJsonError);
      return;
    }
    try {
      const update: IndustryNodeUpdate = {
        name: editName,
        type: editType,
        description: editDescription || undefined,
        fields: editFields,
      };
      await api.updateIndustryNode(selectedId, update);
      setEditing(false);
      await fetchTree();
      await fetchDetail(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update node');
    }
  };

  const handleAddNode = async () => {
    if (!newName.trim()) return;
    try {
      const data: IndustryNodeCreate = {
        name: newName.trim(),
        type: newType,
        parent_id: selectedId,
        description: newDescription.trim() || undefined,
      };
      await api.addIndustryNode(data);
      setShowAddForm(false);
      setNewName('');
      setNewType('sector');
      setNewDescription('');
      // Expand parent to show new child
      if (selectedId) {
        setExpandedIds((prev) => new Set(prev).add(selectedId));
      }
      await fetchTree();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add node');
    }
  };

  const handleDeleteNode = async () => {
    if (!selectedId) return;
    if (!window.confirm(t('industryChain.confirmDelete'))) return;
    try {
      await api.deleteIndustryNode(selectedId);
      setSelectedId(null);
      setDetail(null);
      await fetchTree();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete node');
    }
  };

  const handleDeleteRelation = async (relationId: string) => {
    try {
      await api.deleteIndustryRelation(relationId);
      if (selectedId) await fetchRelations(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete relation');
    }
  };

  const handleAddRelation = async () => {
    if (!selectedId || !newRelationTarget) return;
    try {
      const data: IndustryRelationCreate = {
        relation_type: newRelationType,
        target_id: newRelationTarget,
        note: newRelationNote.trim() || undefined,
      };
      await api.addIndustryRelation(selectedId, data);
      setNewRelationTarget('');
      setNewRelationNote('');
      await fetchRelations(selectedId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add relation');
    }
  };

  // ─── Review actions ─────────────────────────────────────────────

  const handleApproveReview = async (id: string) => {
    try {
      await api.approveReview(id);
      setReviews((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve review');
    }
  };

  const handleRejectReview = async (id: string) => {
    try {
      await api.rejectReview(id);
      setReviews((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject review');
    }
  };

  // ─── Render ─────────────────────────────────────────────────────

  const rootNodes = getChildren(nodes, null);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b">
        <div className="flex items-center gap-3">
          <Network className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-semibold">{t('industryChain.title')}</h1>
        </div>
      </div>

      {error && (
        <div className="mx-6 mt-4 px-4 py-3 bg-destructive/10 text-destructive text-sm rounded-md border border-destructive/20">
          {error}
          <button className="ml-2 underline" onClick={() => setError(null)}>
            {t('common.dismiss')}
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 px-6 pt-4 border-b">
        <button
          className={`px-4 py-2 text-sm font-medium rounded-t-md transition-colors ${
            activeTab === 'tree'
              ? 'bg-background border-x border-t border-border text-foreground -mb-px'
              : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
          }`}
          onClick={() => setActiveTab('tree')}
        >
          {t('industryChain.treeTab')}
        </button>
        <button
          className={`relative px-4 py-2 text-sm font-medium rounded-t-md transition-colors ${
            activeTab === 'reviews'
              ? 'bg-background border-x border-t border-border text-foreground -mb-px'
              : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
          }`}
          onClick={() => setActiveTab('reviews')}
        >
          {t('industryChain.reviewsTab')}
          {reviews.length > 0 && (
            <span className="ml-2 inline-flex items-center justify-center w-5 h-5 text-[11px] font-bold rounded-full bg-primary text-primary-foreground">
              {reviews.length}
            </span>
          )}
        </button>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {activeTab === 'tree' && (
          <>
            {/* Tree sidebar */}
            <aside className="w-72 border-r overflow-y-auto shrink-0">
              <div className="p-3 border-b flex items-center justify-between">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  {t('industryChain.nodeTree')}
                </span>
                <button
                  className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  onClick={() => {
                    setShowAddForm(true);
                    setEditing(false);
                  }}
                >
                  <Plus className="h-3.5 w-3.5" />
                  {t('industryChain.addNode')}
                </button>
              </div>

              {loading ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin mr-2" />
                  {t('common.loading')}
                </div>
              ) : rootNodes.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 px-4 text-center text-muted-foreground">
                  <Network className="h-10 w-10 mb-3 opacity-30" />
                  <p className="text-sm">{t('industryChain.emptyTree')}</p>
                  <button
                    className="mt-3 text-sm text-primary hover:underline"
                    onClick={() => {
                      setShowAddForm(true);
                    }}
                  >
                    {t('industryChain.createFirstNode')}
                  </button>
                </div>
              ) : (
                <div className="py-2">
                  {rootNodes.map((node) => (
                    <TreeNode
                      key={node.id}
                      node={node}
                      nodes={nodes}
                      depth={0}
                      selectedId={selectedId}
                      onSelect={handleSelect}
                      expandedIds={expandedIds}
                      onToggle={handleToggle}
                    />
                  ))}
                </div>
              )}
            </aside>

            {/* Detail / editor panel */}
            <main className="flex-1 overflow-y-auto p-6">
              {showAddForm && (
                <section className="mb-6 p-4 border rounded-lg bg-card">
                  <h3 className="text-sm font-semibold mb-3">{t('industryChain.addNodeForm')}</h3>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-1">
                        {t('industryChain.nameLabel')}
                      </label>
                      <input
                        className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
                        placeholder={t('industryChain.namePlaceholder')}
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-1">
                        {t('industryChain.typeLabel')}
                      </label>
                      <select
                        className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
                        value={newType}
                        onChange={(e) => setNewType(e.target.value as IndustryNode['type'])}
                      >
                        <option value="chain">{t('industryChain.typeChain')}</option>
                        <option value="sector">{t('industryChain.typeSector')}</option>
                        <option value="product">{t('industryChain.typeProduct')}</option>
                        <option value="company">{t('industryChain.typeCompany')}</option>
                        <option value="external">{t('industryChain.typeExternal')}</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-1">
                        {t('industryChain.descriptionLabel')}
                      </label>
                      <textarea
                        className="w-full min-h-[60px] px-3 py-2 rounded-md border border-input bg-background text-sm resize-y"
                        placeholder={t('industryChain.descriptionPlaceholder')}
                        value={newDescription}
                        onChange={(e) => setNewDescription(e.target.value)}
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90"
                        onClick={handleAddNode}
                      >
                        <Plus className="h-4 w-4" />
                        {t('common.create')}
                      </button>
                      <button
                        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-input bg-background text-sm hover:bg-accent"
                        onClick={() => setShowAddForm(false)}
                      >
                        {t('common.cancel')}
                      </button>
                    </div>
                  </div>
                </section>
              )}

              {selectedNode ? (
                <div>
                  {/* Node header */}
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                          {selectedNode.type}
                        </span>
                        <h2 className="text-lg font-semibold">{selectedNode.name}</h2>
                        {detail?.node.code && (
                          <span className="text-xs text-muted-foreground font-mono">{detail.node.code}</span>
                        )}
                      </div>
                      {selectedNode.description && !editing && (
                        <p className="mt-1 text-sm text-muted-foreground">{selectedNode.description}</p>
                      )}
                    </div>
                    <div className="flex gap-1">
                      {!editing && (
                        <button
                          className="inline-flex items-center gap-1 h-8 px-3 rounded-md border border-input bg-background text-sm hover:bg-accent"
                          onClick={startEditing}
                          disabled={!detail}
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                          {t('common.edit')}
                        </button>
                      )}
                      <button
                        className="inline-flex items-center gap-1 h-8 px-3 rounded-md border border-destructive/30 text-destructive text-sm hover:bg-destructive/10"
                        onClick={handleDeleteNode}
                      >
                        {t('common.delete')}
                      </button>
                    </div>
                  </div>

                  {/* Edit form */}
                  {editing && (
                    <section className="p-4 border rounded-lg bg-card mb-4">
                      <h3 className="text-sm font-semibold mb-3">{t('industryChain.editNodeForm')}</h3>
                      <div className="space-y-3">
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">
                            {t('industryChain.nameLabel')}
                          </label>
                          <input
                            className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
                            value={editName}
                            onChange={(e) => setEditName(e.target.value)}
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">
                            {t('industryChain.typeLabel')}
                          </label>
                          <select
                            className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
                            value={editType}
                            onChange={(e) => setEditType(e.target.value as IndustryNode['type'])}
                          >
                            <option value="chain">{t('industryChain.typeChain')}</option>
                            <option value="sector">{t('industryChain.typeSector')}</option>
                            <option value="product">{t('industryChain.typeProduct')}</option>
                            <option value="company">{t('industryChain.typeCompany')}</option>
                            <option value="external">{t('industryChain.typeExternal')}</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">
                            {t('industryChain.fieldSummary')}
                          </label>
                          <textarea
                            className="w-full min-h-[40px] px-3 py-2 rounded-md border border-input bg-background text-sm resize-y"
                            value={editDescription}
                            onChange={(e) => setEditDescription(e.target.value)}
                          />
                        </div>

                        <RichFieldsEditor
                          fields={editFields}
                          onChange={(next) => {
                            setEditFields(next);
                            setEditJsonError(null);
                          }}
                        />

                        {/* Add relation */}
                        <div className="border-t pt-3">
                          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                            {t('industryChain.addRelation')}
                          </h4>
                          <div className="grid grid-cols-3 gap-2">
                            <div>
                              <label className="block text-xs text-muted-foreground mb-1">
                                {t('industryChain.relationType')}
                              </label>
                              <select
                                className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm"
                                value={newRelationType}
                                onChange={(e) => setNewRelationType(e.target.value as RelationType)}
                              >
                                <option value="supplier">{t('industryChain.relUpstream')}</option>
                                <option value="customer">{t('industryChain.relDownstream')}</option>
                                <option value="substitute">{t('industryChain.relSubstitute')}</option>
                                <option value="related">{t('industryChain.relRelated')}</option>
                                <option value="certified_by">{t('industryChain.relCertifiedBy')}</option>
                                <option value="segment_of">{t('industryChain.relBusinessLines')}</option>
                              </select>
                            </div>
                            <div>
                              <label className="block text-xs text-muted-foreground mb-1">
                                {t('industryChain.targetNode')}
                              </label>
                              <select
                                className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm"
                                value={newRelationTarget}
                                onChange={(e) => setNewRelationTarget(e.target.value)}
                              >
                                <option value="">{t('industryChain.selectTarget')}</option>
                                {nodes
                                  .filter((n) => n.id !== selectedId)
                                  .map((n) => (
                                    <option key={n.id} value={n.id}>
                                      [{n.type}] {n.name}
                                    </option>
                                  ))}
                              </select>
                            </div>
                            <div>
                              <label className="block text-xs text-muted-foreground mb-1">
                                {t('industryChain.relationNote')}
                              </label>
                              <input
                                className="w-full h-9 px-2 rounded-md border border-input bg-background text-sm"
                                value={newRelationNote}
                                onChange={(e) => setNewRelationNote(e.target.value)}
                                placeholder={t('common.optional')}
                              />
                            </div>
                          </div>
                          <div className="mt-2">
                            <button
                              className="inline-flex items-center gap-1.5 h-7 px-3 rounded-md border border-input bg-background text-xs hover:bg-accent disabled:opacity-50"
                              onClick={handleAddRelation}
                              disabled={!newRelationTarget}
                            >
                              <Plus className="h-3.5 w-3.5" />
                              {t('industryChain.addRelation')}
                            </button>
                          </div>
                        </div>

                        <div className="flex gap-2 pt-2 border-t">
                          <button
                            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
                            onClick={handleSaveEdit}
                            disabled={!!editJsonError}
                          >
                            <Check className="h-4 w-4" />
                            {t('common.save')}
                          </button>
                          <button
                            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-input bg-background text-sm hover:bg-accent"
                            onClick={() => setEditing(false)}
                          >
                            {t('common.cancel')}
                          </button>
                        </div>
                      </div>
                    </section>
                  )}

                  {/* Detail view (read-only) */}
                  {!editing && (
                    detailLoading ? (
                      <div className="flex items-center justify-center py-12 text-muted-foreground">
                        <Loader2 className="h-5 w-5 animate-spin mr-2" />
                        {t('common.loading')}
                      </div>
                    ) : detail ? (
                      <DetailView detail={detail} relations={relations} onDeleteRelation={handleDeleteRelation} />
                    ) : (
                      <p className="text-sm text-muted-foreground">{t('industryChain.noDetail')}</p>
                    )
                  )}

                  {/* Node children list */}
                  {(() => {
                    const childNodes = getChildren(nodes, selectedNode.id);
                    if (childNodes.length === 0) return null;
                    return (
                      <section className="mt-6 pt-4 border-t">
                        <h3 className="text-sm font-semibold mb-2">{t('industryChain.children')} ({childNodes.length})</h3>
                        <div className="space-y-1">
                          {childNodes.map((child) => (
                            <button
                              key={child.id}
                              className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm hover:bg-accent/50 transition-colors"
                              onClick={() => handleSelect(child.id)}
                            >
                              <span className="text-[10px] uppercase tracking-wider font-semibold px-1 py-0.5 rounded bg-muted text-muted-foreground">
                                {child.type}
                              </span>
                              <span>{child.name}</span>
                            </button>
                          ))}
                        </div>
                      </section>
                    );
                  })()}
                </div>
              ) : (
                !showAddForm && (
                  <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
                    <Network className="h-12 w-12 mb-3 opacity-20" />
                    <p className="text-sm">{t('industryChain.selectNodePrompt')}</p>
                  </div>
                )
              )}
            </main>
          </>
        )}

        {/* ── Reviews Tab ───────────────────────────────────────────── */}
        {activeTab === 'reviews' && (
          <div className="flex-1 overflow-y-auto p-6">
            <h2 className="text-lg font-semibold mb-4">{t('industryChain.pendingReviews')}</h2>

            {reviewsLoading ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                {t('common.loading')}
              </div>
            ) : reviews.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
                <Check className="h-12 w-12 mb-3 opacity-20" />
                <p className="text-sm">{t('industryChain.noPendingReviews')}</p>
              </div>
            ) : (
              <div className="space-y-3">
                {reviews.map((review) => (
                  <div key={review.id} className="p-4 border rounded-lg bg-card">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span
                            className={`text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ${
                              review.status === 'pending'
                                ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                                : review.status === 'approved'
                                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                                  : 'bg-destructive/10 text-destructive'
                            }`}
                          >
                            {review.status}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {t('industryChain.reviewNodeId')}: {review.node_id.slice(0, 8)}...
                          </span>
                        </div>
                        <p className="text-sm">
                          <span className="font-medium">{review.field}</span>: {review.suggested_value}
                        </p>
                        {review.original_value && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {t('industryChain.originalValue')}: {review.original_value}
                          </p>
                        )}
                        <p className="text-xs text-muted-foreground mt-1">
                          {new Date(review.created_at).toLocaleString()}
                        </p>
                      </div>
                      {review.status === 'pending' && (
                        <div className="flex gap-1 shrink-0">
                          <button
                            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700"
                            onClick={() => handleApproveReview(review.id)}
                            title={t('common.approve')}
                          >
                            <Check className="h-3.5 w-3.5" />
                          </button>
                          <button
                            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-destructive text-destructive-foreground text-xs font-medium hover:bg-destructive/90"
                            onClick={() => handleRejectReview(review.id)}
                            title={t('common.reject')}
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
