import { useState, useEffect, useRef } from 'react';
import { Bell, Moon, Sun, User, Menu, Check, ChevronDown, Loader2 } from 'lucide-react';
import { useDataSource } from '../context/DataSourceContext';
import { ListenerAPI } from '../services/api';
import './TopBar.css';

const SOURCE_OPTIONS = [
  { value: 'sql', label: 'SQL Listener' },
  { value: 'adf', label: 'ADF Listener' },
];

const TopBar = ({ title, isDarkMode, toggleDarkMode, isSidebarCollapsed, setIsSidebarCollapsed }) => {
  const { dataSource, setDataSource } = useDataSource();
  const [pendingSource, setPendingSource] = useState(dataSource);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [listenerStatus, setListenerStatus] = useState(null);
  const dropdownRef = useRef(null);

  const hasChange = pendingSource !== dataSource;

  // Fetch listener status on mount + poll
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await ListenerAPI.getStatus();
        setListenerStatus(res);
      } catch { /* ignore */ }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 15000);
    return () => clearInterval(interval);
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleConfirm = () => {
    setSwitching(true);
    // Brief animation delay so the user sees the transition
    setTimeout(() => {
      setDataSource(pendingSource);
      setSwitching(false);
      setDropdownOpen(false);
    }, 600);
  };

  const currentLabel = SOURCE_OPTIONS.find(o => o.value === dataSource)?.label || 'SQL Listener';
  const isRunning = listenerStatus?.running;

  return (
    <header className="topbar">
      <div className="topbar-left">
        {isSidebarCollapsed && (
          <button 
            className="sidebar-toggle-topbar" 
            onClick={() => setIsSidebarCollapsed(false)}
            title="Expand Sidebar"
          >
            <Menu size={18} />
          </button>
        )}
        <h2 className="page-title">{title}</h2>

        {/* Data Source Selector */}
        <div className="source-selector" ref={dropdownRef}>
          <button 
            className={`source-trigger ${dropdownOpen ? 'active' : ''}`}
            onClick={() => setDropdownOpen(!dropdownOpen)}
          >
            <span className={`listener-dot ${isRunning ? 'running' : 'stopped'}`} />
            <span className="source-label">{currentLabel}</span>
            {isRunning && <span className="source-status">• Running</span>}
            <ChevronDown size={14} className={`source-chevron ${dropdownOpen ? 'rotated' : ''}`} />
          </button>

          {dropdownOpen && (
            <div className="source-dropdown">
              <div className="source-dropdown-header">Data Source</div>
              {SOURCE_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  className={`source-option ${pendingSource === opt.value ? 'selected' : ''} ${dataSource === opt.value ? 'current' : ''}`}
                  onClick={() => setPendingSource(opt.value)}
                >
                  <span className="option-radio">
                    {pendingSource === opt.value && <span className="option-radio-inner" />}
                  </span>
                  <span className="option-label">{opt.label}</span>
                  {dataSource === opt.value && <span className="option-badge">Active</span>}
                </button>
              ))}
              {hasChange && (
                <button
                  className={`source-confirm ${switching ? 'loading' : ''}`}
                  onClick={handleConfirm}
                  disabled={switching}
                >
                  {switching ? (
                    <>
                      <Loader2 size={14} className="spin" />
                      Switching…
                    </>
                  ) : (
                    <>
                      <Check size={14} />
                      Apply
                    </>
                  )}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
      
      <div className="topbar-right">
        <div className="topbar-actions">
          <button className="icon-btn"><Bell size={18} /></button>
          <button className="icon-btn" onClick={toggleDarkMode}>
            {isDarkMode ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
        <div className="user-profile">
          <div className="avatar">
            <User size={18} />
          </div>
          <div className="user-info">
            <span className="user-name">Admin User</span>
            <span className="user-email">admin@company.com</span>
          </div>
        </div>
      </div>
    </header>
  );
};

export default TopBar;
