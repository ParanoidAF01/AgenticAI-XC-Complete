import React, { useState, useEffect } from 'react';
import { 
  Play, 
  Square, 
  RefreshCcw, 
  CheckCircle2, 
  XCircle,
  Activity, 
  Clock, 
  Database,
  Cloud,
  Key,
  Cpu,
  Trash2
} from 'lucide-react';
import { SettingsAPI, ListenerAPI } from '../services/api';
import './Settings.css';

const Settings = () => {
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState(null);
  const [healthServices, setHealthServices] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [checkingHealth, setCheckingHealth] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  // Convert the health services ARRAY into a lookup map by service name
  const parseHealthServices = (healthRes) => {
    if (!healthRes?.services) return [];
    // Backend returns services as an array: [{service: "Azure AD Auth", status: "connected", ...}, ...]
    return Array.isArray(healthRes.services) ? healthRes.services : [];
  };

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [settRes, statRes, healthRes, logsRes] = await Promise.all([
          SettingsAPI.getSettings(),
          ListenerAPI.getStatus(),
          ListenerAPI.getHealth(),
          ListenerAPI.getLogs()
        ]);
        setSettings(settRes);
        setStatus(statRes);
        setHealthServices(parseHealthServices(healthRes));
        setLogs(logsRes?.logs || []);
      } catch (err) {
        console.error("Error fetching settings data:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // Auto-refresh logs every 5 seconds when listener is running
  useEffect(() => {
    if (!status?.running) return;
    const interval = setInterval(async () => {
      try {
        const [statRes, logsRes] = await Promise.all([
          ListenerAPI.getStatus(),
          ListenerAPI.getLogs()
        ]);
        setStatus(statRes);
        setLogs(logsRes?.logs || []);
      } catch (err) {
        console.error("Poll refresh error:", err);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [status?.running]);

  const handleStartStop = async () => {
    setActionLoading(true);
    try {
      if (status?.running) {
        await ListenerAPI.stop();
      } else {
        await ListenerAPI.start({ mode: settings?.listener_mode || 'sql' });
      }
      // Small delay then refresh status + logs
      await new Promise(r => setTimeout(r, 500));
      const [newStatus, logsRes] = await Promise.all([
        ListenerAPI.getStatus(),
        ListenerAPI.getLogs()
      ]);
      setStatus(newStatus);
      setLogs(logsRes?.logs || []);
    } catch (err) {
      console.error("Listener control error:", err);
      alert(`Listener action failed: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleModeChange = async (mode) => {
    if (mode === 'databricks' || mode === 'snowflake') return;
    try {
      await SettingsAPI.updateSettings({ listener_mode: mode });
      setSettings(prev => ({ ...prev, listener_mode: mode }));
    } catch (err) {
      console.error("Mode change error:", err);
    }
  };

  const checkHealth = async () => {
    setCheckingHealth(true);
    try {
      const res = await ListenerAPI.checkHealth();
      setHealthServices(parseHealthServices(res));
    } catch (err) {
      console.error("Health check error:", err);
    } finally {
      setCheckingHealth(false);
    }
  };

  // Find a specific health service from the array by name
  const getServiceHealth = (serviceName) => {
    return healthServices.find(s => s.service === serviceName) || null;
  };

  if (loading) return (
    <div className="loading-screen">
      <div className="loader"></div>
      <p>Loading System Settings...</p>
    </div>
  );

  return (
    <div className="settings-page">
      <section className="settings-section">
        <h3>Active Listener</h3>
        <p className="section-desc">Select the polling mechanism for failure detection</p>
        
        <div className="listener-cards">
          <div 
            className={`listener-card ${settings?.listener_mode === 'adf' ? 'active' : ''}`}
            onClick={() => handleModeChange('adf')}
          >
            <div className="card-radio"></div>
            <Cloud size={24} className="card-icon" />
            <h4>ADF SDK Listener</h4>
            <p>Polls Azure Data Factory SDK for failed pipeline runs in real-time.</p>
          </div>

          <div 
            className={`listener-card ${settings?.listener_mode === 'sql' ? 'active' : ''}`}
            onClick={() => handleModeChange('sql')}
          >
            <div className="card-radio"></div>
            <Database size={24} className="card-icon" />
            <h4>SQL Table Listener</h4>
            <p>Polls PipelineRunLog table for failed pipeline runs via SQL query.</p>
          </div>

          <div className="listener-card disabled">
            <Cpu size={24} className="card-icon" />
            <h4>Databricks</h4>
            <span className="coming-soon">COMING SOON</span>
          </div>

          <div className="listener-card disabled">
            <Activity size={24} className="card-icon" />
            <h4>Snowflake</h4>
            <span className="coming-soon">COMING SOON</span>
          </div>
        </div>
      </section>

      <div className="listener-controls card">
        <button 
          className={`control-btn ${status?.running ? 'stop' : 'start'}`}
          onClick={handleStartStop}
          disabled={actionLoading}
        >
          {actionLoading ? (
            <><RefreshCcw size={20} className="spinning" /> Processing...</>
          ) : status?.running ? (
            <><Square size={20} /> Stop Listener</>
          ) : (
            <><Play size={20} fill="currentColor" /> Start Listener</>
          )}
        </button>

        <div className="status-indicator-wrapper">
          <div className={`pulse-dot ${status?.running ? 'running' : 'stopped'}`}></div>
          <div className="status-info">
            <span className="status-label">{status?.running ? 'Running' : 'Stopped'}</span>
            <span className="last-poll">Last poll: {status?.last_poll_time || 'Never'}</span>
          </div>
        </div>

        <div className="interval-selector">
          <label>POLLING INTERVAL</label>
          <div className="select-wrapper">
            <select 
              value={settings?.poll_interval || 30}
              onChange={async (e) => {
                const val = parseInt(e.target.value);
                try {
                  await SettingsAPI.updateSettings({ poll_interval: val });
                  setSettings(prev => ({ ...prev, poll_interval: val }));
                } catch (err) {
                  console.error("Interval update error:", err);
                }
              }}
            >
              <option value={30}>30 seconds</option>
              <option value={60}>1 minute</option>
              <option value={300}>5 minutes</option>
            </select>
            <Clock size={16} className="select-icon" />
          </div>
        </div>
      </div>

      <section className="settings-section">
        <div className="section-header">
          <h3>Connection Health</h3>
          <button 
            className={`refresh-btn ${checkingHealth ? 'spinning' : ''}`}
            onClick={checkHealth}
            disabled={checkingHealth}
          >
            <RefreshCcw size={16} />
          </button>
        </div>
        
        <div className="health-grid">
          <HealthCard 
            title="Azure AD Auth" 
            icon={Key} 
            status={getServiceHealth("Azure AD Auth")} 
          />
          <HealthCard 
            title="ADF SDK" 
            icon={Cloud} 
            status={getServiceHealth("ADF SDK")} 
          />
          <HealthCard 
            title="SQL Server" 
            icon={Database} 
            status={getServiceHealth("SQL Server")} 
          />
          <HealthCard 
            title="ChromaDB" 
            icon={Cpu} 
            status={getServiceHealth("ChromaDB")} 
          />
          <HealthCard 
            title="LLM API (Claude)" 
            icon={Activity} 
            status={getServiceHealth("LLM API")} 
          />
        </div>
      </section>

      <section className="settings-section">
        <div className="section-header">
          <h3>Recent Polls</h3>
          <span className="real-time-badge">{status?.running ? 'LIVE STREAM' : 'PAUSED'}</span>
        </div>
        <div className="card logs-card">
          <table className="logs-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Service</th>
                <th>Message</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log, idx) => (
                <tr key={idx}>
                  <td className="timestamp">{log.timestamp}</td>
                  <td className="service">{log.service}</td>
                  <td className="message">{log.message}</td>
                  <td>
                    <span className={`log-status ${log.status}`}>
                      {log.status?.toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {logs.length === 0 && <div className="empty-logs">No poll logs yet. Start the listener to begin polling.</div>}
        </div>
      </section>
    </div>
  );
};

const HealthCard = ({ title, icon: Icon, status }) => {
  // Backend uses "connected" / "failed" / "unchecked" — NOT "ok"
  const isConnected = status?.status === 'connected';
  const isUnchecked = !status || status?.status === 'unchecked';
  
  return (
    <div className="card health-card">
      <div className="health-header">
        <div className="icon-bg"><Icon size={18} /></div>
        {isConnected ? (
          <CheckCircle2 size={20} className="status-check ok" />
        ) : (
          <XCircle size={20} className="status-check error" />
        )}
      </div>
      <div className="health-body">
        <h4>{title}</h4>
        <p>
          {isUnchecked 
            ? 'Click refresh to check' 
            : isConnected 
              ? status?.message || 'Connected'
              : status?.message || 'Connection failed'
          }
        </p>
        {status?.latency_ms > 0 && (
          <span className="latency">Latency: {status.latency_ms}ms</span>
        )}
      </div>
    </div>
  );
};

export default Settings;
