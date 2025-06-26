import { create } from 'zustand';
import { Model } from '../@types/conversation';
import { useMemo } from 'react';

// Solo Claude 3.5 (Sonnet) disponible
const availableModels = [
  {
    modelId: 'claude-v3.5-sonnet',
    label: 'Claude 3.5 (Sonnet)',
    supportMediaType: ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
  },
];

const useModelState = create<{
  modelId: Model;
  setModelId: (m: Model) => void;
}>((_set) => ({
  modelId: 'claude-v3.5-sonnet',
  setModelId: (_m) => {
    console.warn('Cambio de modelo bloqueado. Solo se permite Claude 3.5 (Sonnet).');
  },
}));

const useModel = () => {
  const { modelId, setModelId } = useModelState();

  const model = useMemo(() => {
    return availableModels.find((model) => model.modelId === modelId);
  }, [modelId]);

  return {
    modelId,
    setModelId,
    model,
    disabledImageUpload: (model?.supportMediaType.length ?? 0) === 0,
    acceptMediaType:
      model?.supportMediaType.map(
        (mediaType) => `.${mediaType.split('/')[1]}`
      ) ?? [],
    availableModels,
  };
};

export default useModel;
