export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = { [key: string]: JsonValue };

export type Supervisor = {
  id: string;
  name: string;
  base_instruction: string;
  tools: string[];
  wake_policy: JsonObject;
  model_config?: JsonObject;
  llm_config?: JsonObject;
};

export type SupervisorCreate = {
  name: string;
  base_instruction: string;
  tools: string[];
  wake_policy: JsonObject;
  model_config: JsonObject;
};

export type Run = {
  id: string;
  order_id: string;
  supervisor_id: string;
  workflow_id: string;
  status: "active" | "paused" | "done" | "terminated" | string;
  next_wake_at: string | null;
  created_at: string;
  updated_at: string;
};

export type RunCreate = {
  order_id: string;
  supervisor_id: string;
  order_payload: JsonObject;
  initial_memory?: string | null;
};

export type RunState = {
  run_id: string;
  status: "active" | "paused" | "done" | "terminated" | string;
  next_wake_at: string | null;
  memory_summary: string;
};

export type TimelineEntry = {
  ts: string;
  kind: string;
  payload: JsonObject;
};

export type EventSubmit = {
  type: string;
  payload: JsonObject;
};

export type InstructionSubmit = {
  instruction: string;
};

export type RunCommand = "interrupt" | "resume" | "terminate";
