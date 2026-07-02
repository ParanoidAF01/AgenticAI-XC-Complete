import { useState, useRef, useEffect, KeyboardEvent, ChangeEvent } from 'react';
import './MessageComposer.css';

interface MessageComposerProps {
  onSend: (content: string) => void;
  isLoading: boolean;
  disabled?: boolean;
}

export default function MessageComposer({ onSend, isLoading, disabled }: MessageComposerProps) {
  const [content, setContent] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
    }
  }, [content]);

  const handleSubmit = () => {
    if (!content.trim() || isLoading || disabled) return;
    onSend(content.trim());
    setContent('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setContent(e.target.value);
  };

  return (
    <div className="composer">
      <div className="composer-inner">
        <textarea
          ref={textareaRef}
          className="composer-input"
          value={content}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={disabled ? 'Select a profile to start...' : 'Ask about your insurance data...'}
          disabled={isLoading || disabled}
          rows={1}
        />
        <button
          className="composer-send"
          onClick={handleSubmit}
          disabled={!content.trim() || isLoading || disabled}
          aria-label="Send message"
        >
          {isLoading ? (
            <svg className="spinner" width="20" height="20" viewBox="0 0 20 20">
              <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="32" strokeLinecap="round">
                <animateTransform attributeName="transform" type="rotate" from="0 10 10" to="360 10 10" dur="0.8s" repeatCount="indefinite" />
              </circle>
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path d="M3.5 10L16.5 3.5L10 16.5L8.5 11.5L3.5 10Z" fill="currentColor" />
            </svg>
          )}
        </button>
      </div>
      <p className="composer-hint">Enter to send • Shift+Enter for new line</p>
    </div>
  );
}
