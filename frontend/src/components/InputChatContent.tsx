import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import ButtonSend from './ButtonSend';
import Textarea from './Textarea';
import useChat from '../hooks/useChat';
// Usaremos PiPaperclip como el ícono unificado
import { PiX, PiPaperclip } from 'react-icons/pi'; // <-- Asegúrate de que PiArrowsCounterClockwise esté aquí si lo usas
import { useTranslation } from 'react-i18next';
import ButtonIcon from './ButtonIcon';
import useModel from '../hooks/useModel';
import { produce } from 'immer';
import { twMerge } from 'tailwind-merge';
import { create } from 'zustand';
import ButtonFileChoose from './ButtonFileChoose';
import { BaseProps } from '../@types/common';
import ModalDialog from './ModalDialog';
import HelpfulInfoModal from './HelpfulInfoModal';
// import Button from './Button'; // <-- Descomenta esto si usas el botón de regenerar

// Props actualizadas para el botón unificado
type Props = BaseProps & {
  disabledSend?: boolean;
  disabled?: boolean;
  placeholder?: string;
  dndMode?: boolean;
  onSend: (content: string, base64EncodedImages?: string[]) => void;
  onRegenerate: () => void;
  attachedFileName: string | null;
  onRemoveAttachedFile: () => void;
  // Nueva prop para pasar el archivo de documento al padre (ChatPage)
  onAttachDocument: (file: File) => void;
  multiple?: boolean;
};

const MAX_IMAGE_WIDTH = 800;
const MAX_IMAGE_HEIGHT = 800;

// Estado global de imágenes y vista previa
// Maneja:
// - Lista de imágenes en base64
// - Modal de vista previa
// - Funciones para agregar, quitar y limpiar imágenes
const useInputChatContentState = create<{
  base64EncodedImages: string[];
  pushBase64EncodedImage: (encodedImage: string) => void;
  removeBase64EncodedImage: (index: number) => void;
  clearBase64EncodedImages: () => void;
  previewImageUrl: string | null;
  setPreviewImageUrl: (url: string | null) => void;
  isOpenPreviewImage: boolean;
  setIsOpenPreviewImage: (isOpen: boolean) => void;
}>((set, get) => ({
  base64EncodedImages: [],
  pushBase64EncodedImage: (encodedImage) => {
    set({
      base64EncodedImages: produce(get().base64EncodedImages, (draft) => {
        draft.push(encodedImage);
      }),
    });
  },
  removeBase64EncodedImage: (index) => {
    set({
      base64EncodedImages: produce(get().base64EncodedImages, (draft) => {
        draft.splice(index, 1);
      }),
    });
  },
  clearBase64EncodedImages: () => {
    set({
      base64EncodedImages: [],
    });
  },
  previewImageUrl: null,
  setPreviewImageUrl: (url) => {
    set({ previewImageUrl: url });
  },
  isOpenPreviewImage: false,
  setIsOpenPreviewImage: (isOpen) => {
    set({ isOpenPreviewImage: isOpen });
  },
}));
//Fin

const InputChatContent: React.FC<Props> = (props) => {
  const { attachedFileName, onRemoveAttachedFile, onAttachDocument } = props;

  // --- AÑADIDO: Se reintroduce el estado del código antiguo para mostrar los botones ---
  const [showHelpfulInfo] = useState(true);

  const { t } = useTranslation();
  const { postingMessage, hasError, messages } = useChat();
  const { disabledImageUpload, acceptMediaType } = useModel();

  const [content, setContent] = useState('');
  const {
    base64EncodedImages,
    pushBase64EncodedImage,
    removeBase64EncodedImage,
    clearBase64EncodedImages,
    previewImageUrl,
    setPreviewImageUrl,
    isOpenPreviewImage,
    setIsOpenPreviewImage,
  } = useInputChatContentState();

  useEffect(() => {
    // Si el usuario elimina el archivo PDF adjunto, también limpiamos imágenes cargadas
    // para evitar que se envíen accidentalmente con el siguiente mensaje
    if (!attachedFileName) {
      clearBase64EncodedImages();
    }
  }, [attachedFileName, clearBase64EncodedImages]);

  const hasAttachment = !!attachedFileName;
  const disabledSend = useMemo(() => {
    const isInputEmpty =
      content.trim() === '' &&
      base64EncodedImages.length === 0 &&
      !hasAttachment;
    return props.disabledSend || hasError || isInputEmpty;
  }, [
    hasError,
    content,
    props.disabledSend,
    base64EncodedImages.length,
    hasAttachment,
  ]);

  const inputRef = useRef<HTMLDivElement>(null);

  const sendContent = useCallback(() => {
    // <--- AÑADIDO: Log en sendContent

    // 🔁 CAMBIOS AÑADIDOS
    // [3] Antes de ejecutar props.onSend()

    props.onSend(
      content,
      !disabledImageUpload && base64EncodedImages.length > 0
        ? base64EncodedImages
        : undefined
    );
    setContent('');
    clearBase64EncodedImages();
  }, [
    base64EncodedImages,
    clearBase64EncodedImages,
    content,
    disabledImageUpload,
    props,
  ]);

  const encodeAndPushImage = useCallback(
    (imageFile: File) => {
      const reader = new FileReader();
      reader.readAsArrayBuffer(imageFile);
      reader.onload = () => {
        if (!reader.result) {
          return;
        }

        const img = new Image();
        img.src = URL.createObjectURL(new Blob([reader.result]));
        img.onload = async () => {
          // Obtenemos dimensiones originales
          const width = img.naturalWidth;
          const height = img.naturalHeight;

          const aspectRatio = width / height;
          // Calculamos dimensiones escaladas para no exceder límites
          let newWidth;
          let newHeight;
          if (aspectRatio > 1) {
            newWidth = width > MAX_IMAGE_WIDTH ? MAX_IMAGE_WIDTH : width;
            newHeight =
              width > MAX_IMAGE_WIDTH ? MAX_IMAGE_WIDTH / aspectRatio : height;
          } else {
            newHeight = height > MAX_IMAGE_HEIGHT ? MAX_IMAGE_HEIGHT : height;
            newWidth =
              height > MAX_IMAGE_HEIGHT
                ? MAX_IMAGE_HEIGHT * aspectRatio
                : width;
          }

          // Dibujamos imagen en canvas con nuevo tamaño
          const canvas = document.createElement('canvas');
          const ctx = canvas.getContext('2d');
          canvas.width = newWidth;
          canvas.height = newHeight;
          ctx?.drawImage(img, 0, 0, newWidth, newHeight);

          // Obtenemos string base64 y lo almacenamos
          const resizedImageData = canvas.toDataURL('image/png');

          // 🔁 CAMBIOS AÑADIDOS
          // [2] Al convertir la imagen a base64 y redimensionarla

          pushBase64EncodedImage(resizedImageData);
        };
      };
    },
    [pushBase64EncodedImage]
  );

  // 2) Aceptar y enviar varios PDFs al padre
  const handleFileSelection = useCallback(
    (fileList: FileList) => {
      if (!fileList || fileList.length === 0) return;

      const all = Array.from(fileList);

      // 1) Imágenes → a base64 (todas)
      const images = all.filter((f) => f.type.startsWith('image/'));
      if (images.length) {
        images.forEach((img) => {
          encodeAndPushImage(img);
        });
      }

      // 2) Documentos (solo PDF por ahora) → enviar al padre como File (sin base64)
      const pdfs = all.filter((f) => f.type === 'application/pdf');
      if (pdfs.length) {
        pdfs.forEach((pdf) => {
          onAttachDocument(pdf); // compat: una llamada por cada PDF
        });
      }

      // 3) Si hay otros tipos no soportados, avisa
      const unsupported = all.filter(
        (f) => !f.type.startsWith('image/') && f.type !== 'application/pdf'
      );
      if (unsupported.length) {
        alert(
          t(
            'error.unsupportedFile',
            'Por ahora solo se admiten imágenes y PDFs.'
          )
        );
      }
    },
    [encodeAndPushImage, onAttachDocument, t]
  );

  // 3) (Opcional, recomendado) Restringir documentos a PDF
  const documentAcceptTypes = '.pdf';
  const combinedAcceptTypes = useMemo(() => {
    return [...acceptMediaType, documentAcceptTypes].join(',');
  }, [acceptMediaType]);

  useEffect(() => {
    const currentElem = inputRef?.current;
    const keypressListener = (e: DocumentEventMap['keypress']) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();

        if (!disabledSend) {
          sendContent();
        }
      }
    };
    currentElem?.addEventListener('keypress', keypressListener);

    const pasteListener = (e: DocumentEventMap['paste']) => {
      handleFileSelection(e.clipboardData?.files ?? new DataTransfer().files);
    };
    currentElem?.addEventListener('paste', pasteListener);

    return () => {
      currentElem?.removeEventListener('keypress', keypressListener);
      currentElem?.removeEventListener('paste', pasteListener);
    };
  });

  const onDragOver: React.DragEventHandler<HTMLDivElement> = useCallback(
    (e) => {
      e.preventDefault();
    },
    []
  );

  const onDrop: React.DragEventHandler<HTMLDivElement> = useCallback(
    (e) => {
      e.preventDefault();
      handleFileSelection(e.dataTransfer.files);
    },
    [handleFileSelection]
  );

  return (
    <>
      {props.dndMode && (
        <div
          className="fixed left-0 top-0 h-full w-full bg-black/40"
          onDrop={onDrop}></div>
      )}
      <div
        ref={inputRef}
        onDragOver={onDragOver}
        onDrop={onDrop}
        className={twMerge(
          props.className,
          'relative mb-7 flex w-11/12 flex-col rounded-xl border border-black/10 bg-white shadow-[0_0_30px_7px] shadow-light-gray/15 md:w-10/12 lg:w-4/6 xl:w-3/6'
        )}>
        {/* UI para mostrar el nombre del documento adjunto */}
        {attachedFileName && (
          <div className="flex items-center justify-between p-2 text-sm border-b border-gray-200 bg-gray-50 rounded-t-xl">
            <span className="text-gray-600 truncate">
              {t('bot.label.attached', 'Adjunto')}: {attachedFileName}
            </span>
            <ButtonIcon
              className="text-gray-500 hover:text-red-500"
              onClick={onRemoveAttachedFile}>
              <PiX />
            </ButtonIcon>
          </div>
        )}

        <div className="flex w-full">
          <Textarea
            className={twMerge(
              'm-1 bg-transparent scrollbar-thin scrollbar-thumb-light-gray pr-12'
            )}
            placeholder={props.placeholder ?? t('app.inputMessage')}
            disabled={props.disabled}
            noBorder
            value={content}
            onChange={setContent}
          />
        </div>

        <div className="absolute bottom-0 right-0 flex items-center">
          {/* 1) Permitir seleccionar varios archivos en el picker */}
          <ButtonFileChoose
            disabled={postingMessage || false} // ya no bloquees por hasAttachment
            icon
            accept={combinedAcceptTypes}
            onChange={handleFileSelection}
            className="m-1 text-gray-600 hover:text-black">
            <PiPaperclip size={20} />
          </ButtonFileChoose>

          <ButtonSend
            className="m-2 align-bottom"
            disabled={disabledSend || props.disabled}
            loading={postingMessage}
            onClick={sendContent}
          />
        </div>

        {/* UI para mostrar las imágenes adjuntas */}
        {base64EncodedImages.length > 0 && (
          <div className="relative m-2 mr-24 flex flex-wrap gap-3">
            {base64EncodedImages.map((imageFile, idx) => (
              <div key={idx} className="relative">
                <img
                  src={imageFile}
                  className="h-16 rounded border border-aws-squid-ink"
                  onClick={() => {
                    setPreviewImageUrl(imageFile);
                    setIsOpenPreviewImage(true);
                  }}
                  alt={`preview ${idx}`}
                />
                <ButtonIcon
                  className="absolute right-0 top-0 -m-2 border border-aws-sea-blue bg-white p-1 text-xs text-aws-sea-blue"
                  onClick={() => {
                    removeBase64EncodedImage(idx);
                  }}>
                  <PiX />
                </ButtonIcon>
              </div>
            ))}
            {disabledImageUpload && (
              <div className="absolute -m-2 flex h-[120%] w-[110%] items-center justify-center bg-black/30">
                <div className="rounded bg-light-red p-3 text-sm text-aws-font-color">
                  {t('error.notSupportedImage')}
                </div>
              </div>
            )}
            <ModalDialog
              isOpen={isOpenPreviewImage}
              onClose={() => setIsOpenPreviewImage(false)}
              onAfterLeave={() => setPreviewImageUrl(null)}
              widthFromContent={true}>
              {previewImageUrl && (
                <img
                  src={previewImageUrl}
                  className="mx-auto max-h-[80vh] max-w-full rounded-md"
                  alt="Preview"
                />
              )}
            </ModalDialog>
          </div>
        )}

        {messages.some((m) => m.role === 'assistant') && (
          <div className="absolute -top-14 right-0 flex gap-2">
            {/**Modal de Referencias */}
            {/* --- DESCOMENTADO: Se vuelve a activar el modal del código antiguo --- */}
            {showHelpfulInfo && <HelpfulInfoModal />}

            {/* Botón de Regenerar */}
            {/*  <Button
              className="bg-aws-paper p-2 text-sm"
              outlined
              disabled={props.disabled || postingMessage}
              onClick={props.onRegenerate}
            >
            <PiArrowsCounterClockwise className="mr-2" />
              {t('button.regenerate')}
            </Button> */}
          </div>
        )}
      </div>
    </>
  );
};

export default InputChatContent;