import { create } from "zustand";

const useDrawerState = create<{
  opened: boolean;
  switchOpen: (value?: boolean) => void;
}>((set) => ({
  opened: false,
  switchOpen: (value?: boolean) => {
    if (typeof value === "boolean") {
      set({ opened: value });
    } else {
      set((state) => ({ opened: !state.opened }));
    }
  },
}));

const useDrawer = () => {
  const [opened, switchOpen] = useDrawerState((state) => [
    state.opened,
    state.switchOpen,
  ]);

  return {
    opened,
    switchOpen,
  };
};

export default useDrawer;
