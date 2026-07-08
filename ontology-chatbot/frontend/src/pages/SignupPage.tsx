import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { AuthLayout } from '@/components/AuthLayout';
import { authApi } from '@/api/auth';

export const SignupPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setIsLoading(true);

    try {
      await authApi.requestSignup({
        email,
        password,
        display_name: username
      });
      // Redirect to OTP verification page, pass email in state
      navigate('/signup/verify', { state: { email } });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred during signup.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-form-title">Create Account</h2>
      <p className="auth-form-subtitle">Get started by creating your account.</p>

      {error && <div className="auth-form-error">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="username">Username</label>
          <input
            id="username"
            type="text"
            className="auth-form-input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            placeholder="Enter a username"
          />
        </div>

        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="email">Email address</label>
          <input
            id="email"
            type="email"
            className="auth-form-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            placeholder="Enter your email address"
          />
        </div>

        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            className="auth-form-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            placeholder="Create a password (min 8 characters)"
          />
        </div>

        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="confirmPassword">Confirm password</label>
          <input
            id="confirmPassword"
            type="password"
            className="auth-form-input"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            placeholder="Confirm your password"
          />
        </div>

        <button 
          type="submit" 
          className="auth-form-button"
          disabled={isLoading || !email || !password || !confirmPassword}
        >
          {isLoading ? 'Processing...' : 'Create account'}
        </button>
      </form>

      <div className="auth-form-footer">
        Already have an account? <Link to="/login" className="auth-form-link" style={{ fontWeight: 600 }}>Sign in</Link>
      </div>
    </AuthLayout>
  );
};
