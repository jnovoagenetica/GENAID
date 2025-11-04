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
      const b64 = result.includes(',') ? result.split(',')[1] : result;
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

      // 1. OBTENER TOKEN DE COGNITO
      const session = await Auth.currentSession();
      const token = session.getIdToken().getJwtToken();

      const text =
        input.message.content.find((c) => c.contentType === 'text')?.body ?? '';

      // 2. Construir contents (texto + imágenes)
      const contents: any[] = [
        { contentType: 'text', body: text },
        ...input.message.content.filter((c) => c.contentType === 'image'),
      ];

      // 3. Adjuntos que ya vienen en el content
      const attachmentsFromContent: AttachmentOut[] = input.message.content
        .filter((c) => c.contentType === 'textAttachment' && c.body)
        .map((c: any) => ({
          name: c.fileName || 'archivo.pdf',
          mimeType: c.mimeType || c.mediaType || 'application/pdf',
          base64: c.body,
        }));

      // 4. Convertir File[] a base64 y agregarlos
      const attachmentsFromFiles: AttachmentOut[] = [];
      for (const f of input.files ?? []) {
        if (f.type === 'application/pdf') {
          const base64 = await fileToBase64(f);
          attachmentsFromFiles.push({
            name: f.name,
            mimeType: f.type || 'application/pdf',
            base64,
          });
          // mantener compatibilidad
          contents.push({
            contentType: 'textAttachment',
            body: base64,
            fileName: f.name,
            mimeType: f.type || 'application/pdf',
          });
        }
      }

      const attachments: AttachmentOut[] = [
        ...attachmentsFromContent,
        ...attachmentsFromFiles,
      ];

      // 5. Payload final
      const payload: any = {
        ...input,
        message: {
          ...input.message,
          content: contents,
        },
        attachments,
        token, // <- lo sigues mandando dentro del mensaje
      };
      delete payload.files;

      const payloadString = JSON.stringify(payload);

      // 6. Trocear
      const chunkedPayloads: string[] = [];
      const chunkCount = Math.ceil(payloadString.length / CHUNK_SIZE);
      for (let i = 0; i < chunkCount; i++) {
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, payloadString.length);
        chunkedPayloads.push(payloadString.substring(start, end));
      }

      let receivedCount = 0;

      return new Promise<string>((resolve, reject) => {
        let completion = '';

        // 7. ***ABRIR WS CON TOKEN EN LA URL***
        const wsUrl = `${WS_ENDPOINT}?token=${encodeURIComponent(token)}`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          // además, le sigues avisando en el primer mensaje
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
                ws.send(
                  JSON.stringify({
                    step: PostStreamingStatus.BODY,
                    index,
                    part: chunk,
                  })
                );
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
                  throw new Error(i18next.t('error.predict.invalidResponse'));
                default:
                  dispatch(i18next.t('app.chatWaitingSymbol'));
              }
            } else {
              ws.close();
              throw new Error(i18next.t('error.predict.invalidResponse'));
            }
          } catch {
            reject(i18next.t('error.predict.general'));
          }
        };

        ws.onerror = () => {
          ws.close();
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
