import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authApi } from '@/api/auth';
import { useAuth } from '@/hooks/useAuth';

export const ChangePasswordPage: React.FC = () => {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const { logout } = useAuth();
  const navigate = useNavigate();

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

  const handleDeleteAccount = async () => {
    try {
      await authApi.deleteAccount();
      // Clearing local auth state
      logout();
      navigate('/signup');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete account.');
      setShowDeleteConfirm(false);
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

      <div className="settings-card" style={{ borderColor: 'rgba(231, 76, 60, 0.3)' }}>
        <h4 style={{ marginBottom: '8px', fontSize: '18px', color: 'var(--error)' }}>Danger Zone</h4>
        <p style={{ fontSize: '14px', color: 'var(--figma-text-subtle)', marginBottom: '16px' }}>
          Once you delete your account, there is no going back. Please be certain.
        </p>

        {!showDeleteConfirm ? (
          <button className="settings-btn-danger" onClick={() => setShowDeleteConfirm(true)}>
            Delete Account
          </button>
        ) : (
          <div style={{ padding: '16px', backgroundColor: 'rgba(231, 76, 60, 0.1)', borderRadius: '8px' }}>
            <p style={{ marginBottom: '16px', fontWeight: 500 }}>Are you absolutely sure you want to delete your account? This action cannot be undone.</p>
            <div style={{ display: 'flex', gap: '12px' }}>
              <button className="settings-btn-danger" style={{ backgroundColor: 'var(--error)', color: '#fff' }} onClick={handleDeleteAccount}>
                Yes, delete my account
              </button>
              <button className="settings-btn-primary" style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--figma-text-white)' }} onClick={() => setShowDeleteConfirm(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
