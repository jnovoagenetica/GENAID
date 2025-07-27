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
          while (childrenIds.length > 0) {
            const targetId = childrenIds.pop()!;
            childrenIds.push(...draft[id][targetId].children);
            delete draft[id][targetId];
          }
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

  useEffect(() => {
    if (error?.response?.status === 404) {
      openSnackbar(t('error.notFoundConversation'));
      navigate('');
      newChat();
    } else if (error) {
      openSnackbar(error?.message ?? '');
    }
  }, [error, navigate, newChat, openSnackbar, t]);

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
  }, [conversationId, data]);

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

  // ------------------- FUNCIÓN CORREGIDA -------------------
  const postChat = (params: {
    content: string;
    base64EncodedImages?: string[];
    bot?: BotInputType;
    // CAMBIO 1: Renombrar de 'pdfFiles' a 'files' para que coincida con lo que se envía
    files?: File[];
  }) => {
    // CAMBIO 2: Extraer 'files' en lugar de 'pdfFiles' de los parámetros
    const { content, bot, base64EncodedImages, files } = params;
    const isNewChat = !conversationId;
    const newConversationId = ulid();

    const tmpMessages = convertMessageMapToArray(
      useChatState.getState().chats[conversationId] ?? {},
      currentMessageId
    );

    const parentMessageId = isNewChat
      ? 'system'
      : tmpMessages[tmpMessages.length - 1].id;

    const modelToPost = isNewChat ? modelId : getPostedModel();
    const imageContents: MessageContent['content'] = (
      base64EncodedImages ?? []
    ).map((encodedImage) => {
      const result =
        /data:(?<mediaType>image\/.+);base64,(?<encodedImage>.+)/.exec(
          encodedImage
        );
      return {
        body: result!.groups!.encodedImage,
        contentType: 'image',
        mediaType: result!.groups!.mediaType,
      };
    });

    const messageContent: MessageContent = {
      content: [
        ...imageContents,
        {
          body: content,
          contentType: 'text',
        },
      ],
      model: modelToPost,
      role: 'user',
      feedback: null,
    };

    // Este es el objeto que SIEMPRE se envía. Incluye los archivos.
    const inputToApi = {
      conversationId: isNewChat ? newConversationId : conversationId,
      message: {
        ...messageContent,
        parentMessageId: parentMessageId,
      },
      botId: bot?.botId,
      // CAMBIO 3: Pasar la propiedad 'files' a la capa de API
      files: files,
    };

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

    const postPromise: Promise<string> = new Promise((resolve, reject) => {
      if (USE_STREAMING && (!files || files.length === 0)) { // Modificado para no usar streaming con archivos
        // En streaming, los archivos se ignoran (o se manejarían de otra forma)
        postStreaming({
          input: inputToApi,
          hasKnowledge: bot?.hasKnowledge,
          dispatch: (c: string) => {
            editMessage(conversationId, NEW_MESSAGE_ID.ASSISTANT, c);
          },
        })
          .then(resolve)
          .catch(reject);
      } else {
        // Sin streaming, SIEMPRE llamamos a postMessage.
        // La lógica de crear FormData está DENTRO de postMessage en useConversationApi.ts
        conversationApi
          .postMessage(inputToApi) // inputToApi ahora contiene la propiedad 'files'
          .then((res) => {
            editMessage(
              conversationId,
              NEW_MESSAGE_ID.ASSISTANT,
              res.data.message.content[0].body
            );
            resolve(res.data.message.content[0].body);
          })
          .catch(reject);
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
        console.error(e);
        setCurrentMessageId(NEW_MESSAGE_ID.ASSISTANT);
      })
      .finally(() => {
        setPostingMessage(false);
      });

    // get related document (for RAG)
    if (inputToApi.botId) {
      conversationApi
        .getRelatedDocuments({
          botId: inputToApi.botId,
          conversationId: inputToApi.conversationId!,
          message: inputToApi.message,
        })
        .then((res) => {
          if (res.data?.length) {
            setRelatedDocuments(NEW_MESSAGE_ID.ASSISTANT, res.data);
          }
        });
    }
  };
  // ------------------- FIN DE LA FUNCIÓN CORREGIDA -------------------


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
          content: [{ contentType: 'text', body: '' }],
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
          if (res.data?.length) {
            setRelatedDocuments(NEW_MESSAGE_ID.ASSISTANT, res.data);
          }
        });
    }
  };

  const hasError = useMemo(() => {
    const length_ = messages.length;
    return length_ === 0 ? false : messages[length_ - 1].role === 'user';
  }, [messages]);

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
    getRelatedDocuments: (messageId: string) => {
      return relatedDocuments[messageId] ?? [];
    },
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