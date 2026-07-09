import React, { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { authApi } from '@/api/auth';

export const DeleteAccountPage: React.FC = () => {
  const { logout } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleDelete = async () => {
    if (window.confirm('WARNING: This action is irreversible. All your data will be permanently deleted. Are you sure you want to delete your account?')) {
      try {
        setLoading(true);
        await authApi.deleteAccount();
        logout(); // clear tokens and redirect to login
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Failed to delete account');
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div className="settings-section">
      <h3 style={{ color: '#ff4d4f' }}>Delete Account</h3>
      <p style={{ marginBottom: '24px', color: 'var(--figma-text-subtle)' }}>
        Once you delete your account, there is no going back. Please be certain.
      </p>
      
      {error && <div className="error-message" style={{ marginBottom: '16px' }}>{error}</div>}

      <button 
        onClick={handleDelete} 
        disabled={loading}
        style={{ 
          padding: '12px 24px', 
          backgroundColor: '#ff4d4f', 
          color: '#fff', 
          border: 'none', 
          borderRadius: '4px', 
          fontWeight: 500,
          cursor: loading ? 'not-allowed' : 'pointer',
          opacity: loading ? 0.7 : 1
        }}
      >
        {loading ? 'Deleting...' : 'Delete My Account'}
      </button>
    </div>
  );
};
