import React from 'react';
import {Composition, Still} from 'remotion';
import {Main} from './Main';
import {Thumb} from './Thumb';
import {OverlayStrip} from './Overlay';

const emptyMap = {path: 'M0,0 Z', w: 1000, h: 1000, places: {}, credit: ''};
const base = {
  unit: 'preview', fps: 30, durationInFrames: 150, title: 'Preview', map: emptyMap,
  shots: [{type: 'text', from: 0, dur: 150, key: 'x', text: 'Preview'}], chapters: [], lowerThirds: [],
  disclosure: {from: 0, dur: 1, text: ''}, captions: [], endCard: {from: 140, dur: 10, title: '', lines: []},
  brand: 'AURUM TRANSFERS',
};

const meta = ({props}: {props: any}) => ({
  durationInFrames: props.durationInFrames,
  fps: props.fps,
  width: props.width,
  height: props.height,
});

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Long" component={Main as any} width={1920} height={1080} fps={30} durationInFrames={150}
      defaultProps={{...base, width: 1920, height: 1080, portrait: false}} calculateMetadata={meta as any} />
    <Composition id="Short" component={Main as any} width={1080} height={1920} fps={30} durationInFrames={150}
      defaultProps={{...base, width: 1080, height: 1920, portrait: true}} calculateMetadata={meta as any} />
    <Composition id="OverlayStrip" component={OverlayStrip as any} width={1920} height={1080} fps={30} durationInFrames={150}
      defaultProps={{fps: 30, width: 1920, height: 1080, durationInFrames: 150, portrait: false, items: [], map: emptyMap, brand: 'AURUM TRANSFERS'}} calculateMetadata={meta as any} />
    <Still id="Thumb" component={Thumb as any} width={1280} height={720}
      defaultProps={{variant: 1, text: 'ARUBA', kicker: '', focus: null, map: emptyMap, brand: 'AURUM TRANSFERS'}} />
  </>
);
