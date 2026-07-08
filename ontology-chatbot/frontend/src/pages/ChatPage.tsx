import { useState } from 'react';
import ChatSidebar from '@/components/ChatSidebar';
import MessageList from '@/components/MessageList';
import MessageComposer from '@/components/MessageComposer';
import DevPanel from '@/components/DevPanel';
import { useAuth } from '@/hooks/useAuth';
import {
  useSessions,
  useMessages,
  useSendMessage,
  useCreateSession,
  useDeleteSession,
  useProfiles,
} from '@/hooks/useChat';
import type { Message } from '@/types/chat';
import './ChatPage.css';

export default function ChatPage() {
  const { user, logout } = useAuth();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [devPanelOpen, setDevPanelOpen] = useState(false);
  const [selectedMessage, setSelectedMessage] = useState<Message | null>(null);

  const { data: sessions = [], isLoading: sessionsLoading } = useSessions();
  const { data: messages = [], isLoading: messagesLoading } = useMessages(activeSessionId);
  const { data: profiles = [] } = useProfiles();
  const sendMessageMutation = useSendMessage();
  const createSessionMutation = useCreateSession();
  const deleteSessionMutation = useDeleteSession();

  const activeSession = sessions.find((s) => s.id === activeSessionId);
  // Default to first profile if none selected
  const activeProfileName = selectedProfile || profiles[0]?.name || '';

  const handleNewChat = async () => {
    if (!activeProfileName) return;

    try {
      const session = await createSessionMutation.mutateAsync({
        profile: activeProfileName,
      });
      setActiveSessionId(session.id);
    } catch {
      // handled by mutation
    }
  };

  const handleSendMessage = async (content: string) => {
    if (!content.trim()) return;
    if (!activeProfileName) return; // DB must be selected

    let sessionId = activeSessionId;

    // Create session on the fly if none
    if (!sessionId) {
      try {
        const session = await createSessionMutation.mutateAsync({
          profile: activeProfileName,
          title: content.slice(0, 60),
        });
        sessionId = session.id;
        setActiveSessionId(session.id);
      } catch {
        return;
      }
    }

    try {
      const response = await sendMessageMutation.mutateAsync({
        content,
        session_id: sessionId,
      });
      setSelectedMessage(response.message);
    } catch {
      // handled by mutation
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSessionMutation.mutateAsync(sessionId);
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setSelectedMessage(null);
      }
    } catch {
      // handled by mutation
    }
  };

  const handleSelectSession = (sessionId: string) => {
    setActiveSessionId(sessionId);
    setSelectedMessage(null);
  };

  const handleMessageSelect = (message: Message) => {
    if (user?.is_admin && message.role === 'assistant') {
      setSelectedMessage(message);
      setDevPanelOpen(true);
    }
  };

  return (
    <div className="chat-page">
      {/* Sidebar */}
      <ChatSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        isOpen={sidebarOpen}
        sessionsLoading={sessionsLoading}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onLogout={logout}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        user={user}
      />

      {/* Main Content */}
      <main className={`chat-main ${sidebarOpen ? '' : 'chat-main--full'}`}>
        {/* Header */}
        <header className="chat-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <button
              className="sidebar-toggle"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-label="Toggle sidebar"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
                <path d="M3 5h14a1 1 0 010 2H3a1 1 0 010-2zm0 4h14a1 1 0 010 2H3a1 1 0 010-2zm0 4h14a1 1 0 010 2H3a1 1 0 010-2z" />
              </svg>
            </button>

            <div className="chat-header-title">
              {activeSession ? (
                <>
                  <h2 style={{ fontSize: '16px', fontWeight: 600 }}>{activeSession.title || 'New Chat'}</h2>
                </>
              ) : (
                <h2 style={{ fontSize: '16px', fontWeight: 600 }}>Ontology Chatbot</h2>
              )}
            </div>
          </div>

          {/* Database Selector in Top Bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '14px', color: 'var(--figma-text-subtle)' }}>Database:</span>
            <select
              value={selectedProfile}
              onChange={(e) => setSelectedProfile(e.target.value)}
              style={{
                backgroundColor: 'var(--figma-bg-card)',
                color: 'var(--figma-text-dark)',
                border: '1px solid var(--figma-border)',
                borderRadius: '8px',
                padding: '6px 12px',
                fontSize: '14px',
                outline: 'none',
                minWidth: '200px'
              }}
            >
              {profiles.length === 0 && <option value="">No databases available</option>}
              {!selectedProfile && profiles.length > 0 && <option value="">Select a database...</option>}
              {profiles.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.display_name || p.name}
                </option>
              ))}
            </select>

            {user?.is_admin && activeSessionId && (
              <button
                className={`dev-toggle ${devPanelOpen ? 'dev-toggle--active' : ''}`}
                onClick={() => setDevPanelOpen(!devPanelOpen)}
                title="Developer Panel"
              >
                <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor">
                  <path d="M5.854 4.146a.5.5 0 10-.708.708L8.293 8l-3.147 3.146a.5.5 0 00.708.708l3.5-3.5a.5.5 0 000-.708l-3.5-3.5zM9.5 12a.5.5 0 000 1h4a.5.5 0 000-1h-4z" />
                </svg>
                Dev
              </button>
            )}
          </div>
        </header>

        {/* Messages or Welcome */}
        <div className="chat-content">
          {activeSessionId ? (
            <MessageList
              messages={messages}
              isLoading={messagesLoading}
              isSending={sendMessageMutation.isPending}
              error={sendMessageMutation.error?.message || null}
              onMessageSelect={handleMessageSelect}
              selectedMessageId={selectedMessage?.id}
            />
          ) : (
            <div className="welcome-screen">
              <div className="welcome-content" style={{ maxWidth: '800px', margin: '0 auto', textAlign: 'center' }}>
                <div className="welcome-icon" style={{ margin: '0 auto 24px auto', width: '64px', height: '64px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                    <rect width="48" height="48" rx="14" fill="var(--figma-primary)" opacity="0.15" />
                    <path
                      d="M16 24C16 19.5817 19.5817 16 24 16C28.4183 16 32 19.5817 32 24C32 28.4183 28.4183 32 24 32"
                      stroke="var(--figma-primary)"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                    />
                    <circle cx="24" cy="24" r="3" fill="var(--figma-primary)" />
                  </svg>
                </div>
                <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '32px', marginBottom: '16px', color: 'var(--figma-text-white)' }}>
                  Welcome to Ontology
                </h2>
                <p style={{ color: 'var(--figma-text-subtle)', marginBottom: '48px', fontSize: '16px' }}>
                  {activeProfileName 
                    ? `You are connected to ${activeProfileName}. Try asking one of the questions below.` 
                    : 'Please select a database from the top right to start querying.'}
                </p>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', textAlign: 'left' }}>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('Show me all tables and their descriptions')}
                    style={{ padding: '24px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-secondary)', borderRadius: '12px', cursor: activeProfileName ? 'pointer' : 'not-allowed', opacity: activeProfileName ? 1 : 0.5, transition: 'background-color 0.2s', textAlign: 'left' }}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>📊</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--figma-text-white)' }}>Database Schema</div>
                    <div style={{ fontSize: '13px', color: 'var(--figma-text-subtle)' }}>Show me all tables and their descriptions</div>
                  </button>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('What are the key entities in this database?')}
                    style={{ padding: '24px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-secondary)', borderRadius: '12px', cursor: activeProfileName ? 'pointer' : 'not-allowed', opacity: activeProfileName ? 1 : 0.5, transition: 'background-color 0.2s', textAlign: 'left' }}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>🧬</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--figma-text-white)' }}>Key Entities</div>
                    <div style={{ fontSize: '13px', color: 'var(--figma-text-subtle)' }}>What are the key entities in this database?</div>
                  </button>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('Can you summarize the relationships between tables?')}
                    style={{ padding: '24px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-secondary)', borderRadius: '12px', cursor: activeProfileName ? 'pointer' : 'not-allowed', opacity: activeProfileName ? 1 : 0.5, transition: 'background-color 0.2s', textAlign: 'left' }}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>🔗</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--figma-text-white)' }}>Relationships</div>
                    <div style={{ fontSize: '13px', color: 'var(--figma-text-subtle)' }}>Can you summarize the relationships between tables?</div>
                  </button>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('Help me construct a complex join query')}
                    style={{ padding: '24px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-secondary)', borderRadius: '12px', cursor: activeProfileName ? 'pointer' : 'not-allowed', opacity: activeProfileName ? 1 : 0.5, transition: 'background-color 0.2s', textAlign: 'left' }}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>🔍</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--figma-text-white)' }}>Query Assistance</div>
                    <div style={{ fontSize: '13px', color: 'var(--figma-text-subtle)' }}>Help me construct a complex join query</div>
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Composer */}
        <MessageComposer
          onSend={handleSendMessage}
          isLoading={sendMessageMutation.isPending || createSessionMutation.isPending}
          disabled={!activeProfileName}
        />
      </main>

      {/* Dev Panel */}
      {user?.is_admin && devPanelOpen && (
        <DevPanel
          message={selectedMessage}
          onClose={() => setDevPanelOpen(false)}
        />
      )}
    </div>
  );
}
