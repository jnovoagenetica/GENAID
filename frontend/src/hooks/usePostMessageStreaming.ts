import { Auth } from 'aws-amplify';
import { PostMessageRequest } from '../@types/conversation';
import { create } from 'zustand';
import i18next from 'i18next';

const WS_ENDPOINT: string = import.meta.env.VITE_APP_WS_ENDPOINT;
const CHUNK_SIZE = 32 * 1024;

const PostStreamingStatus = {
  START: 'START',
  BODY: 'CHUNK',
  END: 'END',
  STREAMING: 'STREAMING',
  STREAMING_END: 'STREAMING_END',
  FETCHING_KNOWLEDGE: 'FETCHING_KNOWLEDGE',
  ERROR: 'ERROR',
};

// Helper: File -> base64 (sin "data:...;base64,")
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const result = String(reader.result || '');
      const b64 = result.includes(',') ? result.split(',')[1] : result; // por si el navegador devuelve dataURL
      resolve(b64);
    };
    reader.readAsDataURL(file);
  });
}

type AttachmentOut = { name: string; mimeType: string; base64: string };

const usePostMessageStreaming = create<{
  post: (params: {
    input: PostMessageRequest & { files?: File[] };
    hasKnowledge?: boolean;
    dispatch: (completion: string) => void;
  }) => Promise<string>;
}>(() => {
  return {
    post: async ({ input, dispatch, hasKnowledge }) => {
      if (hasKnowledge) {
        dispatch(i18next.t('bot.label.retrievingKnowledge'));
      } else {
        dispatch(i18next.t('app.chatWaitingSymbol'));
      }

      const token = (await Auth.currentSession()).getIdToken().getJwtToken();

      const text =
        input.message.content.find((c) => c.contentType === 'text')?.body ?? '';

      // 1) Content para el mensaje (texto + imágenes)
      const contents: any[] = [
        { contentType: 'text', body: text },
        ...input.message.content.filter((c) => c.contentType === 'image'),
      ];

      // 2) Recolectar attachments que ya vengan como "textAttachment" en el content
      const attachmentsFromContent: AttachmentOut[] = input.message.content
        .filter((c) => c.contentType === 'textAttachment' && c.body)
        .map((c: any) => ({
          name: c.fileName || 'archivo.pdf',
          mimeType: c.mimeType || c.mediaType || 'application/pdf',
          base64: c.body, // ya viene en base64
        }));

      // 3) Convertir los File[] entrantes a attachments y, opcionalmente, replicarlos como textAttachment en content
      const attachmentsFromFiles: AttachmentOut[] = [];
      for (const f of input.files ?? []) {
        if (f.type === 'application/pdf') {
          const base64 = await fileToBase64(f);
          attachmentsFromFiles.push({
            name: f.name,
            mimeType: f.type || 'application/pdf',
            base64,
          });

          // Opcional: mantener compatibilidad con flujos antiguos
          contents.push({
            contentType: 'textAttachment',
            body: base64,
            fileName: f.name,
            mimeType: f.type || 'application/pdf',
          });
        }
        // Si luego quieres soportar otros tipos, se agregan aquí.
      }

      const attachments: AttachmentOut[] = [
        ...attachmentsFromContent,
        ...attachmentsFromFiles,
      ];

      // 4) Payload final: incluimos "attachments" a nivel raíz
      const payload: any = {
        ...input,
        message: {
          ...input.message,
          content: contents,
        },
        attachments, // <--- CLAVE para el backend
        token,
      };
      delete payload.files;

      console.log('[STREAMING] Enviando mensaje por WebSocket');
      console.log(
        '[STREAMING] Adjuntos (payload.attachments):',
        attachments.map((a) => ({ name: a.name, mimeType: a.mimeType, size_b64: a.base64.length }))
      );

      const payloadString = JSON.stringify(payload);

      const chunkedPayloads: string[] = [];
      const chunkCount = Math.ceil(payloadString.length / CHUNK_SIZE);

      console.log('[STREAMING] Longitud total del payload:', payloadString.length);
      console.log('[STREAMING] Número de chunks:', chunkCount);

      for (let i = 0; i < chunkCount; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, payloadString.length);
        chunkedPayloads.push(payloadString.substring(start, end));
      }

      let receivedCount = 0;

      return new Promise<string>((resolve, reject) => {
        let completion = '';
        const ws = new WebSocket(WS_ENDPOINT);

        ws.onopen = () => {
          ws.send(JSON.stringify({ step: PostStreamingStatus.START, token }));
        };

        ws.onmessage = (message) => {
          try {
            if (
              message.data === '' ||
              message.data === 'Message sent.' ||
              message.data.startsWith('{"message": "Endpoint request timed out",')
            ) {
              return;
            }

            if (message.data === 'Session started.') {
              chunkedPayloads.forEach((chunk, index) => {
                ws.send(JSON.stringify({ step: PostStreamingStatus.BODY, index, part: chunk }));
              });
              return;
            }

            if (message.data === 'Message part received.') {
              receivedCount++;
              if (receivedCount === chunkedPayloads.length) {
                ws.send(JSON.stringify({ step: PostStreamingStatus.END }));
              }
              return;
            }

            const data = JSON.parse(message.data);

            if (data.status) {
              switch (data.status) {
                case PostStreamingStatus.FETCHING_KNOWLEDGE:
                  dispatch(i18next.t('bot.label.retrievingKnowledge'));
                  break;

                case PostStreamingStatus.STREAMING:
                  if (data.completion || data.completion === '') {
                    if (completion.endsWith(i18next.t('app.chatWaitingSymbol'))) {
                      completion = completion.slice(0, -1);
                    }
                    completion += data.completion + i18next.t('app.chatWaitingSymbol');
                    dispatch(completion);
                  }
                  break;

                case PostStreamingStatus.STREAMING_END:
                  if (completion.endsWith(i18next.t('app.chatWaitingSymbol'))) {
                    completion = completion.slice(0, -1);
                    dispatch(completion);
                  }
                  ws.close();
                  break;

                case PostStreamingStatus.ERROR:
                  ws.close();
                  console.error(data);
                  throw new Error(i18next.t('error.predict.invalidResponse'));

                default:
                  dispatch(i18next.t('app.chatWaitingSymbol'));
              }
            } else {
              ws.close();
              console.error(data);
              throw new Error(i18next.t('error.predict.invalidResponse'));
            }
          } catch (e) {
            console.error(e);
            reject(i18next.t('error.predict.general'));
          }
        };

        ws.onerror = (e) => {
          ws.close();
          console.error(e);
          reject(i18next.t('error.predict.general'));
        };

        ws.onclose = () => {
          resolve(completion);
        };
      });
    },
  };
});

export default usePostMessageStreaming;
