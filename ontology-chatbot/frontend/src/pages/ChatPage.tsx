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

  const handleNewChat = async () => {
    const profileName = selectedProfile || profiles[0]?.name;
    if (!profileName) return;

    try {
      const session = await createSessionMutation.mutateAsync({
        profile: profileName,
      });
      setActiveSessionId(session.id);
    } catch {
      // handled by mutation
    }
  };

  const handleSendMessage = async (content: string) => {
    if (!content.trim()) return;

    let sessionId = activeSessionId;

    // Create session on the fly if none
    if (!sessionId) {
      const profileName = selectedProfile || profiles[0]?.name;
      if (!profileName) return;
      try {
        const session = await createSessionMutation.mutateAsync({
          profile: profileName,
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
        profiles={profiles}
        selectedProfile={selectedProfile}
        sessionsLoading={sessionsLoading}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onSelectProfile={setSelectedProfile}
        onLogout={logout}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        user={user}
      />

      {/* Main Content */}
      <main className={`chat-main ${sidebarOpen ? '' : 'chat-main--full'}`}>
        {/* Header */}
        <header className="chat-header">
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
                <h2>{activeSession.title || 'New Chat'}</h2>
                <span className="chat-header-profile">{activeSession.profile}</span>
              </>
            ) : (
              <h2>Ontology Chatbot</h2>
            )}
          </div>

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
              <div className="welcome-content">
                <div className="welcome-icon">
                  <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                    <rect width="48" height="48" rx="14" fill="var(--accent)" opacity="0.15" />
                    <path
                      d="M16 24C16 19.5817 19.5817 16 24 16C28.4183 16 32 19.5817 32 24C32 28.4183 28.4183 32 24 32"
                      stroke="var(--accent)"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                    />
                    <circle cx="24" cy="24" r="3" fill="var(--accent)" />
                  </svg>
                </div>
                <h2>How can I help you today?</h2>
                <p>Ask questions about your ontology in natural language. I'll translate them to database queries and provide insights.</p>

                <div className="welcome-suggestions">
                  <button
                    className="suggestion-chip"
                    onClick={() => handleSendMessage('Show me all tables in the current schema')}
                  >
                    📊 Show all tables
                  </button>
                  <button
                    className="suggestion-chip"
                    onClick={() => handleSendMessage('What entities are available in the ontology?')}
                  >
                    🧬 List entities
                  </button>
                  <button
                    className="suggestion-chip"
                    onClick={() => handleSendMessage('Describe the relationships between entities')}
                  >
                    🔗 Show relationships
                  </button>
                  <button
                    className="suggestion-chip"
                    onClick={() => handleSendMessage('Help me write a query to find all connected nodes')}
                  >
                    🔍 Query help
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
          disabled={!selectedProfile && !activeSessionId && profiles.length === 0}
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
