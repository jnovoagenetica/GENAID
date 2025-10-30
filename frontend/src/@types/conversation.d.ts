export type Role = 'system' | 'assistant' | 'user';
export type Model =
  | 'claude-v4.5-sonnet' 
  | 'claude-instant-v1'
  | 'claude-v2'
  | 'claude-v3-opus'
  | 'claude-v3-sonnet'
  | 'claude-v3-haiku'
  | 'claude-v3.5-sonnet'
  | 'mistral-7b-instruct'
  | 'mixtral-8x7b-instruct'
  | 'mistral-large';

// --- INICIO DE CAMBIOS ---

// 1. Definimos un tipo específico para cada bloque de contenido.
//    Esto nos permite tener propiedades obligatorias diferentes para cada tipo.

// Bloque de texto: solo necesita `body`.
type TextContent = {
  contentType: 'text';
  body: string;
};

// Bloque de imagen: necesita `body` (base64) y `mediaType`.
type ImageContent = {
  contentType: 'image';
  body: string;
  mediaType: string;
};

// Bloque de adjunto: necesita `body` (base64), `mediaType` y el `fileName`.
// Esto coincide con lo que el backend espera.
type AttachmentContent = {
  contentType: 'textAttachment';
  body: string;
  mediaType: string;
  fileName: string;
};

// 2. Creamos una "unión discriminada". `ContentBlock` puede ser cualquiera de los tipos de arriba.
//    TypeScript sabrá qué propiedades esperar basándose en el valor de `contentType`.
export type ContentBlock = TextContent | ImageContent | AttachmentContent;

// 3. El antiguo tipo `Content` ya no es necesario.
// export type Content = { ... }; // <- ELIMINADO

// 4. Actualizamos `MessageContent` para que use nuestro nuevo tipo `ContentBlock`.
export type MessageContent = {
  role: Role;
  content: ContentBlock[]; // <- Usamos nuestro nuevo tipo unión aquí.
  model: Model;
  feedback: null | Feedback;
};

// --- FIN DE CAMBIOS ---

export type RelatedDocument = {
  chunkBody: string;
  contentType: 's3' | 'url';
  sourceLink: string;
  rank: number;
};

export type DisplayMessageContent = MessageContent & {
  id: string;
  parent: null | string;
  children: string[];
  sibling: string[];
};

// --- CAMBIO APLICADO AQUÍ ---
export type PostMessageRequest = {
  conversationId?: string;
  message: MessageContent & {
    parentMessageId: null | string;
  };
  botId?: string;
  files?: File[]; // Esta línea se puede eliminar si ya no usas multipart/form-data
  
  // 👇 PROPIEDAD AÑADIDA PARA SOLUCIONAR EL ERROR
  filesBase64?: { fileName: string; mediaType: string; base64: string }[];
};
// --- FIN DEL CAMBIO ---

export type PostMessageResponse = {
  conversationId: string;
  createTime: number;
  message: MessageContent;
};

export type GetRelatedDocumentsRequest = {
  conversationId: string;
  message: MessageContent & {
    parentMessageId: null | string;
  };
  botId: string;
};

export type GetRelatedDocumentsResponse = RelatedDocument[] | null;

export type ConversationMeta = {
  id: string;
  title: string;
  createTime: number;
  lastMessageId: string;
  model: Model;
  botId?: string;
};

export type MessageMap = {
  [messageId: string]: MessageContent & {
    children: string[];
    parent: null | string;
  };
};

export type Conversation = ConversationMeta & {
  messageMap: MessageMap;
};

export type PutFeedbackRequest = {
  thumbsUp: boolean;
  category: null | string;
  comment: null | string;
};

export type Feedback = {
  thumbsUp: boolean;
  category: string;
  comment: string;
};