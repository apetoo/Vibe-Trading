import { useCallback, useEffect, useState } from 'react';
import { Network, Plus, Edit3, Check, X, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../lib/api';
import type { IndustryNode, IndustryNodeCreate, IndustryNodeUpdate, PendingReview } from '../types/industryChain';

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

// ─── Main Page ─────────────────────────────────────────────────────

export default function IndustryChain() {
  const { t } = useTranslation();

  // Data state
  const [nodes, setNodes] = useState<IndustryNode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Editor state
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editType, setEditType] = useState<IndustryNode['type']>('unknown');
  const [editDescription, setEditDescription] = useState('');

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
  }, [nodes]);

  const handleToggle = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // ─── CRUD operations ────────────────────────────────────────────

  const handleSaveEdit = async () => {
    if (!selectedId) return;
    try {
      const update: IndustryNodeUpdate = {
        name: editName,
        type: editType,
        description: editDescription || undefined,
      };
      await api.updateIndustryNode(selectedId, update);
      setEditing(false);
      await fetchTree();
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
      await fetchTree();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete node');
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
                      </div>
                      {selectedNode.description && (
                        <p className="mt-1 text-sm text-muted-foreground">{selectedNode.description}</p>
                      )}
                    </div>
                    <div className="flex gap-1">
                      {!editing && (
                        <button
                          className="inline-flex items-center gap-1 h-8 px-3 rounded-md border border-input bg-background text-sm hover:bg-accent"
                          onClick={() => setEditing(true)}
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
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-muted-foreground mb-1">
                            {t('industryChain.descriptionLabel')}
                          </label>
                          <textarea
                            className="w-full min-h-[60px] px-3 py-2 rounded-md border border-input bg-background text-sm resize-y"
                            value={editDescription}
                            onChange={(e) => setEditDescription(e.target.value)}
                          />
                        </div>
                        <div className="flex gap-2">
                          <button
                            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90"
                            onClick={handleSaveEdit}
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

                  {/* Node children list */}
                  {(() => {
                    const childNodes = getChildren(nodes, selectedNode.id);
                    if (childNodes.length === 0) return null;
                    return (
                      <section>
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
