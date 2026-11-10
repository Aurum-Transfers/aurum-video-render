// Overlay-only layer on a transparent background (post-Bali spec, 10 Nov 2026).
// Items are laid out back to back in a strip; tools/title_runner.py places each one over real footage with ffmpeg.
import React from 'react';
import {AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {MapScene} from './scenes';
import {BODY, C, ensureFonts, HEAD, MapData} from './theme';

const clamp = {extrapolateLeft: 'clamp' as const, extrapolateRight: 'clamp' as const};
export type OItem = {kind: string; from: number; dur: number; text?: string; sub?: string; number?: number; badge?: string;
  route?: string[]; focus?: string; focusFrom?: string; lines?: string[]};
export type OStrip = {fps: number; width: number; height: number; durationInFrames: number; portrait: boolean; items: OItem[]; map: MapData; brand: string};

const io = (f: number, d: number, k = 10) => interpolate(f, [0, k, d - k, d], [0, 1, 1, 0], clamp);

const Chapter: React.FC<{it: OItem; p: boolean}> = ({it, p}) => {
  const f = useCurrentFrame(); const {fps, width} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 200}});
  return (
    <div style={{position: 'absolute', left: 0, bottom: p ? '38%' : 150, opacity: io(f, it.dur, 8), transform: `translateX(${(s - 1) * width * 0.5}px)`,
      background: 'rgba(13,27,36,0.82)', padding: p ? '26px 50px 30px 50px' : '22px 60px 28px 80px', borderLeft: `14px solid ${C.turq}`, borderRadius: '0 20px 20px 0', maxWidth: p ? '92%' : '58%'}}>
      <div style={{fontFamily: BODY, fontWeight: 700, fontSize: p ? 30 : 26, color: C.turq, letterSpacing: 6}}>CHAPTER {String(it.number ?? 0).padStart(2, '0')}</div>
      <div style={{fontFamily: HEAD, fontSize: p ? 84 : 86, color: C.white, lineHeight: 1}}>{it.text}</div>
    </div>
  );
};

const Prompt: React.FC<{it: OItem; p: boolean}> = ({it, p}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 14, stiffness: 160}});
  const pulse = 1 + 0.04 * Math.sin(f / 5);
  return (
    <div style={{position: 'absolute', right: p ? 40 : 70, top: p ? 260 : 110, opacity: io(f, it.dur, 8), transform: `scale(${(0.6 + 0.4 * s)})`, transformOrigin: 'top right',
      display: 'flex', alignItems: 'center', gap: 18, background: 'rgba(255,255,255,0.96)', borderRadius: 60, padding: '14px 30px 14px 14px', boxShadow: '0 10px 30px rgba(0,0,0,0.35)', maxWidth: p ? 980 : 880}}>
      <div style={{background: C.coral, color: C.white, fontFamily: HEAD, fontSize: p ? 40 : 36, borderRadius: 40, padding: '8px 22px', transform: `scale(${pulse})`, whiteSpace: 'nowrap'}}>{it.badge || 'COMMENT'}</div>
      <div style={{fontFamily: BODY, fontWeight: 700, fontSize: p ? 36 : 32, color: C.ink, lineHeight: 1.2}}>{it.text}</div>
    </div>
  );
};

const Lower: React.FC<{it: OItem; p: boolean}> = ({it, p}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 200}});
  return (
    <div style={{position: 'absolute', left: p ? 50 : 90, ...(p ? {top: 420} : {bottom: 120}), opacity: io(f, it.dur, 10), transform: `translateY(${(1 - s) * 30}px)`, display: 'flex'}}>
      <div style={{width: 12, background: C.coral, borderRadius: 6}} />
      <div style={{background: 'rgba(255,255,255,0.95)', padding: '14px 28px 16px 24px', borderRadius: '0 14px 14px 0', clipPath: `inset(0 ${(1 - s) * 100}% 0 0)`}}>
        <div style={{fontFamily: HEAD, fontSize: p ? 60 : 56, color: C.deep, lineHeight: 1}}>{it.text}</div>
        {it.sub ? <div style={{fontFamily: BODY, fontWeight: 600, fontSize: p ? 28 : 24, color: C.ink, marginTop: 4}}>{it.sub}</div> : null}
      </div>
    </div>
  );
};

const Disclosure: React.FC<{it: OItem; p: boolean}> = ({it, p}) => {
  const f = useCurrentFrame();
  return (
    <div style={{position: 'absolute', left: p ? 40 : 160, right: p ? 40 : 160, ...(p ? {top: 300} : {bottom: 40}), opacity: io(f, it.dur, 12),
      background: 'rgba(13,27,36,0.86)', border: `3px solid ${C.sun}`, borderRadius: 16, padding: '14px 26px', display: 'flex', gap: 20, alignItems: 'center'}}>
      <div style={{fontFamily: HEAD, fontSize: p ? 40 : 38, color: C.sun, whiteSpace: 'nowrap'}}>AD · AFFILIATE</div>
      <div style={{fontFamily: BODY, fontWeight: 600, fontSize: p ? 26 : 24, color: C.white, lineHeight: 1.3}}>{it.text}</div>
    </div>
  );
};

const MapInset: React.FC<{it: OItem; p: boolean; map: MapData}> = ({it, p, map}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 200}});
  const W = p ? 640 : 560, H = p ? 640 : 560;
  const shot: any = {type: 'map', from: 0, dur: it.dur, key: 'inset', route: it.route, focus: it.focus, focusFrom: it.focusFrom, zoom: 1.6, zoomFrom: 1.0};
  return (
    <div style={{position: 'absolute', right: p ? 220 : 60, top: p ? 520 : 200, width: W, height: H, opacity: io(f, it.dur, 10), transform: `scale(${0.85 + 0.15 * s})`,
      borderRadius: 28, overflow: 'hidden', border: `6px solid ${C.white}`, boxShadow: '0 16px 40px rgba(0,0,0,0.45)', background: C.deep}}>
      <AbsoluteFill><MapScene shot={shot} w={W} h={H} map={map} portrait={false} /></AbsoluteFill>
      {it.text ? <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, background: 'rgba(13,27,36,0.85)', padding: '10px 18px', fontFamily: BODY, fontWeight: 700, fontSize: 26, color: C.white}}>{it.text}</div> : null}
    </div>
  );
};

const EndCard: React.FC<{it: OItem; p: boolean; brand: string}> = ({it, p, brand}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 15], [0, 1], clamp);
  return (
    <AbsoluteFill style={{background: `rgba(10,58,74,${0.78 * o})`, alignItems: 'center', justifyContent: 'center'}}>
      <div style={{textAlign: 'center', padding: 60, opacity: o}}>
        <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 30, letterSpacing: 8, color: C.turq}}>{brand}</div>
        <div style={{fontFamily: HEAD, fontSize: p ? 110 : 120, color: C.white, lineHeight: 1, marginTop: 14}}>{it.text}</div>
        {(it.lines || []).map((l, i) => (
          <div key={i} style={{fontFamily: BODY, fontWeight: 600, fontSize: p ? 40 : 36, color: C.foam, marginTop: 18, opacity: interpolate(f, [10 + i * 8, 25 + i * 8], [0, 1], clamp)}}>{l}</div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

const Hook: React.FC<{it: OItem; p: boolean}> = ({it, p}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 12, stiffness: 180}});
  return (
    <div style={{position: 'absolute', left: 50, right: 50, top: p ? '16%' : '12%', textAlign: 'center', opacity: io(f, it.dur, 4), transform: `scale(${0.7 + 0.3 * s})`}}>
      <span style={{fontFamily: HEAD, fontSize: p ? 112 : 100, lineHeight: 1.05, color: C.white, background: 'rgba(255,122,89,0.92)', padding: '6px 26px', borderRadius: 18,
        boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone'}}>{it.text}</span>
    </div>
  );
};

const Caption: React.FC<{it: OItem; p: boolean}> = ({it, p}) => {
  const f = useCurrentFrame(); const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 20, stiffness: 200}});
  return (
    <div style={{position: 'absolute', left: 50, right: 50, top: p ? '64%' : '78%', textAlign: 'center', transform: `scale(${0.94 + 0.06 * s})`}}>
      <span style={{fontFamily: BODY, fontWeight: 800, fontSize: p ? 60 : 44, lineHeight: 1.25, color: C.white, background: 'rgba(13,27,36,0.8)', padding: '6px 20px', borderRadius: 14,
        boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone'}}>{it.text}</span>
    </div>
  );
};

export const OverlayStrip: React.FC<OStrip> = (o) => {
  ensureFonts();
  const p = o.portrait;
  return (
    <AbsoluteFill style={{backgroundColor: 'transparent'}}>
      {o.items.map((it, i) => (
        <Sequence key={i} from={it.from} durationInFrames={it.dur} name={`${i} ${it.kind}`}>
          {it.kind === 'chapter' ? <Chapter it={it} p={p} /> : it.kind === 'prompt' ? <Prompt it={it} p={p} /> : it.kind === 'lower' ? <Lower it={it} p={p} />
            : it.kind === 'disclosure' ? <Disclosure it={it} p={p} /> : it.kind === 'mapinset' ? <MapInset it={it} p={p} map={o.map} />
            : it.kind === 'endcard' ? <EndCard it={it} p={p} brand={o.brand} /> : it.kind === 'hook' ? <Hook it={it} p={p} /> : <Caption it={it} p={p} />}
        </Sequence>
      ))}
      {o.items.length ? null : null}
    </AbsoluteFill>
  );
};
