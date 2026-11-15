// アプリの 3D の見え方: NLM の preview-v4（ArcViewer の移植・GPLv3）を包んで、譜面・時刻・NJS/JD を外から渡せるようにする。
// preview-v4 はモジュールの中に状態を持つ（1ページに1つ）。写した物には手を入れず、ここで合わせる（SOURCE.md）。
// 使う側のページには import map が要る（three と three/addons/ → このフォルダの js/vendor/three/。importMap() で作れる）。
import * as V4 from './preview-v4/preview-v4.js';

const BASE = new URL('./', import.meta.url).href;
export function importMap() {   // <script type="importmap"> に入れる中身（ページの場所によらず、このフォルダを指す）
  return {imports: {three: BASE + 'js/vendor/three/three.module.js', 'three/addons/': BASE + 'js/vendor/three/addons/'}};
}

// 飛来の距離（JD）とオフセット（拍）: preview-v4 の computeJump と同じ式（NLM の画面の JD 表示とは、短い時の下限の扱いが少し違う）
function defHJD(njs, bpm) {
  let h = 4, g = 0;
  while (njs * 2 * (60 / bpm * h) > 35.998 && g++ < 64) h /= 2;
  return h;
}
export function jdToOffset(jd, njs, bpm) { return jd / (2 * njs * 60 / bpm) - defHJD(njs, bpm); }
export function offsetToJd(offset, njs, bpm) { return njs * 2 * (60 / bpm * Math.max(defHJD(njs, bpm) + (offset || 0), 0.25)); }

const beatOf = o => o.beat ?? o.b ?? 0;
function normalize(m) {   // 拍のキーを preview-v4 の形（ノーツ・ボム・壁・ライト＝beat、アーク・チェーン＝b）にそろえる
  return {
    notes: (m.notes || []).map(o => ({...o, beat: beatOf(o)})),
    bombs: (m.bombs || []).map(o => ({...o, beat: beatOf(o)})),
    walls: (m.walls || []).map(o => ({...o, beat: beatOf(o), dur: o.dur ?? 0})),
    arcs: (m.arcs || []).map(o => ({...o, b: beatOf(o)})),
    chains: (m.chains || []).map(o => ({...o, b: beatOf(o)})),
    lights: (m.lights || []).map(o => ({...o, beat: beatOf(o)})).sort((a, b) => a.beat - b.beat),
  };
}

let live = null;
export async function createPreview(container, opts = {}) {
  if (live) throw new Error('preview3d: 1ページに1つだけ（先に dispose する）');
  if (getComputedStyle(container).position === 'static') container.style.position = 'relative';   // preview-v4 の canvas は inset:0 で重ねる
  V4.init(container);
  const st = {
    data: normalize({}), bpm: opts.bpm || 120, njs: opts.njs || 16, offset: opts.njsOffset || 0, jd: opts.jd ?? null,
    colors: opts.colors || {}, sec: 0, env: null,
  };
  const push = () => {
    if (st.jd != null) st.offset = jdToOffset(st.jd, st.njs, st.bpm);
    V4.setData({...st.data, bpm: st.bpm, njs: st.njs, njsOffset: st.offset, ...st.colors});
    V4.markDirty(); V4.frame(st.sec, false);
  };
  const pv = {
    // 譜面: {bpm, notes, bombs, walls, arcs, chains, lights, njs?, njsOffset?, colors?, env?}（拍は絶対拍。nlmf-map.js の nlmfToMap がこの形を作る）
    setMap(m) {
      st.data = normalize(m);
      if (m.bpm) st.bpm = m.bpm;
      if (m.njs) st.njs = m.njs;
      if (m.njsOffset != null && st.jd == null) st.offset = m.njsOffset;
      if (m.colors) st.colors = m.colors;
      if (m.env) pv.setEnvironment(m.env);
      push();
    },
    setTime(beat, playing = false) { pv.setTimeSec(beat * 60 / st.bpm, playing); },   // 再生に合わせて毎コマ呼ぶ
    setTimeSec(sec, playing = false) { st.sec = sec; V4.frame(sec, playing); },
    setNJS(n) { st.njs = n; push(); },   // JD を決めている時は JD を保つ（オフセットを計算し直す）
    setJD(jd) { st.jd = jd; push(); },
    setNjsOffset(o) { st.jd = null; st.offset = o; push(); },
    jump() {   // 今の NJS・JD・反応時間（秒）・オフセット（拍）
      const jd = offsetToJd(st.offset, st.njs, st.bpm);
      return {njs: st.njs, jd, rt: jd / 2 / st.njs, offset: st.offset};
    },
    environments: () => V4.environments(),
    setEnvironment(name) { st.env = name || 'DefaultEnvironment'; V4.setEnvironment(st.env); V4.markDirty(); },
    setVisible({notes = true, lights = true, structs = true, ambient = false} = {}) {   // NLM の「ノーツ・ライト・構造物・環境ライト」の入り切り
      V4.setVisible(notes, lights); V4.setStructVisible(structs); V4.setAmbient(ambient); V4.frame(st.sec, false);
    },
    setLook({bloomStrength, bloomRadius, bloomThreshold, ambientLevel, emission, reflection} = {}) {   // NLM の環境設定の preview の値（未指定は今のまま）
      if (bloomStrength != null) V4.setBloomStrength(bloomStrength);
      if (bloomRadius != null) V4.setBloomRadius(bloomRadius);
      if (bloomThreshold != null) V4.setBloomThreshold(bloomThreshold);
      if (ambientLevel != null) V4.setAmbientLevel(ambientLevel);
      if (emission != null) V4.setEmissionScale(emission);
      if (reflection != null) V4.setReflStrength(reflection);
      V4.frame(st.sec, false);
    },
    setCameraView(o) { V4.setCameraView(o); V4.frame(st.sec, false); },   // 視点（{fov, y, back}・preview-v4 に足した1つの関数）
    resize() { V4.setActive(true); },   // 大きさは ResizeObserver で追うので、表示を切り替えた直後などに呼ぶ
    render() { V4.markDirty(); V4.frame(st.sec, false); },
    dispose() { V4.dispose(); live = null; },
  };
  V4.setActive(true);
  pv.setEnvironment(opts.env);
  if (opts.visible) pv.setVisible(opts.visible);
  live = pv;
  return pv;
}
