import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { AuthLayout } from '@/components/AuthLayout';
import { authApi } from '@/api/auth';

export const ResetPasswordPage: React.FC = () => {
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const reset_token = location.state?.reset_token;

  useEffect(() => {
    if (!reset_token) {
      navigate('/login');
    }
  }, [reset_token, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setIsLoading(true);

    try {
      await authApi.resetPassword({ reset_token, new_password: password });
      setSuccess('Password reset successfully. Redirecting to login...');
      setTimeout(() => {
        navigate('/login');
      }, 2000);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred. Your reset token may have expired.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-form-title">Set new password</h2>
      <p className="auth-form-subtitle">Must be at least 8 characters.</p>

      {error && <div className="auth-form-error">{error}</div>}
      {success && <div className="auth-form-error" style={{ backgroundColor: 'rgba(46, 204, 113, 0.1)', color: 'var(--success)' }}>{success}</div>}

      <form onSubmit={handleSubmit}>
        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="password">New Password</label>
          <input
            id="password"
            type="password"
            className="auth-form-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            placeholder="Enter new password"
          />
        </div>

        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="confirmPassword">Confirm Password</label>
          <input
            id="confirmPassword"
            type="password"
            className="auth-form-input"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            placeholder="Confirm new password"
          />
        </div>

        <button 
          type="submit" 
          className="auth-form-button"
          disabled={isLoading || !password || !confirmPassword || !!success}
        >
          {isLoading ? 'Resetting...' : 'Reset password'}
        </button>
      </form>

      <div className="auth-form-footer">
        <Link to="/login" className="auth-form-link" style={{ fontWeight: 600 }}>Back to log in</Link>
      </div>
    </AuthLayout>
  );
};
