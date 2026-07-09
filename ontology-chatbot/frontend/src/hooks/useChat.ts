import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { chatApi } from '@/api/chat';
import type { CreateSessionRequest, MessageRequest } from '@/types/chat';

// ─── Sessions ───────────────────────────────────────────────

export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: chatApi.getSessions,
    staleTime: 30_000,
  });
}

export function useSession(sessionId: string | null) {
  return useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => chatApi.getSession(sessionId!),
    enabled: !!sessionId,
  });
}

export function useCreateSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateSessionRequest) => chatApi.createSession(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
  });
}

export function useDeleteSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (sessionId: string) => chatApi.deleteSession(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
  });
}

// ─── Messages ───────────────────────────────────────────────

export function useMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ['messages', sessionId],
    queryFn: () => chatApi.getMessages(sessionId!),
    enabled: !!sessionId,
    refetchOnWindowFocus: false,
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: MessageRequest) => chatApi.sendMessage(data),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: ['messages', variables.session_id] });
      const previousMessages = queryClient.getQueryData(['messages', variables.session_id]);
      
      queryClient.setQueryData(['messages', variables.session_id], (old: any) => {
        const optimisticMsg = {
          id: 'optimistic-' + Date.now(),
          session_id: variables.session_id,
          role: 'user',
          content: variables.content,
          created_at: new Date().toISOString(),
        };
        return old ? [...old, optimisticMsg] : [optimisticMsg];
      });

      return { previousMessages };
    },
    onError: (_err, variables, context) => {
      if (context?.previousMessages) {
        queryClient.setQueryData(['messages', variables.session_id], context.previousMessages);
      }
    },
    onSuccess: (_response, variables) => {
      queryClient.invalidateQueries({ queryKey: ['messages', variables.session_id] });
      queryClient.invalidateQueries({ queryKey: ['sessions'] });
    },
  });
}

// ─── Profiles ───────────────────────────────────────────────

export function useProfiles() {
  return useQuery({
    queryKey: ['profiles'],
    queryFn: chatApi.getProfiles,
    staleTime: 5 * 60_000, // 5 minutes
  });
}
