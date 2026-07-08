import apiClient from './client';
import type { 
  LoginRequest, 
  SignupRequest, 
  SignupVerifyRequest,
  ForgotPasswordRequest,
  VerifyOtpRequest,
  ResetPasswordRequest,
  ChangePasswordRequest,
  UpdateProfileRequest,
  TokenResponse, 
  User 
} from '@/types/auth';

export const authApi = {
  login: async (data: LoginRequest): Promise<TokenResponse> => {
    const response = await apiClient.post<TokenResponse>('/auth/login', data);
    return response.data;
  },

  requestSignup: async (data: SignupRequest): Promise<{message: string}> => {
    const response = await apiClient.post<{message: string}>('/auth/signup/request', data);
    return response.data;
  },

  verifySignup: async (data: SignupVerifyRequest): Promise<User> => {
    const response = await apiClient.post<User>('/auth/signup/verify', data);
    return response.data;
  },

  refresh: async (refreshToken: string): Promise<TokenResponse> => {
    const response = await apiClient.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken });
    return response.data;
  },

  logout: async (refreshToken: string): Promise<void> => {
    await apiClient.post('/auth/logout', { refresh_token: refreshToken });
  },

  forgotPassword: async (data: ForgotPasswordRequest): Promise<{message: string}> => {
    const response = await apiClient.post<{message: string}>('/auth/forgot-password', data);
    return response.data;
  },

  verifyResetOtp: async (data: VerifyOtpRequest): Promise<{reset_token: string}> => {
    const response = await apiClient.post<{reset_token: string}>('/auth/verify-reset-otp', data);
    return response.data;
  },

  resetPassword: async (data: ResetPasswordRequest): Promise<{message: string}> => {
    const response = await apiClient.post<{message: string}>('/auth/reset-password', data);
    return response.data;
  },

  changePassword: async (data: ChangePasswordRequest): Promise<{message: string}> => {
    const response = await apiClient.post<{message: string}>('/auth/change-password', data);
    return response.data;
  },

  getMe: async (): Promise<User> => {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  },

  updateProfile: async (data: UpdateProfileRequest): Promise<User> => {
    const response = await apiClient.patch<User>('/auth/me', data);
    return response.data;
  },

  deleteAccount: async (): Promise<void> => {
    await apiClient.delete('/auth/me');
  }
};
