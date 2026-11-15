// タイムライン（NLM の NLE のように横に並べた帯）: 上の目盛り・帯（見出しの列＋中身）・下の全体の見取り図。
// ホイール＝曲の中を横に動く・Ctrl＋ホイール＝拡大縮小・Shift＋ホイール＝帯を上下に。帯の上をドラッグ＝区間を選ぶ（小節の頭にそろう・
// Alt で拍の頭・Shift で足す）。クリック＝そこへ移る。量のラインはキーフレーム（ダブルクリックで点・ドラッグで動かす・右クリックで切り替え／消す）。
import {S, $, css, fmt, beatOf, timeOf, BEATS, barIdx, barEndBeat, nearestBar, on, emit, commit, takeSnap, newId, UI, motifForms, formColor, formLabel, formRuns, formDiff, formDeleteItems, DIFF_TEXT, locked, lsGet, lsSet, undo} from './store.js';
import {P, STEM, seek, busyPlaying} from './player.js';

let GUT = 132;                       // 見出しの列の幅（表示の大きさで変わる）
const F = (n, w = '') => (w ? w + ' ' : '') + (n * UI.s).toFixed(1) + 'px ' + css('--font');   // 字の大きさ（表示の大きさに合わせる）
export const V = {t0: -1, span: 30};  // 見えている所（秒）
const OPEN = {編集: true, 解析: true, 比べる: false};
let LAYOUT = [];                     // [{n, g, y, h, f, head}]
let drag = null;
// ほかの受け持ちが足す帯（区間の点検＝check.js）: {g 帯のグループ, n 名前, h 高さ, f 描く, click(t, e)→true で受けた, hover(t)→見出し（title）}
const EXT = [];
export function addLane(g, n, h, f, opt = {}) { EXT.push({g, n, h, f, ...opt}); }
// ほかの受け持ちが今ある帯に重ねる印（決めの場所＝check.js）: {n 帯の名前, f 描く（帯と同じ引数・帯の後に描く）,
//   hover(t, p)→見出し（title・'' なら下の帯の見出し）, click(t, e, p)→true で受けた}。p＝{x, dy（帯の上からの高さ）, h, X}
const OVL = [];
export function addOverlay(n, f, opt = {}) { OVL.push({n, f, ...opt}); }
// 帯「作った譜面」のノーツを描く所 → [上, 高さ]（クリップの名前の札の下〜下の端の空き CHART_FOOT の上）。重ねる印（決めの丸＝check.js）も
// これで位置を合わせる。下の端の空き＝同じ音楽の区間の帯と札（repeats.js）の場所＝ノーツを隠さない（2026-11-11・ノーツの大きさは前と同じ）
export const CHART_FOOT = 11;
export function chartNotesBox(y, h) { const u = UI.s; return [y + 13 * u, h - (15 + CHART_FOOT) * u]; }
export function openGroup(g, v = true) { OPEN[g] = v; draw(); emit('lanesDrawn'); }
const LINE_LO = 0.5, LINE_HI = 2.0;   // 量のラインの範囲（2026-11-08 利用者「2 倍までできるように」・前は 150% まで）

// ---- 帯の並び ----
function lanes() {
  const D = S.D, L = [];
  const u = UI.s, group = (g, items) => { L.push({head: true, g, n: g, h: Math.round(20 * u)}); if (OPEN[g]) items.forEach(([n, h, f]) => L.push({g, n, h: Math.round(h * u), f})); };
  group('編集', [['区間', 22, laneSec], ['流れの表', 22, laneBlocks], ['意思入れ', 26, laneIntent], ['量のライン', 96, laneLine], ['作った譜面', 72 + CHART_FOOT, laneChart]]);
  group('解析', [['くり返し伴奏', 16, laneLab('acc')], ['くり返し歌', 16, laneLab('mel')], ['調のずれ', 14, laneShift], ['ドラムの勢い', 26, laneDrumPow],
    ['途切れ', 14, laneBreak], ['歌の広がり', 22, laneBarV('width', -32, -6, '--voc')], ['楽器の多さ', 22, laneBarV('bands', 12, 23, '--oth')],
    ['旋律楽器', 18, laneLead], ['歌の高さ', 70, laneVoc], ['歌の大きさ', 28, laneEnv('vocals')], ['ドラム打点', 42, laneDrum],
    ['ドラム', 26, laneEnv('drums')], ['その他', 30, laneOther], ['ベース', 28, laneBass]]);
  const cmp = [['v0.1', 'notes0'], ['試作4', 'notes4'], ['試作5', 'notes5']].filter(([, k]) => (D[k] || []).length);
  const cmpL = [...EXT.filter(e => e.g === '比べる').map(e => [e.n, e.h, e.f]), ...cmp.map(([n, k]) => [n, 48, (g, X, y, h, t0, t1) => drawNotes(g, X, y, h, t0, t1, D[k])])];
  if (cmpL.length) group('比べる', cmpL);
  let y = 0; L.forEach(l => { l.y = y; y += l.h + (l.head ? 0 : 3); });
  return L;
}

// ---- 座標 ----
const W = () => $('lanes').clientWidth;
const X = t => GUT + (t - V.t0) / V.span * (W() - GUT - 8);
const tAt = x => V.t0 + (x - GUT) / (W() - GUT - 8) * V.span;
function clampView() {
  const dur = S.D ? S.D.dur : 60;
  V.span = Math.max(2, Math.min(dur + 6, V.span));
  V.t0 = Math.max(-3, Math.min(dur + 3 - V.span, V.t0));
}
// 拡大率（見えている秒数 V.span）は曲ごとに覚えて、その曲を開いた時に戻す（2026-11-09 利用者・画面の覚え automap-zoom＝{曲名: 秒}）。
// 位置（V.t0）は覚えない（開いた時は曲の頭から）。覚えるのは利用者が変えた時だけ: ＋－・Ctrl＋ホイール（zoomBy）と、利用者が押した・
// クリックした出来事の中でそのまま呼ばれた showRange（「ここを広げて見る」・同じ振りの回・盛り上がりの繰り返しの「見る」・未反映の場所・
// 別の案の回）。確かめ用（#ctest・#test… はスクリプトから＝本物の入力の出来事ではない）と、待った後に自動で見せる物（別の案を作り終えた・
// 履歴の版を見る＝await の後で出来事の外）は覚えない。Ctrl＋ホイールは続けて来るので 300ms まとめて書く（曲を切り替える前・閉じる前は先に書く）
const ZOOM_KEY = 'automap-zoom', ZOOM_DEF = 30;
let zoomQ = null, zoomT = null;
const zoomMap = () => { const m = lsGet(ZOOM_KEY, {}); return m && typeof m === 'object' ? m : {}; };
function flushZoom() {
  clearTimeout(zoomT); zoomT = null;
  const q = zoomQ; zoomQ = null; if (!q) return;
  lsSet(ZOOM_KEY, {...zoomMap(), [q.song]: q.span});
}
function keepZoom() {   // 曲の名前はここで控える（待つ間に曲を切り替えても前の曲に書く）
  if (!S.song) return;
  zoomQ = {song: S.song, span: Math.round(V.span * 100) / 100};
  clearTimeout(zoomT); zoomT = setTimeout(flushZoom, 300);
}
const byUser = () => { const e = window.event;   // 利用者の入力の出来事を受けている最中か（スクリプトの click()・dispatchEvent は isTrusted が false）
  return !!(e && e.isTrusted && /^(click|dblclick|mousedown|mouseup|pointerdown|pointerup|contextmenu|keydown|keyup|wheel|change|input)$/.test(e.type)); };
addEventListener('beforeunload', flushZoom); addEventListener('pagehide', flushZoom);   // beforeunload＝store の pagehide の送り出しより前
export function zoomBy(f, at, keep = true) { const tm = at ?? (V.t0 + V.span / 2), r = (tm - V.t0) / V.span; V.span *= f; clampView(); V.t0 = tm - r * V.span; clampView(); draw(); if (keep) keepZoom(); }
export function showRange(t0, t1, keep = byUser()) { V.span = Math.max(4, (t1 - t0) * 1.25); V.t0 = t0 - (V.span - (t1 - t0)) / 2; clampView(); draw(); if (keep) keepZoom(); }
export function follow() {   // 再生中は再生位置が見えるように送る（つないだリプレイの再生中も）
  if (!busyPlaying()) return;
  if (S.t > V.t0 + V.span * 0.85 || S.t < V.t0) { V.t0 = S.t - V.span * 0.15; clampView(); }
}
export function reveal() {   // 再生位置が見えていなければ送る（止めたままつないだリプレイの側で動かした時・js/replaypane.js）
  if (S.t > V.t0 + V.span || S.t < V.t0) { V.t0 = S.t - V.span * 0.3; clampView(); draw(); }
}

// ---- 描く ----
function setup(cv, h) {
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth;
  if (h != null) cv.style.height = h + 'px';
  const hh = cv.clientHeight;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(hh * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(hh * dpr); }
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, hh); return [g, w, hh];
}
export function draw() {
  if (!S.D) return;
  GUT = Math.round(132 * UI.s);
  LAYOUT = lanes();
  const total = LAYOUT.length ? LAYOUT[LAYOUT.length - 1].y + LAYOUT[LAYOUT.length - 1].h + 6 : 100;
  const grew = $('lanes').clientHeight !== total;
  drawRuler(); drawLanes(total); drawOverview();
  if (grew) emit('lanesDrawn');
}
function drawGrid(g, h, x0 = GUT) {
  const b0 = Math.ceil(beatOf(V.t0)), b1 = Math.floor(beatOf(V.t0 + V.span)), bars = new Set(BEATS());
  const pxBeat = (W() - GUT) / V.span * 60 / S.D.bpm;
  for (let b = b0; b <= b1; b++) {
    const bar = bars.has(b); if (!bar && pxBeat < 7) continue;
    const x = X(timeOf(b)); if (x < x0) continue;
    g.fillStyle = bar ? css('--gridBar') : css('--grid'); g.fillRect(x, 0, 1, h);
  }
}
function drawRuler() {
  const [g, w, h] = setup($('ruler'));
  g.fillStyle = css('--panel'); g.fillRect(0, 0, w, h);
  const B = BEATS(), pxBar = (W() - GUT) / V.span * 240 / S.D.bpm, every = pxBar > 60 ? 1 : pxBar > 30 ? 2 : pxBar > 14 ? 4 : 8;
  g.font = F(11); g.textBaseline = 'top';
  B.forEach((b, i) => {
    const x = X(timeOf(b)); if (x < GUT - 1 || x > w) return;
    g.fillStyle = css('--gridBar'); g.fillRect(x, h - 10, 1, 10);
    if (i % every === 0) { g.fillStyle = css('--textdim'); g.fillText(String(i + 1), x + 3, 3); }
  });
  const step = V.span > 120 ? 30 : V.span > 40 ? 10 : V.span > 12 ? 5 : 1;
  g.fillStyle = css('--textmute');
  for (let s = Math.ceil(V.t0 / step) * step; s <= V.t0 + V.span; s += step) { const x = X(s); if (x < GUT) continue; g.fillRect(x, h - 4, 1, 4); g.fillText(fmt(s).replace('.0', ''), x + 3, h * 0.52); }
  g.fillStyle = css('--panel2'); g.fillRect(0, 0, GUT, h);
  g.fillStyle = css('--textdim'); g.fillText('小節', 10, 3); g.fillStyle = css('--textmute'); g.fillText('時刻', 10, h * 0.52);
  head(g, h);
}
function head(g, h) { const x = X(S.t); if (x >= GUT) { g.fillStyle = css('--head'); g.fillRect(x - 1, 0, 2, h); } }
function drawLanes(total) {
  const cv = $('lanes'), [g, w] = setup(cv, total);
  drawGrid(g, total);
  LAYOUT.forEach(l => {
    if (l.head) {
      g.fillStyle = css('--panel2'); g.fillRect(0, l.y, w, l.h);
      g.fillStyle = css('--textdim'); g.font = F(12, 'bold'); g.textBaseline = 'middle';
      g.fillText((OPEN[l.g] ? '▾ ' : '▸ ') + l.g, 8, l.y + l.h / 2 + 1); g.textBaseline = 'alphabetic';
      return;
    }
    g.save(); g.beginPath(); g.rect(GUT, l.y, w - GUT, l.h); g.clip(); l.f(g, X, l.y, l.h, V.t0, V.t0 + V.span);
    OVL.forEach(o => { if (o.n === l.n) o.f(g, X, l.y, l.h, V.t0, V.t0 + V.span); }); g.restore();
    g.fillStyle = css('--outline'); g.fillRect(GUT, l.y + l.h + 1, w - GUT, 1);
  });
  // 選んだ所・候補・ドラッグ中
  g.save(); g.beginPath(); g.rect(GUT, 0, w - GUT, total); g.clip();
  S.sel.forEach(([b0, b1]) => { const x0 = X(timeOf(b0)), x1 = X(timeOf(b1));
    g.fillStyle = css('--selFill'); g.fillRect(x0, 0, x1 - x0, total); g.strokeStyle = css('--accent'); g.lineWidth = 2; g.strokeRect(x0, 1, x1 - x0, total - 2); g.lineWidth = 1; });
  g.setLineDash([5, 4]); g.strokeStyle = '#d0a0ff';
  S.cand.filter(c => c.on).forEach(c => { const x0 = X(timeOf(c.b0)), x1 = X(timeOf(c.b1)); g.strokeRect(x0, 1, x1 - x0, total - 2); });
  // 同じ振りのつながり: 指している（か直している）区間の形の全部を光らせ、同じグループのもう1つの形は点線で囲む＝どこが一緒に変わるか
  const MF = motifForms(), cur = MF.byId.get(S.hoverId) || MF.byId.get(S.edit);
  if (cur) {
    const other = cur.key.endsWith('|A') ? cur.group + '|B' : cur.group + '|A';
    (MF.members.get(cur.key) || []).forEach(id => { const r = S.W.ranges.find(q => q.id === id); if (!r || MF.byId.get(id).link) return;
      const x0 = X(timeOf(r.b0)), x1 = X(timeOf(r.b1)); g.fillStyle = formColor(cur, 10).replace('hsl', 'hsla').replace('%)', '%,0.16)');
      g.fillRect(x0, 0, x1 - x0, total); g.strokeStyle = formColor(cur, 15); g.lineWidth = 2; g.strokeRect(x0, 1, x1 - x0, total - 2); g.lineWidth = 1; });
    g.setLineDash([4, 4]);
    (MF.members.get(other) || []).forEach(id => { const r = S.W.ranges.find(q => q.id === id); if (!r || MF.byId.get(id).link) return;
      const x0 = X(timeOf(r.b0)), x1 = X(timeOf(r.b1)); g.strokeStyle = formColor(MF.byId.get(id), 15); g.strokeRect(x0, 1, x1 - x0, total - 2); });
    g.setLineDash([]);
  }
  g.setLineDash([]);
  if (drag && drag.type === 'sel' && drag.moved) { const a = Math.min(drag.t0, drag.t1), b = Math.max(drag.t0, drag.t1);
    g.fillStyle = css('--selFill'); g.fillRect(X(a), 0, X(b) - X(a), total); }
  g.restore();
  // 見出しの列
  LAYOUT.forEach(l => { if (l.head) return;
    g.fillStyle = css('--panel'); g.fillRect(0, l.y, GUT, l.h + 3);
    g.fillStyle = css('--textmute'); g.font = F(12); g.textBaseline = 'middle'; g.fillText(l.n, 12, l.y + Math.min(l.h, 24 * UI.s) / 2 + 1);
    if (l.n === '作った譜面' && S.D.diff) {   // 見ている難易度（派生を見ている間は色を変える・docs/アプリ仕様.md 17 節）
      const der = S.D.base && S.D.diff !== S.D.base;
      g.fillStyle = der ? '#3bc9db' : css('--textmute'); g.font = F(10, der ? 'bold' : '');
      g.fillText((DIFF_TEXT[S.D.diff] || S.D.diff) + (der ? '（派生）' : '（基準）'), 12, l.y + Math.min(l.h, 24 * UI.s) / 2 + 15 * UI.s);
    }
    g.textBaseline = 'alphabetic';
    if (l.n === '量のライン') drawLineClear(g, l); });
  g.fillStyle = css('--outline'); g.fillRect(GUT - 1, 0, 1, total);
  head(g, total);
}
function drawOverview() {
  const [g, w, h] = setup($('ovw'));
  g.fillStyle = css('--panel'); g.fillRect(0, 0, w, h);
  const dur = S.D.dur, OX = t => GUT + t / dur * (w - GUT - 8);
  secs().forEach(s => { g.fillStyle = secCol(s.name) + '88'; g.fillRect(OX(s.t), h * 0.08, Math.max(1, OX(s.t1) - OX(s.t)), h * 0.3); });
  g.fillStyle = css('--textmute');
  S.D.notes.forEach(([t, , , c]) => { g.fillStyle = c === 0 ? css('--red') : css('--blue'); g.fillRect(OX(t), h * (c === 0 ? 0.44 : 0.6), 1, h * 0.13); });
  S.W.ranges.forEach(r => { g.fillStyle = r.set.rest ? '#868e96' : r.set.motif ? '#ae3ec9' : '#e8590c'; g.fillRect(OX(timeOf(r.b0)), h * 0.82, Math.max(2, OX(timeOf(r.b1)) - OX(timeOf(r.b0))), h * 0.09); });
  g.strokeStyle = css('--textdim'); g.lineWidth = 1.5; g.strokeRect(OX(V.t0), 1, OX(V.t0 + V.span) - OX(V.t0), h - 2); g.lineWidth = 1;
  g.fillStyle = css('--head'); g.fillRect(OX(S.t) - 1, 0, 2, h);
  g.fillStyle = css('--panel2'); g.fillRect(0, 0, GUT, h);
  g.fillStyle = css('--textmute'); g.font = F(12); g.fillText('全体', 12, h / 2 + 4);
}

// ---- 帯の中身 ----
let _secs = null, _secsOf = null;
export function secs() {
  if (_secsOf === S.D) return _secs;
  const out = [];
  S.D.marks.forEach(m => { if (m.name) out.push({t: m.t, beat: m.beat, name: m.name, tags: m.tags.slice()}); else if (out.length) out[out.length - 1].tags.push(...m.tags); });
  out.forEach((s, i) => { s.t1 = i + 1 < out.length ? out[i + 1].t : S.D.dur; });
  _secs = out; _secsOf = S.D; return out;
}
const PAL = ['#f08c00', '#3092ff', '#2fbf71', '#b15be6', '#ff4d6a', '#16b8c8', '#8fbf2f', '#e64d9a', '#868e96'];
const SECCOL = {};
export function secCol(n) { if (!(n in SECCOL)) SECCOL[n] = PAL[Object.keys(SECCOL).length % PAL.length]; return SECCOL[n]; }
function text(g, s, x, y, col, size = 11) { g.fillStyle = col; g.font = F(size); g.fillText(s, x, y); }
function laneSec(g, X, y, h) {
  secs().forEach(s => { const x0 = X(s.t), x1 = X(s.t1);
    g.fillStyle = secCol(s.name) + '40'; g.fillRect(x0, y, x1 - x0, h); g.fillStyle = secCol(s.name); g.fillRect(x0, y, 2, h);
    const tg = s.tags.filter(x => !x.startsWith('※')).join('') + (s.tags.some(x => x.startsWith('※')) ? '※' : '');
    text(g, s.name + (tg ? ' ' + tg : ''), x0 + 5, y + h * 0.7, css('--text'), 12); });
}
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
const labName = l => l < 0 ? '' : LETTERS[l % 52] + (l >= 52 ? Math.floor(l / 52) + 1 : '');
const barT = i => S.D.mus.bars[i], barEnd = i => i + 1 < S.D.mus.bars.length ? S.D.mus.bars[i + 1] : S.D.mus.bars[i] + 240 / S.D.bpm;
function laneLab(k) { return (g, X, y, h) => { g.textBaseline = 'middle';
  S.D.mus.lab[k].forEach((l, i) => { if (l < 0) return; const x0 = X(barT(i)), x1 = X(barEnd(i));
    g.fillStyle = 'hsl(' + ((l * 137.508) % 360) + ',55%,48%)'; g.fillRect(x0, y + 1, Math.max(1, x1 - x0 - 1), h - 2);
    if (x1 - x0 > 12) text(g, labName(l), x0 + 2, y + h / 2 + 1, '#fff', 10); });
  g.textBaseline = 'alphabetic'; }; }
function barRect(g, X, i, y, h, r) { const x0 = X(barT(i)), x1 = X(barEnd(i)); r = Math.max(0, Math.min(1, r)); g.fillRect(x0, y + h * (1 - r), Math.max(1, x1 - x0 - 1), h * r); }
function laneBarV(k, lo, hi, col) { return (g, X, y, h) => { g.fillStyle = css(col); S.D.mus.inten[k].forEach((v, i) => { if (v !== null) barRect(g, X, i, y, h, 0.08 + 0.92 * (v - lo) / (hi - lo)); }); }; }
function laneDrumPow(g, X, y, h) {
  g.fillStyle = css('--drm'); S.D.mus.inten.drum.forEach((v, i) => { if (v !== null) barRect(g, X, i, y, h, 0.08 + 0.92 * (v + 3) / 4.5); });
  g.fillStyle = css('--head'); S.D.mus.inten.drum_change.forEach(i => { const x = X(barT(i)); g.fillRect(x - 1, y, 2, h); });
}
function laneBreak(g, X, y, h) { S.D.mus.breaks.forEach(([t, len, kind]) => { g.fillStyle = kind === 'all' ? '#ff4d6a' : '#f08c00'; g.fillRect(X(t), y + 1, Math.max(3, X(t + len) - X(t)), h - 2); }); }
function laneLead(g, X, y, h) { S.D.mus.inten.lead.forEach((v, i) => { if (v === null || v < 0.05) return; g.fillStyle = S.D.mus.inten.sing[i] >= 0.5 ? '#b15be6' : '#2fbf71'; barRect(g, X, i, y, h, 0.2 + v / 0.3); }); }
function laneShift(g, X, y, h) { g.textBaseline = 'middle';
  S.D.mus.shift.forEach((k, i) => { if (!k) return; const x0 = X(barT(i)), x1 = X(barEnd(i)), v = k <= 6 ? k : k - 12;
    g.fillStyle = css('--head'); g.fillRect(x0, y + 1, Math.max(1, x1 - x0), h - 2); if (x1 - x0 > 16) text(g, (v > 0 ? '+' : '−') + Math.abs(v), x0 + 2, y + h / 2 + 1, '#fff', 10); });
  g.textBaseline = 'alphabetic'; }
let TOP = null;
function tops() { if (TOP && TOP.D === S.D) return TOP; TOP = {D: S.D};
  STEM.forEach(s => { const v = S.D.env[s.k].filter(x => x > -90).sort((a, b) => a - b); TOP[s.k] = v.length ? v[Math.floor(v.length * 0.99)] : 0; }); return TOP; }
function laneEnv(k) { return (g, X, y, h, t0, t1) => {
  const i = STEM.findIndex(s => s.k === k), e = S.D.env[k], top = tops()[k], lo = top - 30, fps = S.D.fps, fine = V.span < 40;
  g.fillStyle = css(STEM[i].c); g.globalAlpha = P.on[i] ? 0.85 : 0.25;
  const xa = Math.max(GUT, X(t0)), xb = X(t1), dt = V.span / (W() - GUT - 8);
  for (let px = Math.floor(xa); px < xb; px++) {
    const ta = tAt(px); let f0 = Math.floor(ta * fps), f1 = Math.max(f0 + 1, Math.floor((ta + dt) * fps)), v = -200, p = 0, c = 0;
    for (let f = f0; f < f1 && f < e.length; f++) if (f >= 0) { if (e[f] > v) v = e[f]; p += Math.pow(10, e[f] / 10); c++; }
    if (!fine && c) v = 10 * Math.log10(p / c + 1e-12);
    const r = Math.max(0, Math.min(1, (v - lo) / 30)); if (r > 0) g.fillRect(px, y + h * (1 - r), 1, h * r);
  }
  g.globalAlpha = 1; }; }
let PRANGE = null;
function laneVoc(g, X, y, h, t0, t1) {
  if (!PRANGE || PRANGE.D !== S.D) { const vm = S.D.voc.filter(v => v[3] >= 0.3).map(v => v[2]).sort((a, b) => a - b);
    PRANGE = {D: S.D, lo: vm.length ? Math.floor(vm[Math.floor(vm.length * 0.02)]) - 1 : 50, hi: vm.length ? Math.ceil(vm[Math.floor(vm.length * 0.98)]) + 1 : 80}; }
  const {lo, hi} = PRANGE, py = m => y + h - 3 - (Math.max(lo, Math.min(hi, m)) - lo) / (hi - lo) * (h - 6);
  for (let m = Math.ceil(lo / 12) * 12; m <= hi; m += 12) { g.fillStyle = css('--grid'); g.fillRect(GUT, py(m), W(), 1); text(g, 'C' + (m / 12 - 1), GUT + 4, py(m) - 2, css('--textmute'), 10); }
  g.fillStyle = css('--voc');
  S.D.voc.forEach(([t, len, m, s]) => { if (t + len < t0 || t > t1) return; g.globalAlpha = P.on[0] ? 0.25 + 0.75 * s : 0.2;
    const x0 = X(t), x1 = Math.max(x0 + 1.5, X(t + len)); g.fillRect(x0, py(m) - 2, x1 - x0, 4); });
  g.globalAlpha = 1;
}
function ticks(g, X, arr, y, h, t0, t1, col) { g.fillStyle = col; (arr || []).forEach(([t, s]) => { if (t < t0 || t > t1) return; const hh = Math.max(3, h * Math.min(1, s)); g.fillRect(X(t) - 0.75, y + h - hh, 1.5, hh); }); }
function laneDrum(g, X, y, h, t0, t1) { const r = h / 3; g.globalAlpha = P.on[1] ? 1 : 0.3;
  [['hihat', 'ハイハット'], ['snare', 'スネア'], ['kick', 'キック']].forEach(([k, n], j) => { ticks(g, X, S.D.hits[k], y + r * j + 1, r - 2, t0, t1, css('--drm')); text(g, n, GUT + 3, y + r * j + 10 * UI.s, css('--textmute'), 9); });
  g.globalAlpha = 1; }
function laneOther(g, X, y, h, t0, t1) { laneEnv('other')(g, X, y, h, t0, t1); g.globalAlpha = P.on[3] ? 0.9 : 0.3; ticks(g, X, S.D.hits.other, y, h * 0.5, t0, t1, css('--text')); g.globalAlpha = 1; }
function laneBass(g, X, y, h, t0, t1) { laneEnv('bass')(g, X, y, h, t0, t1); g.globalAlpha = P.on[2] ? 0.9 : 0.3; ticks(g, X, S.D.hits.bass, y, h * 0.5, t0, t1, css('--text')); g.globalAlpha = 1; }
function laneBlocks(g, X, y, h) {
  const BASECOL = {}; S.D.blocks.forEach(([, , , base]) => { if (!(base in BASECOL)) BASECOL[base] = Object.keys(BASECOL).length; });
  g.textBaseline = 'middle';
  S.D.blocks.forEach(([t0, t1, grp, base, lv]) => { const x0 = X(t0), x1 = X(t1);
    g.fillStyle = 'hsl(' + ((BASECOL[base] * 137.508) % 360) + ',50%,' + (30 + lv * 9) + '%)'; g.fillRect(x0, y + 1, Math.max(1, x1 - x0 - 1), h - 2);
    if (x1 - x0 > 18) text(g, grp + lv, x0 + 3, y + h / 2 + 1, '#fff', 11); });
  g.textBaseline = 'alphabetic';
}
const DIRV = [[0, -1], [0, 1], [-1, 0], [1, 0], [-1, -1], [1, -1], [-1, 1], [1, 1]];
function drawNotes(g, X, y, h, t0, t1, list) {
  const r = h / 3, fine = V.span < 24, u = UI.s;
  (list || []).forEach(([t, x, ny, c, d]) => { if (t < t0 - 0.2 || t > t1 + 0.2) return;
    const cx = X(t) + (fine ? (x - 1.5) * 3 * u : 0), cy = y + r * (2 - ny) + r / 2;
    g.fillStyle = c === 0 ? css('--red') : css('--blue'); const sz = (fine ? 8 : 3) * u; g.fillRect(cx - sz / 2, cy - sz / 2, sz, sz);
    if (fine && d >= 0 && d < 8) { const [dx, dy] = DIRV[d]; g.strokeStyle = '#fff'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + dx * 6 * u, cy + dy * 6 * u); g.stroke(); g.lineWidth = 1; } });
}
// クリップの状態の色（NLM とのやり取りの決まり）: 作ったまま＝紫（作り直す）・手で直した＝橙・固定＝緑・利用者のクリップ＝青・前の形式＝灰。
// 作り直しで残るのは紫以外。作ったクリップのレーンの隙間＝NLM で消した所（赤い斜線・空のまま）
const CLIP_ST = {app: ['rgba(16,185,129,0.13)', '#10b981', ''], edited: ['rgba(255,159,26,0.16)', '#ff9f1a', '✎ '], fixed: ['rgba(86,255,193,0.12)', '#56ffc1', '🔒 '],
  user: ['rgba(48,146,255,0.14)', '#3092ff', '👤 '], legacy: ['rgba(160,160,160,0.14)', '#9a9a9a', '? ']};
function laneChart(g, X, y, h, t0, t1) {
  const cs = (S.D.clips || []).slice().sort((a, b) => (a.main === false) - (b.main === false));
  cs.forEach(c => { const x0 = X(c.t0), x1 = X(c.t1), [fill, line, mark] = CLIP_ST[c.state] || CLIP_ST[c.keep ? 'fixed' : 'app'];
    const yy = c.main === false ? y + h - 7 * UI.s : y, hh = c.main === false ? 7 * UI.s : h;   // 作ったクリップと別のレーン（利用者のクリップ等）は下に細く
    g.fillStyle = fill; g.fillRect(x0, yy, x1 - x0, hh);
    g.strokeStyle = line; g.lineWidth = c.state && c.state !== 'app' ? 2 : 1; g.strokeRect(x0 + 0.5, yy + 0.5, x1 - x0 - 1, hh - 1); g.lineWidth = 1;
    if (c.main !== false && x1 - x0 > 40) text(g, mark + c.label + (c.reason ? '（' + c.reason + '・残す）' : ''), x0 + 4, y + 11 * UI.s, c.state && c.state !== 'app' ? line : css('--textdim'), 10); });
  (S.D.holes || []).forEach(([, , ta, tb]) => { const x0 = X(ta), x1 = X(tb);
    g.save(); g.beginPath(); g.rect(x0, y, x1 - x0, h); g.clip(); g.strokeStyle = 'rgba(255,77,106,0.45)';
    for (let x = x0 - h; x < x1; x += 8) { g.beginPath(); g.moveTo(x, y + h); g.lineTo(x + h, y); g.stroke(); }
    g.restore(); g.strokeStyle = '#ff4d6a'; g.strokeRect(x0 + 0.5, y + 0.5, x1 - x0 - 1, h - 1);
    if (x1 - x0 > 40) text(g, '✕ 消した所（空のまま）', x0 + 4, y + 11 * UI.s, '#ff8095', 10); });
  const [ny, nh] = chartNotesBox(y, h);
  drawNotes(g, X, ny, nh, t0, t1, S.D.notes);
}
function summary(set) {
  const out = [];
  const ab = {source: v => '元:' + ({vocal: '歌', drums: 'ドラム', bass: 'ベース', inst: '楽器', 'vocal+drums': '歌＋ドラム'}[v] || v), amount: v => '量' + (v > 0 ? '+' : '−') + Math.abs(v),
    snare: v => 'スネア' + v, kick: v => 'キック' + v, fill: () => '空き埋め', vsnap: v => v ? '歌を拍に' : '歌を寄せない', rest: () => '休み', hands: v => '両手' + (v > 0 ? '+' : '−') + Math.abs(v),
    speed: v => '速さ' + (v > 0 ? '+' : '−') + Math.abs(v)};
  Object.entries(set).forEach(([k, v]) => { if (ab[k]) out.push(ab[k](v)); });
  if (set.variant != null) out.push('案 ' + set.variant);   // 別の案で選んだ案
  if (set.rare) out.push('珍しい型まで');   // 型の幅（inspector.js の CTRL）
  if (set.band != null) out.push(Array.isArray(set.band) ? (set.band[0] <= 0 && set.band[1] >= 99 ? '★全部' : set.band[0] <= 0 ? `★〜${set.band[1]}` : set.band[1] >= 99 ? `★${set.band[0]}〜` : `★${set.band[0]}〜${set.band[1]}`)
    : `★${Math.abs(set.band)}段${set.band > 0 ? '↑' : '↓'}`);   // ★の帯（inspector.js の bandText の短い形）
  if (set.kime) out.push(set.kime > 0 ? '決め入れる' : '決め入れない');
  if (set.motif) out.push(`同じ振り「${set.motif.group}」${set.motif.mode === 'arrange' ? '（アレンジ' + (set.motif.extra != null ? '・量' + (set.motif.extra > 0 ? '+' : set.motif.extra < 0 ? '−' : '') + Math.abs(set.motif.extra) : '') + '）' : ''}`);
  return out;
}
function stripes(g, x0, y, w, h) {   // アレンジの形（B）の目印の斜めの縞
  g.save(); g.beginPath(); g.rect(x0, y, w, h); g.clip(); g.strokeStyle = 'rgba(255,255,255,0.22)'; g.lineWidth = 2;
  for (let x = x0 - h; x < x0 + w; x += 7) { g.beginPath(); g.moveTo(x, y + h); g.lineTo(x + h, y); g.stroke(); }
  g.restore(); g.lineWidth = 1;
}
function laneIntent(g, X, y, h) {
  g.textBaseline = 'middle';
  const MF = motifForms(), mixed = new Set([...MF.members.keys()].filter(k => formDiff(MF, k).length));   // mixed＝回ごとに設定が違う形（札に ≠）
  // 同じ振りの区間を先（下）に、形に付いた指示を後（上・少し細く）に描く
  const order = S.W.ranges.slice().sort((a, b) => (MF.byId.get(a.id)?.link ? 1 : 0) - (MF.byId.get(b.id)?.link ? 1 : 0) || a.id - b.id);
  order.forEach(r => { const x0 = X(timeOf(r.b0)), x1 = X(timeOf(r.b1)), f = MF.byId.get(r.id);
    const yy = f && f.link ? y + h * 0.45 : y + 1, hh = f && f.link ? h * 0.55 - 1 : h - 2;
    const onlyVar = (r.set.variant != null || r.set.rare || r.set.band != null) && Object.keys(r.set).every(k => ['variant', 'rare', 'band', 'comment'].includes(k));   // 「案 k」・「珍しい型まで」・「★の帯」だけの指示（テーマだけ変える）は青
    g.fillStyle = r.set.rest ? '#5c636a' : r.set.keep ? '#3d4248' : f ? formColor(f) : onlyVar ? '#1c7ed6' : '#d9480f';
    g.globalAlpha = r.id === S.edit ? 1 : 0.85; g.fillRect(x0, yy, Math.max(2, x1 - x0 - 1), hh); g.globalAlpha = 1;
    if (f && f.form === 'B' && !f.link) stripes(g, x0, yy, Math.max(2, x1 - x0 - 1), hh);
    if (r.id === S.edit) { g.strokeStyle = '#fff'; g.lineWidth = 2; g.strokeRect(x0, yy, x1 - x0, hh); g.lineWidth = 1; }
    const lab = f && !f.link ? [formLabel(f) + (mixed.has(f.key) ? ' ≠' : ''), ...summary(r.set).filter(s => !s.startsWith('同じ振り'))] : summary(r.set);
    if (x1 - x0 > 24) { g.save(); g.beginPath(); g.rect(x0, yy, x1 - x0 - 2, hh); g.clip(); text(g, lab.join('・') || '（指示なし）', x0 + 4, yy + hh / 2 + 1, '#fff', f && f.link ? 10 : 11); g.restore(); } });
  if (S.W.auto_rest.on) { const b = S.W.auto_rest.b != null ? S.W.auto_rest.b : beatOf(S.D.dur * 0.7), x = X(timeOf(b));
    g.fillStyle = css('--textdim'); g.fillRect(x, y, 2, h); text(g, S.W.auto_rest.b != null ? '休み' : '休み（自動）', x + 4, y + h / 2 + 1, css('--textdim'), 11); }
  g.textBaseline = 'alphabetic';
}
// 量のライン: キーフレーム {b, k, smooth}。その点から次の点まで同じ値（段）・次の点が smooth ならその点へなめらかに。最初の点の前は 100%
export function lineValue(b) {
  const ks = S.W.line.slice().sort((a, c) => a.b - c.b);
  let pb = 0, pk = 1;
  for (const kf of ks) { if (b < kf.b) return kf.smooth ? pk + (kf.k - pk) * (b - pb) / Math.max(1e-6, kf.b - pb) : pk; pb = kf.b; pk = kf.k; }
  return pk;
}
const lineY = (l, k) => l.y + 9 + (l.h - 18) * (1 - (k - LINE_LO) / (LINE_HI - LINE_LO));
const lineK = (l, y) => Math.max(LINE_LO, Math.min(LINE_HI, Math.round((LINE_HI - (y - l.y - 9) / (l.h - 18) * (LINE_HI - LINE_LO)) * 10) / 10));
// 今の譜面の小節ごとの 1 秒のノーツの数（濃淡の元）。譜面が変わった時だけ数え直す
const NPS = {notes: null, bars: null, max: 0};
function barNps() {
  if (NPS.notes === S.D.notes && NPS.bars === BEATS()) return NPS;
  const B = BEATS(), ts = S.D.notes.map(n => n[0]).sort((a, b) => a - b), out = [];
  let j = 0;
  for (let i = 0; i < B.length; i++) {
    const a = timeOf(B[i]), b = timeOf(barEndBeat(i));
    while (j < ts.length && ts[j] < a - 1e-6) j++;
    let k = j; while (k < ts.length && ts[k] < b - 1e-6) k++;
    out.push(b > a ? (k - j) / (b - a) : 0); j = k;
  }
  const live = out.filter(v => v > 0).sort((a, b) => a - b);   // 色の幅は曲の中の少ない小節（下から 1 割）〜一番多い小節（同じような密度の曲でも差が見える）
  Object.assign(NPS, {notes: S.D.notes, bars: B, v: out, lo: live.length ? live[Math.floor(live.length * 0.1)] : 0, max: Math.max(1, ...out)});
  return NPS;
}
// 作り直した時の量のライン（pending.js が /api/versions/pending の line_was を S.pendLine に入れる・点を直線でつなぐ形＝intent_table）
function prevLineValue(b) {
  const p = S.pendLine;
  if (!p || !p.length) return 1;
  if (b <= p[0].b) return p[0].k;
  for (let i = 1; i < p.length; i++) if (b <= p[i].b) return p[i - 1].k + (p[i].k - p[i - 1].k) * (b - p[i - 1].b) / Math.max(1e-6, p[i].b - p[i - 1].b);
  return p[p.length - 1].k;
}
function laneLine(g, X, y, h, t0, t1) {
  const l = {y, h};
  // 背景: 今の譜面の小節ごとの 1 秒のノーツの数を濃淡で（濃いほど多い・曲の中で一番多い小節が一番濃い）。その上に量のライン（黄色）
  const B = BEATS(), np = barNps(), i0 = Math.max(0, barIdx(beatOf(Math.max(0, t0)))), i1 = barIdx(beatOf(t1));
  for (let i = i0; i <= i1 && i < B.length; i++) {
    const x0 = X(timeOf(B[i])), x1 = X(timeOf(barEndBeat(i))), v = np.v[i] || 0;
    const r = v > 0 ? Math.max(0, Math.min(1, (v - np.lo) / Math.max(0.5, np.max - np.lo))) : 0;
    g.fillStyle = v > 0 ? `rgba(70,160,255,${(0.08 + 0.55 * r).toFixed(3)})` : 'rgba(0,0,0,0)'; g.fillRect(x0, y, x1 - x0 + 0.5, h);
    if (x1 - x0 > 30) text(g, v.toFixed(1), x0 + 3, y + h - 3, r > 0.6 ? css('--text') : css('--textmute'), 9);
  }
  // 量のラインを直したが、まだ作り直していない小節（今の濃淡は前の譜面のまま＝計算が合っていない）: 網掛けと枠
  if (S.pendLine) {
    let run = null;
    const flush = () => { if (!run) return; const x0 = X(timeOf(run[0])), x1 = X(timeOf(run[1]));
      g.save(); g.beginPath(); g.rect(x0, y, x1 - x0, h); g.clip(); g.strokeStyle = 'rgba(255,170,40,0.55)'; g.lineWidth = 1.5;
      for (let x = x0 - h; x < x1; x += 7) { g.beginPath(); g.moveTo(x, y + h); g.lineTo(x + h, y); g.stroke(); }
      g.restore(); g.strokeStyle = '#ffaa28'; g.lineWidth = 2; g.setLineDash([5, 3]); g.strokeRect(x0 + 1, y + 1, x1 - x0 - 2, h - 2); g.setLineDash([]); g.lineWidth = 1;
      if (x1 - x0 > 70) text(g, '未反映（作り直すと変わる）', x0 + 5, y + h - 15 * UI.s, '#ffaa28', 10);
      run = null; };
    for (let i = i0; i <= i1 && i < B.length; i++) {
      const bad = Math.abs(prevLineValue(B[i]) - lineValue(B[i])) > 0.005;
      if (bad) run = run ? [run[0], barEndBeat(i)] : [B[i], barEndBeat(i)]; else flush();
    }
    flush();
  }
  for (let k = LINE_LO; k <= LINE_HI + 1e-6; k += 0.5) { const yy = lineY(l, k); g.fillStyle = Math.abs(k - 1) < 1e-6 ? css('--textmute') : css('--grid'); g.fillRect(GUT, yy, W(), 1); }   // 50% ごと（10% ごとは多すぎた）
  text(g, '200%', GUT + 3, lineY(l, 2.0) + 9, css('--textmute'), 9); text(g, '150%', GUT + 3, lineY(l, 1.5) - 2, css('--textmute'), 9);
  text(g, '100%', GUT + 3, lineY(l, 1) - 2, css('--textmute'), 9); text(g, '50%', GUT + 3, lineY(l, 0.5) - 2, css('--textmute'), 9);
  const bA = beatOf(Math.max(0, t0)), bB = beatOf(t1), n = 240;
  g.strokeStyle = css('--accent2'); g.lineWidth = 2; g.beginPath();
  for (let i = 0; i <= n; i++) { const b = bA + (bB - bA) * i / n, xx = X(timeOf(b)), yy = lineY(l, lineValue(b)); i ? g.lineTo(xx, yy) : g.moveTo(xx, yy); }
  g.stroke(); g.lineWidth = 1;
  S.W.line.forEach(kf => { const xx = X(timeOf(kf.b)), yy = lineY(l, kf.k), sel = kf === S.lineSel;
    const rr = 5 * UI.s; g.fillStyle = sel ? '#fff' : css('--accent2'); g.beginPath(); kf.smooth ? g.arc(xx, yy, rr, 0, 7) : g.rect(xx - rr, yy - rr, rr * 2, rr * 2); g.fill();
    if (sel) { g.strokeStyle = css('--accent2'); g.lineWidth = 2; g.stroke(); g.lineWidth = 1; }
    text(g, Math.round(kf.k * 100) + '%', xx + 7, kf.k >= 1.85 ? yy + 13 : yy - 6, css('--text'), 11); });   // 上の方は点の下に書く（帯の上で切れない）
}

// ---- 操作 ----
function headTextEnd(l) { const g = $('lanes').getContext('2d'); g.font = F(12, 'bold'); return 8 + g.measureText((OPEN[l.g] ? '▾ ' : '▸ ') + l.g).width + 6; }
const posIn = (cv, e) => { const r = cv.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; };
const laneAt = y => LAYOUT.find(l => y >= l.y && y < l.y + l.h + (l.head ? 0 : 3));
function keyAt(x, y, l) { return S.W.line.find(kf => Math.hypot(X(timeOf(kf.b)) - x, lineY(l, kf.k) - y) < 9 * UI.s) || null; }
function blockAt(t) { return S.D.blocks.find(k => t >= k[0] && t < k[1]); }
function rangeAtT(t) { return S.W.ranges.filter(r => t >= timeOf(r.b0) && t < timeOf(r.b1)).sort((a, b) => b.id - a.id)[0]; }
function snapBeat(t, alt) { const b = beatOf(t); return alt ? Math.round(b) : nearestBar(b); }
export function selectRange(b0, b1, add) {
  // 付けた指示（形の回）を直している間に帯で区間を選んだ＝その指示を外して、新しい区間の空の指示に（2026-11-02 利用者。前は直している
  // 指示が残り、「直す」で指示を選んだ区間へ動かしていた）
  if (S.edit != null) { S.edit = null; S.panel = {}; }
  if (!add) S.sel = [];
  if (!S.sel.some(([a, b]) => Math.abs(a - b0) < 1e-6 && Math.abs(b - b1) < 1e-6)) S.sel.push([b0, b1]);
  S.sel.sort((p, q) => p[0] - q[0]); S.cand = []; emit('select');
}
function addKey(b, k) {
  commit(Wk => { const ex = Wk.line.find(kf => Math.abs(kf.b - b) < 1e-6); if (ex) ex.k = k; else Wk.line.push({b, k, smooth: false}); });
  S.lineSel = S.W.line.find(kf => Math.abs(kf.b - b) < 1e-6) || null; draw();
}
export function deleteKey(kf) { commit(Wk => { const i = Wk.line.indexOf(kf); if (i >= 0) Wk.line.splice(i, 1); }); S.lineSel = null; draw(); }
// 量のラインを全部消すボタン（2026-11-09 利用者・前は右の欄の一番下）: 見出しの列の「量のライン」の字の下に canvas で描き、見出しのクリックで受ける
// （帯と一緒に縦にスクロールし、「編集」を畳むと消え、表示の大きさで大きさが変わる）。点が無い時・派生を見ている間（locked）は薄く、押しても
// 消さない（ロック中は emit('locked') で知らせる）。消すのは前と同じ commit（元に戻すで戻る）
let lcHover = false;
const lineClearRect = l => { const u = UI.s; return {x: 10 * u, y: l.y + 30 * u, w: GUT - 20 * u, h: 22 * u}; };
const inLineClear = (l, x, y) => { if (!l || l.n !== '量のライン') return false; const r = lineClearRect(l); return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; };
const lineClearOn = () => S.W.line.length > 0 && !locked();
function drawLineClear(g, l) {
  const r = lineClearRect(l), on = lineClearOn(), u = UI.s;
  g.save(); g.globalAlpha = on ? 1 : 0.4;
  g.fillStyle = css(on && lcHover ? '--widget2' : '--widget'); g.strokeStyle = '#1d1d1d'; g.lineWidth = 1;
  g.beginPath(); if (g.roundRect) g.roundRect(r.x + 0.5, r.y + 0.5, r.w, r.h, 5 * u); else g.rect(r.x + 0.5, r.y + 0.5, r.w, r.h); g.fill(); g.stroke();
  g.fillStyle = css('--text'); g.font = F(11); g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(S.W.line.length ? `全部消す（${S.W.line.length} 点）` : '全部消す', r.x + r.w / 2, r.y + r.h / 2 + 1);
  g.restore();
}
function lineClearTip() {
  if (!S.W.line.length) return '量のラインに点が無い';
  if (locked()) return '派生を見ている間は量のラインを変えられない（基準に戻って消す）';
  return `量のラインの点を全部（${S.W.line.length} 点）消す（元に戻すで戻せる）`;
}
function clearLine() {
  if (!S.W.line.length) return;
  if (locked()) { emit('locked'); return; }
  S.lineSel = null; lcHover = false; commit(W => { W.line = []; }); draw();
}
export function menu(e, items) {   // e＝{clientX, clientY}（右クリックの出来事か、ボタンの位置）
  const m = $('ctx'); m.innerHTML = ''; items.forEach(([n, fn]) => { const b = document.createElement('button'); b.textContent = n; b.onclick = () => { hideMenu(); fn(); }; m.appendChild(b); });
  m.style.display = 'block'; m.style.left = Math.min(e.clientX, innerWidth - 200) + 'px'; m.style.top = Math.min(e.clientY, innerHeight - 40 * items.length) + 'px';
}
export function hideMenu() { $('ctx').style.display = 'none'; }

export function init() {
  const cv = $('lanes'), wrap = $('lanesWrap');
  cv.addEventListener('mousedown', e => {
    hideMenu(); if (e.button !== 0 || !S.D) return;
    const {x, y} = posIn(cv, e), l = laneAt(y);
    if (!l) return;
    if (l.head) {   // 畳む・開くのは見出しの文字（▾ 編集 など）の上だけ（行のほかの所を間違ってクリックして畳んでしまった・利用者）
      if (x <= headTextEnd(l)) { OPEN[l.g] = !OPEN[l.g]; draw(); emit('lanesDrawn'); }
      else if (x >= GUT) seek(tAt(x));
      return;
    }
    if (x < GUT) { if (inLineClear(l, x, y)) clearLine(); return; }   // 見出しの列: 量のラインの「全部消す」だけ
    if (l.n === '量のライン') {
      if (locked()) { if (keyAt(x, y, l)) emit('locked'); else seek(tAt(x)); return; }   // 派生を見ている間は点を動かさない（store.locked）
      const kf = keyAt(x, y, l);
      S.lineSel = kf; if (kf) drag = {type: 'key', kf, l, before: takeSnap(), alt: e.altKey};
      draw(); return;
    }
    drag = {type: 'sel', x0: x, y0: y, t0: tAt(x), t1: tAt(x), moved: false, shift: e.shiftKey, beat: e.altKey, l, e};
  });
  window.addEventListener('mousemove', e => {
    if (!drag) return;
    const {x, y} = posIn(cv, e);
    if (drag.type === 'key') { drag.kf.b = Math.max(0, snapBeat(tAt(x), e.altKey)); drag.kf.k = lineK(drag.l, y); drag.moved = true; draw(); emit('lineDrag'); return; }
    if (Math.abs(x - drag.x0) > 4) drag.moved = true;
    drag.t1 = tAt(x); if (drag.moved) draw();
  });
  window.addEventListener('mouseup', e => {
    if (!drag) return;
    const d = drag; drag = null;
    if (d.type === 'key') { if (d.moved) commit(() => {}, {before: d.before}); draw(); return; }
    if (d.moved) {
      const a = Math.min(d.t0, d.t1), b = Math.max(d.t0, d.t1);
      if (d.beat) { const ba = Math.floor(beatOf(a) + 1e-6); selectRange(ba, Math.max(ba + 1, Math.ceil(beatOf(b) - 1e-6)), d.shift); }
      else { const B = BEATS(), i0 = barIdx(beatOf(a)), bb = beatOf(b), i1 = barIdx(bb); selectRange(B[i0], Math.abs(B[i1] - bb) < 1e-6 ? B[i1] : barEndBeat(i1), d.shift); }
      draw(); return;
    }
    const t = d.t0;   // クリック
    const op = {x: d.x0, dy: d.y0 - d.l.y, h: d.l.h, X};
    if (OVL.some(o => o.n === d.l.n && o.click && o.click(t, e, op))) { draw(); return; }   // 重ねた印
    const ex = EXT.find(q => q.n === d.l.n); if (ex && ex.click && ex.click(t, e)) { draw(); return; }
    if (d.l.n === '流れの表') { const k = blockAt(t); if (k) { selectRange(k[5], k[6], e.shiftKey); draw(); return; } }
    if (d.l.n === '意思入れ' && !locked()) { const r = rangeAtT(t); if (r) { emit('editDirective', r); draw(); return; } }   // 派生を見ている間は指示を開かない
    seek(t);
  });
  cv.addEventListener('mousemove', e => { if (drag) return; const {x, y} = posIn(cv, e), l = laneAt(y);
    const op = l && !l.head && x >= GUT ? {x, dy: y - l.y, h: l.h, X} : null;
    const otip = op ? OVL.reduce((s, o) => s || (o.n === l.n && o.hover ? o.hover(tAt(x), op) || '' : ''), '') : '';   // 重ねた印の見出し
    const lc = x < GUT && inLineClear(l, x, y);   // 量のラインの「全部消す」
    cv.style.cursor = (l && l.head && x <= headTextEnd(l)) || otip || (lc && lineClearOn()) ? 'pointer' : '';
    const ex = l && !l.head && x >= GUT && EXT.find(q => q.n === l.n), tip = lc ? lineClearTip() : otip || (ex && ex.hover ? ex.hover(tAt(x)) || '' : '');   // 足した帯の数字（title）
    if (cv.title !== tip) cv.title = tip;
    if (lc !== lcHover) { lcHover = lc; draw(); }
    const r = l && l.n === '意思入れ' && x >= GUT ? rangeAtT(tAt(x)) : null, id = r ? r.id : null;   // 指している同じ振りの形を光らせる
    if (id !== S.hoverId) { S.hoverId = id; draw(); } });
  cv.addEventListener('mouseleave', () => { if (S.hoverId != null || lcHover) { S.hoverId = null; lcHover = false; draw(); } });
  cv.addEventListener('dblclick', e => {
    const {x, y} = posIn(cv, e), l = laneAt(y); if (!l || l.head || x < GUT) return;
    if (l.n === '流れの表') { const k = blockAt(tAt(x)); if (k) { S.sel = []; S.D.blocks.filter(q => q[3] === k[3]).forEach(q => selectRange(q[5], q[6], true)); draw(); } }
    if (l.n === '量のライン' && !keyAt(x, y, l)) { if (locked()) { emit('locked'); return; } addKey(Math.max(0, snapBeat(tAt(x), e.altKey)), lineK(l, y)); }
  });
  cv.addEventListener('contextmenu', e => {
    e.preventDefault(); const {x, y} = posIn(cv, e), l = laneAt(y); if (!l || l.head || x < GUT) return;
    if (locked() && (l.n === '量のライン' || l.n === '意思入れ')) { emit('locked'); return; }   // 派生を見ている間は直す・消すを出さない
    if (l.n === '量のライン') {
      const kf = keyAt(x, y, l);
      if (kf) { S.lineSel = kf; draw();
        menu(e, [[kf.smooth ? '段にする（この点から急に変える）' : '前の点からなめらかにつなぐ', () => commit(() => { kf.smooth = !kf.smooth; })],
                 ['この点を消す', () => deleteKey(kf)]]); }
      else menu(e, [['ここに点を置く（' + Math.round(lineK(l, y) * 100) + '%）', () => addKey(Math.max(0, snapBeat(tAt(x), e.altKey)), lineK(l, y))]]);
      return;
    }
    if (l.n === '意思入れ') { const r = rangeAtT(tAt(x)); if (!r) return;
      const MF = motifForms(), f = MF.byId.get(r.id), del = formDeleteItems(r, MF);   // 同じ振りの回＝形の全部を直す・消すのは回だけ／形の全部／グループの全部
      if (del) menu(e, [[`この形を直す（${f.group} ${f.form}・${formRuns(MF, f.key).length} 回をそろえる）`, () => emit('editDirective', r)], ...del]);
      else menu(e, [['この指示を直す', () => emit('editDirective', r)], ['この指示を消す', () => emit('deleteDirective', r)]]); }
  });
  wrap.addEventListener('wheel', e => {
    if (!S.D) return;
    const d = e.deltaY || e.deltaX;
    if (e.shiftKey) { wrap.scrollTop += d; e.preventDefault(); return; }
    e.preventDefault();
    if (e.ctrlKey) { const {x} = posIn(cv, e); zoomBy(Math.exp(d * 0.0015), x > GUT ? tAt(x) : undefined); return; }
    V.t0 += d / (W() - GUT) * V.span; clampView(); draw();
  }, {passive: false});
  const rul = $('ruler');
  let scrub = false;
  rul.addEventListener('mousedown', e => { const {x} = posIn(rul, e); if (x < GUT) return; scrub = true; seek(tAt(x)); });
  window.addEventListener('mousemove', e => { if (scrub) seek(tAt(posIn(rul, e).x)); });
  window.addEventListener('mouseup', () => { scrub = false; });
  const ov = $('ovw');
  let ovDrag = false;
  const ovMove = e => { const {x} = posIn(ov, e), w = ov.clientWidth; const t = (x - GUT) / (w - GUT - 8) * S.D.dur; V.t0 = t - V.span / 2; clampView(); draw(); };
  ov.addEventListener('mousedown', e => { if (!S.D || posIn(ov, e).x < GUT) return; ovDrag = true; ovMove(e); });
  window.addEventListener('mousemove', e => { if (ovDrag) ovMove(e); });
  window.addEventListener('mouseup', () => { ovDrag = false; });
  new ResizeObserver(() => draw()).observe($('tl'));
  window.addEventListener('mousedown', e => { if (!e.target.closest('#ctx')) hideMenu(); });
  on('frame', () => { follow(); draw(); });
  on('work', draw); on('select', draw); on('player', draw); on('ui', draw); on('pending', draw);
  if (location.hash.startsWith('#zmtest')) zoomTest();
  if (location.hash.startsWith('#lctest')) lineClearTest();
}

// 確かめ用（見えない Edge で #lctest）: 量のラインに点を 2 つ置き（作業ファイルには保存しない）→ 見出しの「全部消す」でマウスを押す → 消えたか →
// 元に戻す → 戻ったか → 派生を見ている間（S.view を仮に入れる）は押しても消えず知らせるか → 点を戻した形で写す。結果は document.title と #lctestOut
async function lineClearTest() {
  const out = [], sleep = ms => new Promise(r => setTimeout(r, ms));
  let ok = true; const chk = (name, c) => { out.push((c ? 'OK ' : 'NG ') + name); ok = ok && c; };
  try {
    for (let i = 0; !(S.D && resets > 0); i++) { if (i > 600) throw new Error('曲が開かない'); await sleep(50); }
    await sleep(300);
    S.readonly = true; OPEN['編集'] = true;
    const B = BEATS(), cv = $('lanes');
    commit(W => { W.line = [{b: B[8], k: 1.3, smooth: false}, {b: B[16], k: 0.8, smooth: true}]; });
    showRange(timeOf(B[4]), timeOf(B[24])); draw();
    const l = LAYOUT.find(q => q.n === '量のライン'), r = lineClearRect(l);
    const press = () => { const rc = cv.getBoundingClientRect(), o = {clientX: rc.left + r.x + r.w / 2, clientY: rc.top + r.y + r.h / 2, button: 0, bubbles: true};
      cv.dispatchEvent(new MouseEvent('mousedown', o)); window.dispatchEvent(new MouseEvent('mouseup', o)); };
    const px = () => { const d = window.devicePixelRatio || 1, p = cv.getContext('2d').getImageData(Math.round((r.x + 4 * UI.s) * d), Math.round((r.y + r.h / 2) * d), 1, 1).data; return [p[0], p[1], p[2]].join(','); };
    let lockedSeen = 0; on('locked', () => { lockedSeen++; });
    chk(`右の欄のボタンが無い（#iLineClear ${$('iLineClear') ? 'ある' : '無い'}）`, !$('iLineClear'));
    const pxOn = px();
    chk(`点 ${S.W.line.length} → 全部消すを押す`, S.W.line.length === 2);
    press(); await sleep(50);
    chk(`消えた（点 ${S.W.line.length}）`, S.W.line.length === 0);
    const pxOff = px();
    chk(`点が無い時は薄い（色 ${pxOn} → ${pxOff}）`, pxOn !== pxOff);
    press(); await sleep(50);
    chk(`点が無い時に押しても何も起きない（点 ${S.W.line.length}・知らせ ${lockedSeen}）`, S.W.line.length === 0 && lockedSeen === 0);
    undo(); await sleep(50);
    chk(`元に戻すで戻った（点 ${S.W.line.length}）`, S.W.line.length === 2);
    S.view = 'Expert'; draw(); const pxLock = px();
    press(); await sleep(50);
    chk(`派生を見ている間は消えない（点 ${S.W.line.length}・知らせ ${lockedSeen}・薄い ${pxLock !== pxOn}）`, S.W.line.length === 2 && lockedSeen === 1 && pxLock !== pxOn);
    S.view = null; draw();
    chk(`戻した後の色 ${px()}`, px() === pxOn);
  } catch (e) { out.push('エラー ' + e.message); ok = false; }
  document.title = 'lctest ' + (ok ? 'OK' : 'NG') + ' ' + out.join(' ／ ');
  const pre = document.createElement('pre'); pre.id = 'lctestOut'; pre.style.display = 'none'; pre.textContent = (ok ? 'OK' : 'NG') + '\n' + out.join('\n'); document.body.appendChild(pre);
}
let resets = 0;   // 確かめ用（曲を開き終えたか）
export function reset() {   // 曲を開いた時（main.js の openSong が S.song・S.D を入れた後）: 拡大率はその曲で覚えた物（無ければ 30 秒）・位置は曲の頭
  flushZoom();
  const z = +zoomMap()[S.song];
  V.t0 = -1; V.span = z > 0 ? z : ZOOM_DEF; clampView(); _secsOf = null; for (const k in SECCOL) delete SECCOL[k];
  resets++;
}

// 確かめ用（見えない Edge で #zmtest）: 曲 X の覚えを消して開き直す → ＋（zoomBy）2 回 → 300ms 待たずに曲 Y → Y でスクリプトから showRange
// （覚えない）→ X に戻す（戻るか）→ X で Ctrl＋ホイールを 5 回（まとめて 1 回だけ書くか）→ アプリの設定（/api/prefs）に入ったか。
// 結果は document.title と #zmtestOut（--dump-dom）。#zmtest=look は開いた曲の拡大率と覚えを出すだけ（起動し直して戻るかを見る）
async function zoomTest() {
  const out = [], sleep = ms => new Promise(r => setTimeout(r, ms)), fin = ok => {
    document.title = 'zmtest ' + (ok ? 'OK' : 'NG') + ' ' + out.join(' ／ ');
    let pre = $('zmtestOut'); if (!pre) { pre = document.createElement('pre'); pre.id = 'zmtestOut'; pre.style.display = 'none'; document.body.appendChild(pre); }
    pre.textContent = (ok ? 'OK' : 'NG') + '\n' + out.join('\n');
  };
  const until = async (f, ms = 30000) => { for (let i = 0; !f(); i++) { if (i * 50 > ms) throw new Error('待ちきれない'); await sleep(50); } };
  const open = async name => { const n = resets; $('song').value = name; $('song').dispatchEvent(new Event('change')); await until(() => resets > n && S.song === name); await sleep(50); };
  const sp = () => Math.round(V.span * 100) / 100, near = (a, b) => Math.abs(a - b) < 0.02;
  try {
    await until(() => S.D && resets > 0 && S.songs.length);
    if ((location.hash.split('=')[1] || '') === 'look') { out.push(`曲 ${S.song} 拡大率 ${sp()} 覚え ${JSON.stringify(zoomMap())}`); fin(true); return; }
    const X = S.song, Y = (S.songs.find(q => q.song !== X) || {}).song;
    if (!Y) { out.push('曲が 1 つしか無い'); fin(false); return; }
    const m0 = zoomMap(); delete m0[X]; delete m0[Y]; lsSet(ZOOM_KEY, m0);
    await open(Y); await open(X);
    let ok = true; const chk = (name, c) => { out.push((c ? 'OK ' : 'NG ') + name); ok = ok && c; };
    chk(`X=${X} 覚えなし→既定 ${sp()}`, near(sp(), ZOOM_DEF));
    zoomBy(1 / 1.5); zoomBy(1 / 1.5); const want = sp();
    chk(`X で＋2回→${want}`, near(want, ZOOM_DEF / 2.25));
    await open(Y);   // 300ms 待たずに切り替える（切り替えの前に書く）
    chk(`Y=${Y} 覚えなし→既定 ${sp()}`, near(sp(), ZOOM_DEF));
    chk(`切り替えの前に X を書いた（覚え ${zoomMap()[X]}）`, near(+zoomMap()[X], want));
    showRange(10, 14); await sleep(400);
    chk(`Y でスクリプトから showRange→${sp()}・覚えない（${zoomMap()[Y]}）`, near(sp(), 5) && zoomMap()[Y] === undefined);
    await open(X);
    chk(`X に戻した→${sp()}`, near(sp(), want));
    const cnt = {n: 0}, ls0 = window.localStorage.setItem.bind(window.localStorage);
    try { Storage.prototype._zmSet = Storage.prototype.setItem; Storage.prototype.setItem = function (k, v) { if (k === ZOOM_KEY) cnt.n++; return this._zmSet(k, v); };
      for (let i = 0; i < 5; i++) { $('lanesWrap').dispatchEvent(new WheelEvent('wheel', {deltaY: 100, ctrlKey: true, cancelable: true, clientX: 600, clientY: 300})); await sleep(30); }
      await sleep(450);
    } finally { Storage.prototype.setItem = Storage.prototype._zmSet; delete Storage.prototype._zmSet; void ls0; }
    const wv = sp();
    chk(`X で Ctrl＋ホイール 5 回→${wv}・書いたのは ${cnt.n} 回`, wv > want && cnt.n === 1 && near(+zoomMap()[X], wv));
    await sleep(600);   // アプリの設定へ送るのは 400ms まとめて
    const pr = await (await fetch('/api/prefs', {headers: {'X-Automap': '1'}})).json(), sv = (pr[ZOOM_KEY] || {});
    chk(`アプリの設定に入った（${X}=${sv[X]}・${Y}=${sv[Y]}）`, near(+sv[X], wv) && sv[Y] === undefined);
    fin(ok);
  } catch (e) { out.push('エラー ' + e.message); fin(false); }
}
export {newId};
