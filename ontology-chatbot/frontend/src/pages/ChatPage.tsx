import { useState, useRef, useEffect } from 'react';
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
import { jsPDF } from 'jspdf';
import './ChatPage.css';

export default function ChatPage() {
  const { user } = useAuth();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  const [devPanelOpen, setDevPanelOpen] = useState(false);
  const [selectedMessage, setSelectedMessage] = useState<Message | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

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
      // 1. Cleanup any existing empty sessions before creating a new one
      const emptySessions = sessions.filter(s => !s.profile);
      for (const emptySession of emptySessions) {
        if (emptySession.id !== activeSessionId) {
          try {
            await deleteSessionMutation.mutateAsync(emptySession.id);
          } catch {
            // ignore cleanup errors
          }
        }
      }

      // 2. Check if the currently active session is already empty
      if (activeSessionId) {
        const currentActive = sessions.find(s => s.id === activeSessionId);
        if (currentActive && !currentActive.profile) {
          // If we are already on an empty session, just clear the screen and do nothing else
          setSelectedMessage(null);
          setSelectedProfile('');
          return;
        }
      }

      // 3. Create a fresh empty session
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
      // Update session profile and title if we are reusing a "New Chat" empty session
      const currentSession = sessions.find(s => s.id === sessionId);
      if (currentSession && !currentSession.profile) {
        try {
          await chatApi.updateSession(sessionId, { 
            profile: activeProfileName,
            title: content.slice(0, 60)
          });
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

  const handleExportSession = async (sessionId: string) => {
    try {
      // Fetch messages and session info directly from API
      const [exportMessages, sessionInfo] = await Promise.all([
        chatApi.getMessages(sessionId),
        chatApi.getSession(sessionId),
      ]);

      if (!exportMessages.length) return;

      const pdf = new jsPDF('p', 'mm', 'a4');
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 18;
      const contentWidth = pageWidth - margin * 2;
      let y = margin;

      // ── Colors ──
      const brandYellow: [number, number, number] = [255, 214, 0];
      const userBg: [number, number, number] = [235, 245, 255];
      const userBorder: [number, number, number] = [59, 130, 246];
      const assistantBg: [number, number, number] = [248, 249, 250];
      const assistantBorder: [number, number, number] = [200, 200, 200];
      const darkText: [number, number, number] = [26, 28, 27];
      const mutedText: [number, number, number] = [107, 107, 107];
      const userLabelColor: [number, number, number] = [37, 99, 235];
      const assistantLabelColor: [number, number, number] = [16, 185, 129];

      // ── Helper: check page break ──
      const ensureSpace = (needed: number) => {
        if (y + needed > pageHeight - margin) {
          pdf.addPage();
          y = margin;
        }
      };

      // ── Header ──
      pdf.setFillColor(...brandYellow);
      pdf.rect(0, 0, pageWidth, 28, 'F');
      pdf.setFont('helvetica', 'bold');
      pdf.setFontSize(16);
      pdf.setTextColor(...darkText);
      pdf.text(sessionInfo.title || 'Chat Export', margin, 12);
      pdf.setFont('helvetica', 'normal');
      pdf.setFontSize(9);
      pdf.setTextColor(...mutedText);
      const dateStr = new Date(sessionInfo.created_at).toLocaleDateString('en-US', {
        year: 'numeric', month: 'long', day: 'numeric',
      });
      pdf.text(`Exported on ${dateStr}`, margin, 19);
      pdf.text(`${exportMessages.length} messages`, margin, 24);

      // Separator line
      y = 32;
      pdf.setDrawColor(230, 230, 230);
      pdf.setLineWidth(0.3);
      pdf.line(margin, y, pageWidth - margin, y);
      y += 8;

      // ── Render each message ──
      for (const msg of exportMessages) {
        const isUser = msg.role === 'user';
        const label = isUser ? (user?.display_name || 'You') : 'NexusAI';
        const timestamp = new Date(msg.created_at).toLocaleTimeString([], {
          hour: '2-digit', minute: '2-digit',
        });

        // Wrap text to fit content width minus padding
        const textPadding = 8;
        const textWidth = contentWidth - textPadding * 2;
        pdf.setFont('helvetica', 'normal');
        pdf.setFontSize(10);
        const lines = pdf.splitTextToSize(msg.content, textWidth);
        const blockHeight = lines.length * 5 + 20; // text + label + padding

        ensureSpace(blockHeight + 6);

        // Message card background
        const bgColor = isUser ? userBg : assistantBg;
        const borderColor = isUser ? userBorder : assistantBorder;
        const cardX = margin;
        const cardWidth = contentWidth;
        const cardHeight = blockHeight;

        // Rounded rect fill
        pdf.setFillColor(...bgColor);
        pdf.roundedRect(cardX, y, cardWidth, cardHeight, 3, 3, 'F');

        // Left accent bar
        pdf.setFillColor(...borderColor);
        pdf.rect(cardX, y + 2, 2, cardHeight - 4, 'F');

        // Role label
        let textY = y + 7;
        pdf.setFont('helvetica', 'bold');
        pdf.setFontSize(9);
        pdf.setTextColor(...(isUser ? userLabelColor : assistantLabelColor));
        pdf.text(label, cardX + textPadding + 3, textY);

        // Timestamp
        pdf.setFont('helvetica', 'normal');
        pdf.setFontSize(7.5);
        pdf.setTextColor(...mutedText);
        pdf.text(timestamp, cardX + cardWidth - textPadding - pdf.getTextWidth(timestamp), textY);

        // Message text
        textY += 6;
        pdf.setFont('helvetica', 'normal');
        pdf.setFontSize(10);
        pdf.setTextColor(...darkText);

        for (const line of lines) {
          if (textY > pageHeight - margin - 5) {
            pdf.addPage();
            textY = margin + 5;
          }
          pdf.text(line, cardX + textPadding + 3, textY);
          textY += 5;
        }

        y += cardHeight + 5;
      }

      // ── Footer on last page ──
      pdf.setFont('helvetica', 'italic');
      pdf.setFontSize(7.5);
      pdf.setTextColor(...mutedText);
      pdf.text(
        `Generated by NexusAI • ${new Date().toLocaleString()}`,
        pageWidth / 2,
        pageHeight - 8,
        { align: 'center' }
      );

      pdf.save(`Chat_Export_${new Date().toISOString().split('T')[0]}.pdf`);
    } catch (err) {
      console.error('Error exporting PDF:', err);
    }
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
        onExportSession={handleExportSession}
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
              <img 
                  src= "/sidebar-left-svgrepo-com.svg"
                  alt=""
                  style={{width: '18px', height: '18px', marginRight: '8px', display: 'inline-block', verticalAlign: 'middle'}}
                  />
            </button>

            <div className="chat-header-title">
              {activeSession ? (
                <>
                  <h2 style={{ fontSize: '16px', fontWeight: 600 }}>{activeSession.title || 'New Chat'}</h2>
                </>
              ) : (
                <h2 style={{ fontSize: '16px', fontWeight: 600 }}>Nexus AI</h2>
              )}
            </div>
          </div>

          {/* Database Selector in Top Bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '14px', color: 'var(--figma-text-subtle)' }}>Database:</span>
            <div className="custom-dropdown" ref={dropdownRef}>
              <button
                className="custom-dropdown-btn"
                onClick={() => setDropdownOpen(!dropdownOpen)}
              >
                <span className={!selectedProfile ? 'placeholder' : ''}>
                  {selectedProfile 
                    ? (profiles.find(p => p.name === selectedProfile)?.display_name || selectedProfile)
                    : 'Select a database...'}
                </span>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: dropdownOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </button>
              
              {dropdownOpen && (
                <ul className="custom-dropdown-list">
                  {profiles.length === 0 && (
                    <li className="custom-dropdown-item disabled">No databases available</li>
                  )}
                  {profiles.map((p) => (
                    <li 
                      key={p.name} 
                      className={`custom-dropdown-item ${selectedProfile === p.name ? 'selected' : ''}`}
                      onClick={() => {
                        setSelectedProfile(p.name);
                        setDropdownOpen(false);
                      }}
                    >
                      {p.display_name || p.name}
                    </li>
                  ))}
                </ul>
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

            <img 
              src="/company-logo.png" 
              alt="Company Logo" 
              style={{ height: '32px', marginLeft: '8px', objectFit: 'contain' }}
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
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
              user={user}
            />
          ) : (
            <div className="welcome-screen">
              <div className="welcome-content" style={{ maxWidth: '800px', margin: '0 auto', textAlign: 'center' }}>
                <div className="welcome-icon" style={{ margin: '0 auto 24px auto', width: '48px', height: '48px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '12px' }}>
                  <img 
                  src= "/company-logo.png"
                  alt="Company Logo"
                  style={{height: '32px', marginLeft: '8px', objectFit: 'contain'}}/>
                </div>
                <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '28px', marginBottom: '16px', color: 'var(--text-primary)', fontWeight: 700 }}>
                  Welcome to Nexus AI
                </h2>
                <p style={{ color: activeProfileName ? 'var(--figma-text-subtle)' : '#000000', marginBottom: '48px', fontSize: '16px' }}>
                  {activeProfileName 
                    ? `You are connected to ${activeProfileName}. Try asking questions from insurance database.` 
                    : 'Insurance Chatbot powered by Xceedance Insurance Data Platform'}
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
                Please select a database from top-right to start chatting.
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
