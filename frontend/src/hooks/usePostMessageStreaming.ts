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

// --- AÑADIDO: Helper para convertir File -> base64 (sin el prefijo "data:...") ---
async function fileToBase64(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  let binary = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}
// --- FIN DEL AÑADIDO ---

const usePostMessageStreaming = create<{
  post: (params: {
    // Se añade `files` a la entrada para procesarlos aquí
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

      // Construir el contenido del mensaje para streaming
      const contents: any[] = [
        // 1. Añadir el texto del usuario
        { contentType: 'text', body: text },
        // 2. Añadir imágenes que ya venían en el content (si las hay)
        ...input.message.content.filter((c) => c.contentType === 'image'),
        // 2.5 (AÑADIDO) Añadir adjuntos que ya venían (si existieran)
        ...input.message.content.filter(
          (c) => c.contentType === 'textAttachment'
        ),
      ];

      // 3. Procesar y adjuntar PDFs (y otros archivos) que vienen como File[]
      for (const f of input.files ?? []) {
        if (f.type === 'application/pdf') {
          const b64 = await fileToBase64(f);
          contents.push({
            contentType: 'textAttachment',
            body: b64, // solo la cadena base64
            fileName: f.name,
            mediaType: f.type, // "application/pdf"
          });
        }
        // Aquí se podría añadir lógica para otros tipos de archivo si es necesario
      }

      // 4. Construir el payload final que se enviará por WebSocket
      const payload = {
        ...input,
        message: {
          ...input.message,
          content: contents, // Usamos el contenido recién construido
        },
        token,
      };
      // Quitar la propiedad `files` para no enviarla en el JSON
      delete (payload as any).files;

      console.log('[STREAMING] Enviando mensaje por WebSocket');
      console.log(
        '[STREAMING] Nº adjuntos totales (PDF/otros):',
        contents.filter((c) => c.contentType === 'textAttachment').length
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

                // --- CORREGIDO: Se eliminó el guion bajo erróneo ---
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