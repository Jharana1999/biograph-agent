export type Citation = {
  source: string;
  id: string;
  title?: string | null;
  url?: string | null;
};

export type EvidenceItem = {
  evidence_id: string;
  target_id: string;
  disease_id: string;
  score?: number | null;
  datasource?: string | null;
  description?: string | null;
  citations: Citation[];
};

export type RankedTarget = {
  target_id: string;
  target_symbol?: string | null;
  target_name?: string | null;
  score: number;
  rationale: string[];
  top_evidence: EvidenceItem[];
};

export type GraphNode = {
  id: string;
  label: string;
  name?: string | null;
  score?: number | null;
};

export type GraphEdge = {
  source: string;
  target: string;
  type: string;
};

export type GraphSummary = {
  nodes_added: number;
  edges_added: number;
  focus_disease_id?: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type EvalCheck = {
  label?: string;
  description?: string;
  value: unknown;
  pass: boolean;
};

export type EvaluationSummary = {
  passed: boolean;
  checks: Record<string, EvalCheck>;
  notes?: string | null;
};

export type ChatResponse = {
  run_id: string;
  session_id: number;
  plan: { steps: string[] };
  answer_markdown: string;
  ranked_targets: RankedTarget[];
  citations: Citation[];
  evidence: EvidenceItem[];
  graph: GraphSummary;
  evaluation: EvaluationSummary;
};

export type EntityProfile = {
  id: string;
  labels: string[];
  properties: Record<string, any>;
  related?: { relationship: string; node: EntityProfile }[];
};
