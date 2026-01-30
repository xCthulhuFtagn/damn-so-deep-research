// User types
export interface User {
  id: string;
  username: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  username: string;
}

// Run types
export interface Run {
  id: string;
  title: string;
  status: 'active' | 'paused' | 'completed' | 'failed' | 'awaiting_confirmation';
  created_at: string;
  total_tokens: number;
}

export interface RunListResponse {
  runs: Run[];
  total: number;
}

// Plan types
export interface Substep {
  id: number;
  search_queries: string[];
  findings: string[];
  status: 'DONE' | 'FAILED';
  error?: string;
}

export interface PlanStep {
  id: number;
  description: string;
  status: 'TODO' | 'IN_PROGRESS' | 'DONE' | 'FAILED' | 'SKIPPED';
  result?: string;
  error?: string;
  // Per-step recovery
  substeps?: Substep[];
  current_substep_index?: number;
  max_substeps?: number;
  accumulated_findings?: string[];
}

// Message types
export interface Message {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  name?: string;
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

// Research state
export interface ResearchState {
  run_id: string;
  phase: string;
  plan: PlanStep[];
  current_step_index: number;
  messages: Message[];
  is_running: boolean;
}

// Approval types
export interface Approval {
  command_hash: string;
  run_id: string;
  command_text: string;
  approved: number;
}

export interface PendingApprovalsResponse {
  approvals: Approval[];
  count: number;
}

// WebSocket event types
export type WSEventType =
  | 'connected'
  | 'phase_change'
  | 'message'
  | 'tool_call'
  | 'step_start'
  | 'step_complete'
  | 'search_start'
  | 'search_complete'
  | 'search_parallel'
  | 'approval_needed'
  | 'approval_response'
  | 'question'
  | 'plan_confirmation_needed'
  | 'plan_update'
  | 'token_update'
  | 'run_start'
  | 'run_complete'
  | 'run_error'
  | 'run_paused'
  | 'state_sync'
  | 'pong';

export interface WSEvent {
  type: WSEventType;
  [key: string]: unknown;
}

export interface PhaseChangeEvent extends WSEvent {
  type: 'phase_change';
  phase: string;
  step?: number;
}

export interface MessageEvent extends WSEvent {
  type: 'message';
  role: string;
  content: string;
  name?: string;
}

export interface StepEvent extends WSEvent {
  type: 'step_start' | 'step_complete';
  step_index: number;
  description?: string;
  status?: string;
  result?: string;
}

export interface ApprovalEvent extends WSEvent {
  type: 'approval_needed';
  command: string;
  command_hash: string;
}

export interface SearchParallelEvent extends WSEvent {
  type: 'search_parallel';
  themes: string[];
  count: number;
}

export interface PlanUpdateEvent extends WSEvent {
  type: 'plan_update';
  plan: PlanStep[];
}

export interface RunCompleteEvent extends WSEvent {
  type: 'run_complete';
  report?: string;
}

export interface RunErrorEvent extends WSEvent {
  type: 'run_error';
  error: string;
}

export interface PlanConfirmationNeededEvent extends WSEvent {
  type: 'plan_confirmation_needed';
  plan: PlanStep[];
}

export interface TokenUpdateEvent extends WSEvent {
  type: 'token_update';
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface StateSyncEvent extends WSEvent {
  type: 'state_sync';
  run_id: string;
  is_running: boolean;
  phase: string;
  plan: PlanStep[];
  current_step_index: number;
  search_themes: string[];
  messages: Message[];
  pending_terminal?: {
    command: string;
    hash: string;
    timeout?: number;
  };
}
