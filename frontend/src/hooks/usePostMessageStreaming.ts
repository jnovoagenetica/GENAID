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

const usePostMessageStreaming = create<{
  post: (params: {
    input: PostMessageRequest;
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

      console.log('[STREAMING] Enviando mensaje por WebSocket');
      console.log('[STREAMING] Texto:', input.message);
      console.log(
        '[STREAMING] Nº imágenes:',
        input.message.content.filter((c) => c.contentType === 'image').length
      );
      console.log(
        '[STREAMING] Imagenes (base64 recortado):',
        input.message.content
          .filter((c) => c.contentType === 'image')
          .map((img, i) => `Img ${i + 1}: ${img.body.slice(0, 60)}...`)
      );

      // --- INICIO DEL CÓDIGO AÑADIDO ---
      // 👉 También loguea y valida adjuntos PDF enviados como bloques 'textAttachment'
      const attachments = input.message.content.filter(
        (c: any) => c.contentType === 'textAttachment'
      ) as Array<{ fileName?: string; mediaType?: string; body?: string }>;

      console.log('[STREAMING] Nº adjuntos (PDF):', attachments.length);
      console.log(
        '[STREAMING] Adjuntos:',
        attachments.map((a, i) => ({
          i: i + 1,
          fileName: a.fileName,
          mediaType: a.mediaType,
          base64Sample: (a.body || '').slice(0, 60) + '...',
          approxKB: Math.round(((a.body?.length || 0) * 3) / 4 / 1024), // aprox
        }))
      );

      // Validaciones mínimas para evitar payloads mal formados
      attachments.forEach((a, i) => {
        if (!a.fileName || !a.mediaType || !a.body) {
          console.warn(
            `[STREAMING] ⚠️ textAttachment #${i + 1} incompleto:`,
            {
              fileName: a.fileName,
              mediaType: a.mediaType,
              hasBody: !!a.body,
            }
          );
        }
      });
      // --- FIN DEL CÓDIGO AÑADIDO ---

      const payloadString = JSON.stringify({
        ...input,
        token,
      });

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
          ws.send(
            JSON.stringify({
              step: PostStreamingStatus.START,
              token,
            })
          );
        };

        ws.onmessage = (message) => {
          try {
            if (
              message.data === '' ||
              message.data === 'Message sent.' ||
              message.data.startsWith(
                '{"message": "Endpoint request timed out",'
              )
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
                ws.send(
                  JSON.stringify({
                    step: PostStreamingStatus.END,
                  })
                );
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
                    if (
                      completion.endsWith(i18next.t('app.chatWaitingSymbol'))
                    ) {
                      completion = completion.slice(0, -1);
                    }
                    completion +=
                      data.completion + i18next.t('app.chatWaitingSymbol');
                    dispatch(completion);
                  }
                  break;

                case PostStreamingStatus.STREAMING_END:
                  if (
                    completion.endsWith(i18next.t('app.chatWaitingSymbol'))
                  ) {
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