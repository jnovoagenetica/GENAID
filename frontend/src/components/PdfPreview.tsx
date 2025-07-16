import React from 'react';
import { Document, Page, pdfjs } from 'react-pdf';

// Importamos el worker usando '?url'.
// Vite procesará el archivo y nos devolverá su URL pública como un string.
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

// Ahora le pasamos la URL (el string) que obtuvimos de la importación.
// Esto satisface tanto a TypeScript como a react-pdf.
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

interface PdfPreviewProps {
  file: File;
}

const PdfPreview: React.FC<PdfPreviewProps> = ({ file }) => {
  function onDocumentLoadError(error: Error) {
    console.error('[PdfPreview] Error DETALLADO al cargar el documento PDF:', error.message);
  }

  if (!file) {
    return null; 
  }

  return (
    <div className="w-full h-full flex items-center justify-center bg-gray-200 overflow-hidden">
      <Document
        file={file}
        loading={<div className="text-xs p-1">Cargando...</div>}
        error={<div className="text-xs text-red-500 p-1">Error al cargar PDF</div>}
        onLoadError={onDocumentLoadError}
        className="flex items-center justify-center"
      >
        <Page
          pageNumber={1}
          width={64}
          renderTextLayer={false}
          renderAnnotationLayer={false}
        />
      </Document>
    </div>
  );
};

export default PdfPreview;