import React from 'react';
import {AbsoluteFill} from 'remotion';
import {BODY, C, ensureFonts, HEAD, MapData} from './theme';

type P = {variant: number; text: string; kicker: string; focus: string | null; map: MapData; brand: string};

const Island: React.FC<{map: MapData; w: number; h: number; cx: number; cy: number; scale: number; pin?: string | null}> = ({map, w, h, cx, cy, scale, pin}) => {
  const p = pin ? map.places[pin] : null;
  const inv = 1 / scale;
  return (
    <svg width={w} height={h} style={{position: 'absolute', left: 0, top: 0}}>
      <defs>
        <filter id="tsh" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy={8 * inv} stdDeviation={14 * inv} floodColor="#000" floodOpacity="0.5" />
        </filter>
      </defs>
      <g transform={`translate(${cx},${cy}) scale(${scale}) translate(${-map.w / 2},${-map.h / 2})`}>
        {[1.12, 1.28].map((r, i) => (
          <path key={i} d={map.path} fill="none" stroke={C.foam} strokeOpacity={0.25 - i * 0.1} strokeWidth={3 * inv}
            transform={`translate(${map.w / 2},${map.h / 2}) scale(${r}) translate(${-map.w / 2},${-map.h / 2})`} />
        ))}
        <path d={map.path} fill={C.sand} stroke={C.white} strokeWidth={5 * inv} filter="url(#tsh)" />
        {p ? <circle cx={p.x} cy={p.y} r={16 * inv} fill={C.coral} stroke={C.white} strokeWidth={6 * inv} /> : null}
      </g>
    </svg>
  );
};

export const Thumb: React.FC<P> = ({variant, text, kicker, focus, map, brand}) => {
  ensureFonts();
  const W = 1280;
  const H = 720;
  const lines = text.split('\n');
  if (variant === 2) {
    return (
      <AbsoluteFill style={{background: `radial-gradient(circle at 60% 50%, ${C.sea}, ${C.ink})`}}>
        <Island map={map} w={W} h={H} cx={W * 0.62} cy={H * 0.5} scale={0.9} pin={focus} />
        <div style={{position: 'absolute', left: 50, top: 120, background: C.sun, padding: '18px 34px 6px 34px', transform: 'rotate(-3deg)'}}>
          {lines.map((l, i) => <div key={i} style={{fontFamily: HEAD, fontSize: 170, lineHeight: 0.9, color: C.ink}}>{l}</div>)}
        </div>
        {kicker ? <div style={{position: 'absolute', left: 60, bottom: 60, fontFamily: BODY, fontWeight: 800, fontSize: 46, color: C.white}}>{kicker}</div> : null}
        <div style={{position: 'absolute', right: 40, top: 30, fontFamily: BODY, fontWeight: 700, fontSize: 24, letterSpacing: 5, color: C.white, opacity: 0.8}}>{brand}</div>
      </AbsoluteFill>
    );
  }
  if (variant === 3) {
    return (
      <AbsoluteFill style={{background: 'linear-gradient(180deg, #3b2c5a 0%, #ff9a62 58%, #2ec4b6 58%, #0a3a4a 100%)'}}>
        <div style={{position: 'absolute', left: W * 0.62, top: H * 0.22, width: 230, height: 230, borderRadius: 999, background: C.sun}} />
        <div style={{position: 'absolute', left: 0, right: 0, top: H * 0.58, height: 8, background: 'rgba(255,255,255,0.5)'}} />
        <div style={{position: 'absolute', left: 60, top: 90}}>
          {lines.map((l, i) => <div key={i} style={{fontFamily: HEAD, fontSize: 180, lineHeight: 0.88, color: C.white,
            textShadow: '0 8px 0 rgba(13,27,36,0.85)'}}>{l}</div>)}
        </div>
        {kicker ? <div style={{position: 'absolute', left: 64, bottom: 54, fontFamily: BODY, fontWeight: 800, fontSize: 46, color: C.white,
          background: 'rgba(13,27,36,0.8)', padding: '8px 20px', borderRadius: 12}}>{kicker}</div> : null}
        <div style={{position: 'absolute', right: 40, top: 30, fontFamily: BODY, fontWeight: 700, fontSize: 24, letterSpacing: 5, color: C.white, opacity: 0.85}}>{brand}</div>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{background: `linear-gradient(120deg, ${C.deep} 0%, ${C.sea} 100%)`}}>
      <Island map={map} w={W} h={H} cx={W * 0.8} cy={H * 0.55} scale={0.72} pin={focus} />
      <div style={{position: 'absolute', left: 60, top: 110}}>
        {lines.map((l, i) => <div key={i} style={{fontFamily: HEAD, fontSize: 176, lineHeight: 0.88, color: i === lines.length - 1 ? C.sun : C.white,
          textShadow: '0 6px 24px rgba(0,0,0,0.45)'}}>{l}</div>)}
      </div>
      {kicker ? <div style={{position: 'absolute', left: 64, bottom: 60, fontFamily: BODY, fontWeight: 800, fontSize: 44, color: C.ink,
        background: C.white, padding: '8px 20px', borderRadius: 12}}>{kicker}</div> : null}
      <div style={{position: 'absolute', right: 40, top: 30, fontFamily: BODY, fontWeight: 700, fontSize: 24, letterSpacing: 5, color: C.white, opacity: 0.8}}>{brand}</div>
    </AbsoluteFill>
  );
};
