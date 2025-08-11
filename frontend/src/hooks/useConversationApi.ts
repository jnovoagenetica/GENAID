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

    // postMessage se encarga de enviar un mensaje al backend.
    // Redirige al endpoint correcto según si hay archivos o no.
    postMessage: async (input: PostMessageRequest) => {
      alert("✅ Ejecutando useConversationApi.postMessage");
      console.log('[🔥] postMessage() ejecutándose'); 
      console.log('[useConversationApi] postMessage ejecutado');
      // Si el input incluye archivos PDF (o cualquier otro tipo), usa FormData y el endpoint /conversation
      if (input.files && input.files.length > 0) {
        const formData = new FormData();

        formData.append('conversation_id', input.conversationId || '');
        formData.append('message', JSON.stringify(input.message));
        formData.append('bot_id', input.botId || '');
        input.files.forEach((file) => formData.append('files', file));

        console.log(
          '[useConversationApi → postMessage] Enviando mensaje con archivos (FormData) a /conversation'
        );
        console.log(
          '[useConversationApi → postMessage] Conversación ID:',
          input.conversationId
        );
        console.log('[useConversationApi → postMessage] Bot ID:', input.botId);

        // Ver todo lo que hay en el FormData para depuración
        for (let [key, value] of formData.entries()) {
          if (value instanceof File) {
            console.log(
              `[useConversationApi → postMessage] FormData → key="${key}", archivo=`,
              {
                name: value.name,
                size: value.size,
                type: value.type,
              }
            );
          } else {
            console.log(
              `[useConversationApi → postMessage] FormData → key="${key}", valor="${value}"`
            );
          }
        }

        // Se envía como POST con FormData, con manejo de errores
        try {
          return await http.post<PostMessageResponse>(
            'conversation',
            formData
          );
        } catch (err) {
          console.error(
            '[useConversationApi → postMessage] ❌ Error al enviar FormData a /conversation:',
            err
          );
          throw err; // Re-lanzamos el error para que sea manejado por el caller (useChat)
        }
      }

      // --- INICIO DEL BLOQUE CORREGIDO Y CON LOGS AÑADIDOS ---
      // Si NO hay archivos, se envía como JSON tradicional al endpoint /conversation/json
      const payload = {
        ...input,
        files: input.files ?? [],
      };

      // LOG para trazabilidad completa
      console.log(
        '[useConversationApi → postMessage] Enviando mensaje sin archivos (JSON) a /conversation/json'
      );
      // Logs específicos añadidos
      console.log(
        '[useConversationApi → postMessage] Payload JSON → texto:',
        input.message
      );
      console.log(
        '[useConversationApi → postMessage] Payload JSON → imágenes base64:',
        {
          total:
            input.message.content.filter((c) => c.contentType === 'image')
              .length || 0,
          muestras: input.message.content
            .filter((c) => c.contentType === 'image')
            .map(
              (img, i) => `Imagen ${i + 1}: ${img.body.slice(0, 60)}...`
            ),
        }
      );

      try {
        return await http.post<PostMessageResponse>(
          'conversation/json',
          payload
        );
      } catch (err) {
        console.error(
          '[useConversationApi → postMessage] ❌ Error al enviar mensaje JSON a /conversation/json:',
          err
        );
        throw err; // Re-lanzamos el error
      }
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