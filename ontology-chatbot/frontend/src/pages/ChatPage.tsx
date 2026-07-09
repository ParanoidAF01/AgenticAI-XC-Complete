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
import { chatApi } from '@/api/chat';
import type { Message } from '@/types/chat';
import './ChatPage.css';

export default function ChatPage() {
  const { user } = useAuth();
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
  // Require explicit profile selection
  const activeProfileName = selectedProfile || '';

  const handleNewChat = async () => {
    try {
      const session = await createSessionMutation.mutateAsync({
        profile: undefined,
      });
      setActiveSessionId(session.id);
      setSelectedMessage(null);
      setSelectedProfile('');
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
    } else {
      // Update session profile if we are reusing a "New Chat" empty session
      const currentSession = sessions.find(s => s.id === sessionId);
      if (currentSession && !currentSession.profile) {
        try {
          await chatApi.updateSession(sessionId, { profile: activeProfileName });
        } catch {
          // ignore error and proceed
        }
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
              {!selectedProfile && profiles.length > 0 && <option value="" disabled>Select a database...</option>}
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
                <div className="welcome-icon" style={{ margin: '0 auto 24px auto', width: '48px', height: '48px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFD600', borderRadius: '12px' }}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM11 19.93C7.06 19.43 4 16.05 4 12C4 7.95 7.06 4.57 11 4.07V19.93ZM13 4.07C14.03 4.2 15 4.52 15.87 5H13V4.07ZM13 7H17.24C18.13 8.39 18.76 9.97 18.95 11H13V7ZM13 13H18.95C18.76 14.03 18.13 15.61 17.24 17H13V13ZM13 19.93V19H15.87C15 19.48 14.03 19.8 13 19.93Z" fill="#111111" />
                  </svg>
                </div>
                <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '28px', marginBottom: '16px', color: 'var(--text-primary)', fontWeight: 700 }}>
                  Welcome to Ontology
                </h2>
                <p style={{ color: 'var(--figma-text-subtle)', marginBottom: '48px', fontSize: '16px' }}>
                  {activeProfileName 
                    ? `You are connected to ${activeProfileName}. Try asking one of the questions below.` 
                    : 'Please select a database from the top right to start querying.'}
                </p>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '16px', textAlign: 'left', maxWidth: '800px', margin: '0 auto' }}>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('Show me all tables and their descriptions')}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>📊</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--text-primary)', fontSize: '15px' }}>Database Schema</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Show me all tables and their descriptions</div>
                  </button>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('What are the key entities in this database?')}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>🧬</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--text-primary)', fontSize: '15px' }}>Key Entities</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>What are the key entities in this database?</div>
                  </button>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('Can you summarize the relationships between tables?')}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>🔗</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--text-primary)', fontSize: '15px' }}>Relationships</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Can you summarize the relationships between tables?</div>
                  </button>
                  <button
                    className="suggestion-card"
                    disabled={!activeProfileName}
                    onClick={() => handleSendMessage('Help me construct a complex join query')}
                  >
                    <div style={{ fontSize: '20px', marginBottom: '8px' }}>🔍</div>
                    <div style={{ fontWeight: 600, marginBottom: '4px', color: 'var(--text-primary)', fontSize: '15px' }}>Query Assistance</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Help me construct a complex join query</div>
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Composer wrapper for relative positioning of the locked overlay */}
        <div style={{ position: 'relative' }}>
          {!activeProfileName && (
            <div style={{
              position: 'absolute',
              top: '-24px',
              left: '0',
              right: '0',
              textAlign: 'center',
              zIndex: 10,
              pointerEvents: 'none'
            }}>
              <span style={{
                color: 'var(--figma-text-secondary)',
                fontSize: '12px',
                fontFamily: 'var(--font-sans)',
              }}>
                Please select a database to start chatting.
              </span>
            </div>
          )}
          <MessageComposer
            onSend={handleSendMessage}
            isLoading={sendMessageMutation.isPending || createSessionMutation.isPending}
            disabled={!activeProfileName}
          />
        </div>
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
