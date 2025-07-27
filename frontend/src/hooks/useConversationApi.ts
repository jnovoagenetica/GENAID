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

    // --- FUNCIÓN CORREGIDA ---
    postMessage: (input: PostMessageRequest & { files?: File[] }) => {
      // CAMBIO 1: La condición ahora busca 'files' en lugar de 'pdfFiles'.
      // Esto permite que CUALQUIER tipo de archivo (PDF, imagen, etc.)
      // active la lógica de subida.
      if (input.files && input.files.length > 0) {
        const formData = new FormData();

        // CAMBIO 2 (Mejora): Encontrar el contenido de texto de forma segura.
        // En lugar de asumir que está en la posición [0], lo buscamos por su 'contentType'.
        const textContent = input.message.content.find(c => c.contentType === 'text')?.body ?? '';
        formData.append('message', textContent);

        if (input.conversationId) {
          formData.append('conversation_id', input.conversationId);
        }

        if (input.botId) {
          formData.append('bot_id', input.botId);
        }
        
        // --- INICIO DE LA MODIFICACIÓN CLAVE ---
        // El backend fallaba porque faltaban estos campos. Ahora los añadimos al formulario.
        if (input.message.parentMessageId) {
          formData.append('parent_message_id', input.message.parentMessageId);
        }
        if (input.message.model) {
          formData.append('model', input.message.model);
        }
        // --- FIN DE LA MODIFICACIÓN CLAVE ---

        // CAMBIO 3: Se ha eliminado la comprobación que lanzaba un error si el archivo no era PDF.
        // if (input.pdfFiles[0].type !== 'application/pdf') { ... } // <- ESTO SE FUE

        // CAMBIO 4: Se adjunta el primer archivo de la lista 'files'.
        // Nota: Tu backend actual acepta un solo archivo. Si necesitaras subir varios,
        // tendrías que modificar el backend y hacer un bucle aquí.
        formData.append('file', input.files[0]);

        // Se llama al endpoint de subida con el FormData.
        return http.post<PostMessageResponse>('conversation/upload', formData);
      }

      // Fallback si no hay archivos. La lógica sigue igual.
      return http.post<PostMessageResponse>('conversation', input);
    },
    // --- FIN DE LA FUNCIÓN CORREGIDA ---

    getRelatedDocuments: (input: GetRelatedDocumentsRequest) => {
      return http.post<GetRelatedDocumentsResponse>(
        'conversation/related-documents',
        input
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