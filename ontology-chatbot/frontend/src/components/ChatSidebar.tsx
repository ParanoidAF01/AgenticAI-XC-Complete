import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Session } from '@/types/chat';
import type { User } from '@/types/auth';
import './ChatSidebar.css';

interface Props {
  sessions: Session[];
  activeSessionId: string | null;
  isOpen: boolean;
  sessionsLoading: boolean;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  onToggle: () => void;
  user: User | null;
}

export default function ChatSidebar({
  sessions,
  activeSessionId,
  isOpen,
  sessionsLoading,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onToggle,
  user,
}: Props) {
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const handleDelete = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (deleteConfirm === sessionId) {
      onDeleteSession(sessionId);
      setDeleteConfirm(null);
    } else {
      setDeleteConfirm(sessionId);
      setTimeout(() => setDeleteConfirm(null), 3000);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / 86400000);

    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days} days ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && <div className="sidebar-overlay" onClick={onToggle} />}

      <aside className={`chat-sidebar ${isOpen ? 'chat-sidebar--open' : ''}`}>
        {/* Header Logo */}
        <div className="sidebar-header" style={{ padding: '16px 16px 8px 16px', display: 'flex', justifyContent: 'center' }}>
          <img 
            src="/nexus-logo.png" 
            alt="NexusAI" 
            style={{ width: '100%', maxWidth: '110px', objectFit: 'contain' }}
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        </div>

        {/* New Chat Section */}
        <div className="sidebar-top">
          <button className="new-chat-btn" onClick={onNewChat} style={{ backgroundColor: 'var(--figma-primary)', color: '#000', fontWeight: 600 }}>
            <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
              <path d="M9 2a1 1 0 011 1v5h5a1 1 0 010 2h-5v5a1 1 0 01-2 0v-5H3a1 1 0 010-2h5V3a1 1 0 011-1z" />
            </svg>
            New Chat
          </button>
        </div>

        {/* Session List */}
        <div className="sidebar-sessions">
          <div className="sidebar-section-label">Recent Chats</div>

          {sessionsLoading ? (
            <div className="sidebar-loading">
              {[1, 2, 3].map((i) => (
                <div key={i} className="session-skeleton" />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <div className="sidebar-empty">
              <p>No conversations yet</p>
              <p className="sidebar-empty-hint">Start a new chat to begin</p>
            </div>
          ) : (
            <ul className="session-list">
              {sessions.map((session, index) => (
                <li
                  key={session.id}
                  className={`session-item ${activeSessionId === session.id ? 'session-item--active' : ''}`}
                  onClick={() => onSelectSession(session.id)}
                  style={{ animationDelay: `${index * 30}ms` }}
                >
                  <div className="session-item-content">
                    <svg className="session-icon" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M2 3a1 1 0 011-1h10a1 1 0 011 1v8a1 1 0 01-1 1H5l-3 3V3z" />
                    </svg>
                    <div className="session-info">
                      <span className="session-title">{session.title || 'New Chat'}</span>
                      <span className="session-date">{formatDate(session.created_at)}</span>
                    </div>
                  </div>

                  <button
                    className={`session-delete ${deleteConfirm === session.id ? 'session-delete--confirm' : ''}`}
                    onClick={(e) => handleDelete(session.id, e)}
                    title={deleteConfirm === session.id ? 'Click again to confirm' : 'Delete'}
                  >
                    {deleteConfirm === session.id ? (
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                        <path d="M5.5 5.5A.5.5 0 016 6v5a.5.5 0 01-1 0V6a.5.5 0 01.5-.5zm2.5 0a.5.5 0 01.5.5v5a.5.5 0 01-1 0V6a.5.5 0 01.5-.5zm3-3.5a.5.5 0 010 1H3a.5.5 0 010-1h2.5l.5-.5h2l.5.5H11zm-7.5 2v8a1 1 0 001 1h5a1 1 0 001-1V4.5h-7z" />
                      </svg>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                        <path d="M5.5 5.5A.5.5 0 016 6v5a.5.5 0 01-1 0V6a.5.5 0 01.5-.5zm2.5 0a.5.5 0 01.5.5v5a.5.5 0 01-1 0V6a.5.5 0 01.5-.5zm3-3.5a.5.5 0 010 1H3a.5.5 0 010-1h2.5l.5-.5h2l.5.5H11zm-7.5 2v8a1 1 0 001 1h5a1 1 0 001-1V4.5h-7z" />
                      </svg>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* User section */}
        <div className="sidebar-bottom" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className="sidebar-user">
            <div className="user-avatar" style={{ backgroundColor: 'var(--figma-primary)', color: '#000' }}>
              {user?.display_name?.charAt(0).toUpperCase() || 'U'}
            </div>
            <div className="user-info">
              <span className="user-name">{user?.display_name || 'User'}</span>
              <span className="user-email">{user?.email || ''}</span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <Link to="/settings" className="logout-btn" title="Settings" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"></circle>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
              </svg>
            </Link>
          </div>
        </div>
      </aside>
    </>
  );
}
