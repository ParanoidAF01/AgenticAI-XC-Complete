import apiClient from './client';
import type {
  Session,
  Message,
  ChatResponse,
  CreateSessionRequest,
  MessageRequest,
  UpdateSessionRequest,
} from '@/types/chat';
import type { ProfileResponse } from '@/types/api';

export const chatApi = {
  // Sessions
  createSession: async (data: CreateSessionRequest): Promise<Session> => {
    const response = await apiClient.post<Session>('/chats', data);
    return response.data;
  },

  getSessions: async (): Promise<Session[]> => {
    const response = await apiClient.get<Session[]>('/chats');
    return response.data;
  },

  getSession: async (sessionId: string): Promise<Session> => {
    const response = await apiClient.get<Session>(`/chats/${sessionId}`);
    return response.data;
  },

  updateSession: async (sessionId: string, data: UpdateSessionRequest): Promise<Session> => {
    const response = await apiClient.patch<Session>(`/chats/${sessionId}`, data);
    return response.data;
  },

  deleteSession: async (sessionId: string): Promise<void> => {
    await apiClient.delete(`/chats/${sessionId}`);
  },

  // Messages
  getMessages: async (sessionId: string): Promise<Message[]> => {
    const response = await apiClient.get<Message[]>(`/chats/${sessionId}/messages`);
    return response.data;
  },

  sendMessage: async (data: MessageRequest): Promise<ChatResponse> => {
    const { session_id, content } = data;
    const response = await apiClient.post<ChatResponse>(
      `/chats/${session_id}/messages`,
      { content }
    );
    return response.data;
  },

  // Profiles
  getProfiles: async (): Promise<ProfileResponse[]> => {
    const response = await apiClient.get<ProfileResponse[]>('/profiles');
    return response.data;
  },
};
