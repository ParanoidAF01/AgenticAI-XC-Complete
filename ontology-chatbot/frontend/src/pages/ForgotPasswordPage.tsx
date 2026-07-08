import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { AuthLayout } from '@/components/AuthLayout';
import { authApi } from '@/api/auth';

export const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await authApi.forgotPassword({ email });
      navigate('/verify-reset-otp', { state: { email } });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-form-title">Forgot Password</h2>
      <p className="auth-form-subtitle">Enter your email address and we'll send you a link to reset your password.</p>

      {error && <div className="auth-form-error">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            className="auth-form-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="Enter your email"
          />
        </div>

        <button 
          type="submit" 
          className="auth-form-button"
          disabled={isLoading || !email}
        >
          {isLoading ? 'Sending...' : 'Send reset code'}
        </button>
      </form>

      <div className="auth-form-footer">
        Remember your password? <Link to="/login" className="auth-form-link" style={{ fontWeight: 600 }}>Sign in</Link>
      </div>
    </AuthLayout>
  );
};
