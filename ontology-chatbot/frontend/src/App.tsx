import { Routes, Route, Navigate } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { SignupPage } from './pages/SignupPage';
import { SignupVerifyPage } from './pages/SignupVerifyPage';
import { ForgotPasswordPage } from './pages/ForgotPasswordPage';
import { VerifyOtpPage } from './pages/VerifyOtpPage';
import { ResetPasswordPage } from './pages/ResetPasswordPage';
import ChatPage from './pages/ChatPage';
import ProtectedRoute from './components/ProtectedRoute';

// Settings
import { SettingsLayout } from './pages/Settings/SettingsLayout';
import { ProfileSettingsPage } from './pages/Settings/ProfileSettingsPage';
import { ChangePasswordPage } from './pages/Settings/ChangePasswordPage';
import { LogoutPage } from './pages/Settings/LogoutPage';
import { DeleteAccountPage } from './pages/Settings/DeleteAccountPage';

function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <ChatPage />
          </ProtectedRoute>
        }
      />
      
      {/* Settings Routes */}
      <Route path="/settings" element={<ProtectedRoute><SettingsLayout /></ProtectedRoute>}>
        <Route index element={<Navigate to="profile" replace />} />
        <Route path="profile" element={<ProfileSettingsPage />} />
        <Route path="security" element={<ChangePasswordPage />} />
        <Route path="logout" element={<LogoutPage />} />
        <Route path="delete-account" element={<DeleteAccountPage />} />
      </Route>

      {/* Auth Routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/signup/verify" element={<SignupVerifyPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/verify-reset-otp" element={<VerifyOtpPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
