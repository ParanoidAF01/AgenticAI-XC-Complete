import { useState } from "react";
import type { ChatMessage } from "../types";
import { MarkdownContent } from "./MarkdownContent";
import { MessageDetails } from "./MessageDetails";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const [showDetails, setShowDetails] = useState(false);
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const hasDetails =
    message.metadata &&
    (message.metadata.sql ||
      message.metadata.results?.length ||
      message.metadata.intent ||
      message.metadata.entities?.length);

  if (isSystem) {
    return (
      <div className="flex justify-center px-4 py-1">
        <p className="msg-system rounded-full px-3 py-1 text-xs">{message.content}</p>
      </div>
    );
  }

  return (
    <div className={`flex px-4 py-2 ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`${
          isUser ? "max-w-[min(100%,36rem)]" : "max-w-[min(100%,52rem)] w-full"
        } rounded-2xl px-4 py-3 sm:px-5 sm:py-4 ${
          isUser ? "msg-user" : "msg-assistant"
        }`}
      >
        {!isUser && (
          <div className="mb-3 flex items-center gap-2">
            <span className="msg-assistant__icon flex h-6 w-6 items-center justify-center rounded-lg">
              <svg
                viewBox="0 0 24 24"
                className="h-3.5 w-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden
              >
                <path d="M12 3v2M12 19v2M5 12H3M21 12h-2M7 7l-1.5-1.5M18.5 18.5L17 17M7 17l-1.5 1.5M18.5 5.5L17 7" />
                <circle cx="12" cy="12" r="4" />
              </svg>
            </span>
            <span className="msg-assistant__label text-xs font-semibold uppercase tracking-wide">
              Assistant
            </span>
            {message.metadata?.intent && (
              <span className="msg-intent-badge rounded-md px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide">
                {message.metadata.intent}
              </span>
            )}
          </div>
        )}

        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
        ) : (
          <MarkdownContent content={message.content} />
        )}

        {!isUser && hasDetails && (
          <div className="msg-details-divider mt-4 border-t pt-3">
            <button
              type="button"
              onClick={() => setShowDetails((v) => !v)}
              className="msg-details-toggle inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium"
            >
              <svg
                viewBox="0 0 20 20"
                className={`h-3.5 w-3.5 transition-transform ${showDetails ? "rotate-180" : ""}`}
                fill="currentColor"
                aria-hidden
              >
                <path
                  fillRule="evenodd"
                  d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                  clipRule="evenodd"
                />
              </svg>
              {showDetails ? "Hide SQL & raw data" : "Show SQL & raw data"}
            </button>
            {showDetails && message.metadata && (
              <MessageDetails metadata={message.metadata} />
            )}
          </div>
        )}

        <p className="msg-meta mt-3 text-[10px]">
          {message.timestamp.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
          {!isUser && message.metadata?.executionTimeMs !== undefined && (
            <span className="ml-2 opacity-80">
              · {message.metadata.executionTimeMs.toFixed(0)} ms
            </span>
          )}
        </p>
      </div>
    </div>
  );
}
