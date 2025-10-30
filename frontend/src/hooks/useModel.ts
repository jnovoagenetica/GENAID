import { create } from 'zustand';
import { Model } from '../@types/conversation';
import { useMemo } from 'react';

const availableModels = [
  {
    modelId: 'claude-v4.5-sonnet',
    label: 'Claude Sonnet 4.5',
    supportMediaType: [
      'image/jpeg',
      'image/png',
      'image/gif',
      'image/webp',
      'application/pdf', // opcional si aceptas PDF desde UI
    ],
  },
];

const useModelState = create<{
  modelId: Model;
  setModelId: (m: Model) => void;
}>((set) => ({
  modelId: 'claude-v4.5-sonnet',
  setModelId: (m) => {
    set({ modelId: m });
  },
}));

const useModel = () => {
  const { modelId, setModelId } = useModelState();

  const model = useMemo(() => {
    return availableModels.find((m) => m.modelId === modelId);
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
