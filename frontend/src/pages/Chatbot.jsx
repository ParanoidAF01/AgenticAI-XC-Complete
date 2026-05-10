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

  return (
    <div className="chatbot-page">
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
          <Trash2 size={16} /> Clear Chat
        </button>
      </div>

      <div className="chat-window">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="empty-icon">👋</div>
            <h3>Hi! I'm your ADF Pipeline Assistant.</h3>
            <p>I can help you understand pipeline errors, find root causes, and suggest fixes. Ask me anything!</p>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div key={idx} className={`message-wrapper ${msg.role}`}>
              <div className="avatar">
                {msg.role === 'user' ? <User size={18} /> : <Bot size={18} />}
              </div>
              <div className="message-content">
                <div className="message-text">
                  {/* Simple text formatting for demo, in real app use react-markdown */}
                  <pre className="content-pre">{msg.content}</pre>
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
        <div className="quick-actions">
          <button onClick={() => setInput("Most common errors this week")}>Most common errors this week</button>
          <button onClick={() => setInput("Why did PL_Template fail?")}>Why did PL_Template fail?</button>
          <button onClick={() => setInput("How to fix Type 3 errors?")}>How to fix Type 3 errors?</button>
        </div>
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
      </div>
    </div>
  );
};

export default Chatbot;
