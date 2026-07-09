import React from 'react';
import { useAuth } from '@/hooks/useAuth';

export const LogoutPage: React.FC = () => {
  const { logout } = useAuth();

  const handleLogout = () => {
    if (window.confirm('Are you sure you want to sign out?')) {
      logout();
    }
  };

  return (
    <div className="settings-section">
      <h3>Logout</h3>
      <p style={{ marginBottom: '24px', color: 'var(--figma-text-subtle)' }}>
        Sign out of your account on this device.
      </p>
      <button 
        onClick={handleLogout} 
        style={{ 
          padding: '12px 24px', 
          backgroundColor: '#ff4d4f', 
          color: '#fff', 
          border: 'none', 
          borderRadius: '4px', 
          fontWeight: 500,
          cursor: 'pointer' 
        }}
      >
        Log Out
      </button>
    </div>
  );
};
