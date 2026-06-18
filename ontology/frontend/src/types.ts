export interface Entity {
  type?: string;
  value?: string;
  resolved?: string;
  source?: string;
  resolved_range?: { start?: string; end?: string };
  [key: string]: unknown;
}

export interface ChatRequest {
  question: string;
  session_id?: string;
}

export interface ChatResponse {
  question: string;
  answer: string;
  sql?: string | null;
  results?: Record<string, unknown>[] | null;
  tables_used?: string[];
  intent?: string | null;
  entities?: Entity[] | null;
  execution_time_ms: number;
  session_id?: string | null;
}

export type WsMessageType =
  | "progress"
  | "final"
  | "clarification"
  | "error";

export interface WsMessage {
  type: WsMessageType;
  message: string;
  session_id?: string;
  generated_sql?: string;
  query_result?: Record<string, unknown>[];
  intent?: string;
  entities?: Entity[];
  execution_time_ms?: number;
}

export interface AssistantMetadata {
  sql?: string | null;
  results?: Record<string, unknown>[] | null;
  tablesUsed?: string[];
  intent?: string | null;
  entities?: Entity[] | null;
  executionTimeMs?: number;
  isClarification?: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  metadata?: AssistantMetadata;
}

export const PIPELINE_STEPS = [
  "input_processor",
  "intent_classifier",
  "entity_extractor",
  "clarity_checker",
  "graphrag_retriever",
  "ontology_lookup",
  "sql_generator",
  "sql_validator",
  "sql_executor",
  "response_generator",
] as const;

export const STEP_LABELS: Record<string, string> = {
  input_processor: "Understanding question",
  intent_classifier: "Classifying intent",
  entity_extractor: "Extracting entities",
  clarity_checker: "Checking clarity",
  graphrag_retriever: "Retrieving graph context",
  ontology_lookup: "Looking up schema",
  sql_generator: "Generating SQL",
  sql_validator: "Validating SQL",
  sql_executor: "Executing query",
  response_generator: "Formatting answer",
};

export const EXAMPLE_QUESTIONS = [
  "How many active policies are there?",
  "Show the top 5 agencies by premium volume",
  "List policies in California with their status",
  "What is the total premium for commercial auto this year?",
];
