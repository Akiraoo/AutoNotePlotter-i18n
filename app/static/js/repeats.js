// 同じ音楽の区間（自動の同じ振り・automap/repeat.py・app/repeats.py）の組と各回の範囲を、帯「作った譜面」に重ねて出す。main.js が init(app) を呼ぶ。
// 2026-11-11 利用者「繰り返しの箇所が具体的にどこなのか譜面のラインで見たい。その上で難易度展開でその繰り返しをどう展開しているか確認したい」。
// 読むのは見ている譜面の作り直しの報告（/api/repeats）: 基準＝<結果>.report.md・派生を見ている間（S.view）＝<結果>.<難易度>.report.md・
//   別の案・履歴の版（versions.js の viewing()）＝その版の報告（決めの場所と同じ選び方）。
// 描き方: 帯の下の端の空き（timeline.js の CHART_FOOT・ノーツの下）に組ごとの色の細い帯と回の両端の縦線・回の頭に札「自動1 手本」「自動1 同じ」「自動1 反転」
//   （狭いと「1 手本」→「1」→ 札なし）。手本＝濃い帯・同じ＝薄い帯・左右反転＝斜めの縞。決めの枠（check.js・金色）は上の端に札を出す＝重ならない。
//   下の端の帯に重ねると組の名前・小節の数・その回の拍と時刻・種類・同じ組のほかの回（重ねている間は同じ組の全部の回を薄く塗る）、
//   押すとその回の範囲を選ぶ（Shift で足す）。重ね描きは決めより先に足す（main.js）＝下の端の帯の上ではこちらの見出しが先・枠は上に描かれる。
// 読み直すのは曲を開いた・作り直した（'generated'）・譜面を読み直した（'chart'＝見る難易度を変えた・別の案や履歴の版を見ている）時。
//   古い答えが後から来ても今の物を消さない（seq）。見ている物（難易度・版）が変わった後は、答えが来るまで前の物を出さない（key）。
// 確かめ用: #rptest[&song=曲名][&diff=Expert]（その曲を開き・その難易度を見てから、1 つ目の組の範囲を見せ、組の一覧と重ねた時の文を
//   見えない <pre id="rptestOut"> に＝--dump-dom で読む。マウスの出来事を帯に送って、重ねた時の見出し・光らせた組・ノーツの所へ動かすと
//   消えるかも）・#rptest=2（2 つ目の組）・#rptest=click（その組の 1 つ目の回を押す→選んだ区間）・
//   &span=秒（1 回目の頭からその秒数だけ見せる＝細かい見え方）。
import {S, $, css, fmt, api, on, UI, timeOf, diffText} from './store.js';
import * as tl from './timeline.js';
import {viewing} from './versions.js';

const R = {list: null, D: null, key: '', seq: 0, state: '', file: '', diff: '', derived: false, err: '', hot: null, seen: null};
let timer = null, A = null;   // A＝main.js から渡された口（確かめ用に曲を開く）
// 組ごとの色（決めの金色 #ffd43b・ノーツの赤青・クリップの橙と離した）
const PAL = ['#4dabf7', '#f783ac', '#38d9a9', '#b197fc', '#94d82d', '#66d9e8', '#e599f7', '#ffa8a8', '#91a7ff'];
const KIND = {model: '手本', same: '同じ', mirror: '反転'};
const KIND_LONG = {model: '手本（1 回目・ここの打点と置き方をほかの回へ写す）', same: '同じ（手本と同じ置き方）',
  mirror: '左右反転（手本の置き方を左右逆に・手を入れ替え）'};
const F = (n, w = '') => (w ? w + ' ' : '') + (n * UI.s).toFixed(1) + 'px ' + css('--font');
const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
const viewKey = () => { const v = viewing(); return (S.view || '') + '|' + (v ? (v.ver ? 'v' + v.ver : 'c' + v.cand) : ''); };
const groups = () => (R.D === S.D && R.key === viewKey() && R.list) || [];
const colOf = i => PAL[i % PAL.length];
const num = g => g.name.replace(/^自動/, '');
const beats = o => `拍 ${+o.b0.toFixed(2)}〜${+o.b1.toFixed(2)}`;
const span = o => `${fmt(timeOf(o.b0))}〜${fmt(timeOf(o.b1))}`;

async function refresh() {
  if (!S.file || !S.D) return;
  const v = viewing(), key = viewKey(), my = ++R.seq, D = S.D;
  const qs = v ? (v.ver ? '&ver=' + encodeURIComponent(v.ver) : '&cand=' + v.cand) : S.view ? '&diff=' + encodeURIComponent(S.view) : '';
  try {
    const r = await api('GET', '/api/repeats?file=' + encodeURIComponent(S.file) + qs);
    if (my !== R.seq || S.D !== D) return;
    Object.assign(R, {list: r.groups || [], state: r.state, file: r.file, diff: r.diff, derived: !!r.derived, err: '', D, key});
  } catch (e) {
    if (my !== R.seq || S.D !== D) return;
    Object.assign(R, {list: [], state: 'error', file: '', err: e.message, D, key});
  }
  if (R.hot && !groups().some(g => g.name === R.hot)) R.hot = null;
  tl.draw();
  if (location.hash.startsWith('#rptest')) selfTest();
}
function later() { clearTimeout(timer); timer = setTimeout(refresh, 120); }   // 'chart' と 'generated' が続けて来ても 1 回だけ

// ---- 帯「作った譜面」に重ねる ----
// 置く所: 帯「作った譜面」の下の端の空き（timeline.js の CHART_FOOT＝ノーツの下）。一番下の 7u は別のレーンのクリップ（利用者のクリップ等）の細い帯
// （timeline.js の laneChart）なので、その上に置く
const geo = (y, h) => { const u = UI.s, bot = y + h - 7 * u, bh = 5 * u, tagH = 10 * u; return {u, bh, tagH, bot, by: bot - bh, ty: bot - tagH, cap: tagH}; };
function label(g, gr, o, w) {   // 札の字（狭いと短く・入らなければ ''）
  const pad = 6 * UI.s;
  for (const s of [`${gr.name} ${KIND[o.kind] || o.kind}`, `${num(gr)} ${KIND[o.kind] || o.kind}`, num(gr)]) {
    if (g.measureText(s).width + pad <= w) return s;
  }
  return '';
}
function stripes(g, x0, y, w, h, col) {   // 左右反転の回の目印の斜めの縞
  g.save(); g.beginPath(); g.rect(x0, y, w, h); g.clip(); g.strokeStyle = col; g.lineWidth = 1.5;
  for (let x = x0 - h; x < x0 + w; x += 5 * UI.s) { g.beginPath(); g.moveTo(x, y + h); g.lineTo(x + h, y); g.stroke(); }
  g.restore();
}
function draw(g, X, y, h, t0, t1) {
  const gs = groups(); if (!gs.length) return;
  const {u, bh, tagH, bot, by, ty, cap} = geo(y, h);
  g.font = F(9, 'bold');
  gs.forEach((gr, gi) => {
    const col = colOf(gi), hot = R.hot === gr.name;
    gr.occ.forEach(o => {
      if (timeOf(o.b1) < t0 - 1 || timeOf(o.b0) > t1 + 1) return;
      const x0 = X(timeOf(o.b0)), x1 = X(timeOf(o.b1)), w = Math.max(1, x1 - x0);
      if (hot) {   // 重ねている組の全部の回を薄く塗る＝どこが同じ音楽か
        g.fillStyle = rgba(col, 0.13); g.fillRect(x0, y + 1, w, h - 2);
        g.fillStyle = rgba(col, 0.85); g.fillRect(x0, y + 1, 1.5, h - 2); g.fillRect(x1 - 1.5, y + 1, 1.5, h - 2);
      }
      g.fillStyle = rgba(col, o.kind === 'model' ? 0.95 : o.kind === 'same' ? 0.55 : 0.4); g.fillRect(x0, by, w, bh);
      if (o.kind === 'mirror') stripes(g, x0, by, w, bh, rgba(col, 1));
      g.fillStyle = col; g.fillRect(x0, bot - cap, 1.5 * u, cap); g.fillRect(x1 - 1.5 * u, bot - cap, 1.5 * u, cap);   // 回の両端
      const lab = label(g, gr, o, w);
      if (!lab) return;
      const tw = g.measureText(lab).width + 6 * u;
      g.fillStyle = rgba(col, hot ? 1 : 0.92); g.fillRect(x0, ty, tw, tagH);
      g.fillStyle = '#111'; g.textBaseline = 'middle'; g.fillText(lab, x0 + 3 * u, ty + tagH / 2 + 0.5); g.textBaseline = 'alphabetic';
    });
  });
}
function at(p) {   // 重ねた所（下の端の札と帯の高さ）の回 → [組, 組の番号, 回] か null
  const {ty, bot} = geo(0, p.h);
  if (p.dy < ty - 2 * UI.s || p.dy > bot + 2 * UI.s) return null;
  const gs = groups();
  for (let gi = 0; gi < gs.length; gi++) {
    const o = gs[gi].occ.find(q => { const x0 = p.X(timeOf(q.b0)), x1 = p.X(timeOf(q.b1)); return p.x >= x0 - 1 && p.x <= x1 + 1; });
    if (o) return [gs[gi], gi, o];
  }
  return null;
}
function text(gr, o) {
  const i = gr.occ.indexOf(o);
  return [`同じ音楽の区間（自動の同じ振り）　${gr.name}・${gr.bars} 小節・${gr.occ.length} 回`,
    `この回（${i + 1} 回目）: ${KIND_LONG[o.kind] || o.kind}　${span(o)}（${beats(o)}）`,
    '同じ組の回:', ...gr.occ.map((q, k) => `${q === o ? '▶' : '　'} ${k + 1}. ${KIND[q.kind] || q.kind}　${span(q)}（${beats(q)}）`),
    `（${R.derived ? diffText(R.diff) + '（派生）' : diffText(R.diff) + '（基準）'}の作り直しの報告 ${R.file} から）`].join('\n');
}
function hover(t, p) {
  const a = at(p); R.seen = a ? a[0].name : null;
  return a ? text(a[0], a[2]) + '\n（押すとこの回の範囲を選ぶ・Shift で足す）' : '';
}
function click(t, e, p) {
  const a = at(p); if (!a) return false;
  tl.selectRange(a[2].b0, a[2].b1, e.shiftKey);
  return true;
}

// ---- 確かめ用 ----
function dump(extra = []) {
  let pre = $('rptestOut');
  if (!pre) { pre = document.createElement('pre'); pre.id = 'rptestOut'; pre.style.display = 'none'; document.body.appendChild(pre); }
  const gs = groups();
  pre.textContent = [`file=${R.file} state=${R.state} diff=${R.diff} derived=${R.derived} view=${S.view || '(基準)'} base=${S.D.base} groups=${gs.length}${R.err ? ' err=' + R.err : ''}`,
    ...gs.map(g => `${g.name} ${g.bars} 小節: ` + g.occ.map(o => `${KIND[o.kind] || o.kind} ${fmt(timeOf(o.b0))}（${beats(o)}）`).join(' → ')),
    ...extra, '', '----', ...gs.flatMap(g => g.occ.map(o => text(g, o) + '\n----'))].join('\n');
}
function probe(g, o, press) {   // 本物のマウスの出来事を帯に送る: 重ねた時の見出し（title）・光らせた組・ノーツの所へ動かすと消えるか・押すとその回を選ぶか
  const cv = $('lanes'), rc = cv.getBoundingClientRect(), GUT = Math.round(132 * UI.s);   // 横の位置は timeline.js の X と同じ式
  const x = GUT + (timeOf(o.b0) - tl.V.t0) / tl.V.span * (cv.clientWidth - GUT - 8) + 4 * UI.s;
  const ev = (type, y) => cv.dispatchEvent(new MouseEvent(type, {clientX: rc.left + x, clientY: rc.top + y, button: 0, bubbles: true}));
  let y0 = null;
  for (let y = 0; y < cv.clientHeight && y0 == null; y++) { ev('mousemove', y); if (cv.title.startsWith('同じ音楽の区間')) y0 = y; }
  if (y0 == null) return ['NG 重ねても見出しが出ない'];
  const t1 = cv.title, hot1 = R.hot;
  ev('mousemove', y0 - 14 * UI.s); const t2 = cv.title, hot2 = R.hot;   // 上のノーツの所（決めの枠・帯の見出しの所）
  const ok1 = t1.includes(`${g.name}・${g.bars} 小節`) && hot1 === g.name, ok2 = !t2.startsWith('同じ音楽の区間') && hot2 === null;
  const out = [`${ok1 ? 'OK' : 'NG'} 重ねた（帯の上から ${Math.round(y0)}px）: 光らせた組 ${hot1}・見出しの 1 行目「${t1.split('\n')[0]}」`,
    `${ok2 ? 'OK' : 'NG'} 上のノーツの所へ動かした: 光らせた組 ${hot2}・見出し「${t2.split('\n')[0]}」`];
  if (press) {
    ev('mousemove', y0); ev('mousedown', y0); ev('mouseup', y0);
    const sel = JSON.stringify(S.sel), ok3 = S.sel.length === 1 && Math.abs(S.sel[0][0] - o.b0) < 1e-6 && Math.abs(S.sel[0][1] - o.b1) < 1e-6;
    out.push(`${ok3 ? 'OK' : 'NG'} 押した: 選んだ区間 ${sel}（回 ${o.b0}〜${o.b1}）`);
  }
  return out;
}
async function selfTest() {   // 見えない Edge で #rptest を開いて画像に写す（後ろに &song=曲名・&diff=難易度）
  const h = decodeURIComponent(location.hash), sm = h.match(/&song=([^&]+)/), dm = h.match(/&diff=([^&]+)/);
  if (sm && S.song !== sm[1] && A && S.songs.some(q => q.song === sm[1])) { if (!R.opening) { R.opening = true; await A.openSong(sm[1]); } return; }
  const want = dm && dm[1] !== S.D.base ? dm[1] : null;
  if (want && S.view !== want) {   // 見る難易度を変える（上の列の選びと同じ道＝main.js の setView）→ 'chart' でここに戻る
    if (!R.viewing) { R.viewing = true; S.readonly = true; const sel = $('viewDiff'); sel.value = want; sel.dispatchEvent(new Event('change')); }
    return;
  }
  if (R.tested) return; R.tested = true; S.readonly = true;
  const gs = groups(), arg = (h.match(/^#rptest(?:=([a-z0-9]+))?/) || [])[1] || '', g = gs[Math.max(0, (+arg || 1) - 1)];
  let extra = [];
  if (g) {
    const sp = +((h.match(/&span=([\d.]+)/) || [])[1] || 0), t0 = timeOf(g.occ[0].b0);   // &span=秒＝1 回目の頭からその秒数だけ（細かい見え方）
    if (sp > 0) tl.showRange(t0 - 1, t0 - 1 + sp); else tl.showRange(t0 - 2, timeOf(g.occ[g.occ.length - 1].b1) + 2);
    await new Promise(r => setTimeout(r, 50));
    extra = ['', '---- マウス', ...probe(g, g.occ[0], arg === 'click')];
    R.hot = g.name; tl.draw();   // 重ねた時と同じ見え方で写す（マウスが動くまで残る）
  }
  document.title = `rptest ${gs.length} ${R.state} ${R.file}` + (extra.some(l => l.startsWith('NG')) ? ' NG' : g ? ' OK' : '');
  dump(extra);
}

export function init(app) {
  A = app;
  tl.addOverlay('作った譜面', draw, {hover, click});
  // 重ねている組を光らせる: timeline.js の見出しの処理（hover を呼ぶ）の後に、今の動きで hover が組を指したかを見る（帯の外・下の端の外では消す）
  const cv = $('lanes');
  cv.addEventListener('mousemove', () => { const s = R.seen; R.seen = null; if (s !== R.hot) { R.hot = s; tl.draw(); } });
  cv.addEventListener('mouseleave', () => { R.seen = null; if (R.hot) { R.hot = null; tl.draw(); } });
  on('work', () => { if (S.D && S.D !== R.D) { R.list = null; R.hot = null; later(); } });   // 曲を開いた
  on('chart', later);       // 譜面を読み直した・見る難易度を変えた・別の案や履歴の版を見ている
  on('generated', later);   // 作り直した（報告が変わる）
}
