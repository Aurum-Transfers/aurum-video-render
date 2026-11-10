import React from 'react';
import {AbsoluteFill, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SCENES} from './scenes';
import {BODY, C, ensureFonts, HEAD, Timeline} from './theme';

const clamp = {extrapolateLeft: 'clamp' as const, extrapolateRight: 'clamp' as const};

const fadeInOut = (f: number, dur: number, k = 10) =>
  interpolate(f, [0, k, dur - k, dur], [0, 1, 1, 0], clamp);

const ChapterCard: React.FC<{index: number; title: string; dur: number; portrait: boolean}> = ({index, title, dur, portrait}) => {
  const f = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 200}});
  const out = interpolate(f, [dur - 12, dur], [1, 0], clamp);
  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div style={{position: 'absolute', left: 0, top: portrait ? '34%' : '32%', transform: `translateX(${(s - 1) * width * 0.6}px)`, opacity: out,
        background: 'rgba(13,27,36,0.88)', padding: portrait ? '40px 70px 46px 70px' : '36px 90px 44px 110px', borderLeft: `18px solid ${C.turq}`,
        borderRadius: '0 24px 24px 0', maxWidth: portrait ? '90%' : '62%'}}>
        <div style={{fontFamily: BODY, fontWeight: 700, fontSize: portrait ? 34 : 30, color: C.turq, letterSpacing: 6}}>
          CHAPTER {String(index + 1).padStart(2, '0')}
        </div>
        <div style={{fontFamily: HEAD, fontSize: portrait ? 104 : 112, color: C.white, lineHeight: 1}}>{title}</div>
      </div>
    </AbsoluteFill>
  );
};

const LowerThird: React.FC<{title: string; sub?: string; dur: number; portrait: boolean}> = ({title, sub, dur, portrait}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 200}});
  const out = interpolate(f, [dur - 12, dur], [1, 0], clamp);
  return (
    <div style={{position: 'absolute', left: portrait ? 60 : 90, ...(portrait ? {top: 150} : {bottom: 110}), opacity: out,
      transform: `translateY(${(1 - s) * 30}px)`, display: 'flex', alignItems: 'stretch'}}>
      <div style={{width: 12, background: C.coral, borderRadius: 6}} />
      <div style={{background: 'rgba(255,255,255,0.95)', padding: '16px 30px 18px 26px', borderRadius: '0 14px 14px 0', clipPath: `inset(0 ${(1 - s) * 100}% 0 0)`}}>
        <div style={{fontFamily: HEAD, fontSize: portrait ? 64 : 60, color: C.deep, lineHeight: 1}}>{title}</div>
        {sub ? <div style={{fontFamily: BODY, fontWeight: 600, fontSize: portrait ? 30 : 26, color: C.ink, marginTop: 4}}>{sub}</div> : null}
      </div>
    </div>
  );
};

const Disclosure: React.FC<{text: string; dur: number; portrait: boolean}> = ({text, dur, portrait}) => {
  const f = useCurrentFrame();
  return (
    <div style={{position: 'absolute', left: portrait ? 50 : 140, right: portrait ? 50 : 140, ...(portrait ? {top: 300} : {bottom: 70}),
      opacity: fadeInOut(f, dur, 12), background: 'rgba(13,27,36,0.9)', border: `3px solid ${C.sun}`, borderRadius: 18,
      padding: portrait ? '26px 34px' : '22px 34px', display: 'flex', gap: 24, alignItems: 'center'}}>
      <div style={{fontFamily: HEAD, fontSize: portrait ? 46 : 44, color: C.sun, whiteSpace: 'nowrap'}}>AD · AFFILIATE</div>
      <div style={{fontFamily: BODY, fontWeight: 600, fontSize: portrait ? 30 : 28, color: C.white, lineHeight: 1.3}}>{text}</div>
    </div>
  );
};

const CaptionLine: React.FC<{text: string; dur: number}> = ({text, dur}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: f, fps, config: {damping: 20, stiffness: 200}});
  return (
    <div style={{position: 'absolute', left: 60, right: 60, top: '66%', textAlign: 'center', transform: `scale(${0.92 + 0.08 * s})`,
      opacity: interpolate(f, [dur - 3, dur], [1, 0.9], clamp)}}>
      <span style={{fontFamily: BODY, fontWeight: 800, fontSize: 64, lineHeight: 1.25, color: C.white, background: 'rgba(13,27,36,0.78)',
        padding: '8px 22px', borderRadius: 16, boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone'}}>{text}</span>
    </div>
  );
};

const EndCard: React.FC<{title: string; lines: string[]; dur: number; brand: string; portrait: boolean}> = ({title, lines, dur, brand, portrait}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 15], [0, 1], clamp);
  return (
    <AbsoluteFill style={{background: `rgba(10,58,74,${0.92 * o})`, alignItems: 'center', justifyContent: 'center', opacity: o}}>
      <div style={{textAlign: 'center', padding: 60}}>
        <div style={{fontFamily: BODY, fontWeight: 700, fontSize: portrait ? 36 : 32, letterSpacing: 8, color: C.turq}}>{brand}</div>
        <div style={{fontFamily: HEAD, fontSize: portrait ? 120 : 130, color: C.white, lineHeight: 1, marginTop: 16}}>{title}</div>
        {lines.map((l, i) => (
          <div key={i} style={{fontFamily: BODY, fontWeight: 600, fontSize: portrait ? 42 : 38, color: C.foam, marginTop: 20,
            opacity: interpolate(f, [10 + i * 8, 25 + i * 8], [0, 1], clamp)}}>{l}</div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

export const Main: React.FC<Timeline> = (tl) => {
  ensureFonts();
  const {width: w, height: h} = useVideoConfig();
  const p = tl.portrait;
  return (
    <AbsoluteFill style={{background: C.ink}}>
      {tl.shots.map((s) => {
        const Scene = SCENES[s.type] || SCENES.text;
        return (
          <Sequence key={s.key} from={s.from} durationInFrames={s.dur} name={`${s.key} ${s.type}`}>
            <Scene shot={s} w={w} h={h} map={tl.map} portrait={p} />
          </Sequence>
        );
      })}
      {tl.lowerThirds.map((l, i) => (
        <Sequence key={`lt${i}`} from={l.from} durationInFrames={l.dur} name="lower-third">
          <LowerThird title={l.title} sub={l.sub} dur={l.dur} portrait={p} />
        </Sequence>
      ))}
      {tl.chapters.map((c) => (
        <Sequence key={`ch${c.index}`} from={c.from} durationInFrames={c.dur} name="chapter">
          <ChapterCard index={c.index} title={c.title} dur={c.dur} portrait={p} />
        </Sequence>
      ))}
      <Sequence from={tl.disclosure.from} durationInFrames={tl.disclosure.dur} name="disclosure">
        <Disclosure text={tl.disclosure.text} dur={tl.disclosure.dur} portrait={p} />
      </Sequence>
      {tl.captions.map((c, i) => (
        <Sequence key={`cap${i}`} from={c.from} durationInFrames={c.dur} name="caption">
          <CaptionLine text={c.text} dur={c.dur} />
        </Sequence>
      ))}
      <Sequence from={tl.endCard.from} durationInFrames={tl.endCard.dur} name="end">
        <EndCard title={tl.endCard.title} lines={tl.endCard.lines} dur={tl.endCard.dur} brand={tl.brand} portrait={p} />
      </Sequence>
      <div style={{position: 'absolute', top: p ? 60 : 34, right: p ? 50 : 44, fontFamily: BODY, fontWeight: 700, fontSize: p ? 26 : 22,
        letterSpacing: 5, color: C.white, opacity: 0.55, textShadow: '0 2px 8px rgba(0,0,0,0.5)'}}>{tl.brand}</div>
    </AbsoluteFill>
  );
};
