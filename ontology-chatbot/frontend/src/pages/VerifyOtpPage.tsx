import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { AuthLayout } from '@/components/AuthLayout';
import { authApi } from '@/api/auth';

export const VerifyOtpPage: React.FC = () => {
  const [otp, setOtp] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const email = location.state?.email;

  useEffect(() => {
    if (!email) {
      navigate('/forgot-password');
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
      const { reset_token } = await authApi.verifyResetOtp({ email, otp });
      navigate('/reset-password', { state: { reset_token } });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Invalid verification code.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <h2 className="auth-form-title">Enter reset code</h2>
      <p className="auth-form-subtitle">
        We've sent a 6-digit code to <strong style={{color: 'var(--figma-text-dark)'}}>{email}</strong>.
      </p>

      {error && <div className="auth-form-error">{error}</div>}

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
          disabled={isLoading || otp.length !== 6}
        >
          {isLoading ? 'Verifying...' : 'Verify Code'}
        </button>
      </form>

      <div className="auth-form-footer">
        Didn't receive the email? <Link to="/forgot-password" className="auth-form-link">Try again</Link>
      </div>
    </AuthLayout>
  );
};
