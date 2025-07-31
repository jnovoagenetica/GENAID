import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useRef,
} from 'react';
import InputChatContent from '../components/InputChatContent';
import useChat from '../hooks/useChat';
import ChatMessage from '../components/ChatMessage';
import useScroll from '../hooks/useScroll';
import { useParams } from 'react-router-dom';
import {
  PiArrowsCounterClockwise,
  PiWarningCircleFill,
} from 'react-icons/pi';
import Button from '../components/Button';
import { useTranslation } from 'react-i18next';
import useConversation from '../hooks/useConversation';
import Alert from '../components/Alert';
import useBotSummary from '../hooks/useBotSummary';
import useModel from '../hooks/useModel';
import { motion } from 'framer-motion';

const ChatPage: React.FC = () => {
  const { t } = useTranslation();

  const {
    postingMessage,
    postChat,
    messages,
    conversationId,
    setConversationId,
    hasError,
    retryPostChat,
    setCurrentMessageId,
    regenerate,
  } = useChat();

  const { getBotId } = useConversation();
  const { scrollToBottom, scrollToTop } = useScroll();
  const { conversationId: paramConversationId, botId: paramBotId } =
    useParams();

  // Estado para el archivo adjunto. Sigue siendo la única fuente de verdad.
  const [attachedFile, setAttachedFile] = useState<File | null>(null);

  const botId = useMemo(() => {
    return paramBotId ?? getBotId(conversationId);
  }, [conversationId, getBotId, paramBotId]);

  const {
    data: bot,
    error: botError,
    isLoading: isLoadingBot,
  } = useBotSummary(botId ?? undefined);

  const [pageTitle, setPageTitle] = useState('');
  const [isAvailabilityBot, setIsAvailabilityBot] = useState(false);

  useEffect(() => {
    setIsAvailabilityBot(false);
    if (bot) {
      setIsAvailabilityBot(true);
      setPageTitle(bot.title);
    } else {
      setPageTitle(t('bot.label.normalChat'));
    }
    if (botError) {
      if (botError.response?.status === 404) {
        setPageTitle(t('bot.label.notAvailableBot'));
      }
    }
  }, [bot, botError, t]);

  const description = useMemo<string>(() => {
    if (!bot) {
      return '';
    } else if (bot.description === '') {
      return t('bot.label.noDescription');
    } else {
      return bot.description;
    }
  }, [bot, t]);

  const disabledInput = useMemo(() => {
    return botId !== null && !isAvailabilityBot && !isLoadingBot;
  }, [botId, isAvailabilityBot, isLoadingBot]);

  useEffect(() => {
    setConversationId(paramConversationId ?? '');
    // Limpiar el archivo adjunto si cambia la conversación
    setAttachedFile(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramConversationId]);

  const inputBotParams = useMemo(() => {
    return botId
      ? {
          botId: botId,
          hasKnowledge: bot?.hasKnowledge ?? false,
        }
      : undefined;
  }, [bot?.hasKnowledge, botId]);

  // La lógica de `onSend` no cambia, sigue funcionando perfectamente
  const onSend = useCallback(
    async (content: string, base64EncodedImages?: string[]) => {
      let attachments: { fileName: string; mediaType: string; body: string }[] =
        [];

      if (attachedFile) {
        const fileToBase64 = (file: File): Promise<string> =>
          new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.readAsDataURL(file);
            reader.onload = () => {
              const base64String = (reader.result as string).split(',')[1];
              resolve(base64String);
            };
            reader.onerror = (error) => reject(error);
          });

        try {
          const base64Body = await fileToBase64(attachedFile);
          attachments.push({
            fileName: attachedFile.name,
            mediaType: attachedFile.type || 'application/octet-stream',
            body: base64Body,
          });
        } catch (error) {
          console.error('Error al codificar el archivo a Base64:', error);
          return;
        }
      }

      postChat({
        content,
        base64EncodedImages,
        attachments: attachments.length > 0 ? attachments : undefined,
        bot: inputBotParams,
      });

      setAttachedFile(null);
    },
    [inputBotParams, postChat, attachedFile]
  );

  const handleRemoveAttachedFile = () => {
    setAttachedFile(null);
  };

  const onChangeCurrentMessageId = useCallback(
    (messageId: string) => {
      setCurrentMessageId(messageId);
    },
    [setCurrentMessageId]
  );

  const onSubmitEditedContent = useCallback(
    (messageId: string, content: string) => {
      if (hasError) {
        retryPostChat({
          content,
          bot: inputBotParams,
        });
      } else {
        regenerate({
          messageId,
          content,
          bot: inputBotParams,
        });
      }
    },
    [hasError, inputBotParams, regenerate, retryPostChat]
  );

  const onRegenerate = useCallback(() => {
    regenerate({
      bot: inputBotParams,
    });
  }, [inputBotParams, regenerate]);

  useEffect(() => {
    if (messages.length > 0) {
      scrollToBottom();
    } else {
      scrollToTop();
    }
  }, [messages, scrollToBottom, scrollToTop]);

  const { disabledImageUpload } = useModel();
  const [dndMode, setDndMode] = useState(false);
  const onDragOver: React.DragEventHandler<HTMLDivElement> = useCallback(
    (e) => {
      if (!disabledImageUpload) {
        setDndMode(true);
      }
      e.preventDefault();
    },
    [disabledImageUpload]
  );
  const endDnd: React.DragEventHandler<HTMLDivElement> = useCallback((e) => {
    setDndMode(false);
    e.preventDefault();
  }, []);

  const isDesktop = window.innerWidth >= 1024;

  return (
    <div
      className="bg-[#D4EEF3] min-h-screen"
      onDragOver={onDragOver}
      onDrop={endDnd}
      onDragEnd={endDnd}>
      <div className="relative h-14 w-full">
        <div className="flex w-full justify-between">
          <div className="p-2">
            <div className="mr-10 font-bold">{pageTitle}</div>
            <div className="text-xs font-thin text-dark-black ">
              {description}
            </div>
          </div>
        </div>
      </div>

      <hr className="w-full border-t border-gray" />

      {/* Contenedor de mensajes con scroll */}
      <div className="pb-52 lg:pb-40">
        {messages.length === 0 ? (
          <div className="relative flex w-full flex-col items-center">
            <motion.div
              initial={false}
              animate={
                messages.length === 0
                  ? {
                      position: 'fixed',
                      top: '50%',
                      left: '50%',
                      x: '-50%',
                      // Posición final ajustada para responsive
                      y: isDesktop ? '-65%' : '-85%',
                    }
                  : {
                      position: 'fixed',
                      top: 20,
                      left: '50%',
                      x: '-50%',
                      y: 0,
                    }
              }
              transition={{ type: 'spring', stiffness: 100, damping: 20 }}
              className="z-20 flex w-full justify-center pointer-events-none">
              
              {/* ===== INICIO DE LA CORRECCIÓN FINAL RESPONSIVE ===== */}
              <div className="flex items-center justify-center space-x-2 sm:space-x-4">
                {/* Nueva escala de tamaños: pequeño en móvil, grande en escritorio */}
                <img
                  src="/Gentica_Humana.png"
                  alt="Logo Genetica Humana"
                  className="w-auto h-24 sm:h-32 md:h-48 lg:h-64 xl:h-72"
                />
                <img
                  src="/GeneticaLogoAid.png"
                  alt="Logo GHene Aid"
                  className="w-auto h-24 sm:h-32 md:h-48 lg:h-64 xl:h-72"
                />
              </div>
              {/* ===== FIN DE LA CORRECCIÓN FINAL RESPONSIVE ===== */}

            </motion.div>
          </div>
        ) : (
          messages.map((message, idx) => (
            <div
              key={idx}
              className={`${
                message.role === 'assistant' ? 'bg-[#A3D1E4]' : ''
              }`}>
              <ChatMessage
                chatContent={message}
                onChangeMessageId={onChangeCurrentMessageId}
                onSubmit={onSubmitEditedContent}
              />
              <div className="w-full border-b border-aws-squid-ink/10"></div>
            </div>
          ))
        )}

        {hasError && (
          <div className="mb-12 mt-2 flex flex-col items-center">
            <div className="flex items-center font-bold text-red">
              <PiWarningCircleFill className="mr-1 text-2xl" />
              {t('error.answerResponse')}
            </div>
            <Button
              className="mt-2 shadow"
              icon={<PiArrowsCounterClockwise />}
              outlined
              onClick={() => {
                retryPostChat({
                  bot: inputBotParams,
                });
              }}>
              {t('button.resend')}
            </Button>
          </div>
        )}

        {postingMessage && (
          <div className="flex justify-center items-center mb-6 text-sm text-gray-700 animate-pulse">
            🧠 Pensando...
          </div>
        )}
      </div>

      {/* Barra inferior fija */}
      <div className="absolute bottom-0 bg-[#D4EEF3] pt-4 pb-2 z-0 flex w-full flex-col items-center justify-center">
        {bot && bot.syncStatus !== 'SUCCEEDED' && (
          <div className="mb-8 w-1/2">
            <Alert
              severity="warning"
              title={t('bot.alert.sync.incomplete.title')}>
              {t('bot.alert.sync.incomplete.body')}
            </Alert>
          </div>
        )}
        <div className="mb-0 w-full flex justify-center">
          {/* Props simplificadas para InputChatContent */}
          <InputChatContent
            dndMode={dndMode}
            disabledSend={postingMessage}
            disabled={disabledInput}
            placeholder={
              disabledInput
                ? t('bot.label.notAvailableBotInputMessage')
                : undefined
            }
            onSend={onSend}
            onRegenerate={onRegenerate}
            // Props para manejar el adjunto
            attachedFileName={attachedFile ? attachedFile.name : null}
            onRemoveAttachedFile={handleRemoveAttachedFile}
            // Pasamos la función para que el hijo pueda actualizar el estado del documento
            onAttachDocument={setAttachedFile}
          />
        </div>
        <div className="w-full px-4 flex flex-wrap items-center justify-center gap-2 sm:gap-4 text-xs sm:text-sm text-gray-700">
          <span>© Genética Humana E.U. 2025</span>
          <img
            src="/Gentica_Humana.png"
            alt="Logo Genetica"
            className="h-5 sm:h-6 w-auto opacity-80"
          />
          <img
            src="/GeneticaLogoAid.png"
            alt="Logo Genetica"
            className="h-5 sm:h-6 w-auto opacity-80"
          />
          <span>Powered by Norsoft S.A.S.</span>
          <img
            src="/LogoNorSoft.png"
            alt="Logo NorSoft"
            className="h-5 sm:h-6 w-auto opacity-80"
          />
        </div>
      </div>
    </div>
  );
};

export default ChatPage;