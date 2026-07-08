import React from 'react';
import './AuthLayout.css';

interface AuthLayoutProps {
  children: React.ReactNode;
}

export const AuthLayout: React.FC<AuthLayoutProps> = ({ children }) => {
  return (
    <div className="auth-layout-container">
      <div className="auth-layout-left">
        <div className="auth-layout-left-content">
          <div className="auth-layout-logo">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="currentColor"/>
              <path d="M2 17L12 22L22 17" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M2 12L12 17L22 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span>Ontology</span>
          </div>
          <h1 className="auth-layout-headline">Master your data topology.</h1>
          <p className="auth-layout-subheadline">
            Connect your databases, define your ontology, and chat with your data in natural language.
          </p>
        </div>
      </div>
      <div className="auth-layout-right">
        <div className="auth-form-wrapper">
          {children}
        </div>
      </div>
    </div>
  );
};
