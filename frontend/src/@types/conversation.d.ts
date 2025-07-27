export type Role = 'system' | 'assistant' | 'user';
export type Model =
  | 'claude-instant-v1'
  | 'claude-v2'
  | 'claude-v3-opus'
  | 'claude-v3-sonnet'
  | 'claude-v3-haiku'
  |  'claude-v3.5-sonnet'
  | 'mistral-7b-instruct'
  | 'mixtral-8x7b-instruct'
  | 'mistral-large';

// --- INICIO DE LA MODIFICACIÓN CLAVE ---
// Hemos convertido 'Content' en una "unión discriminada".
// Esto permite que el objeto tenga diferentes propiedades obligatorias
// dependiendo del valor de 'contentType'.

export type Content =
  | {
      contentType: 'text';
      body: string;
      mediaType?: string; // El mediaType es opcional para el texto
    }
  | {
      contentType: 'image';
      body: string; // Contenido en Base64
      mediaType: string; // ej. 'image/png'
    }
  | {
      contentType: 'attachment';
      body: string; // Contenido en Base64
      mediaType: string; // ej. 'application/pdf'
      file_name?: string; // La propiedad que faltaba para el nombre del archivo
    };
// --- FIN DE LA MODIFICACIÓN CLAVE ---

export type MessageContent = {
  role: Role;
  content: Content[];
  model: Model;
  feedback: null | Feedback;
};

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

export type PostMessageRequest = {
  conversationId?: string;
  message: MessageContent & {
    parentMessageId: null | string;
  };
  botId?: string;
};

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