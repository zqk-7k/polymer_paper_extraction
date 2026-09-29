import type { ReactNode } from "react";
import sampleCandidate from "../data/reference_no_0101911_candidate.json";

export const API_BASE =
  (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_EXTRACTION_API_BASE_URL ||
  (typeof process !== "undefined" ? process.env?.NEXT_PUBLIC_EXTRACTION_API_BASE_URL : "") ||
  (import.meta.env.DEV ? "http://localhost:8000" : "");
export type ViewKey = "upload" | "history" | "batch" | "polyinfo" | "results" | "polymer" | "sample";
export type CandidateData = typeof sampleCandidate;
export type PolymerEntity = CandidateData["polymer_entities"][number];
export type PropertyObservation = CandidateData["property_observations"][number];
export type Evidence = CandidateData["evidence"][number];
export type GraphNodePayload = {
  id: string;
  type: "paper" | "polymer" | "sample" | "process" | "property" | "characterization";
  label: string;
  data: Record<string, unknown>;
};
export type GraphPayload = {
  nodes: GraphNodePayload[];
  edges: Array<{ id: string; source: string; target: string; type: string; label: string }>;
  stats: { node_counts: Record<string, number>; edge_count: number };
};
export type JobStage = {
  id: string;
  status: "pending" | "running" | "complete" | "failed";
  artifact: string | null;
};
export type ExtractionJob = {
  task_id: string;
  ref_no: string;
  source_reference_no?: string | null;
  file_name: string;
  file_size: number;
  status: "queued" | "running" | "complete" | "failed" | "cancelled";
  created_at: string;
  updated_at: string;
  current_stage: string | null;
  progress: number;
  result_ready: boolean;
  result_url: string | null;
  pdf_url: string;
  stages: JobStage[];
  error?: string | null;
  paper?: CandidateData["paper"];
  stats?: ResultStats;
  validation_status?: string | null;
  source_kind?: "web";
};
export type ResultStats = {
  polymer_count: number;
  sample_count: number;
  property_count: number;
  process_count: number;
  characterization_count: number;
  evidence_count: number;
};
export type BatchResultSummary = {
  source_kind: "batch";
  collection_id: string;
  result_date?: string | null;
  result_mode?: string | null;
  ref_no: string;
  source_batch?: string | null;
  collection_kind?: "production" | "review";
  production_eligible?: boolean;
  publication_status?: string | null;
  result_url: string;
  graph_url: string;
  pdf_url?: string | null;
  paper: CandidateData["paper"];
  stats: ResultStats;
  validation_status?: string | null;
};
export type BatchCollectionSummary = {
  collection_id: string;
  collection_kind: "production" | "review";
  production_eligible: boolean;
  result_date: string;
  generated_at: string;
  result_mode: string;
  is_active: boolean;
  document_count: number;
  paired_documents: number;
  publication_status: { complete: number; partial: number; other: number };
  strict_compliance_claimed: boolean;
  validation_status: string;
  totals: {
    polymer_entities: number;
    samples: number;
    process_steps: number;
    property_observations: number;
    evidence: number;
  };
  quality: {
    sample_binding_coverage: number;
    evidence_coverage: number;
    unit_completeness: number;
    condition_coverage: number;
    final_document_rate: number;
  };
  anchor: {
    matched: number;
    value_diff: number;
    polyinfo_only: number;
    extraction_only: number;
    precision: number;
    recall: number;
    f1: number;
  };
  stage: {
    stage4_pre_properties: number;
    stage4_post_properties: number;
    candidate_properties: number;
    final_properties: number;
    stage4r_recovered: number;
    stage4r_migrated: number;
    stage4r_skipped: number;
    stage6_warnings: number;
    stage6_errors: number;
    rejected_objects: number;
    final_documents: number;
  };
};
export type PolyInfoStats = ResultStats & {
  property_type_count: number;
  measurement_condition_count: number;
  structure_count: number;
};
export type PolyInfoSummary = {
  source_kind: "polyinfo";
  collection_id: string;
  group: string;
  ref_no: string;
  reference: { author?: string; journal?: string; year?: string; doi?: string; volume?: string; issue?: string; page?: string };
  polymer_names: string[];
  polymer_name_count: number;
  stats: PolyInfoStats;
  has_pdf: boolean;
  has_batch_result?: boolean;
  detail_url: string;
  comparison_url: string;
};
export type PolyInfoProperty = {
  id: string;
  sample_id: string;
  polymer_id: string;
  category: string;
  name: string;
  value: string;
  value_min?: number | null;
  value_max?: number | null;
  unit?: string | null;
  method?: string | null;
  condition?: string | null;
  remark?: string | null;
  source: string;
};
export type PolyInfoComparison = {
  ref_no: string;
  message: string;
  polyinfo: {
    group: string;
    ref_no: string;
    reference: PolyInfoSummary["reference"];
    stats: PolyInfoStats;
    pdf_url?: string | null;
    polymers: Array<{ polymer_id: string; polymer_names: string[]; polymer_type?: string; cu_formula?: string; structure_image?: string | null; sample_ids: string[] }>;
    samples: Array<{ sample_id: string; polymer_id: string; polymer_name: string[]; polymer_type?: string; polymer_class: string[]; material_type: string[]; cu_formula?: string; property_count: number; process_count: number; source_file: string }>;
    properties: PolyInfoProperty[];
    processes: Array<{ sample_id: string; kind: string; value: string }>;
  };
  extraction: null | {
    source_kind: "batch";
    collection_id: string;
    created_at: string;
    file_name: string;
    paper: CandidateData["paper"];
    stats: PolyInfoStats;
    quality: {
      properties: number;
      sample_bound: number;
      evidence_bound: number;
      unit_complete: number;
      condition_bound: number;
      sample_binding_coverage: number;
      evidence_coverage: number;
      unit_completeness: number;
      condition_coverage: number;
    };
    polymer_entities: CandidateData["polymer_entities"];
    samples: CandidateData["samples"];
  };
  metrics: Array<{ key: string; label: string; polyinfo: number; extraction: number; interpretation: string }>;
  property_alignment: Array<{ status: "matched" | "value_diff" | "polyinfo_only" | "extraction_only"; canonical_name: string; polyinfo: PolyInfoProperty | null; extraction: PropertyObservation | null }>;
  alignment_stats?: {
    matched: number;
    value_diff: number;
    polyinfo_only: number;
    extraction_only: number;
    precision: number;
    recall: number;
    f1: number;
  };
};
export type HealthState = {
  status: string;
  python_ready: boolean;
  mineru_key_ready: boolean;
  llm_key_ready: boolean;
  key_submission_allowed?: boolean;
  requires_https_for_keys?: boolean;
};
export type RepeatUnitDefinition = {
  formula: string;
  backbone: ReactNode;
  note?: string;
};
