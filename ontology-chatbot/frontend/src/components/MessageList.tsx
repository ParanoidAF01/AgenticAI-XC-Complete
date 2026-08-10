import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ChartRenderer from './ChartRenderer';
import type { ChartConfig } from '@/types/chat';
import type { Message } from '@/types/chat';
import type { User } from '@/types/auth';
import './MessageList.css';

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  isSending: boolean;
  error: string | null;
  onMessageSelect?: (message: Message) => void;
  selectedMessageId?: string;
  user?: User | null;
}

export default function MessageList({
  messages,
  isLoading,
  isSending,
  error,
  onMessageSelect,
  selectedMessageId,
  user,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [expandedSql, setExpandedSql] = useState<Set<string>>(new Set());

  const toggleSql = (e: React.MouseEvent, msgId: string) => {
    e.stopPropagation();
    setExpandedSql(prev => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };

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
              <div className="avatar avatar--user">{user?.display_name?.charAt(0).toUpperCase() || user?.email?.charAt(0).toUpperCase() || 'U'}</div>
            ) : (
              <div className="avatar avatar--assistant">
                {/* <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
                  <circle cx="9" cy="9" r="8" fill="var(--accent)" opacity="0.2" />
                  <circle cx="9" cy="9" r="4" fill="var(--accent)" />
                </svg> */}
                <img src = "/company-logo.png"
                alt="Company Logo"
                width = "18"
                height = "18"
                style = {{width: '18px', height: '18px', objectFit: 'contain'}}
                />
              </div>
            )}
          </div>
          <div className="message-body">
            <div className="message-content">
              {msg.role === 'assistant' ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {msg.content}
                </ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
            {msg.role === 'assistant' && msg.metadata_?.chart_config && (msg.metadata_.chart_config as ChartConfig).show && msg.metadata_?.results ? (
              <ChartRenderer
                config={msg.metadata_.chart_config as ChartConfig}
                results={msg.metadata_.results as Record<string, unknown>}
              />
            ) : null}
            {msg.role === 'assistant' && !!msg.metadata_?.sql && (
              <div className="message-sql-container">
                <button 
                  className="view-sql-btn" 
                  onClick={(e) => toggleSql(e, msg.id)}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '6px' }}>
                    <polyline points="16 18 22 12 16 6"></polyline>
                    <polyline points="8 6 2 12 8 18"></polyline>
                  </svg>
                  {expandedSql.has(msg.id) ? 'Hide SQL' : 'View SQL'}
                </button>
                {expandedSql.has(msg.id) && (
                  <div className="sql-code-block" onClick={(e) => e.stopPropagation()}>
                    <pre>
                      <code>
                        {Array.isArray(msg.metadata_.sql) ? (msg.metadata_.sql as string[]).join('\n\n') : String(msg.metadata_.sql)}
                      </code>
                    </pre>
                  </div>
                )}
              </div>
            )}
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
              <div className="typing-dots">
                <span /><span /><span />
              </div>
              <span className="typing-text">Analyzing your data...</span>
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
