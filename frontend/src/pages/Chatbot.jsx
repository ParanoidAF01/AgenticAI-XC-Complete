import React, { useState, useEffect, useRef } from 'react';
import { Send, Trash2, User, Bot, ChevronDown, Sparkles } from 'lucide-react';
import { ChatAPI } from '../services/api';
import './Chatbot.css';

const Chatbot = () => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [pipelines, setPipelines] = useState([]);
  const [selectedPipeline, setSelectedPipeline] = useState('all');
  const [loading, setLoading] = useState(false);
  const [conversations, setConversations] = useState([
    { id: '1', title: 'Pipeline Error Analysis', date: 'Today' },
    { id: '2', title: 'Data Flow Debugging', date: 'Yesterday' },
    { id: '3', title: 'Credential Refresh Help', date: 'May 12' }
  ]);
  const [activeChatId, setActiveChatId] = useState('1');
  const chatEndRef = useRef(null);

  useEffect(() => {
    const initChat = async () => {
      try {
        const [histRes, pipeRes] = await Promise.all([
          ChatAPI.getHistory(),
          ChatAPI.getPipelines()
        ]);
        setMessages(histRes.messages);
        setPipelines(pipeRes.pipelines.all);
      } catch (err) {
        console.error("Chat init error:", err);
      }
    };
    initChat();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMsg = {
      role: 'user',
      content: input,
      timestamp: new Date().toLocaleTimeString()
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await ChatAPI.sendMessage({
        question: input,
        pipeline_name: selectedPipeline === 'all' ? null : selectedPipeline
      });

      const assistantMsg = {
        role: 'assistant',
        content: res.answer,
        timestamp: new Date().toLocaleTimeString()
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err) {
      console.error("Chat error:", err);
    } finally {
      setLoading(false);
    }
  };

  const clearChat = async () => {
    if (window.confirm("Are you sure you want to clear the chat history?")) {
      await ChatAPI.clearHistory();
      setMessages([]);
    }
  };

  const formatContent = (content) => {
    if (!content) return null;
    
    // Simple markdown-like formatter for professional look
    const lines = content.split('\n');
    return lines.map((line, i) => {
      // Horizontal Rule
      if (line.trim() === '---' || line.trim() === '===') return <hr key={i} className="chat-hr" />;
      
      // Headers
      if (line.startsWith('### ')) return <h4 key={i} className="chat-h4">{line.replace('### ', '')}</h4>;
      if (line.startsWith('## ')) return <h3 key={i} className="chat-h3">{line.replace('## ', '')}</h3>;
      if (line.startsWith('# ')) return <h2 key={i} className="chat-h2">{line.replace('# ', '')}</h2>;
      
      // Bullet points
      if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
        const bulletPart = line.trim().slice(2);
        return (
          <div key={i} className="chat-bullet">
            <span className="bullet-dot">•</span>
            <p className="chat-p">{formatInline(bulletPart)}</p>
          </div>
        );
      }

      return <p key={i} className="chat-p">{formatInline(line)}</p>;
    });
  };

  const formatInline = (text) => {
    return text.split(/(\*\*.*?\*\*)/g).map((part, j) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={j}>{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  };

  return (
    <div className="chatbot-container">
      <aside className="chat-sidebar">
        <button className="new-chat-btn" onClick={() => setMessages([])}>
          <span>+</span> New Chat
        </button>
        
        <div className="history-section">
          <label>Recent Chats</label>
          <div className="history-list">
            {conversations.map(chat => (
              <div 
                key={chat.id} 
                className={`history-item ${activeChatId === chat.id ? 'active' : ''}`}
                onClick={() => setActiveChatId(chat.id)}
              >
                <span className="chat-title">{chat.title}</span>
                <span className="chat-date">{chat.date}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="sidebar-footer-info">
          <div className="user-info">
            <div className="user-avatar">A</div>
            <div className="user-details">
              <span className="user-name">Admin User</span>
              <span className="user-plan">Pro Plan</span>
            </div>
          </div>
        </div>
      </aside>

      <div className="chatbot-main">
        <div className="chatbot-header">
          <div className="header-left">
            <Sparkles size={20} className="sparkle-icon" />
            <h2>AI Assistant</h2>
            <div className="pipeline-selector">
              <select 
                value={selectedPipeline} 
                onChange={(e) => setSelectedPipeline(e.target.value)}
              >
                <option value="all">All Pipelines</option>
                {pipelines.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
              <ChevronDown size={14} className="select-icon" />
            </div>
          </div>
          <button className="clear-btn" onClick={clearChat}>
            <Trash2 size={16} /> Clear
          </button>
        </div>

        <div className="chat-window">
          {messages.length === 0 ? (
            <div className="chat-empty">
              <div className="empty-icon">
                <Bot size={48} />
              </div>
              <h3>How can I help you today?</h3>
              <p>Ask me about pipeline errors, performance bottlenecks, or recovery strategies.</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div key={idx} className={`message-wrapper ${msg.role}`}>
                <div className="avatar">
                  {msg.role === 'user' ? <User size={18} /> : <Bot size={18} />}
                </div>
                <div className="message-content">
                  <div className="message-text">
                    {formatContent(msg.content)}
                  </div>
                  <span className="message-time">{msg.timestamp}</span>
                </div>
              </div>
            ))
          )}
          {loading && (
            <div className="message-wrapper assistant loading">
              <div className="avatar"><Bot size={18} /></div>
              <div className="message-content">
                <div className="typing-indicator">
                  <span></span><span></span><span></span>
                </div>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <div className="chat-footer">
          <form className="input-area" onSubmit={handleSend}>
            <input 
              type="text" 
              placeholder="Ask about pipeline errors..." 
              value={input}
              onChange={(e) => setInput(e.target.value)}
            />
            <button type="submit" className="send-btn" disabled={!input.trim() || loading}>
              <Send size={20} />
            </button>
          </form>
          <div className="footer-disclaimer">
            AI can make mistakes. Check important info.
          </div>
        </div>
      </div>
    </div>
  );
};

export default Chatbot;
