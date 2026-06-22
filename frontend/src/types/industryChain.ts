// Industry Chain Knowledge Graph types

/** Represents a single node in the industry chain tree */
export interface IndustryNode {
  /** Unique identifier for this node */
  id: string;
  /** Display name */
  name: string;
  /** Node type */
  type: 'chain' | 'sector' | 'product' | 'company' | 'unknown';
  /** Parent node ID (null for root) */
  parent_id: string | null;
  /** Description of this node */
  description?: string;
  /** Stock/ticker code (company nodes) */
  code?: string;
  /** Child node IDs */
  children?: string[];
  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/** Represents a relationship between two nodes */
export interface IndustryRelation {
  id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
  /** Description of the relationship */
  description?: string;
}

/** Request body for adding a node */
export interface IndustryNodeCreate {
  name: string;
  type: IndustryNode['type'];
  parent_id: string | null;
  description?: string;
  metadata?: Record<string, unknown>;
}

/** Request body for editing a node */
export interface IndustryNodeUpdate {
  name?: string;
  type?: IndustryNode['type'];
  parent_id?: string | null;
  description?: string;
  fields?: IndustryNodeFields;
  metadata?: Record<string, unknown>;
}

/** Rich fields stored on a node version (mirrors backend NodeVersion) */
export interface IndustryNodeFields {
  summary?: string;
  narrative?: string;
  market_size?: string;
  growth_rate?: string;
  chain_position?: string;
  localization?: string;
  gross_margin?: string;
  tech_trend?: string;
  /** Parsed JSON array of macro driver strings */
  macro_drivers?: string[];
  /** Parsed JSON object of financial highlights */
  financials?: Record<string, unknown>;
  /** Parsed JSON object of operating metrics */
  operating_metrics?: Record<string, unknown>;
  /** Parsed JSON object of customer structure */
  customer_structure?: Record<string, unknown>;
  validation_status?: string;
}

/** A source citation attached to a node version */
export interface IndustryNodeSource {
  source_type: string;
  title?: string;
  publisher?: string;
  url?: string;
  published_date?: string;
  cited_text?: string;
}

/** Full node detail: node + rich fields + sources + version info */
export interface IndustryNodeDetailResponse {
  node: IndustryNode;
  fields: IndustryNodeFields;
  sources: IndustryNodeSource[];
  version_id?: string;
  snapshot_at?: string;
}

/** Request body for adding a relation */
export interface IndustryRelationCreate {
  source_id: string;
  target_id: string;
  relation_type: string;
  description?: string;
}

/** Represents the full chain tree response */
export interface IndustryChainTree {
  nodes: IndustryNode[];
  relations: IndustryRelation[];
}

/** Represents a pending review item */
export interface PendingReview {
  id: string;
  node_id: string;
  field: string;
  original_value: string | null;
  suggested_value: string;
  status: 'pending' | 'approved' | 'rejected';
  created_at: string;
  updated_at?: string;
}

/** Summary statistics for the industry chain */
export interface IndustryChainStats {
  total_nodes: number;
  total_relations: number;
  pending_reviews: number;
  chain_count: number;
  sector_count: number;
  product_count: number;
  company_count: number;
}

/** Response wrapper for the tree endpoint */
export interface IndustryChainTreeResponse {
  tree: IndustryChainTree;
  stats?: IndustryChainStats;
}

/** Response wrapper for pending reviews */
export interface PendingReviewsResponse {
  reviews: PendingReview[];
  total: number;
}

/** Response for a single node operation */
export interface IndustryNodeResponse {
  node: IndustryNode;
}

/** Response for a single relation operation */
export interface IndustryRelationResponse {
  relation: IndustryRelation;
}
