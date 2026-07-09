import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { AuthLayout } from '@/components/AuthLayout';

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const { login, isAuthenticated, isInitialized } = useAuth();

  useEffect(() => {
    if (isInitialized && isAuthenticated) {
      navigate('/');
    }
  }, [isInitialized, isAuthenticated, navigate]);

  if (!isInitialized) {
    return (
      <div style={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: 'var(--text-secondary)' }}>Loading...</div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      await login({ email, password });
      navigate('/');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Invalid username/email or password.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-form-title">Sign In</h2>
      <p className="auth-form-subtitle">Welcome back! Please enter your details.</p>

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

        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            className="auth-form-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            placeholder="Enter your password"
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '16px' }}>
          <Link to="/forgot-password" className="auth-form-link">Forgot password?</Link>
        </div>

        <button 
          type="submit" 
          className="auth-form-button"
          disabled={isLoading || !email || !password}
        >
          {isLoading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>

      <div className="auth-form-footer">
        New user? <Link to="/signup" className="auth-form-link" style={{ fontWeight: 600 }}>Sign up</Link>
      </div>
    </AuthLayout>
  );
};
