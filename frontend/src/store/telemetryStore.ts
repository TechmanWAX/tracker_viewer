import { create } from 'zustand';
import type { TelemetryPoint } from '../types/telemetry';

interface TelemetryState {
  points: TelemetryPoint[];
  // Total points in the trip (from backend COUNT). The store only
  // holds up to API_FETCH_LIMIT_OVERVIEW points (currently 50k),
  // so this is the "of Y" in the map overlay's "X of Y pts".
  totalPoints: number;
  currentIndex: number;
  isPlaying: boolean;
  speed: number;
  setPoints: (points: TelemetryPoint[], total?: number) => void;
  setCurrentIndex: (i: number) => void;
  setIsPlaying: (v: boolean) => void;
  setSpeed: (s: number) => void;
}

export const useTelemetryStore = create<TelemetryState>((set) => ({
  points: [],
  totalPoints: 0,
  currentIndex: 0,
  isPlaying: false,
  speed: 1,
  setPoints: (points, total?) => set({ points, totalPoints: total ?? points.length, currentIndex: 0 }),
  setCurrentIndex: (i) => set({ currentIndex: i }),
  setIsPlaying: (v) => set({ isPlaying: v }),
  setSpeed: (s) => set({ speed: s }),
}));
