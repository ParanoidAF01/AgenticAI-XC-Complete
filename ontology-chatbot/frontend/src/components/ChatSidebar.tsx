import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
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
  onExportSession: (id: string) => void;
  onToggle: () => void;
  user: User | null;
}

/* ── Floating Dropdown (Portal) ──────────────────────────── */
function FloatingDropdown({
  anchorRef,
  sessionId,
  onExport,
  onDelete,
  onClose,
}: {
  anchorRef: HTMLButtonElement | null;
  sessionId: string;
  onExport: (id: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  // Compute position relative to the anchor button
  useEffect(() => {
    if (!anchorRef) return;
    const rect = anchorRef.getBoundingClientRect();
    const menuHeight = 80; // approximate height of 2-item menu
    const spaceBelow = window.innerHeight - rect.bottom;
    const sidebarWidth = anchorRef.closest('.chat-sidebar')?.getBoundingClientRect().width ?? 260;

    // If not enough space below, open above
    const top = spaceBelow < menuHeight + 8
      ? rect.top - menuHeight - 4
      : rect.bottom + 4;

    // Position to the right of the sidebar
    const left = sidebarWidth + 4;

    setPos({ top, left });
  }, [anchorRef]);

  // Click outside to close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        anchorRef &&
        !anchorRef.contains(e.target as Node)
      ) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose, anchorRef]);

  if (!pos) return null;

  return createPortal(
    <div
      ref={menuRef}
      className="session-dropdown-portal"
      style={{ top: pos.top, left: pos.left }}
    >
      <button
        className="dropdown-item"
        onClick={(e) => {
          e.stopPropagation();
          onExport(sessionId);
          onClose();
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
          <line x1="12" y1="18" x2="12" y2="12"></line>
          <line x1="9" y1="15" x2="12" y2="18"></line>
          <line x1="15" y1="15" x2="12" y2="18"></line>
        </svg>
        Export chat as PDF
      </button>
      <button
        className="dropdown-item dropdown-item--danger"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(sessionId);
          onClose();
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
        Delete chat
      </button>
    </div>,
    document.body
  );
}

/* ── Main Sidebar ────────────────────────────────────────── */
export default function ChatSidebar({
  sessions,
  activeSessionId,
  isOpen,
  sessionsLoading,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onExportSession,
  onToggle,
  user,
}: Props) {
  const [sessionToDelete, setSessionToDelete] = useState<string | null>(null);
  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const [anchorEl, setAnchorEl] = useState<HTMLButtonElement | null>(null);

  const handleDeleteConfirm = () => {
    if (sessionToDelete) {
      onDeleteSession(sessionToDelete);
      setSessionToDelete(null);
    }
  };

  const openMenu = useCallback((sessionId: string, btnEl: HTMLButtonElement) => {
    if (activeDropdown === sessionId) {
      setActiveDropdown(null);
      setAnchorEl(null);
    } else {
      setActiveDropdown(sessionId);
      setAnchorEl(btnEl);
    }
  }, [activeDropdown]);

  const closeMenu = useCallback(() => {
    setActiveDropdown(null);
    setAnchorEl(null);
  }, []);

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

      {/* Delete Confirmation Modal */}
      {sessionToDelete && (
        <div className="modal-overlay" onClick={() => setSessionToDelete(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3 className="modal-title">Are you sure you want to delete this chat?</h3>
            <div className="modal-actions">
              <button
                className="modal-btn modal-btn--cancel"
                onClick={() => setSessionToDelete(null)}
              >
                Cancel
              </button>
              <button
                className="modal-btn modal-btn--danger"
                onClick={handleDeleteConfirm}
              >
                Yes, Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Portal dropdown renders on document.body */}
      {activeDropdown && anchorEl && (
        <FloatingDropdown
          anchorRef={anchorEl}
          sessionId={activeDropdown}
          onExport={onExportSession}
          onDelete={(id) => setSessionToDelete(id)}
          onClose={closeMenu}
        />
      )}

      <aside className={`chat-sidebar ${isOpen ? 'chat-sidebar--open' : ''}`}>
        {/* Header Logo */}
        <div className="sidebar-header" style={{ padding: '20px 0px 0px 0px', display: 'flex', justifyContent: 'center' }}>
          <img
            src="/nexus-logo.png"
            alt="NexusAI"
            style={{ width: '100%', maxWidth: '200px', objectFit: 'contain' }}
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
                    className={`session-menu-btn ${activeDropdown === session.id ? 'session-menu-btn--open' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      openMenu(session.id, e.currentTarget);
                    }}
                    title="Menu"
                  >
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                      <path d="M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zm0-5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zm0 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z" />
                    </svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* User section */}
        <div className="sidebar-bottom" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className="sidebar-user">
            <div className="user-avatar">
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
