export interface CaseSummary {
  case_id: string;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface BranchSummary {
  branch_id: string;
  depth: number;
  hypothesis_summary: string;
  entity_count: number;
  evidence_count: number;
}

export interface EvidenceRef {
  source_type: string;
  source_id: string;
}

export interface VerdictPacket {
  decision: "MALICIOUS" | "BENIGN" | "INCONCLUSIVE" | "NEEDS_MORE_INFO";
  confidence: number;
  next_best_action: string;
  evidence_refs: EvidenceRef[];
  reasoning_summary: string;
  branch_summaries: BranchSummary[];
  policy_applicable: string[];
}

export interface CaseDetail {
  case_id: string;
  seed: any;
  status: string;
  version: number;
  tracker_confidence: number | null;
  flanker_confidence: number | null;
  overall_confidence: number | null;
  verdict_decision: string | null;
  review_decision: string | null;
  branches: any[];
  created_at: string;
  updated_at: string;
}

export interface TimelineEvent {
  entry_type: string;
  content: any;
  agent_run_id: string | null;
  timestamp: string;
}
