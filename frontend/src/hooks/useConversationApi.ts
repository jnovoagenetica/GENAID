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

    // postMessage se encarga de enviar un mensaje al backend,
    // y si el mensaje incluye archivos (como PDF), los envía usando FormData.

    postMessage: (input: PostMessageRequest) => {
      // Si el input incluye archivos PDF (o cualquier otro tipo)
      if (input.files && input.files.length > 0) {
        console.log('Archivos a enviar:', input.files);
        const formData = new FormData();

        // Se añaden los campos individualmente, como espera el backend Form(...)
        // Estos campos son obligatorios y deben ir con nombres específicos,
        // ya que el backend usa Form(...) para recibirlos.

        // ID de la conversación
        formData.append('conversation_id', input.conversationId || '');

        // Contenido del mensaje, convertido a string JSON
        formData.append('message', JSON.stringify(input.message));

        // ID del bot asociado
        formData.append('bot_id', input.botId || '');

        // Adjuntamos todos los archivos (uno o más), con el campo `file`
        input.files.forEach((file) => formData.append('files', file));

        console.log(
          '[useConversationApi] Enviando archivo(s) al backend:',
          input.files.map((f) => ({
            name: f.name,
            size: f.size,
            type: f.type,
          }))
        );

        // ✅ Versión mejorada con logs de depuración
        console.log(
          '[DEBUG FRONT] ➤ Enviando mensaje con archivos (FormData)'
        );
        console.log('[DEBUG FRONT] Conversación ID:', input.conversationId);
        console.log('[DEBUG FRONT] Bot ID:', input.botId);
        console.log('[DEBUG FRONT] Contenido del mensaje:', input.message);
        console.log('[DEBUG FRONT] Archivos a enviar:', input.files);

        // Ver todo lo que hay en el FormData
        for (let [key, value] of formData.entries()) {
          if (value instanceof File) {
            console.log(`[DEBUG FRONT] FormData → key="${key}", archivo=`, {
              name: value.name,
              size: value.size,
              type: value.type,
            });
          } else {
            console.log(`[DEBUG FRONT] FormData → key="${key}", valor="${value}"`);
          }
        }

        // Se envía como POST con FormData al endpoint `/conversation`
        return http.post<PostMessageResponse>('conversation', formData);
      }

      // Si NO hay archivos, se envía como JSON tradicional
      return http.post<PostMessageResponse>('conversation', input);
    },
    // --- FIN DEL BLOQUE CORREGIDO ---

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
      const res = await http.getOnce<{ title: string }>(
        `conversation/${conversationId}/proposed-title`
      );
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