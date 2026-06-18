import { useEffect, useRef } from "react";
import type { ChatMessage } from "../types";
import { EXAMPLE_QUESTIONS } from "../types";
import { ChatInput } from "./ChatInput";
import { MessageBubble } from "./MessageBubble";
import { ProgressIndicator } from "./ProgressIndicator";

interface ChatPanelProps {
  messages: ChatMessage[];
  isLoading: boolean;
  progressMessage: string | null;
  onSend: (question: string) => void;
  onCancel: () => void;
}

export function ChatPanel({
  messages,
  isLoading,
  progressMessage,
  onSend,
  onCancel,
}: ChatPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading, progressMessage]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto py-4">
        {messages.length === 0 ? (
          <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-4 text-center">
            <div className="chat-welcome-card mb-6 rounded-2xl p-6">
              <h2 className="text-lg font-semibold">
                Ask your insurance data warehouse
              </h2>
              <p className="mt-2 max-w-md text-sm">
                Questions are mapped through your Neo4j ontology graph, converted
                to validated SQL, and answered in plain English.
              </p>
            </div>
            <div className="grid w-full max-w-xl gap-2 sm:grid-cols-2">
              {EXAMPLE_QUESTIONS.map((example) => (
                <button
                  key={example}
                  type="button"
                  disabled={isLoading}
                  onClick={() => onSend(example)}
                  className="chat-example-btn rounded-xl px-3 py-2.5 text-left text-xs disabled:opacity-50"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {isLoading && progressMessage && (
              <div className="px-4 py-2">
                <ProgressIndicator message={progressMessage} />
              </div>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-input-bar shrink-0 p-4">
        <div className="mx-auto max-w-3xl">
          <ChatInput
            onSend={onSend}
            onCancel={onCancel}
            isLoading={isLoading}
          />
        </div>
      </div>
    </div>
  );
}
