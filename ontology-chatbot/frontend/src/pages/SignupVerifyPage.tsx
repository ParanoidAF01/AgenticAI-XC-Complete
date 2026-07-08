import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { AuthLayout } from '@/components/AuthLayout';
import { authApi } from '@/api/auth';
// Removed useAuth import as it is no longer needed

export const SignupVerifyPage: React.FC = () => {
  const [otp, setOtp] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  // Removed unused login variable

  const email = location.state?.email;

  useEffect(() => {
    if (!email) {
      navigate('/signup');
    }
  }, [email, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    
    if (otp.length !== 6) {
      setError('Please enter a valid 6-digit code.');
      return;
    }

    setIsLoading(true);

    try {
      await authApi.verifySignup({ email, otp });
      setSuccess('Account created successfully! Redirecting to login...');
      setTimeout(() => {
        navigate('/login');
      }, 2000);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Invalid verification code.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-form-title">Check your email</h2>
      <p className="auth-form-subtitle">
        We've sent a 6-digit verification code to <strong style={{color: 'var(--figma-text-dark)'}}>{email}</strong>. 
        Please enter it below to verify your account.
      </p>

      {error && <div className="auth-form-error">{error}</div>}
      {success && <div className="auth-form-error" style={{ backgroundColor: 'rgba(46, 204, 113, 0.1)', color: 'var(--success)' }}>{success}</div>}

      <form onSubmit={handleSubmit}>
        <div className="auth-form-group">
          <label className="auth-form-label" htmlFor="otp">Verification Code</label>
          <input
            id="otp"
            type="text"
            className="auth-form-input"
            style={{ fontSize: '24px', letterSpacing: '4px', textAlign: 'center' }}
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\\D/g, '').slice(0, 6))}
            required
            placeholder="000000"
            maxLength={6}
          />
        </div>

        <button 
          type="submit" 
          className="auth-form-button"
          disabled={isLoading || otp.length !== 6 || !!success}
        >
          {isLoading ? 'Verifying...' : 'Verify Email'}
        </button>
      </form>

      <div className="auth-form-footer">
        Didn't receive the email? <Link to="/signup" className="auth-form-link">Try again</Link>
      </div>
    </AuthLayout>
  );
};
