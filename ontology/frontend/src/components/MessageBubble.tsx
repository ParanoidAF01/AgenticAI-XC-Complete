import { useState } from "react";
import type { ChatMessage } from "../types";
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
        <p className="rounded-full bg-rose-500/10 px-3 py-1 text-xs text-rose-300">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div className={`flex px-4 py-2 ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[min(100%,42rem)] rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-gradient-to-br from-teal-600 to-cyan-700 text-white shadow-lg shadow-teal-950/30"
            : "border border-slate-700/60 bg-surface-800/90 text-slate-100 shadow-lg shadow-black/10"
        }`}
      >
        {!isUser && (
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-teal-400/80">
            Assistant
          </p>
        )}
        <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>

        {!isUser && hasDetails && (
          <>
            <button
              type="button"
              onClick={() => setShowDetails((v) => !v)}
              className="mt-2 text-xs text-teal-400 transition hover:text-teal-300"
            >
              {showDetails ? "Hide details" : "Show SQL & results"}
            </button>
            {showDetails && message.metadata && (
              <MessageDetails metadata={message.metadata} />
            )}
          </>
        )}

        <p
          className={`mt-2 text-[10px] ${isUser ? "text-teal-100/60" : "text-slate-500"}`}
        >
          {message.timestamp.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>
    </div>
  );
}
