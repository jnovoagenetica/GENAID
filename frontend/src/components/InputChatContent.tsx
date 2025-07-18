// src/components/InputChatContent.tsx

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
import { PiX } from 'react-icons/pi';
//import { TbPhotoPlus } from 'react-icons/tb'; // Cambiaremos esto por un ícono más genérico
import { PiFile } from 'react-icons/pi'; // Ícono más genérico para archivos
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
import PdfPreview from './PdfPreview'; // Importamos el nuevo componente

// --- MODIFICACIÓN CLAVE 1: Actualizamos la firma de `onSend` ---
type Props = BaseProps & {
  disabledSend?: boolean;
  disabled?: boolean;
  placeholder?: string;
  dndMode?: boolean;
  onSend: (
    content: string,
    options?: { // El segundo argumento ahora es un objeto de opciones
      base64EncodedImages?: string[];
      pdfFiles?: File[];
    }
  ) => void;
  onRegenerate: () => void;
};
// ---------------------------------------------------------------

// --- MODIFICACIÓN: Creamos una interfaz para el archivo adjunto
interface AttachedFile {
  // Guardamos el archivo original para PDFs y para procesar imágenes
  file: File;
  type: 'image' | 'pdf';
  // Guardamos el base64 solo para las imágenes, como antes
  base64: string | null;
}

const MAX_IMAGE_WIDTH = 800;
const MAX_IMAGE_HEIGHT = 800;

// --- CORRECCIÓN: Restauramos el contenido completo del estado de Zustand ---
const useInputChatContentState = create<{
  attachedFiles: AttachedFile[];
  addFile: (file: AttachedFile) => void;
  removeFile: (index: number) => void;
  clearFiles: () => void;
  previewImageUrl: string | null;
  setPreviewImageUrl: (url: string | null) => void;
  isOpenPreviewImage: boolean;
  setIsOpenPreviewImage: (isOpen: boolean) => void;
}>((set, get) => ({
  attachedFiles: [],
  addFile: (file) => {
    set({
      attachedFiles: produce(get().attachedFiles, (draft) => {
        // Evitar duplicados por nombre de archivo
        if (!draft.some(f => f.file.name === file.file.name)) {
          draft.push(file);
        }
      }),
    });
  },
  removeFile: (index) => {
    set({
      attachedFiles: produce(get().attachedFiles, (draft) => {
        draft.splice(index, 1);
      }),
    });
  },
  clearFiles: () => {
    set({
      attachedFiles: [],
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
// -------------------------------------------------------------------------

const InputChatContent: React.FC<Props> = (props) => {
  const [showHelpfulInfo] = useState(true);
  const { t } = useTranslation();
  const { postingMessage, hasError, messages } = useChat();
  const { disabledImageUpload, model, acceptMediaType } = useModel();

  const [content, setContent] = useState('');
  
  // --- MODIFICACIÓN: Usamos el nuevo estado de Zustand
  const {
    attachedFiles,
    addFile,
    removeFile,
    clearFiles,
    previewImageUrl,
    setPreviewImageUrl,
    isOpenPreviewImage,
    setIsOpenPreviewImage,
  } = useInputChatContentState();

  useEffect(() => {
    clearFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const disabledSend = useMemo(() => {
    // El botón de enviar se activa si hay texto O si hay archivos adjuntos
    return (content.trim() === '' && attachedFiles.length === 0) || props.disabledSend || hasError;
  }, [hasError, content, props.disabledSend, attachedFiles.length]);

  const inputRef = useRef<HTMLDivElement>(null);

  // --- MODIFICACIÓN CLAVE 2: Actualizamos `sendContent` para enviar los PDFs ---
  const sendContent = useCallback(() => {
    // Recopilamos las imágenes como antes
    const base64EncodedImages = attachedFiles
      .filter((f) => f.type === 'image' && f.base64)
      .map((f) => f.base64!);

    // Recopilamos los archivos PDF
    const pdfFiles = attachedFiles
      .filter((f) => f.type === 'pdf')
      .map((f) => f.file);

    if (pdfFiles.length > 0) {
      console.log("Preparando para enviar los siguientes PDFs:", pdfFiles.map(f => f.name));
    }

    // Llamamos a `props.onSend` con la nueva estructura de datos
    props.onSend(content, {
      base64EncodedImages: !disabledImageUpload && base64EncodedImages.length > 0 ? base64EncodedImages : undefined,
      pdfFiles: pdfFiles.length > 0 ? pdfFiles : undefined,
    });

    // Limpiamos todo después de enviar
    setContent('');
    clearFiles();
  }, [
    attachedFiles,
    clearFiles,
    content,
    disabledImageUpload,
    props,
  ]);
  // -------------------------------------------------------------------------
  
  // --- MODIFICACIÓN: Creamos una función para manejar tanto imágenes como PDFs
  const processAndAddFile = useCallback(
    (file: File) => {
      // Si es PDF, lo añadimos directamente
      if (file.type === 'application/pdf') {
        addFile({
          file: file,
          type: 'pdf',
          base64: null,
        });
        return;
      }

      // Si es imagen, la procesamos a base64 como antes
      if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.readAsArrayBuffer(file);
        reader.onload = () => {
          if (!reader.result) {
            return;
          }
  
          const img = new Image();
          img.src = URL.createObjectURL(new Blob([reader.result]));
          img.onload = async () => {
            const width = img.naturalWidth;
            const height = img.naturalHeight;
  
            const aspectRatio = width / height;
            let newWidth;
            let newHeight;
            if (aspectRatio > 1) {
              newWidth = width > MAX_IMAGE_WIDTH ? MAX_IMAGE_WIDTH : width;
              newHeight = width > MAX_IMAGE_WIDTH ? MAX_IMAGE_WIDTH / aspectRatio : height;
            } else {
              newHeight = height > MAX_IMAGE_HEIGHT ? MAX_IMAGE_HEIGHT : height;
              newWidth = height > MAX_IMAGE_HEIGHT ? MAX_IMAGE_HEIGHT * aspectRatio : width;
            }
  
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            canvas.width = newWidth;
            canvas.height = newHeight;
            ctx?.drawImage(img, 0, 0, newWidth, newHeight);
  
            const resizedImageData = canvas.toDataURL('image/png');
            
            // Añadimos el archivo completo al estado
            addFile({
              file: file,
              type: 'image',
              base64: resizedImageData,
            });
          };
        };
      }
    },
    [addFile]
  );

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
      const clipboardItems = e.clipboardData?.items;
      if (!clipboardItems || clipboardItems.length === 0) {
        return;
      }

      for (let i = 0; i < clipboardItems.length; i++) {
        // --- MODIFICACIÓN: Permitimos pegar PDFs también
        if (model?.supportMediaType.includes(clipboardItems[i].type) || clipboardItems[i].type === 'application/pdf') {
          const pastedFile = clipboardItems[i].getAsFile();
          if (pastedFile) {
            processAndAddFile(pastedFile);
            e.preventDefault();
          }
        }
      }
    };
    currentElem?.addEventListener('paste', pasteListener);

    return () => {
      currentElem?.removeEventListener('keypress', keypressListener);
      currentElem?.removeEventListener('paste', pasteListener);
    };
  });

  // --- MODIFICACIÓN: La función de cambio ahora usa `processAndAddFile`
  const onChangeFile = useCallback(
    (fileList: FileList) => {
      for (let i = 0; i < fileList.length; i++) {
        const file = fileList.item(i);
        if (file) {
          processAndAddFile(file);
        }
      }
    },
    [processAndAddFile]
  );

  const onDragOver: React.DragEventHandler<HTMLDivElement> = useCallback(
    (e) => {
      e.preventDefault();
    },
    []
  );

  const onDrop: React.DragEventHandler<HTMLDivElement> = useCallback(
    (e) => {
      e.preventDefault();
      onChangeFile(e.dataTransfer.files);
    },
    [onChangeFile]
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
        <div className="flex w-full">
          <Textarea
            className={twMerge(
              'm-1  bg-transparent scrollbar-thin scrollbar-thumb-light-gray',
              disabledImageUpload ? 'pr-6' : 'pr-12'
            )}
            placeholder={props.placeholder ?? t('app.inputMessage')}
            disabled={props.disabled}
            noBorder
            value={content}
            onChange={setContent}
          />
        </div>
        <div className="absolute bottom-0 right-0 flex items-center">
          {!disabledImageUpload && (
            <ButtonFileChoose
              disabled={postingMessage}
              icon
              // --- MODIFICACIÓN: Aceptamos imágenes y PDFs
              accept={`${acceptMediaType.join(',')},.pdf`}
              onChange={onChangeFile}>
              {/* Usamos un ícono más genérico */}
              <PiFile /> 
            </ButtonFileChoose>
          )}
          <ButtonSend
            className="m-2 align-bottom"
            disabled={disabledSend || props.disabled}
            loading={postingMessage}
            onClick={sendContent}
          />
        </div>
        
        {/* --- MODIFICACIÓN: Renderizado de la nueva lista de archivos */}
        {attachedFiles.length > 0 && (
          <div className="relative m-2 mr-24 flex flex-wrap gap-3">
            {attachedFiles.map((item, idx) => (
              <div key={idx} className="relative">
                <div className="h-16 w-16 rounded border border-aws-squid-ink overflow-hidden flex items-center justify-center">
                  {item.type === 'image' && item.base64 && (
                    <img
                      src={item.base64}
                      className="h-full w-full object-cover cursor-pointer"
                      onClick={() => {
                        setPreviewImageUrl(item.base64);
                        setIsOpenPreviewImage(true);
                      }}
                      alt={item.file.name}
                    />
                  )}
                  {item.type === 'pdf' && (
                     <PdfPreview file={item.file} />
                  )}
                </div>
                <ButtonIcon
                  className="absolute right-0 top-0 -m-2 border border-aws-sea-blue bg-white p-1 text-xs text-aws-sea-blue"
                  onClick={() => {
                    removeFile(idx);
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
                  alt='Preview'
                />
              )}
            </ModalDialog>
          </div>
        )}
        
        {messages.some((m) => m.role === 'assistant') && (
          <div className="absolute -top-14 right-0 flex gap-2">
      
            {/**Modal de Referencias */}
            {showHelpfulInfo && (
              <HelpfulInfoModal />
            )}

          {/* Botón de Regenerar */}
          {/*  <Button
            className="bg-aws-paper p-2 text-sm"
            outlined
            disabled={disabledRegenerate || props.disabled}
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