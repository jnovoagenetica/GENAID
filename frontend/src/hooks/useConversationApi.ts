// --- CÓDIGO COMPLETO Y FINAL PARA src/hooks/useConversationApi.ts (AJUSTADO A TUS TIPOS) ---

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

    // /-------------------------------------------------------------------\
    // |    INICIO DE LA FUNCIÓN postMessage CORREGIDA PARA TUS TIPOS    |
    // \-------------------------------------------------------------------/
    postMessage: (input: PostMessageRequest, files?: File[]) => {
      const formData = new FormData();

      // 1. Añadimos el mensaje del usuario (campo obligatorio).
      // Según tu 'conversation.d.ts', el texto está en input.message.content[0].body
      // Añadimos una comprobación de seguridad para evitar errores si el array está vacío.
      const messageText = input.message.content.length > 0 ? input.message.content[0].body : '';
      // El backend espera una clave llamada 'message' (en minúsculas)
      formData.append('message', messageText);

      // 2. Añadimos conversation_id si existe.
      // Tu tipo usa 'conversationId' (camelCase), pero el backend espera 'conversation_id' (snake_case).
      // Aquí hacemos la "traducción".
      if (input.conversationId) {
        formData.append('conversation_id', input.conversationId);
      }

      // 3. Añadimos bot_id si existe.
      // Tu tipo usa 'botId' (camelCase), pero el backend espera 'bot_id' (snake_case).
      if (input.botId) {
        formData.append('bot_id', input.botId);
      }
      
      // 4. Añadimos el archivo si se proporcionó uno.
      // El backend espera la clave 'file'.
      if (files && files.length > 0) {
        formData.append('file', files[0]);
      }
      
      // Hacemos la petición POST con el FormData correctamente construido.
      return http.post<PostMessageResponse>('conversation', formData);
    },
    // /-------------------------------------------------------------------\
    // |      FIN DE LA FUNCIÓN postMessage CORREGIDA PARA TUS TIPOS     |
    // \-------------------------------------------------------------------/

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