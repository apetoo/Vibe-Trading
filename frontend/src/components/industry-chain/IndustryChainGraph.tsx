/**
 * React Flow knowledge-graph view for the industry chain.
 *
 * Renders nodes (5 types + external) with dagre hierarchical (TB) layout.
 * Tree (parent_id) edges form the faint layered backbone; 6 relation edge
 * types overlay as colored labeled edges. Hover shows a STRUCTURE-only
 * tooltip (no dynamic fields). Click selects → detail panel.
 */

import '@xyflow/react/dist/style.css';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  NodeToolbar,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from '@xyflow/react';
import { useTranslation } from 'react-i18next';
import {
  Building2, Globe, Layers, Maximize, Network, Package, RefreshCw, Search,
} from 'lucide-react';
import clsx from 'clsx';

import type {
  IndustryNode, IndustryRelationEdge, RelationType,
} from '@/types/industryChain';
import {
  buildRelationEdges, buildTreeEdges, getChainPath, getNodeCode,
  getRelationCounts, layoutWithDagre, NODE_HEIGHT, NODE_TYPE_STYLES,
  NODE_WIDTH, RELATION_EDGE_STYLES, RELATION_ORDER, type GraphEdgeData,
  type NodeIconName,
} from './graphUtils';

const ICONS: Record<NodeIconName, typeof Network> = {
  Network, Layers, Package, Building2, Globe,
};

const ALL_TYPES: IndustryNode['type'][] = ['chain', 'sector', 'product', 'company', 'external'];

// ── Node card data ──────────────────────────────────────────────────

interface NodeCardData extends Record<string, unknown> {
  node: IndustryNode;
  code?: string;
  isSelected: boolean;
  isDimmed: boolean;
  chainPath: string[];
  relationCounts: Record<RelationType, number>;
}

interface NodeCardProps {
  data: NodeCardData;
}

function NodeCard({ data }: NodeCardProps) {
  const { t } = useTranslation();
  const style = NODE_TYPE_STYLES[data.node.type] ?? NODE_TYPE_STYLES.unknown;
  const Icon = ICONS[style.icon];
  const typeLabelKey = `industryChain.type${
    data.node.type.charAt(0).toUpperCase() + data.node.type.slice(1)
  }`;

  // Non-zero relation counts in display order
  const counts = RELATION_ORDER
    .map((rt) => ({ rt, n: data.relationCounts[rt] }))
    .filter((c) => c.n > 0);

  return (
    <>
      <NodeToolbar
        position={Position.Top}
        offset={8}
        className="!bg-card !border !rounded-md !shadow-lg !p-3 !max-w-xs"
      >
        <div className="text-xs space-y-1">
          <div className="font-semibold text-sm text-foreground">{data.node.name}</div>
          <div className="text-muted-foreground">{t(typeLabelKey)}</div>
          {data.code && (
            <div className="font-mono text-muted-foreground">{data.code}</div>
          )}
          {data.chainPath.length > 1 && (
            <div className="text-muted-foreground">
              <span className="font-medium">{t('industryChain.tooltipChainPath')}:</span>{' '}
              {data.chainPath.join(' › ')}
            </div>
          )}
          {data.node.description && (
            <div className="text-muted-foreground line-clamp-2 pt-1">
              {data.node.description}
            </div>
          )}
          <div className="pt-1 border-t border-border">
            {counts.length === 0 ? (
              <span className="text-muted-foreground">{t('industryChain.tooltipNoRelations')}</span>
            ) : (
              <>
                <span className="font-medium">{t('industryChain.tooltipRelations')}:</span>
                <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
                  {counts.map(({ rt, n }) => (
                    <span key={rt} style={{ color: RELATION_EDGE_STYLES[rt].color }}>
                      {t(`industryChain.${RELATION_EDGE_STYLES[rt].i18nKey}`)} ×{n}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </NodeToolbar>

      <div
        className={clsx(
          'px-3 py-2 rounded-md border-2 bg-card transition-opacity',
          style.border,
          data.isSelected && `ring-2 ${style.ring}`,
          data.isDimmed && 'opacity-40',
        )}
        style={{ width: NODE_WIDTH, minHeight: NODE_HEIGHT - 12 }}
      >
        <Handle type="target" position={Position.Top} className="!opacity-0 !w-1 !h-1" />
        <div className="flex items-center gap-1.5">
          <Icon className={clsx('h-3.5 w-3.5 shrink-0', style.text)} />
          <span className="text-sm font-medium truncate">{data.node.name}</span>
        </div>
        {data.code && (
          <div className={clsx('text-[10px] font-mono mt-0.5', style.text)}>{data.code}</div>
        )}
        <Handle type="source" position={Position.Bottom} className="!opacity-0 !w-1 !h-1" />
      </div>
    </>
  );
}

const nodeTypes = { card: NodeCard };

// ── Graph component ─────────────────────────────────────────────────

interface IndustryChainGraphProps {
  nodes: IndustryNode[];
  relations: IndustryRelationEdge[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function GraphInner({ nodes, relations, selectedId, onSelect }: IndustryChainGraphProps) {
  const { t } = useTranslation();
  const { fitView } = useReactFlow();
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<Node<NodeCardData>>([]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<Edge<GraphEdgeData>>([]);

  const [showTreeEdges, setShowTreeEdges] = useState(true);
  const [enabledTypes, setEnabledTypes] = useState<Set<IndustryNode['type']>>(new Set(ALL_TYPES));
  const [search, setSearch] = useState('');

  // Precompute per-node structure (cheap, identity-stable on nodes/relations).
  const enriched = useMemo(() => {
    const codeMap = new Map<string, string>();
    const pathMap = new Map<string, string[]>();
    const countMap = new Map<string, Record<RelationType, number>>();
    for (const n of nodes) {
      codeMap.set(n.id, getNodeCode(n) ?? '');
      pathMap.set(n.id, getChainPath(nodes, n.id));
      countMap.set(n.id, getRelationCounts(relations, n.id));
    }
    return { codeMap, pathMap, countMap };
  }, [nodes, relations]);

  // Effect 1: rebuild layout when nodes/relations/t change.
  useEffect(() => {
    const baseNodes: Node<NodeCardData>[] = nodes.map((n) => ({
      id: n.id,
      type: 'card',
      position: { x: 0, y: 0 },
      data: {
        node: n,
        code: enriched.codeMap.get(n.id) || undefined,
        isSelected: false,
        isDimmed: false,
        chainPath: enriched.pathMap.get(n.id) ?? [],
        relationCounts: enriched.countMap.get(n.id) ?? {
          supplier: 0, customer: 0, substitute: 0, related: 0, certified_by: 0, segment_of: 0,
        },
      },
    }));
    const treeEdges = buildTreeEdges(nodes);
    const relEdges = buildRelationEdges(relations, t);
    const allEdges = [...treeEdges, ...relEdges];
    const laidOut = layoutWithDagre(baseNodes, allEdges);
    setRfNodes(laidOut);
    setRfEdges(allEdges);
    const raf = requestAnimationFrame(() => fitView({ padding: 0.2, duration: 200 }));
    return () => cancelAnimationFrame(raf);
  }, [nodes, relations, enriched, t, setRfNodes, setRfEdges, fitView]);

  // Effect 2: selection + dimming WITHOUT re-layout (preserves drag).
  // Neighbors are derived from props (parent_id + relations), NOT from rfEdges
  // — reading rfEdges here would create a set-state → effect → set-state loop.
  useEffect(() => {
    if (!selectedId) {
      setRfNodes((prev) => prev.map((n) => ({
        ...n,
        data: { ...n.data, isSelected: false, isDimmed: false },
      })));
      setRfEdges((prev) => prev.map((e) => ({
        ...e,
        animated: false,
        data: { ...e.data, dimmed: false },
      })));
      return;
    }
    const neighbors = new Set<string>([selectedId]);
    // Tree neighbors: parent + direct children
    for (const n of nodes) {
      if (n.id === selectedId && n.parent_id) neighbors.add(n.parent_id);
      if (n.parent_id === selectedId) neighbors.add(n.id);
    }
    // Relation neighbors
    for (const r of relations) {
      if (r.source_id === selectedId) neighbors.add(r.target_id);
      if (r.target_id === selectedId) neighbors.add(r.source_id);
    }
    setRfNodes((prev) => prev.map((n) => ({
      ...n,
      data: {
        ...n.data,
        isSelected: n.id === selectedId,
        isDimmed: !neighbors.has(n.id),
      },
    })));
    setRfEdges((prev) => prev.map((e) => ({
      ...e,
      animated: e.source === selectedId || e.target === selectedId,
      data: { ...e.data, dimmed: e.source !== selectedId && e.target !== selectedId },
    })));
  }, [selectedId, nodes, relations, setRfNodes, setRfEdges]);

  // Filtered view: hide nodes whose type is disabled or don't match search;
  // hide edges touching hidden nodes.
  const visibleRfNodes = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rfNodes.filter((n) => {
      if (!enabledTypes.has(n.data.node.type)) return false;
      if (!q) return true;
      const name = n.data.node.name.toLowerCase();
      const code = (n.data.code ?? '').toLowerCase();
      return name.includes(q) || code.includes(q);
    });
  }, [rfNodes, enabledTypes, search]);

  const visibleNodeIds = useMemo(
    () => new Set(visibleRfNodes.map((n) => n.id)),
    [visibleRfNodes],
  );

  const visibleRfEdges = useMemo(() => {
    return rfEdges.filter((e) => {
      if (e.data?.kind === 'tree' && !showTreeEdges) return false;
      return visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target);
    });
  }, [rfEdges, showTreeEdges, visibleNodeIds]);

  const handleRelayout = useCallback(() => {
    const laidOut = layoutWithDagre(rfNodes, rfEdges);
    setRfNodes(laidOut);
    requestAnimationFrame(() => fitView({ padding: 0.2, duration: 200 }));
  }, [rfNodes, rfEdges, setRfNodes, fitView]);

  const onNodeClick = useCallback<NodeMouseHandler>((_, node) => {
    onSelect(node.id);
  }, [onSelect]);

  const toggleType = (tp: IndustryNode['type']) => {
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(tp)) next.delete(tp);
      else next.add(tp);
      return next;
    });
  };

  return (
    <div className="relative w-full h-full">
      {/* Floating toolbar */}
      <div className="absolute top-2 left-2 z-10 flex flex-wrap items-center gap-2 bg-card border rounded-md shadow-sm px-2.5 py-1.5 text-xs">
        <button
          onClick={() => fitView({ padding: 0.2, duration: 200 })}
          className="flex items-center gap-1 px-2 py-1 rounded hover:bg-muted"
          title={t('industryChain.fitView')}
        >
          <Maximize className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={handleRelayout}
          className="flex items-center gap-1 px-2 py-1 rounded hover:bg-muted"
          title={t('industryChain.relayout')}
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
        <label className="flex items-center gap-1 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showTreeEdges}
            onChange={(e) => setShowTreeEdges(e.target.checked)}
            className="h-3 w-3"
          />
          {t('industryChain.showTreeEdges')}
        </label>
        <span className="text-muted-foreground">·</span>
        <div className="flex items-center gap-1.5">
          {ALL_TYPES.map((tp) => {
            const s = NODE_TYPE_STYLES[tp];
            const on = enabledTypes.has(tp);
            return (
              <button
                key={tp}
                onClick={() => toggleType(tp)}
                className={clsx(
                  'flex items-center gap-1 px-1.5 py-0.5 rounded border',
                  on ? 'border-transparent' : 'border-border opacity-40',
                )}
                style={{ color: s.hex }}
                title={t(`industryChain.type${tp.charAt(0).toUpperCase() + tp.slice(1)}`)}
              >
                <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: s.hex }} />
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-1 ml-1">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('industryChain.searchPlaceholder')}
            className="w-32 px-1.5 py-0.5 bg-transparent border-b border-border focus:outline-none focus:border-primary"
          />
        </div>
        <span className="text-muted-foreground ml-1">
          {t('industryChain.nodesCount', { count: visibleRfNodes.length })} ·{' '}
          {t('industryChain.edgesCount', {
            count: visibleRfEdges.filter((e) => e.data?.kind === 'relation').length,
          })}
        </span>
      </div>

      <ReactFlow
        nodes={visibleRfNodes}
        edges={visibleRfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const d = n.data as NodeCardData | undefined;
            return d?.node ? NODE_TYPE_STYLES[d.node.type]?.hex ?? '#9ca3af' : '#9ca3af';
          }}
          nodeStrokeWidth={2}
          pannable
          zoomable
        />
      </ReactFlow>
    </div>
  );
}

export function IndustryChainGraph(props: IndustryChainGraphProps) {
  return (
    <ReactFlowProvider>
      <GraphInner {...props} />
    </ReactFlowProvider>
  );
}
