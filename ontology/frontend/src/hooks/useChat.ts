import { useCallback, useEffect, useRef, useState } from "react";
import { askQuestion } from "../api/client";
import { askViaWebSocket } from "../api/websocket";
import type { AssistantMetadata, ChatMessage } from "../types";

function createId(): string {
  return crypto.randomUUID();
}

function wsToMetadata(payload: {
  generated_sql?: string;
  query_result?: Record<string, unknown>[];
  intent?: string;
  entities?: AssistantMetadata["entities"];
  execution_time_ms?: number;
  type?: string;
}): AssistantMetadata {
  return {
    sql: payload.generated_sql ?? null,
    results: payload.query_result ?? null,
    intent: payload.intent ?? null,
    entities: payload.entities ?? null,
    executionTimeMs: payload.execution_time_ms,
    isClarification: payload.type === "clarification",
  };
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string>(() => createId());
  const [isLoading, setIsLoading] = useState(false);
  const [progressMessage, setProgressMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const cancelRequest = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsLoading(false);
    setProgressMessage(null);
  }, []);

  const newSession = useCallback(() => {
    cancelRequest();
    setSessionId(createId());
    setMessages([]);
    setError(null);
    setProgressMessage(null);
  }, [cancelRequest]);

  const sendMessage = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || isLoading) return;

      setError(null);
      setIsLoading(true);
      setProgressMessage("Connecting…");

      const userMessage: ChatMessage = {
        id: createId(),
        role: "user",
        content: trimmed,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const wsResult = await askViaWebSocket({
          question: trimmed,
          sessionId,
          onProgress: setProgressMessage,
          signal: controller.signal,
        });

        if (wsResult.session_id) {
          setSessionId(wsResult.session_id);
        }

        const assistantMessage: ChatMessage = {
          id: createId(),
          role: "assistant",
          content: wsResult.message,
          timestamp: new Date(),
          metadata: wsToMetadata(wsResult),
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } catch (wsError) {
        if (controller.signal.aborted) return;

        setProgressMessage("Retrying via HTTP…");
        try {
          const httpResult = await askQuestion({
            question: trimmed,
            session_id: sessionId,
          });

          if (httpResult.session_id) {
            setSessionId(httpResult.session_id);
          }

          const assistantMessage: ChatMessage = {
            id: createId(),
            role: "assistant",
            content: httpResult.answer,
            timestamp: new Date(),
            metadata: {
              sql: httpResult.sql ?? null,
              results: httpResult.results ?? null,
              tablesUsed: httpResult.tables_used ?? [],
              intent: httpResult.intent ?? null,
              entities: httpResult.entities ?? null,
              executionTimeMs: httpResult.execution_time_ms,
              isClarification: !httpResult.sql && !httpResult.results,
            },
          };
          setMessages((prev) => [...prev, assistantMessage]);
        } catch (httpError) {
          const message =
            httpError instanceof Error
              ? httpError.message
              : wsError instanceof Error
                ? wsError.message
                : "Something went wrong.";
          setError(message);
          setMessages((prev) => [
            ...prev,
            {
              id: createId(),
              role: "system",
              content: message,
              timestamp: new Date(),
            },
          ]);
        }
      } finally {
        abortRef.current = null;
        setIsLoading(false);
        setProgressMessage(null);
      }
    },
    [isLoading, sessionId],
  );

  useEffect(() => () => abortRef.current?.abort(), []);

  return {
    messages,
    sessionId,
    isLoading,
    progressMessage,
    error,
    sendMessage,
    cancelRequest,
    newSession,
  };
}
