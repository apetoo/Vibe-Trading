/**
 * Helpers for the industry-chain React Flow graph: node/relation visual maps,
 * dagre layout, and pure-structure derivations (chain path, relation counts,
 * edge builders).
 *
 * Design principle: the graph carries STRUCTURE only (slow-changing topology).
 * Dynamic fields (market_size, financials, growth_rate, ...) NEVER appear here.
 */

import type { Edge, Node } from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import type {
  IndustryNode,
  IndustryRelationEdge,
  RelationType,
} from '@/types/industryChain';

// ── Node type → visual style ────────────────────────────────────────

export type NodeIconName = 'Network' | 'Layers' | 'Package' | 'Building2' | 'Globe';

export interface NodeStyle {
  border: string; // Tailwind border color, e.g. 'border-blue-400'
  text: string; // Tailwind text color
  bg: string; // Tailwind bg tint
  ring: string; // Tailwind ring color (selected)
  hex: string; // raw color for MiniMap / edge fallback
  icon: NodeIconName;
}

export const NODE_TYPE_STYLES: Record<IndustryNode['type'], NodeStyle> = {
  chain: { border: 'border-blue-400', text: 'text-blue-600', bg: 'bg-blue-50', ring: 'ring-blue-400', hex: '#60a5fa', icon: 'Network' },
  sector: { border: 'border-emerald-400', text: 'text-emerald-600', bg: 'bg-emerald-50', ring: 'ring-emerald-400', hex: '#34d399', icon: 'Layers' },
  product: { border: 'border-purple-400', text: 'text-purple-600', bg: 'bg-purple-50', ring: 'ring-purple-400', hex: '#c084fc', icon: 'Package' },
  company: { border: 'border-amber-400', text: 'text-amber-600', bg: 'bg-amber-50', ring: 'ring-amber-400', hex: '#fbbf24', icon: 'Building2' },
  external: { border: 'border-orange-400', text: 'text-orange-600', bg: 'bg-orange-50', ring: 'ring-orange-400', hex: '#fb923c', icon: 'Globe' },
  unknown: { border: 'border-gray-400', text: 'text-gray-600', bg: 'bg-gray-50', ring: 'ring-gray-400', hex: '#9ca3af', icon: 'Globe' },
};

// ── Relation type → edge style ──────────────────────────────────────

export interface RelationEdgeStyle {
  color: string;
  dashed: boolean;
  arrow: boolean;
  /** i18n key under the industryChain namespace, e.g. 'relUpstream'. */
  i18nKey: string;
}

export const RELATION_EDGE_STYLES: Record<RelationType, RelationEdgeStyle> = {
  supplier: { color: '#3b82f6', dashed: false, arrow: true, i18nKey: 'relUpstream' },
  customer: { color: '#10b981', dashed: false, arrow: true, i18nKey: 'relDownstream' },
  substitute: { color: '#f59e0b', dashed: true, arrow: true, i18nKey: 'relSubstitute' },
  related: { color: '#6b7280', dashed: true, arrow: false, i18nKey: 'relRelated' },
  certified_by: { color: '#8b5cf6', dashed: false, arrow: true, i18nKey: 'relCertifiedBy' },
  segment_of: { color: '#14b8a6', dashed: false, arrow: true, i18nKey: 'relBusinessLines' },
};

export const TREE_EDGE_COLOR = '#d1d5db'; // faint gray for parent_id structural edges

/** Display order for relation-type grouping (matches DetailView). */
export const RELATION_ORDER: RelationType[] = [
  'supplier', 'customer', 'substitute', 'related', 'certified_by', 'segment_of',
];

// ── Layout ──────────────────────────────────────────────────────────

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 64;

/**
 * Compute dagre hierarchical (TB) positions. Only edges tagged
 * `data.kind === 'tree'` participate in ranking — relation edges overlay on
 * top without distorting the layered backbone.
 */
export function layoutWithDagre<TData extends Record<string, unknown>>(
  nodes: Node<TData>[],
  edges: Edge[],
): Node<TData>[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: 60, ranksep: 80, marginx: 40, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of edges) {
    if (e.data?.kind === 'tree') {
      g.setEdge(e.source, e.target);
    }
  }
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    return { ...n, position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 } };
  });
}

// ── Pure-structure derivations ──────────────────────────────────────

/** Root → current node name path (topology only). */
export function getChainPath(nodes: IndustryNode[], nodeId: string): string[] {
  const map = new Map(nodes.map((n) => [n.id, n]));
  const path: string[] = [];
  let cur = map.get(nodeId);
  let guard = 0;
  while (cur && guard++ < 50) {
    path.unshift(cur.name);
    cur = cur.parent_id ? map.get(cur.parent_id) : undefined;
  }
  return path;
}

/** Count edges incident to a node, per relation type (topology only). */
export function getRelationCounts(
  relations: IndustryRelationEdge[],
  nodeId: string,
): Record<RelationType, number> {
  const counts: Record<RelationType, number> = {
    supplier: 0, customer: 0, substitute: 0, related: 0, certified_by: 0, segment_of: 0,
  };
  for (const r of relations) {
    if (r.source_id === nodeId || r.target_id === nodeId) {
      counts[r.relation_type]++;
    }
  }
  return counts;
}

// ── Edge builders ───────────────────────────────────────────────────

/** The node's stock code, if any. /tree nests it in metadata.code. */
export function getNodeCode(node: IndustryNode): string | undefined {
  const meta = node.metadata as { code?: unknown } | undefined;
  const code = meta?.code;
  return typeof code === 'string' && code ? code : undefined;
}

export interface GraphEdgeData {
  kind?: 'tree' | 'relation';
  relationType?: RelationType;
  dimmed?: boolean;
  [key: string]: unknown;
}

/** Build faint structural parent_id edges. */
export function buildTreeEdges(nodes: IndustryNode[]): Edge<GraphEdgeData>[] {
  return nodes
    .filter((n) => n.parent_id)
    .map((n) => ({
      id: `tree-${n.parent_id}-${n.id}`,
      source: n.parent_id as string,
      target: n.id,
      type: 'smoothstep',
      style: { stroke: TREE_EDGE_COLOR, strokeWidth: 1 },
      interactionDisabled: true,
      data: { kind: 'tree' as const },
    }));
}

/** Build colored labeled relation edges. */
export function buildRelationEdges(
  relations: IndustryRelationEdge[],
  t: (key: string) => string,
): Edge<GraphEdgeData>[] {
  return relations.map((r) => {
    const style = RELATION_EDGE_STYLES[r.relation_type];
    return {
      id: `rel-${r.relation_id}`,
      source: r.source_id,
      target: r.target_id,
      type: 'smoothstep',
      label: t(`industryChain.${style.i18nKey}`),
      labelStyle: { fill: style.color, fontSize: 10, fontWeight: 600 },
      labelBgStyle: { fill: 'white', fillOpacity: 0.85 },
      labelBgPadding: [4, 2] as [number, number],
      style: {
        stroke: style.color,
        strokeWidth: 1.5,
        strokeDasharray: style.dashed ? '5 3' : undefined,
      },
      markerEnd: style.arrow
        ? { type: 'arrowclosed' as const, color: style.color, width: 16, height: 16 }
        : undefined,
      data: { kind: 'relation' as const, relationType: r.relation_type },
    };
  });
}
