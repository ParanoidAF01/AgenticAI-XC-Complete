export interface Session {
  id: string;
  title: string | null;
  profile: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  metadata_?: Record<string, unknown>;
  created_at: string;
}

export interface ChatResponse {
  message: Message;
  route?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  sql?: string[] | string;
  validation_trace?: unknown[];
  results?: Record<string, unknown>;
  is_clarification: boolean;
}

export interface CreateSessionRequest {
  profile?: string;
  title?: string;
}

export interface MessageRequest {
  content: string;
  session_id: string;
}

export interface UpdateSessionRequest {
  title?: string;
  is_archived?: boolean;
  profile?: string | null;
}
