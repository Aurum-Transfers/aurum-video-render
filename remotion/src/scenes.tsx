import React from 'react';
import {AbsoluteFill, Easing, Freeze, interpolate, OffthreadVideo, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {BODY, C, HEAD, MapData, rand, Shot} from './theme';

type SP = {shot: Shot; w: number; h: number; map: MapData; portrait: boolean};

const ease = Easing.bezier(0.45, 0, 0.25, 1);
const clamp = {extrapolateLeft: 'clamp' as const, extrapolateRight: 'clamp' as const};

// ---------- shared bits ----------
const Caption: React.FC<{text?: string; sub?: string; w: number; h: number; portrait: boolean; align?: 'left' | 'center'}> = ({text, sub, w, h, portrait, align = 'left'}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (!text) return null;
  const s = spring({frame: f - 8, fps, config: {damping: 200}});
  const size = portrait ? 104 : 120;
  return (
    <div style={{position: 'absolute', left: portrait ? 60 : 90, maxWidth: portrait ? w - 120 : w * 0.5, top: portrait ? h * 0.17 : h * 0.13,
      textAlign: align, opacity: s, transform: `translateY(${(1 - s) * 40}px)`, background: 'rgba(13,27,36,0.62)',
      padding: portrait ? '24px 34px 28px 34px' : '22px 36px 26px 36px', borderRadius: 22}}>
      <div style={{fontFamily: HEAD, fontSize: size, lineHeight: 0.95, color: C.white, letterSpacing: 1,
        textShadow: '0 6px 30px rgba(0,0,0,0.35)'}}>{text}</div>
      {sub ? <div style={{fontFamily: BODY, fontWeight: 600, fontSize: portrait ? 40 : 38, color: C.foam, marginTop: 18,
        textShadow: '0 3px 16px rgba(0,0,0,0.4)'}}>{sub}</div> : null}
    </div>
  );
};

const wavePath = (w: number, y0: number, amp: number, freq: number, phase: number, bottom: number) => {
  const n = 48;
  let d = `M0,${bottom} L0,${y0}`;
  for (let i = 0; i <= n; i++) {
    const x = (w * i) / n;
    const y = y0 + amp * Math.sin((i / n) * Math.PI * 2 * freq + phase) + amp * 0.35 * Math.sin((i / n) * Math.PI * 2 * freq * 2.3 + phase * 1.7);
    d += ` L${x.toFixed(1)},${y.toFixed(1)}`;
  }
  return d + ` L${w},${bottom} Z`;
};

// ---------- MAP ----------
const segLengths = (pts: {x: number; y: number}[]) => {
  const l = [0];
  for (let i = 1; i < pts.length; i++) l.push(l[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y));
  return l;
};
const pointAt = (pts: {x: number; y: number}[], t: number) => {
  const l = segLengths(pts);
  const target = l[l.length - 1] * t;
  for (let i = 1; i < pts.length; i++) {
    if (l[i] >= target) {
      const k = (target - l[i - 1]) / ((l[i] - l[i - 1]) || 1);
      return {x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * k, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * k,
        a: Math.atan2(pts[i].y - pts[i - 1].y, pts[i].x - pts[i - 1].x)};
    }
  }
  const p = pts[pts.length - 1];
  return {x: p.x, y: p.y, a: 0};
};

export const MapScene: React.FC<SP> = ({shot, w, h, map, portrait}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const D = shot.dur;
  const places = map.places;
  const focus = shot.focus && places[shot.focus] ? places[shot.focus] : {x: map.w / 2, y: map.h / 2};
  const zEnd = shot.zoom ?? (shot.focus ? 2.0 : 1.12);
  const zStart = shot.zoomFrom ?? (shot.focus ? Math.max(1, zEnd * 0.62) : 1.0);
  const t = interpolate(f, [0, D], [0, 1], {...clamp, easing: ease});
  const z = zStart + (zEnd - zStart) * t;
  const startC = shot.focusFrom && places[shot.focusFrom] ? places[shot.focusFrom] : {x: map.w / 2, y: map.h / 2};
  const cx = startC.x + (focus.x - startC.x) * t;
  const cy = startC.y + (focus.y - startC.y) * t;
  const base = (Math.min(w, h) / map.w) * (portrait ? 1.05 : 0.98);
  const s = base * z;
  const hasText = !!shot.text;
  const offX = hasText && !portrait ? w * 0.2 : 0;
  const offY = portrait ? (hasText ? h * 0.12 : 60) : 0;
  const tr = `translate(${w / 2 + offX},${h / 2 + offY}) scale(${s}) translate(${-cx},${-cy})`;
  const inv = 1 / s;
  const route = (shot.route || []).map((k: string) => places[k]).filter(Boolean);
  const rStart = 0.12 * D;
  const rEnd = 0.8 * D;
  const rp = interpolate(f, [rStart, rEnd], [0, 1], {...clamp, easing: ease});
  const pins: string[] = Array.from(new Set([...(shot.pins || []), ...(shot.route || [])]));
  const plane = shot.plane && places[shot.plane];
  const planePts = plane ? [{x: -700, y: -500}, {x: plane.x - 380, y: plane.y - 520}, {x: plane.x - 120, y: plane.y - 160}, {x: plane.x, y: plane.y}] : [];
  const pp = interpolate(f, [0, D * 0.7], [0, 1], {...clamp, easing: Easing.out(Easing.quad)});
  const rings = [1.06, 1.16, 1.3, 1.48];
  return (
    <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 45%, ${C.sea} 0%, ${C.deep} 60%, #06222c 100%)`}}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
        <defs>
          <linearGradient id="sand" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={C.sand} />
            <stop offset="1" stopColor={C.sandDark} />
          </linearGradient>
          <filter id="sh" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy={6 * inv} stdDeviation={10 * inv} floodColor="#021820" floodOpacity="0.55" />
          </filter>
        </defs>
        <g transform={tr}>
          {rings.map((r, i) => (
            <path key={i} d={map.path} fill="none" stroke={C.foam} strokeOpacity={0.16 - i * 0.03} strokeWidth={1.6 * inv}
              strokeDasharray={`${6 * inv} ${10 * inv}`} strokeDashoffset={-f * 0.6 * inv * (i + 1)}
              transform={`translate(${map.w / 2},${map.h / 2}) scale(${r + 0.01 * Math.sin(f / 40 + i)}) translate(${-map.w / 2},${-map.h / 2})`} />
          ))}
          <path d={map.path} fill="url(#sand)" stroke={C.white} strokeWidth={2.5 * inv} filter="url(#sh)" />
          {planePts.length ? (
            <path d={`M${planePts.map((p) => `${p.x},${p.y}`).join(' L')}`} fill="none" stroke={C.white} strokeOpacity={0.7}
              strokeWidth={3 * inv} strokeDasharray={`${10 * inv} ${8 * inv}`} pathLength={1}
              style={{strokeDasharray: `${pp} 1`}} />
          ) : null}
          {route.length > 1 ? (
            <>
              <path d={`M${route.map((p: any) => `${p.x},${p.y}`).join(' L')}`} fill="none" stroke={C.ink} strokeOpacity={0.25}
                strokeWidth={10 * inv} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - rp} />
              <path d={`M${route.map((p: any) => `${p.x},${p.y}`).join(' L')}`} fill="none" stroke={C.coral}
                strokeWidth={6 * inv} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - rp} />
              {(() => {
                const p = pointAt(route, rp);
                return <circle cx={p.x} cy={p.y} r={11 * inv} fill={C.white} stroke={C.coral} strokeWidth={5 * inv} />;
              })()}
            </>
          ) : null}
          {pins.map((k, i) => {
            const p = places[k];
            if (!p) return null;
            const ps = spring({frame: f - 10 - i * 7, fps, config: {damping: 14, stiffness: 120}});
            const pulse = (f + i * 9) % 45 / 45;
            const sx = w / 2 + offX + (p.x - cx) * s;
            const left = sx > w * 0.5;
            return (
              <g key={k} transform={`translate(${p.x},${p.y}) scale(${inv * ps})`}>
                <circle r={18 + pulse * 30} fill="none" stroke={C.coral} strokeOpacity={1 - pulse} strokeWidth={3} />
                <circle r={13} fill={C.coral} stroke={C.white} strokeWidth={4} />
                <g transform={`translate(${left ? -24 : 24},-26)`}>
                  <text textAnchor={left ? 'end' : 'start'} fontFamily={BODY} fontWeight={700} fontSize={portrait ? 40 : 34}
                    fill={C.white} stroke={C.ink} strokeWidth={8} paintOrder="stroke" strokeLinejoin="round">{p.label}</text>
                </g>
              </g>
            );
          })}
          {plane ? (() => {
            const p = pointAt(planePts, pp);
            return (
              <g transform={`translate(${p.x},${p.y}) rotate(${(p.a * 180) / Math.PI}) scale(${inv * 1.6})`} opacity={pp < 1 ? 1 : interpolate(f, [D * 0.7, D * 0.8], [1, 0], clamp)}>
                <path d="M-22,0 L-6,-4 L4,-22 L10,-22 L6,-4 L22,-3 L26,-10 L30,-10 L28,0 L30,10 L26,10 L22,3 L6,4 L10,22 L4,22 L-6,4 L-22,0 Z"
                  fill={C.white} stroke={C.ink} strokeWidth={1.5} />
              </g>
            );
          })() : null}
        </g>
      </svg>
      <Caption text={shot.text} sub={shot.sub} w={w} h={h} portrait={portrait} />
      <div style={{position: 'absolute', right: 24, bottom: portrait ? 300 : 18, fontFamily: BODY, fontSize: 18, color: C.foam, opacity: 0.6}}>
        {map.credit}
      </div>
    </AbsoluteFill>
  );
};

// ---------- SEA ----------
const SKY: Record<string, [string, string]> = {
  day: ['#4fb3d9', '#bfe9f5'],
  sunset: ['#3b2c5a', '#ff9a62'],
  morning: ['#7ec8e3', '#ffe4b5'],
  night: ['#0b1630', '#24335c'],
};

export const SeaScene: React.FC<SP> = ({shot, w, h, portrait}) => {
  const f = useCurrentFrame();
  const time = shot.time || 'day';
  const [a, b] = SKY[time] || SKY.day;
  const horizon = h * (portrait ? 0.5 : 0.56);
  const sunY = interpolate(f, [0, shot.dur], [horizon - h * 0.18, horizon - h * 0.26]);
  const layers = [0, 1, 2, 3];
  const boatX = interpolate(f, [0, shot.dur], [-0.15 * w, 1.1 * w]);
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${a} 0%, ${b} ${(horizon / h) * 100}%)`}}>
      <svg width={w} height={h}>
        {time === 'night' ? Array.from({length: 70}).map((_, i) => (
          <circle key={i} cx={rand(i) * w} cy={rand(i + 99) * horizon * 0.9} r={1 + rand(i + 7) * 2}
            fill="#fff" opacity={0.4 + 0.6 * Math.abs(Math.sin(f / 20 + i))} />
        )) : null}
        <circle cx={w * (shot.sunX ?? 0.72)} cy={sunY} r={portrait ? 110 : 90} fill={time === 'night' ? '#f4f1de' : C.sun} opacity={0.95} />
        {[0, 1, 2].map((i) => (
          <ellipse key={i} cx={((rand(i + 3) * w + f * (0.6 + i * 0.3)) % (w + 400)) - 200} cy={h * (0.12 + i * 0.08)} rx={140 + i * 40} ry={26 + i * 6}
            fill="#fff" opacity={time === 'night' ? 0.06 : 0.5} />
        ))}
        {shot.wind ? Array.from({length: 14}).map((_, i) => {
          const y = h * 0.1 + rand(i) * horizon * 0.8;
          const x = ((f * (8 + rand(i + 5) * 6) + rand(i + 9) * w * 2) % (w + 600)) - 300;
          return <path key={i} d={`M${x},${y} q 60,-14 120,0 t 120,0`} stroke="#fff" strokeOpacity={0.55} strokeWidth={3} fill="none" strokeLinecap="round" />;
        }) : null}
        {shot.kites ? [0, 1, 2].map((i) => {
          const kx = w * (0.25 + i * 0.22) + 30 * Math.sin(f / 18 + i);
          const ky = h * (0.18 + 0.06 * i) + 20 * Math.cos(f / 22 + i * 2);
          return (
            <g key={i}>
              <path d={`M${kx},${ky + 40} Q ${kx + 40},${horizon - 60} ${w * (0.3 + i * 0.2)},${horizon + 20}`} stroke="#fff" strokeOpacity={0.6} strokeWidth={2} fill="none" />
              <path d={`M${kx - 70},${ky} Q ${kx},${ky - 50} ${kx + 70},${ky} Q ${kx},${ky - 20} ${kx - 70},${ky} Z`} fill={[C.coral, C.sun, C.turq][i]} />
            </g>
          );
        }) : null}
        {layers.map((i) => (
          <path key={i} d={wavePath(w, horizon + i * h * 0.1, 10 + i * 6, 2 + i * 0.6, f * (0.03 + i * 0.012) + i * 1.3, h)}
            fill={[C.turq, '#1aa5a0', C.sea, C.deep][i]} opacity={0.95} />
        ))}
        {shot.beach ? <path d={wavePath(w, h * 0.86, 12, 1.2, f * 0.02, h)} fill={C.sand} /> : null}
        {shot.boat ? (
          <g transform={`translate(${boatX},${horizon + h * 0.05 + 6 * Math.sin(f / 12)})`}>
            <path d="M-60,0 L60,0 L45,22 L-45,22 Z" fill={C.white} />
            <path d="M0,-6 L0,-120 L55,-10 Z" fill={C.white} />
            <path d="M-6,-10 L-6,-95 L-48,-12 Z" fill={C.coral} />
          </g>
        ) : null}
        {shot.reef ? Array.from({length: 18}).map((_, i) => {
          const fx = ((rand(i) * w + f * (1.5 + rand(i + 2) * 2) * (i % 2 ? 1 : -1)) % w + w) % w;
          const fy = horizon + h * 0.2 + rand(i + 4) * h * 0.25 + 8 * Math.sin(f / 10 + i);
          const dir = i % 2 ? 1 : -1;
          return <path key={i} transform={`translate(${fx},${fy}) scale(${dir},1)`} d="M-18,0 Q0,-12 18,0 Q0,12 -18,0 Z M18,0 L30,-9 L30,9 Z" fill={[C.sun, C.coral, '#ffffff'][i % 3]} opacity={0.9} />;
        }) : null}
      </svg>
      <Caption text={shot.text} sub={shot.sub} w={w} h={h} portrait={portrait} />
    </AbsoluteFill>
  );
};

// ---------- DESERT (Arikok, rocks, Hooiberg) ----------
const Cactus: React.FC<{x: number; y: number; s: number}> = ({x, y, s}) => (
  <g transform={`translate(${x},${y}) scale(${s})`}>
    <rect x={-14} y={-180} width={28} height={180} rx={14} fill={C.cactus} />
    <rect x={-58} y={-120} width={22} height={70} rx={11} fill={C.cactus} />
    <rect x={-58} y={-62} width={50} height={20} rx={10} fill={C.cactus} />
    <rect x={36} y={-150} width={22} height={80} rx={11} fill={C.cactus} />
    <rect x={8} y={-82} width={50} height={20} rx={10} fill={C.cactus} />
  </g>
);

export const DesertScene: React.FC<SP> = ({shot, w, h, portrait}) => {
  const f = useCurrentFrame();
  const pan = interpolate(f, [0, shot.dur], [0, -w * 0.12]);
  const ground = h * (portrait ? 0.68 : 0.72);
  const coneProgress = interpolate(f, [shot.dur * 0.1, shot.dur * 0.85], [0, 1], {...clamp, easing: ease});
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, #8fd3f4 0%, #fbe7c6 75%)`}}>
      <svg width={w} height={h}>
        <circle cx={w * 0.8} cy={h * 0.18} r={80} fill={C.sun} />
        <g transform={`translate(${pan * 0.3},0)`}>
          <path d={`M-200,${ground} Q ${w * 0.2},${ground - h * 0.25} ${w * 0.45},${ground - h * 0.1} T ${w * 1.3},${ground - h * 0.12} L ${w * 1.4},${h} L -200,${h} Z`} fill="#d8b98a" />
        </g>
        {shot.cone ? (
          <g transform={`translate(${w * 0.5 + pan * 0.5},${ground})`}>
            <path d={`M${-w * 0.34},0 C ${-w * 0.14},${-h * 0.3} ${-w * 0.06},${-h * 0.5} 0,${-h * 0.5} C ${w * 0.06},${-h * 0.5} ${w * 0.14},${-h * 0.3} ${w * 0.34},0 Z`} fill="#9c8a5a" />
            <path d={`M${-w * 0.34},0 C ${-w * 0.14},${-h * 0.3} ${-w * 0.06},${-h * 0.5} 0,${-h * 0.5} C ${-w * 0.03},${-h * 0.3} ${-w * 0.06},${-h * 0.15} ${-w * 0.08},0 Z`} fill="#b3a06c" />
            {Array.from({length: 26}).map((_, i) => (
              <circle key={i} cx={(rand(i) - 0.5) * 2 * w * 0.26 * Math.pow(1 - rand(i + 50) * 0.85, 1.6)} cy={-h * 0.5 * rand(i + 50) * 0.85} r={10 + rand(i + 9) * 10} fill="#6f8f4e" opacity={0.85} />
            ))}
            <path d={Array.from({length: 13}).map((_, i) => {
              const k = i / 12;
              const y = -h * 0.5 * k;
              const x = (i % 2 ? 1 : -1) * w * 0.3 * (1 - k) * 0.55;
              return `${i ? 'L' : 'M'}${x},${y}`;
            }).join(' ')} fill="none" stroke={C.white} strokeWidth={6} strokeLinecap="round" strokeLinejoin="round"
              pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - coneProgress} />
          </g>
        ) : null}
        <g transform={`translate(${pan},0)`}>
          <path d={`M-200,${ground + 30} Q ${w * 0.3},${ground - 40} ${w * 0.7},${ground + 10} T ${w * 1.4},${ground} L ${w * 1.4},${h} L -200,${h} Z`} fill="#e9cf9f" />
          {shot.rocks ? [0, 1, 2, 3, 4].map((i) => (
            <ellipse key={i} cx={w * (0.15 + i * 0.2)} cy={ground + 10 - (i % 2) * 30} rx={90 + rand(i) * 80} ry={70 + rand(i + 3) * 70}
              fill={i % 2 ? C.rock : '#9c865f'} />
          )) : null}
          {shot.cacti !== false ? [0, 1, 2, 3, 4, 5].map((i) => (
            <Cactus key={i} x={w * (0.08 + i * 0.19) + rand(i) * 60} y={ground + 40 + rand(i + 5) * 60} s={0.8 + rand(i + 2) * 0.7} />
          )) : null}
        </g>
      </svg>
      <Caption text={shot.text} sub={shot.sub} w={w} h={h} portrait={portrait} />
    </AbsoluteFill>
  );
};

// ---------- TOWN (Oranjestad facades, fort tower) ----------
const PASTELS = ['#f7a8b8', '#ffd166', '#7bdff2', '#b9fbc0', '#f6c6ea', '#ffb703', '#a0c4ff', '#ff9f80'];

export const TownScene: React.FC<SP> = ({shot, w, h, portrait}) => {
  const f = useCurrentFrame();
  const hw = portrait ? 300 : 260;
  const n = Math.ceil(w / hw) + 4;
  const scroll = interpolate(f, [0, shot.dur], [0, -hw * 2.2]);
  const base = h * (portrait ? 0.78 : 0.86);
  const angle = (f / 30) * 6;
  return (
    <AbsoluteFill style={{background: 'linear-gradient(180deg, #5ec2e8 0%, #d6f1fb 100%)'}}>
      <svg width={w} height={h}>
        {shot.fort ? (
          <g transform={`translate(${w * 0.78 + scroll * 0.3},${base - 120})`}>
            <rect x={-60} y={-520} width={120} height={520} fill="#f4efe1" stroke="#c9b991" strokeWidth={4} />
            <path d="M-75,-520 L0,-600 L75,-520 Z" fill="#c45b3c" />
            <circle cx={0} cy={-430} r={40} fill="#fff" stroke={C.ink} strokeWidth={5} />
            <line x1={0} y1={-430} x2={22 * Math.sin((angle * Math.PI) / 180)} y2={-430 - 22 * Math.cos((angle * Math.PI) / 180)} stroke={C.ink} strokeWidth={5} />
            <line x1={0} y1={-430} x2={30 * Math.sin((angle * 12 * Math.PI) / 180)} y2={-430 - 30 * Math.cos((angle * 12 * Math.PI) / 180)} stroke={C.coral} strokeWidth={3} />
            <rect x={-260} y={-160} width={210} height={160} fill="#efe6cf" stroke="#c9b991" strokeWidth={4} />
          </g>
        ) : null}
        <g transform={`translate(${scroll},0)`}>
          {Array.from({length: n}).map((_, i) => {
            const x = i * hw;
            const hh = (portrait ? 520 : 420) + rand(i) * 120;
            const col = PASTELS[i % PASTELS.length];
            const top = base - hh;
            return (
              <g key={i}>
                <path d={`M${x},${base} L${x},${top + 60} Q${x + hw * 0.12},${top + 40} ${x + hw * 0.2},${top + 30} L${x + hw * 0.35},${top}
                  L${x + hw * 0.65},${top} L${x + hw * 0.8},${top + 30} Q${x + hw * 0.88},${top + 40} ${x + hw},${top + 60} L${x + hw},${base} Z`}
                  fill={col} stroke="#ffffff" strokeWidth={6} />
                {[0, 1].map((r) => [0, 1, 2].map((c) => (
                  <rect key={`${r}${c}`} x={x + hw * (0.14 + c * 0.27)} y={top + 110 + r * 120} width={hw * 0.18} height={80} rx={6}
                    fill="#ffffff" stroke="#3d5a80" strokeWidth={4} />
                )))}
                <rect x={x + hw * 0.4} y={base - 130} width={hw * 0.2} height={130} rx={hw * 0.1} fill="#3d5a80" />
              </g>
            );
          })}
        </g>
        <rect x={0} y={base} width={w} height={h - base} fill="#d9d2c3" />
      </svg>
      <Caption text={shot.text} sub={shot.sub} w={w} h={h} portrait={portrait} />
    </AbsoluteFill>
  );
};

// ---------- CALENDAR ----------
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

export const CalendarScene: React.FC<SP> = ({shot, w, h, portrait}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cols = portrait ? 3 : 6;
  const rows = 12 / cols;
  const gw = portrait ? w * 0.86 : w * 0.8;
  const cell = gw / cols;
  const cellH = portrait ? 230 : 190;
  const x0 = (w - gw) / 2;
  const y0 = portrait ? h * 0.3 : h * 0.3;
  const bands: {from: number; to: number; label: string; color: string}[] = shot.bands || [];
  const per = shot.dur / Math.max(1, bands.length);
  const inBand = (m: number, b: any) => (b.from <= b.to ? m >= b.from && m <= b.to : m >= b.from || m <= b.to);
  const active = Math.min(bands.length - 1, Math.floor(f / per));
  return (
    <AbsoluteFill style={{background: `linear-gradient(160deg, ${C.deep}, ${C.ink})`}}>
      <div style={{position: 'absolute', top: portrait ? h * 0.12 : h * 0.1, width: '100%', textAlign: 'center', fontFamily: HEAD,
        fontSize: portrait ? 96 : 92, color: C.white}}>{shot.text || 'THE ARUBAN YEAR'}</div>
      {MONTHS.map((m, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        const s = spring({frame: f - i * 2, fps, config: {damping: 200}});
        const b = bands[active];
        const on = b && inBand(i + 1, b);
        return (
          <div key={m} style={{position: 'absolute', left: x0 + col * cell + 8, top: y0 + row * (cellH + 16), width: cell - 16, height: cellH,
            borderRadius: 18, background: on ? b.color : 'rgba(255,255,255,0.08)', border: '2px solid rgba(255,255,255,0.25)',
            transform: `scale(${0.9 + 0.1 * s})`, opacity: s, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: HEAD, fontSize: portrait ? 72 : 64, color: on ? C.ink : C.white, transition: 'none'}}>{m}</div>
        );
      })}
      {bands[active] ? (
        <div style={{position: 'absolute', top: y0 + rows * (cellH + 16) + 30, width: '100%', textAlign: 'center', fontFamily: BODY,
          fontWeight: 700, fontSize: portrait ? 50 : 46, color: bands[active].color}}>{bands[active].label}</div>
      ) : null}
    </AbsoluteFill>
  );
};

// ---------- CHECKLIST ----------
export const ChecklistScene: React.FC<SP> = ({shot, w, h, portrait}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const items: string[] = shot.items || [];
  const per = (shot.dur * 0.8) / Math.max(1, items.length);
  return (
    <AbsoluteFill style={{background: `linear-gradient(135deg, ${C.sand}, #fff7e6)`}}>
      <div style={{position: 'absolute', left: portrait ? 80 : 160, top: portrait ? h * 0.16 : h * 0.12, fontFamily: HEAD,
        fontSize: portrait ? 110 : 104, color: C.deep}}>{shot.text}</div>
      {items.map((it, i) => {
        const s = spring({frame: f - 10 - i * per, fps, config: {damping: 18}});
        const tick = interpolate(f, [10 + i * per + 8, 10 + i * per + 22], [0, 1], clamp);
        return (
          <div key={i} style={{position: 'absolute', left: portrait ? 80 : 160, top: (portrait ? h * 0.32 : h * 0.32) + i * (portrait ? 170 : 130),
            display: 'flex', alignItems: 'center', opacity: s, transform: `translateX(${(1 - s) * -60}px)`}}>
            <svg width={84} height={84} viewBox="0 0 84 84">
              <rect x={4} y={4} width={76} height={76} rx={18} fill={C.white} stroke={C.deep} strokeWidth={6} />
              <path d="M20,44 L36,60 L66,26" fill="none" stroke={C.coral} strokeWidth={10} strokeLinecap="round" strokeLinejoin="round"
                pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - tick} />
            </svg>
            <div style={{marginLeft: 34, fontFamily: BODY, fontWeight: 700, fontSize: portrait ? 50 : 48, color: C.ink, maxWidth: portrait ? w - 300 : w * 0.7}}>{it}</div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

// ---------- TEXT ----------
const BGS: Record<string, string> = {
  sea: `linear-gradient(135deg, ${C.deep}, ${C.turq})`,
  sand: `linear-gradient(135deg, ${C.sandDark}, ${C.coral})`,
  coral: `linear-gradient(135deg, ${C.coral}, ${C.sun})`,
  ink: `linear-gradient(135deg, ${C.ink}, ${C.deep})`,
};
export const TextScene: React.FC<SP> = ({shot, w, h, portrait}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const words = String(shot.text || '').split(' ');
  return (
    <AbsoluteFill style={{background: BGS[shot.bg || 'sea']}}>
      <svg width={w} height={h} style={{position: 'absolute'}}>
        {Array.from({length: 9}).map((_, i) => (
          <circle key={i} cx={rand(i) * w + 40 * Math.sin(f / 50 + i)} cy={rand(i + 20) * h + 30 * Math.cos(f / 60 + i)}
            r={60 + rand(i + 40) * 220} fill="#fff" opacity={0.05 + rand(i + 60) * 0.06} />
        ))}
      </svg>
      <div style={{position: 'absolute', left: portrait ? 70 : 140, right: portrait ? 70 : 140, top: portrait ? h * 0.3 : h * 0.3,
        fontFamily: HEAD, fontSize: portrait ? 132 : 150, lineHeight: 0.95, color: C.white}}>
        {words.map((wd, i) => {
          const s = spring({frame: f - 6 - i * 4, fps, config: {damping: 200}});
          return <span key={i} style={{display: 'inline-block', marginRight: 26, opacity: s, transform: `translateY(${(1 - s) * 50}px)`}}>{wd}</span>;
        })}
        {shot.sub ? <div style={{fontFamily: BODY, fontWeight: 600, fontSize: portrait ? 46 : 44, marginTop: 30, color: C.foam,
          opacity: interpolate(f, [20, 40], [0, 1], clamp)}}>{shot.sub}</div> : null}
      </div>
    </AbsoluteFill>
  );
};

// ---------- CLIP (stock, always moving + layered) ----------
export const ClipScene: React.FC<SP> = ({shot, w, h, portrait}) => {
  const f = useCurrentFrame();
  // Play a unique in-point (startFrom) once. A last-frame freeze is allowed
  // for at most ~1s of rounding slop — never loop or Ken-Burns-pad footage.
  const startFrom = Math.max(0, shot.startFrom || 0);
  const clipFrames = Math.max(1, shot.clipFrames || (startFrom + shot.dur));
  const lastLocal = Math.max(0, clipFrames - startFrom - 1);
  const video = shot.src ? (
    <OffthreadVideo src={staticFile(shot.src)} muted startFrom={startFrom} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
  ) : null;
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: C.ink}}>
      <AbsoluteFill>
        {f >= lastLocal ? <Freeze frame={lastLocal}>{video}</Freeze> : video}
      </AbsoluteFill>
      <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(13,27,36,0) 70%, rgba(13,27,36,0.22) 100%)', pointerEvents: 'none'}} />
      <Caption text={shot.text} sub={shot.sub} w={w} h={h} portrait={portrait} />
    </AbsoluteFill>
  );
};

export const SCENES: Record<string, React.FC<SP>> = {
  map: MapScene, sea: SeaScene, desert: DesertScene, town: TownScene, calendar: CalendarScene,
  checklist: ChecklistScene, text: TextScene, clip: ClipScene,
};
