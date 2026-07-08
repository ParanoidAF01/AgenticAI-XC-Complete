import React from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import './Settings.css';

export const SettingsLayout: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="settings-container">
      {/* Top Header */}
      <div className="settings-header">
        <button className="settings-back-btn" onClick={() => navigate('/')}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="19" y1="12" x2="5" y2="12"></line>
            <polyline points="12 19 5 12 12 5"></polyline>
          </svg>
        </button>
        <h2>Settings</h2>
      </div>

      <div className="settings-content">
        {/* Sidebar */}
        <aside className="settings-sidebar">
          <nav className="settings-nav">
            <NavLink to="/settings/profile" className={({isActive}) => isActive ? "settings-nav-item active" : "settings-nav-item"}>
              Profile
            </NavLink>
            <NavLink to="/settings/security" className={({isActive}) => isActive ? "settings-nav-item active" : "settings-nav-item"}>
              Security
            </NavLink>
          </nav>
        </aside>

        {/* Main Content Area */}
        <main className="settings-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
