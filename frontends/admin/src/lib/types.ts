/** Shapes returned by the admin API (mirrors the backend's api/schemas). */

export type Role = "owner" | "editor" | "viewer" | "support_agent";
export const ROLES: Role[] = ["owner", "editor", "support_agent", "viewer"];

export type Outcome = "answered" | "smalltalk" | "denied" | "handoff" | "blocked" | "login_required" | "agent_reply" | "error";
export const OUTCOMES: Outcome[] = ["answered", "smalltalk", "denied", "handoff", "blocked", "login_required", "agent_reply", "error"];

export type MetadataValue = string | number | boolean | null;
export type Metadata = Record<string, MetadataValue | MetadataValue[]>;

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface MessageResponse {
  message: string;
}

export interface AdminUser {
  id: string;
  email: string;
  role: Role;
  disabled: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Citation {
  document_id: string;
  chunk_id: string;
  title: string;
  source: string;
  url?: string | null;
  score: number;
}

// ---------------------------------------------------------------- knowledge

export interface Source {
  id: number;
  name: string;
  description: string;
  priority: number;
  enabled: boolean;
  document_count: number;
}

export type DocumentStatus = "processing" | "ready" | "failed";

export interface ChunkingSpec {
  strategy: string;
  [param: string]: unknown;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  source: string;
  original_filename: string | null;
  file_type: string;
  status: DocumentStatus;
  error: string | null;
  enabled: boolean;
  chunk_count: number;
  metadata: Metadata;
  chunking: Partial<ChunkingSpec>;
  can_rechunk: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  access_tier: string;
  language: "vi" | "en" | "mixed" | null;
  version: string | null;
  effective_from: string | null;
  effective_to: string | null;
  supersedes_id: string | null;
}

export interface CitingAnswer {
  id: string;
  conversation_id: string;
  content: string;
  created_at: string;
}

export interface Chunk {
  id: string;
  position: number;
  content: string;
  metadata: Metadata;
  edited: boolean;
  updated_at: string;
}

export interface DocumentDetail extends KnowledgeDocument {
  chunks: Chunk[];
}

/** A JSON-schema property as produced by Pydantic for the strategy parameters. */
export interface SchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  minimum?: number;
  maximum?: number;
}

export interface ChunkingStrategyInfo {
  name: string;
  description: string;
  params_schema: { properties?: Record<string, SchemaProperty>; required?: string[] };
}

export interface PreviewChunk {
  position: number;
  content: string;
  metadata: Metadata;
  char_count: number;
}

export interface ChunkingPreview {
  chunk_count: number;
  min_chars: number;
  max_chars: number;
  avg_chars: number;
  warnings: string[];
  chunks: PreviewChunk[];
}

// ---------------------------------------------------------------- conversations

export interface ConversationSummary {
  id: string;
  end_user_id: string;
  channel: string;
  status: string;
  message_count: number;
  /** Kept past its retention period (owners set it). */
  legal_hold: boolean;
  created_at: string;
  last_activity_at: string;
}

export interface AdminMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  outcome: Outcome | null;
  citations: Citation[];
  confidence: number | null;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number | null;
  cached: boolean;
  guard_reason: string | null;
  request_id: string | null;
  created_at: string;
  feedback: { rating: number; comment: string | null } | null;
}

export interface ConversationDetail extends ConversationSummary {
  messages: AdminMessage[];
}

export interface FeedbackItem {
  id: string;
  rating: number;
  comment: string | null;
  created_at: string;
  message_id: string;
  conversation_id: string;
  question: string | null;
  answer: string;
  outcome: Outcome | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
}

/** A golden question copied from a real answer, personal data masked (ADM-12). */
export interface EvalCase {
  id: string;
  question: string;
  expected_answer: string;
  expected_sources: string[];
  document_ids: string[];
  note: string | null;
  created_by: string | null;
  created_at: string;
}

/** What a data-subject deletion removed, and what legal hold kept (PRV-03). */
export interface DataSubjectDeleted {
  conversations: number;
  tickets: number;
  token_usage: number;
  kept_on_hold: number;
}

export type HandoffStatus = "open" | "assigned" | "answered" | "closed";
export const HANDOFF_REASONS = ["no_knowledge", "user_request", "sensitive_topic", "repeated_no_answer", "negative_feedback", "tool_error"] as const;

export interface Handoff {
  id: string;
  conversation_id: string;
  message_id: string | null;
  reason: string;
  status: HandoffStatus;
  note: string | null;
  signed_in: boolean;
  /** Masked (a***@example.com, ***123); owners can reveal them. */
  contact_email: string | null;
  contact_phone: string | null;
  has_contact: boolean;
  consent_at: string | null;
  details: string | null;
  assigned_to: string | null;
  answer: string | null;
  answered_at: string | null;
  emailed_at: string | null;
  due_at: string | null;
  closed_at: string | null;
  legal_hold: boolean;
  created_at: string;
  updated_at: string;
}

export interface DailyMetrics {
  day: string;
  turns: number;
  conversations: number;
  errors: number;
  handoffs: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p95_first_token_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_micro_usd: number;
  breakdown: Record<string, unknown>;
}

export interface MessageTrace {
  message_id: string;
  route: string | null;
  intent: string | null;
  confidence: number | null;
  rewritten_query: string | null;
  filters: Record<string, unknown>;
  chunks: { chunk_id: string; document_id: string; relevance: number; semantic: number; keyword: number; rerank: number | null; matched: boolean }[];
  tool_calls: { name: string; ok: boolean; duration_ms: number; argument_names: string[] }[];
  prompt_version: string | null;
  steps_ms: Record<string, number>;
  calls: { purpose: string; model: string; prompt_tokens: number; completion_tokens: number; cost_micro_usd: number }[];
  created_at: string;
}

export interface HandoffContact {
  name: string | null;
  email: string | null;
  phone: string | null;
}

// ---------------------------------------------------------------- monitoring

export interface UsageSummary {
  since: string;
  daily: Array<{ day: string; model: string; prompt_tokens: number; completion_tokens: number; cost_micro_usd: number; calls: number }>;
  by_purpose: Array<{ purpose: string; tokens: number; calls: number }>;
  by_tier: Array<{ tier: string; tokens: number; cost_micro_usd: number }>;
  outcomes: Partial<Record<Outcome, number>>;
  feedback: { positive: number; negative: number };
  latency: { p50_ms: number | null; p95_ms: number | null; conversations: number };
  totals: { prompt_tokens: number; completion_tokens: number; calls: number; cost_micro_usd: number };
  month: { tokens: number; cost_micro_usd: number };
}

export interface LiveEvent {
  type: "hello" | "turn" | "handoff" | "error";
  ts?: string;
  conversation_id?: string;
  outcome?: Outcome;
  prompt_tokens?: number;
  completion_tokens?: number;
  latency_ms?: number | null;
  model?: string | null;
  reason?: string;
  message?: string;
}

export interface LogEntry {
  ts: string;
  level: string;
  logger: string;
  message: string;
  request_id: string | null;
  exception?: string | null;
}

export interface SystemStatus {
  version: string;
  uptime_seconds: number;
  database: boolean;
  knowledge_index_version: number;
  indexed_chunks: number;
  indexed_sources: Record<string, number>;
  llm_provider: string;
  llm_model: string;
  embedding_model: string;
  reranker_loaded: boolean;
  cache: Record<string, string | number>;
  fallback_mode: "deny" | "handoff";
  ingestion_queue: { pending: number; in_progress: number; oldest_pending_seconds: number | null };
}

// ---------------------------------------------------------------- configuration

export interface Settings {
  fallback_mode: "deny" | "handoff";
  deny_message: string;
  handoff_message: string;
  guard_block_message: string;
  greeting_message: string;
  thanks_message: string;
  assistant_instructions: string;
  widget_title: string;
  widget_welcome_message: string;
  widget_primary_color: string;
  widget_suggested_questions: string[];
  chat_model: string;
  light_model: string;
  similarity_threshold: number;
  semantic_weight: number;
  retrieval_top_k: number;
  max_context_chunks: number;
  limit_anonymous_per_minute: number;
  limit_anonymous_per_hour: number;
  tokens_anonymous_per_day: number;
  limit_user_per_minute: number;
  limit_user_per_hour: number;
  tokens_user_per_day: number;
  tokens_ip_per_day: number;
  spend_cap_monthly_usd: number;
  spend_anonymous_cutoff_ratio: number;
  support_hours: Record<string, string>;
  support_holidays: string[];
  ticket_reply_hours: number;
  handoff_topics: string[];
  retention_chat_days: number;
  retention_anonymous_chat_days: number;
  retention_trace_days: number;
  retention_ticket_days: number;
  retention_audit_days: number;
}

export interface SqlTool {
  name: string;
  description: string;
  required_tier: string;
  sql_template: string;
  allowed_columns: string[];
  masked_columns: string[];
  row_limit: number;
  enabled: boolean;
  updated_by: string | null;
  updated_at: string;
}

export interface ModelPrice {
  model: string;
  input_usd_per_million: string;
  output_usd_per_million: string;
  updated_by: string | null;
  updated_at: string;
}

/** Scopes a server-to-server API key can carry (backend: core/storage/tables/access_tables.py). */
export const API_KEY_SCOPES = ["chat", "documents:write", "conversations:read", "admin:read"] as const;
export type ApiKeyScope = (typeof API_KEY_SCOPES)[number];

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: ApiKeyScope[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  expires_at: string | null;
  rate_limit_per_minute: number;
  rotated_from_id: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface AuditEntry {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_email: string | null;
  actor_role: Role | null;
  method: string;
  path: string;
  status_code: number;
  request_id: string | null;
  client_ip: string | null;
  request_body: unknown;
  response_body: unknown;
}
