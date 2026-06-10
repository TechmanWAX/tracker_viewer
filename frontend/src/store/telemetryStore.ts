import { create } from 'zustand';
import type { TelemetryPoint } from '../types/telemetry';

interface TelemetryState {
  points: TelemetryPoint[];
  totalPoints: number;
  currentIndex: number;
  isPlaying: boolean;
  speed: number;
  hoverMs: number | null;
  setPoints: (points: TelemetryPoint[], total?: number) => void;
  setCurrentIndex: (i: number) => void;
  setIsPlaying: (v: boolean) => void;
  setSpeed: (s: number) => void;
  setHoverMs: (ms: number | null) => void;
}

export const useTelemetryStore = create<TelemetryState>((set) => ({
  points: [],
  totalPoints: 0,
  currentIndex: 0,
  isPlaying: false,
  speed: 1,
  hoverMs: null,
  setPoints: (points, total?) =>
    set({ points, totalPoints: total ?? points.length, currentIndex: 0, hoverMs: null }),
  setCurrentIndex: (i) => set({ currentIndex: i }),
  setIsPlaying: (v) => set({ isPlaying: v }),
  setSpeed: (s) => set({ speed: s }),
  setHoverMs: (ms) => set({ hoverMs: ms }),
}));
