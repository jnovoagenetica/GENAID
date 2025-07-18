// src/hooks/useConversationApi.ts

import { MutatorCallback, useSWRConfig } from 'swr';
import {
  Conversation,
  ConversationMeta,
  GetRelatedDocumentsRequest,
  GetRelatedDocumentsResponse,
  PostMessageRequest,
  PostMessageResponse,
} from '../@types/conversation';
import useHttp from './useHttp';

const useConversationApi = () => {
  const http = useHttp();
  const { mutate } = useSWRConfig();

  const updateTitle = (conversationId: string, title: string) => {
    return http.patch(`conversation/${conversationId}/title`, {
      newTitle: title,
    });
  };

  return {
    getConversations: () => {
      return http.get<ConversationMeta[]>('conversations', {
        keepPreviousData: true,
      });
    },
    getConversation: (conversationId?: string) => {
      return http.get<Conversation>(
        !conversationId ? null : `conversation/${conversationId}`,
        {
          keepPreviousData: true,
        }
      );
    },

    // --- MODIFICACIÓN PRINCIPAL ---
    postMessage: (input: PostMessageRequest, files?: File[]) => {
      // Si hay archivos, debemos usar FormData.
      if (files && files.length > 0) {
        const formData = new FormData();
        
        // El backend necesitará parsear este string 'request' a un objeto JSON
        formData.append('request', JSON.stringify(input));
        
        // Adjuntamos cada archivo
        files.forEach(file => {
          // El nombre 'files' debe coincidir con lo que espera tu backend
          formData.append('files', file, file.name); 
        });
        
        // Usamos el http.post pero con el FormData.
        // El navegador establecerá el 'Content-Type' a 'multipart/form-data' automáticamente.
        return http.post<PostMessageResponse>('conversation', formData);
      } else {
        // Si no hay archivos, el comportamiento es el mismo de antes (enviar JSON).
        return http.post<PostMessageResponse>('conversation', {
          ...input,
        });
      }
    },
    // ---------------------------------

    getRelatedDocuments: (input: GetRelatedDocumentsRequest) => {
      return http.post<GetRelatedDocumentsResponse>(
        'conversation/related-documents',
        {
          ...input,
        }
      );
    },
    deleteConversation: (conversationId: string) => {
      return http.delete(`conversation/${conversationId}`);
    },
    clearConversations: () => {
      return http.delete('conversations');
    },
    updateTitle,
    updateTitleWithGeneratedTitle: async (conversationId: string) => {
      const res = await http.getOnce<{
        title: string;
      }>(`conversation/${conversationId}/proposed-title`);
      return updateTitle(conversationId, res.data.title);
    },
    mutateConversations: (
      conversations?:
        | ConversationMeta[]
        | Promise<ConversationMeta[]>
        | MutatorCallback<ConversationMeta[]>,
      options?: Parameters<typeof mutate>[2]
    ) => {
      return mutate('conversations', conversations, options);
    },
  };
};

export default useConversationApi;