import { useEffect, useRef } from 'react';
import type { Message } from '@/types/chat';
import './MessageList.css';

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  isSending: boolean;
  error: string | null;
  onMessageSelect?: (message: Message) => void;
  selectedMessageId?: string;
}

export default function MessageList({
  messages,
  isLoading,
  isSending,
  error,
  onMessageSelect,
  selectedMessageId,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending]);

  if (isLoading) {
    return (
      <div className="message-list-loading">
        <div className="loading-dots">
          <span /><span /><span />
        </div>
        <p>Loading messages...</p>
      </div>
    );
  }

  if (messages.length === 0 && !isSending) {
    return (
      <div className="message-list-empty">
        <p>No messages yet. Start a conversation!</p>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`message ${msg.role === 'user' ? 'message--user' : 'message--assistant'} ${
            selectedMessageId === msg.id ? 'message--selected' : ''
          }`}
          onClick={() => msg.role === 'assistant' && onMessageSelect?.(msg)}
        >
          <div className="message-avatar">
            {msg.role === 'user' ? (
              <div className="avatar avatar--user">U</div>
            ) : (
              <div className="avatar avatar--assistant">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
                  <circle cx="9" cy="9" r="8" fill="var(--accent)" opacity="0.2" />
                  <circle cx="9" cy="9" r="4" fill="var(--accent)" />
                </svg>
              </div>
            )}
          </div>
          <div className="message-body">
            <div className="message-content">
              {msg.content}
            </div>
            <div className="message-time">
              {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </div>
          </div>
        </div>
      ))}

      {isSending && (
        <div className="message message--assistant message--typing">
          <div className="message-avatar">
            <div className="avatar avatar--assistant">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
                <circle cx="9" cy="9" r="8" fill="var(--accent)" opacity="0.2" />
                <circle cx="9" cy="9" r="4" fill="var(--accent)" />
              </svg>
            </div>
          </div>
          <div className="message-body">
            <div className="typing-indicator">
              <span /><span /><span />
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="message-error">
          <span className="error-icon">⚠️</span>
          <span>{error}</span>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
