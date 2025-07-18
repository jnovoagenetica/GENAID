import React from 'react';
import { Document, Page, pdfjs } from 'react-pdf';

import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

// ✅ Worker local para evitar errores de Cloudflare
import workerSrc from 'pdfjs-dist/build/pdf.worker.min?url';
pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

interface PdfPreviewProps {
  file: File;
}

const PdfPreview: React.FC<PdfPreviewProps> = ({ file }) => {
  function onDocumentLoadError(error: Error) {
    console.error('[PdfPreview] Error al cargar PDF:', error.message);
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
