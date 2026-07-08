import React, { useState, useEffect } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { authApi } from '@/api/auth';

export const ProfileSettingsPage: React.FC = () => {
  const { user } = useAuth();
  const [displayName, setDisplayName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (user) {
      setDisplayName(user.display_name || '');
    }
  }, [user]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setMessage('');
    setIsLoading(true);

    try {
      await authApi.updateProfile({ display_name: displayName });
      setMessage('Profile updated successfully.');
      // Ideally update the user object in the auth store here
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update profile.');
    } finally {
      setIsLoading(false);
    }
  };

  if (!user) return null;

  return (
    <div>
      <h3 className="settings-page-title">Profile Settings</h3>
      <p className="settings-page-subtitle">Manage your personal information.</p>

      <div className="settings-card">
        {message && <div style={{ color: 'var(--success)', marginBottom: '16px' }}>{message}</div>}
        {error && <div style={{ color: 'var(--error)', marginBottom: '16px' }}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="settings-form-group">
            <label className="settings-form-label">Email Address (Cannot be changed)</label>
            <div style={{ position: 'relative' }}>
              <input 
                type="email" 
                className="settings-form-input" 
                value={user.email} 
                disabled 
              />
              <svg 
                width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--figma-text-subtle)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                style={{ position: 'absolute', right: '12px', top: '12px' }}
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
            </div>
          </div>

          <div className="settings-form-group">
            <label className="settings-form-label" htmlFor="displayName">Username / Display Name</label>
            <input 
              id="displayName"
              type="text" 
              className="settings-form-input" 
              value={displayName} 
              onChange={(e) => setDisplayName(e.target.value)} 
              required
            />
          </div>

          <button type="submit" className="settings-btn-primary" disabled={isLoading || displayName === user.display_name}>
            {isLoading ? 'Saving...' : 'Save Changes'}
          </button>
        </form>
      </div>
    </div>
  );
};
