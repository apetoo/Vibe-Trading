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
  metadata?: Record<string, unknown>;
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
