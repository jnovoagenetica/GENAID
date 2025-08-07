import { useCallback, useEffect, useMemo } from 'react';
import useConversationApi from './useConversationApi';
import { produce } from 'immer';
import {
  MessageContent,
  DisplayMessageContent,
  MessageMap,
  Model,
  PostMessageRequest,
  RelatedDocument,
  Conversation,
  PutFeedbackRequest,
  ContentBlock,
} from '../@types/conversation';
import useConversation from './useConversation';
import { create } from 'zustand';
import usePostMessageStreaming from './usePostMessageStreaming';
import useSnackbar from './useSnackbar';
import { useNavigate } from 'react-router-dom';
import { ulid } from 'ulid';
import { convertMessageMapToArray } from '../utils/MessageUtils';
import { useTranslation } from 'react-i18next';
import useModel from './useModel';
import useFeedbackApi from './useFeedbackApi';

// Parámetros para la función postChat, ahora usa 'pdfFiles'
// Tipo de los parámetros que recibe la función `postChat`.
// Se incluye `pdfFiles`, que es un array de archivos tipo File.
type PostChatParams = {
  content: string; // Texto del mensaje
  base64EncodedImages?: string[]; // Imágenes en base64 opcionales
  pdfFiles?: File[]; // Archivos PDF opcionales
  bot?: BotInputType; // Información del bot (si aplica)
};

type ChatStateType = {
  [id: string]: MessageMap;
};

type BotInputType = {
  botId: string;
  hasKnowledge: boolean;
};

const NEW_MESSAGE_ID = {
  USER: 'new-message',
  ASSISTANT: 'new-message-assistant',
};
const USE_STREAMING: boolean =
  import.meta.env.VITE_APP_USE_STREAMING === 'true';

const useChatState = create<{
  conversationId: string;
  setConversationId: (s: string) => void;
  postingMessage: boolean;
  setPostingMessage: (b: boolean) => void;
  chats: ChatStateType;
  relatedDocuments: {
    [messageId: string]: RelatedDocument[];
  };
  setMessages: (id: string, messageMap: MessageMap) => void;
  copyMessages: (fromId: string, toId: string) => void;
  pushMessage: (
    id: string,
    parentMessageId: string | null,
    currentMessageId: string,
    content: MessageContent
  ) => void;
  removeMessage: (id: string, messageId: string) => void;
  editMessage: (id: string, messageId: string, content: string) => void;
  getMessages: (
    id: string,
    currentMessageId: string
  ) => DisplayMessageContent[];
  setRelatedDocuments: (
    messageId: string,
    documents: RelatedDocument[]
  ) => void;
  moveRelatedDocuments: (fromMessageId: string, toMessageId: string) => void;
  currentMessageId: string;
  setCurrentMessageId: (s: string) => void;
  isGeneratedTitle: boolean;
  setIsGeneratedTitle: (b: boolean) => void;
  getPostedModel: () => Model;
  shouldUpdateMessages: (currentConversation: Conversation) => boolean;
}>((set, get) => {
  return {
    conversationId: '',
    setConversationId: (s) => {
      set(() => {
        return {
          conversationId: s,
        };
      });
    },
    postingMessage: false,
    setPostingMessage: (b) => {
      set(() => ({
        postingMessage: b,
      }));
    },
    chats: {},
    relatedDocuments: {},
    setMessages: (id: string, messageMap: MessageMap) => {
      set((state) => ({
        chats: produce(state.chats, (draft) => {
          draft[id] = messageMap;
        }),
      }));
    },
    copyMessages: (fromId: string, toId: string) => {
      set((state) => ({
        chats: produce(state.chats, (draft) => {
          draft[toId] = JSON.parse(JSON.stringify(draft[fromId]));
        }),
      }));
    },
    pushMessage: (
      id: string,
      parentMessageId: string | null,
      currentMessageId: string,
      content: MessageContent
    ) => {
      set(() => ({
        chats: produce(get().chats, (draft) => {
          // 追加対象が子ノードの場合は親ノードに参照情報を追加
          if (draft[id] && parentMessageId && parentMessageId !== 'system') {
            draft[id][parentMessageId] = {
              ...draft[id][parentMessageId],
              children: [
                ...draft[id][parentMessageId].children,
                currentMessageId,
              ],
            };
            draft[id][currentMessageId] = {
              ...content,
              parent: parentMessageId,
              children: [],
            };
          } else {
            draft[id] = {
              [currentMessageId]: {
                ...content,
                children: [],
                parent: null,
              },
            };
          }
        }),
      }));
    },
    editMessage: (id: string, messageId: string, content: string) => {
      set(() => ({
        chats: produce(get().chats, (draft) => {
          draft[id][messageId].content[0].body = content;
        }),
      }));
    },
    removeMessage: (id: string, messageId: string) => {
      set((state) => ({
        chats: produce(state.chats, (draft) => {
          const childrenIds = [...draft[id][messageId].children];

          // childrenに設定されているノードも全て削除
          while (childrenIds.length > 0) {
            const targetId = childrenIds.pop()!;
            childrenIds.push(...draft[id][targetId].children);
            delete draft[id][targetId];
          }

          // 削除対象のノードを他ノードの参照から削除
          Object.keys(draft[id]).forEach((key) => {
            const idx = draft[id][key].children.findIndex(
              (c) => c === messageId
            );
            if (idx > -1) {
              draft[id][key].children.splice(idx, 1);
            }
          });
          delete draft[id][messageId];
        }),
      }));
    },
    getMessages: (id: string, currentMessageId: string) => {
      return convertMessageMapToArray(get().chats[id] ?? {}, currentMessageId);
    },
    setRelatedDocuments: (messageId, documents) => {
      set((state) => ({
        relatedDocuments: produce(state.relatedDocuments, (draft) => {
          draft[messageId] = documents;
        }),
      }));
    },
    moveRelatedDocuments: (fromId, toId) => {
      set(() => ({
        relatedDocuments: produce(get().relatedDocuments, (draft) => {
          draft[toId] = get().relatedDocuments[fromId];
          draft[fromId] = [];
        }),
      }));
    },
    currentMessageId: '',
    setCurrentMessageId: (s: string) => {
      set(() => ({
        currentMessageId: s,
      }));
    },
    isGeneratedTitle: false,
    setIsGeneratedTitle: (b: boolean) => {
      set(() => ({
        isGeneratedTitle: b,
      }));
    },
    getPostedModel: () => {
      return (
        get().chats[get().conversationId]?.system?.model ??
        // 画面に即時反映するためNEW_MESSAGEを評価
        get().chats['']?.[NEW_MESSAGE_ID.ASSISTANT]?.model
      );
    },
    shouldUpdateMessages: (currentConversation) => {
      return (
        !!get().conversationId &&
        currentConversation.id === get().conversationId &&
        !get().postingMessage &&
        get().currentMessageId !== currentConversation.lastMessageId
      );
    },
  };
});

const useChat = () => {
  const { t } = useTranslation();
  const {
    chats,
    conversationId,
    setConversationId,
    postingMessage,
    setPostingMessage,
    setMessages,
    pushMessage,
    editMessage,
    copyMessages,
    removeMessage,
    getMessages,
    currentMessageId,
    setCurrentMessageId,
    isGeneratedTitle,
    setIsGeneratedTitle,
    getPostedModel,
    relatedDocuments,
    setRelatedDocuments,
    moveRelatedDocuments,
    shouldUpdateMessages,
  } = useChatState();
  const { open: openSnackbar } = useSnackbar();
  const navigate = useNavigate();

  const { post: postStreaming } = usePostMessageStreaming();
  const { modelId, setModelId } = useModel();

  const conversationApi = useConversationApi();
  const feedbackApi = useFeedbackApi();
  const {
    data,
    mutate,
    isLoading: loadingConversation,
    error,
  } = conversationApi.getConversation(conversationId);
  const { syncConversations } = useConversation();

  const messages = useMemo(() => {
    return getMessages(conversationId, currentMessageId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, chats, currentMessageId]);

  const newChat = useCallback(() => {
    setConversationId('');
    setMessages('', {});
  }, [setConversationId, setMessages]);

  // Error Handling
  useEffect(() => {
    if (error?.response?.status === 404) {
      openSnackbar(t('error.notFoundConversation'));
      navigate('');
      newChat();
    } else if (error) {
      openSnackbar(error?.message ?? '');
    }
  }, [error, navigate, newChat, openSnackbar, t]);

  // when updated messages
  useEffect(() => {
    if (data && shouldUpdateMessages(data)) {
      const tempId = NEW_MESSAGE_ID.ASSISTANT;
      const tempMessage = chats[conversationId]?.[tempId];
      const lastRealId = data.lastMessageId;
      const realMessages = data.messageMap;

      if (tempMessage && lastRealId && !realMessages[tempId]) {
        const mergedMap = {
          ...realMessages,
          [lastRealId]: {
            ...realMessages[lastRealId],
            content:
              tempMessage.content.length > 0
                ? tempMessage.content
                : realMessages[lastRealId].content,
          },
        };

        setMessages(conversationId, mergedMap);
        setCurrentMessageId(lastRealId);

        if ((relatedDocuments[tempId]?.length ?? 0) > 0) {
          moveRelatedDocuments(tempId, lastRealId);
        }
      } else {
        const updatedMap = {
          ...realMessages,
          ...(tempMessage ? { [tempId]: tempMessage } : {}),
        };
        setMessages(conversationId, updatedMap);
        setCurrentMessageId(lastRealId || tempId);
      }

      setModelId(getPostedModel());
    }
  }, [
    conversationId,
    data,
    chats,
    moveRelatedDocuments,
    relatedDocuments,
    setMessages,
    setCurrentMessageId,
    setModelId,
    getPostedModel,
    shouldUpdateMessages,
  ]);

  useEffect(() => {
    setIsGeneratedTitle(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const pushNewMessage = (
    parentMessageId: string | null,
    messageContent: MessageContent
  ) => {
    pushMessage(
      conversationId ?? '',
      parentMessageId,
      NEW_MESSAGE_ID.USER,
      messageContent
    );
    pushMessage(
      conversationId ?? '',
      NEW_MESSAGE_ID.USER,
      NEW_MESSAGE_ID.ASSISTANT,
      {
        role: 'assistant',
        content: [
          {
            contentType: 'text',
            body: '',
          },
        ],
        model: messageContent.model,
        feedback: messageContent.feedback,
      }
    );
  };

  const postChat = (params: PostChatParams) => {
    const { content, bot, base64EncodedImages, pdfFiles } = params;

    // 🔁 CAMBIOS AÑADIDOS CON LOGS VISIBLES
    // [1] Entrada al método
    console.log('[useChat/postChat] Iniciando envío de mensaje', {
      content,
      imageCount: base64EncodedImages?.length || 0,
      pdfCount: pdfFiles?.length || 0,
    });

    const isNewChat = !conversationId;
    const newConversationId = ulid();

    const tmpMessages = convertMessageMapToArray(
      useChatState.getState().chats[conversationId] ?? {},
      currentMessageId
    );

    const parentMessageId = isNewChat
      ? 'system'
      : tmpMessages[tmpMessages.length - 1]?.id ?? 'system';

    const modelToPost = isNewChat ? modelId : getPostedModel();

    const messageContents: ContentBlock[] = [];

    // Agregamos cada imagen como bloque de tipo "image"
    (base64EncodedImages ?? []).forEach((encodedImage) => {
      const result =
        /data:(?<mediaType>image\/.+);base64,(?<encodedImage>.+)/.exec(
          encodedImage
        );
      if (result?.groups) {
        console.log('Imagen 1');
        messageContents.push({
          contentType: 'image',
          mediaType: result.groups.mediaType,
          body: result.groups.encodedImage,
        });
        console.log('Imagen 2');
      }
    });

    // Agregamos cada archivo PDF como bloque de tipo "textAttachment"
    (pdfFiles ?? []).forEach((file) => {
      console.log('PDF1');
      messageContents.push({
        contentType: 'textAttachment',
        fileName: file.name,
        mediaType: file.type || 'application/pdf',
        body: '', // el archivo se manda fuera de este objeto
      });
      console.log('PDF2');
    });

    // Agregamos el texto del mensaje (si hay)
    if (content.trim() !== '') {
      messageContents.push({
        contentType: 'text',
        body: content,
      });
    }

    if (messageContents.length === 0) {
      openSnackbar(
        'No hay nada que enviar. Escribe un mensaje o adjunta un archivo.'
      );
      return;
    }

    const messageContent: MessageContent = {
      content: messageContents,
      model: modelToPost,
      role: 'user',
      feedback: null,
    };

    const input: PostMessageRequest = {
      conversationId: isNewChat ? newConversationId : conversationId,
      message: {
        ...messageContent,
        parentMessageId: parentMessageId,
      },
      botId: bot?.botId,
      files: pdfFiles?.length ? pdfFiles : undefined,
    };

    // 🔁 CAMBIOS AÑADIDOS CON LOGS VISIBLES
    // [2] Construcción del payload para enviar
    console.log('[useChat/postChat] Payload que se enviará:', {
      conversationId: input.conversationId,
      message: content,
      files: pdfFiles?.map((f) => f.name),
      images: base64EncodedImages?.map(
        (img, i) => `Imagen ${i + 1}: ${img.slice(0, 60)}...`
      ),
      useStreaming: USE_STREAMING,
    });

    // <--- LOG AÑADIDO: Bloque de logs antes de enviar al backend
    // 4. Log para FormData vs JSON
    if (pdfFiles?.length) {
      console.log('[useChat] Se usará FormData para enviar los archivos PDF');
    } else {
      console.log('[useChat] Se usará JSON estándar');
    }

    // 1. Log del payload antes de enviar
    console.log('[useChat] Enviando mensaje al backend');
    console.log('[useChat] Texto:', content);
    console.log(
      '[useChat] Archivos PDF adjuntos:',
      pdfFiles?.map((f) => f.name)
    );
    console.log(
      '[useChat] Imágenes base64 adjuntas:',
      base64EncodedImages?.length || 0
    );
    console.log('[useChat] Streaming habilitado:', USE_STREAMING);
    console.log('[useChat] Payload resumido:', {
      ...input,
      files: pdfFiles?.map((f) => f.name), // Mostrar solo nombres de archivo en el log
      message: {
        ...input.message,
        // Evitar loggear todo el contenido base64
        content: input.message.content.map((c) =>
          c.contentType === 'image'
            ? { ...c, body: `(imagen_base64_truncada)` }
            : c
        ),
      },
    });

    const createNewConversation = () => {
      copyMessages('', newConversationId);
      conversationApi
        .updateTitleWithGeneratedTitle(newConversationId)
        .then(() => {
          setConversationId(newConversationId);
        })
        .finally(() => {
          syncConversations().then(() => {
            setIsGeneratedTitle(true);
          });
        });
    };

    setPostingMessage(true);
    pushNewMessage(parentMessageId, messageContent);

    // 🔁 CAMBIOS AÑADIDOS CON LOGS VISIBLES
    // [3] Antes de llamar a la API
    console.log('[useChat/postChat] Enviando a postMessage...');

    // Si está habilitado el streaming, se usa WebSocket.
    // Sino, se usa `conversationApi.postMessage` con FormData si hay archivos.
    const postPromise: Promise<string> = new Promise((resolve, reject) => {
      // <--- LOG AÑADIDO: Indica el modo de envío
      if (USE_STREAMING) {
        console.log('[useChat] Usando WebSocket para streaming de respuesta');
        postStreaming({
          input,
          hasKnowledge: bot?.hasKnowledge,
          dispatch: (c: string) => {
            editMessage(conversationId, NEW_MESSAGE_ID.ASSISTANT, c);
          },
        })
          .then((message) => {
            // <--- LOG AÑADIDO: Confirma que el streaming terminó
            console.log('[useChat] Respuesta de streaming completada.');
            resolve(message);
          })
          .catch((e) => reject(e));
      } else {
        console.log('[useChat] Envío estándar sin streaming');
        console.log('[useChat] Llamando a postMessage de useConversationApi');
        conversationApi
          .postMessage(input)
          .then((res) => {
            // 🔁 CAMBIOS AÑADIDOS CON LOGS VISIBLES
            // [4] Si no hay streaming, log de la respuesta
            if (!USE_STREAMING) {
              console.log(
                '[useChat/postChat] Respuesta del backend (sin streaming):',
                res.data
              );
            }
            // <--- LOG AÑADIDO: Confirma la respuesta y loguea el ID del mensaje
            console.log('[useChat] Respuesta del backend recibida');
            console.log('[useChat] Mensaje ID:', (res.data.message as any).id);
            editMessage(
              conversationId,
              NEW_MESSAGE_ID.ASSISTANT,
              res.data.message.content[0].body
            );
            resolve(res.data.message.content[0].body);
          })
          .catch((e) => reject(e));
      }
    });

    postPromise
      .then(() => {
        if (isNewChat) {
          createNewConversation();
        } else {
          mutate();
        }
      })
      .catch((e) => {
        // <--- LOG AÑADIDO: Captura y loguea errores
        console.error('[useChat] Error al enviar el mensaje:', e);
        setCurrentMessageId(NEW_MESSAGE_ID.ASSISTANT);
      })
      .finally(() => {
        setPostingMessage(false);
      });

    if (input.botId) {
      conversationApi
        .getRelatedDocuments({
          botId: input.botId,
          conversationId: input.conversationId!,
          message: input.message,
        })
        .then((res) => {
          if (res.data) {
            setRelatedDocuments(NEW_MESSAGE_ID.ASSISTANT, res.data);
          }
        });
    }
  };

  const regenerate = (props?: {
    content?: string;
    messageId?: string;
    bot?: BotInputType;
  }) => {
    let index: number = -1;
    if (props?.messageId) {
      index = messages.findIndex((m) => m.id === props.messageId);
    }

    const isRetryError = messages[messages.length - 1].role === 'user';
    if (index === -1) {
      index = isRetryError ? messages.length - 1 : messages.length - 2;
    }

    const parentMessage = produce(messages[index], (draft) => {
      if (props?.content) {
        draft.content[0].body = props.content;
      }
    });

    if (props?.content) {
      editMessage(conversationId, parentMessage.id, props.content);
    }

    const input: PostMessageRequest = {
      conversationId: conversationId,
      message: {
        ...parentMessage,
        parentMessageId: parentMessage.parent,
      },
      botId: props?.bot?.botId,
    };

    if (input.message.parentMessageId === null) {
      input.message.parentMessageId = 'system';
    }

    setPostingMessage(true);

    if (isRetryError) {
      pushMessage(
        conversationId ?? '',
        parentMessage.id,
        NEW_MESSAGE_ID.ASSISTANT,
        {
          role: 'assistant',
          content: [
            {
              contentType: 'text',
              body: '',
            },
          ],
          model: messages[index].model,
          feedback: messages[index].feedback,
        }
      );
    } else {
      pushNewMessage(parentMessage.parent, parentMessage);
    }

    setCurrentMessageId(NEW_MESSAGE_ID.ASSISTANT);

    postStreaming({
      input,
      dispatch: (c: string) => {
        editMessage(conversationId, NEW_MESSAGE_ID.ASSISTANT, c);
      },
    })
      .then(() => {
        mutate();
      })
      .catch((e) => {
        console.error(e);
        setCurrentMessageId(NEW_MESSAGE_ID.USER);
        removeMessage(conversationId, NEW_MESSAGE_ID.ASSISTANT);
      })
      .finally(() => {
        setPostingMessage(false);
      });

    if (input.botId) {
      conversationApi
        .getRelatedDocuments({
          botId: input.botId,
          conversationId: input.conversationId!,
          message: input.message,
        })
        .then((res) => {
          if (res.data) {
            setRelatedDocuments(NEW_MESSAGE_ID.ASSISTANT, res.data);
          }
        });
    }
  };

  const hasError = useMemo(() => {
    const length_ = messages.length;
    return length_ === 0 ? false : messages[length_ - 1].role === 'user';
  }, [messages]);

  const getRelatedDocuments = useCallback(
    (messageId: string) => {
      return relatedDocuments[messageId] ?? [];
    },
    [relatedDocuments]
  );

  return {
    hasError,
    setConversationId,
    conversationId,
    loadingConversation,
    postingMessage: postingMessage || loadingConversation,
    isGeneratedTitle,
    setIsGeneratedTitle,
    newChat,
    messages,
    setCurrentMessageId,
    postChat,
    regenerate,
    getPostedModel,
    retryPostChat: (params: { content?: string; bot?: BotInputType }) => {
      const length_ = messages.length;
      if (length_ === 0) {
        return;
      }
      const latestMessage = messages[length_ - 1];
      if (latestMessage.sibling.length === 1) {
        removeMessage(conversationId, latestMessage.id);
        postChat({
          content: params.content ?? latestMessage.content[0].body,
          bot: params.bot
            ? {
                botId: params.bot.botId,
                hasKnowledge: params.bot.hasKnowledge,
              }
            : undefined,
        });
      } else {
        regenerate({
          content: params.content ?? latestMessage.content[0].body,
          bot: params.bot,
        });
      }
    },
    getRelatedDocuments,
    giveFeedback: (messageId: string, feedback: PutFeedbackRequest) => {
      return feedbackApi
        .putFeedback(conversationId, messageId, feedback)
        .then(() => {
          mutate();
        });
    },
  };
};

export default useChat;