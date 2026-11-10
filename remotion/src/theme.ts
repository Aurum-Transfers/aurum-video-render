import {loadFont} from '@remotion/fonts';
import {staticFile} from 'remotion';

export const C = {
  ink: '#0d1b24',
  deep: '#0a3a4a',
  sea: '#0f6e7f',
  turq: '#2ec4b6',
  foam: '#cbf3f0',
  sand: '#f6e3b4',
  sandDark: '#e3c27f',
  coral: '#ff7a59',
  sun: '#ffd166',
  white: '#ffffff',
  green: '#7fb069',
  cactus: '#4f7d5b',
  rock: '#b8a27a',
};

export const HEAD = 'Bebas Neue, Impact, sans-serif';
export const BODY = 'Montserrat, Arial, sans-serif';

let loaded = false;
export const ensureFonts = () => {
  if (loaded) return;
  loaded = true;
  loadFont({family: 'Bebas Neue', url: staticFile('fonts/BebasNeue-Regular.ttf')});
  loadFont({family: 'Montserrat', url: staticFile('fonts/Montserrat.ttf'), weight: '100 900'});
};

export type Place = {x: number; y: number; label: string};
export type MapData = {path: string; w: number; h: number; places: Record<string, Place>; credit: string};

export type Shot = {
  type: string;
  from: number;
  dur: number;
  key: string;
  [k: string]: any;
};

export type Timeline = {
  unit: string;
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  portrait: boolean;
  title: string;
  map: MapData;
  shots: Shot[];
  chapters: {from: number; dur: number; index: number; title: string}[];
  lowerThirds: {from: number; dur: number; title: string; sub?: string}[];
  disclosure: {from: number; dur: number; text: string};
  captions: {from: number; dur: number; text: string}[];
  endCard: {from: number; dur: number; title: string; lines: string[]};
  brand: string;
};

// deterministic pseudo-random (no Math.random in renders)
export const rand = (seed: number) => {
  const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
