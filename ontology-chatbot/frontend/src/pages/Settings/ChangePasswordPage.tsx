import React, { useState } from 'react';
import { authApi } from '@/api/auth';

export const ChangePasswordPage: React.FC = () => {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');



  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setMessage('');

    if (newPassword !== confirmPassword) {
      setError('New passwords do not match.');
      return;
    }

    setIsLoading(true);

    try {
      await authApi.changePassword({ current_password: currentPassword, new_password: newPassword });
      setMessage('Password changed successfully.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to change password.');
    } finally {
      setIsLoading(false);
    }
  };



  return (
    <div>
      <h3 className="settings-page-title">Security Settings</h3>
      <p className="settings-page-subtitle">Update your password and manage your account security.</p>

      <div className="settings-card" style={{ marginBottom: '32px' }}>
        <h4 style={{ marginBottom: '16px', fontSize: '18px' }}>Change Password</h4>
        {message && <div style={{ color: 'var(--success)', marginBottom: '16px' }}>{message}</div>}
        {error && <div style={{ color: 'var(--error)', marginBottom: '16px' }}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="settings-form-group">
            <label className="settings-form-label" htmlFor="currentPassword">Current Password</label>
            <input 
              id="currentPassword"
              type="password" 
              className="settings-form-input" 
              value={currentPassword} 
              onChange={(e) => setCurrentPassword(e.target.value)} 
              required
            />
          </div>

          <div className="settings-form-group">
            <label className="settings-form-label" htmlFor="newPassword">New Password</label>
            <input 
              id="newPassword"
              type="password" 
              className="settings-form-input" 
              value={newPassword} 
              onChange={(e) => setNewPassword(e.target.value)} 
              required
              minLength={8}
            />
          </div>

          <div className="settings-form-group">
            <label className="settings-form-label" htmlFor="confirmPassword">Confirm New Password</label>
            <input 
              id="confirmPassword"
              type="password" 
              className="settings-form-input" 
              value={confirmPassword} 
              onChange={(e) => setConfirmPassword(e.target.value)} 
              required
              minLength={8}
            />
          </div>

          <button type="submit" className="settings-btn-primary" disabled={isLoading || !currentPassword || !newPassword || !confirmPassword}>
            {isLoading ? 'Updating...' : 'Update Password'}
          </button>
        </form>
      </div>
    </div>
  );
};
