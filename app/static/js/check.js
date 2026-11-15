// 区間の点検（app/check.py・automap/section_check.py）の画面。main.js が init(app) を呼ぶ。
// タイムラインの「比べる」のグループに帯「区間の点検」を足す（帯「区間」と同じ切り方）。区間ごとに:
//  1. 人の譜面との近さ＝色の濃さ（4振りの並びが人の譜面（2曲以上）に出る割合。濃い＝人の譜面によくある並び・薄い＝珍しい並び）
//  2. 曲の中での似かた＝印（≠ 同じ音楽なのに譜面が違う・＝ 違う音楽なのに前の区間とほぼ同じ）
//  3. 振りの交互の崩れ・NLM の振りの警告と同じ決まり（⚠ の数）
//  4. 意思入れの指示・「案 k」・残したクリップ（NLM で直した所）があるか（画面で数える）
// 帯に重ねると数字（title）、押すとその区間を選ぶ（右の欄の「この区間だけ作り直す」「別の案を作る」へ進める）。
// 曲を開いた・作り直した（'generated'）・譜面を読み直した／別の案や履歴の版を見ている（'chart'）・ライブラリの設定を変えた時に数え直す。
// 数えるのは見ている譜面（S.D.notes）。境目（印の目安）は仮＝数字をそのまま見て人が決める。
// 派生の難易度を見ている間（S.view・docs/アプリ仕様.md 17 節）は基準の譜面で数える（ノーツを送らない＝サーバーが基準の難易度を読む・
// 作り直す区間を選ぶ材料なので）。決めの場所も基準の物なので、その間は出さない。
// 決めの場所（珍しい型の「決め」・automap/kime.py＝型のデータベースの曲だけ）: /api/kime（作り直しの報告の表）を読み、帯「作った譜面」に
//   重ねて金色の枠と札「決」（決めのノーツは丸で囲む）・帯「区間の点検」に「決N」。重ねると型・場所・曲の数、押すとその区間を選ぶ。
//   見ている版（別の案・履歴の版＝versions.js の viewing()）の報告を読む。作り直した後・譜面を読み直した時に読み直す。決めの無い曲では何も出さない。
//   確かめ用: #ktest（1つ目の決めを見せて、重ねた時の文を #ktestOut に）・#ktest=2（2つ目）・#ktest=click（1つ目を押す→選んだ区間を title に）。
import {S, css, fmt, api, on, UI, barIdx, timeOf, beatOf, diffText} from './store.js';
import * as tl from './timeline.js';
import {viewing} from './versions.js';

const LO = 0.6;   // 色の一番薄い所（人の譜面の 32 拍ごとの中央は 85% 前後・作った譜面は 70〜100%）
const C = {res: null, D: null, notesOf: null, libKey: null, seq: 0, busy: false, err: '', stale: false, tries: 0};
let timer = null, A = null;   // A＝main.js から渡された口（確かめ用に曲を開く）
const K = {list: null, notes: [], D: null, seq: 0, file: ''};   // 決めの場所（/api/kime の答え）
const KC = '#ffd43b';   // 決めの色
const kimes = () => (!S.view && K.D === S.D && K.list) || [];   // 派生を見ている間は出さない（決めは基準の報告）
const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
const pct1 = v => (v == null ? '—' : (v * 100 < 10 ? (v * 100).toFixed(1) : Math.round(v * 100)) + '%');
const libKey = () => JSON.stringify((S.W && S.W.library) || null);
const F = (n, w = '') => (w ? w + ' ' : '') + (n * UI.s).toFixed(1) + 'px ' + css('--font');

async function refresh() {
  if (!S.file || !S.D) return;
  const my = ++C.seq, D = S.D, notes = S.D.notes, base = !S.view;
  C.busy = true; tl.draw();
  try {
    const r = await api('POST', '/api/check', {file: S.file, ...(base ? {notes} : {}), library: (S.W && S.W.library) || null, wait: 6});
    if (my !== C.seq || S.D !== D) return;
    C.res = r; C.D = D; C.notesOf = notes; C.libKey = libKey(); C.err = '';
    if (r.library.state === 'building' && C.tries++ < 30) { timer = setTimeout(refresh, 300); return; }   // ライブラリを数えている＝少し待って聞き直す
    C.tries = 0;
    if (location.hash.startsWith('#ctest')) selfTest();
  } catch (e) {
    if (my !== C.seq) return;
    C.err = e.message; C.tries = 0;
  } finally {
    if (my === C.seq) { C.busy = false; tl.draw(); }
  }
}
function later() { clearTimeout(timer); C.tries = 0; timer = setTimeout(() => { refresh(); refreshKime(); }, 120); }   // 'chart' と 'generated' が続けて来ても 1 回だけ

// ---- 決めの場所 ----
async function refreshKime() {
  if (!S.file || !S.D) return;
  const v = viewing(), qs = !v ? '' : v.ver ? '&ver=' + encodeURIComponent(v.ver) : '&cand=' + v.cand;
  const my = ++K.seq, D = S.D;
  try {
    const r = await api('GET', '/api/kime?file=' + encodeURIComponent(S.file) + qs);
    if (my !== K.seq || S.D !== D) return;
    K.list = r.kimes || []; K.notes = r.notes || []; K.file = r.file; K.D = D;
  } catch (e) { if (my === K.seq) { K.list = []; K.D = D; } }
  tl.draw();
  if (location.hash.startsWith('#ktest')) kimeTest();
  else if (location.hash.startsWith('#vtest')) dumpKime();   // 別の案・履歴の版を見ている時の決め（--dump-dom で見る）
}
const PAD = () => 5 * UI.s;
const kimeX = (k, X) => [X(timeOf(k.b0)) - PAD(), X(timeOf(k.b1)) + PAD()];
function drawKime(g, X, y, h, t0, t1) {   // 帯「作った譜面」に重ねる（ノーツの位置は timeline.js の drawNotes と同じ決まり）
  const ks = kimes(); if (!ks.length) return;
  const u = UI.s, tagH = 12 * u, [ny, nh] = tl.chartNotesBox(y, h), r = nh / 3, fine = tl.V.span < 24;
  ks.forEach(k => {
    if (timeOf(k.b1) < t0 - 1 || timeOf(k.b0) > t1 + 1) return;
    const [x0, x1] = kimeX(k, X);
    g.globalAlpha = k.gone ? 0.45 : 1;
    g.fillStyle = 'rgba(255,212,59,0.10)'; g.fillRect(x0, y + 1, x1 - x0, h - 2);
    g.strokeStyle = KC; g.lineWidth = 1.5; if (k.gone) g.setLineDash([4, 3]);
    g.strokeRect(x0 + 0.5, y + 1.5, x1 - x0 - 1, h - 3); g.setLineDash([]);
    S.D.notes.forEach(([t, x, yy, c, , b]) => {   // 決めのノーツ（その手・最初と最後の振りの間）を丸で囲む
      if (c !== k.hand || b < k.b0 - 1e-3 || b > k.b1 + 1e-3) return;
      g.beginPath(); g.arc(X(t) + (fine ? (x - 1.5) * 3 * u : 0), ny + r * (2 - yy) + r / 2, (fine ? 7 : 4) * u, 0, 7); g.stroke();
    });
    g.lineWidth = 1;
    const lab = x1 - x0 > 90 * u ? `決 ${k.place}` : '決';
    g.font = F(10, 'bold'); const w = g.measureText(lab).width + 6 * u;
    g.fillStyle = KC; g.fillRect(x0, y + 1, w, tagH);
    g.fillStyle = '#111'; g.textBaseline = 'middle'; g.fillText(lab, x0 + 3 * u, y + 1 + tagH / 2 + 0.5); g.textBaseline = 'alphabetic';
    g.globalAlpha = 1;
  });
}
const kimeAt = p => kimes().find(k => { const [x0, x1] = kimeX(k, p.X); return p.x >= x0 && p.x <= x1; });
function kimeText(k) {
  const hand = k.hand === 1 ? '右手' : '左手', sr = secOfBeat(k.b0), lane = sr ? tl.secs().find(s => Math.abs(s.beat - sr[0]) < 1e-6) : null;
  const sec = lane && lane.name !== k.sec ? `${k.sec}（作り直しの区間・帯「区間」では ${lane.name}）` : k.sec;   // 流れの表で作った時は、まとまりの記号＋何回目
  return [`決め（珍しい型）　${fmt(timeOf(k.b0))}〜${fmt(timeOf(k.b1))}（拍 ${+k.b0.toFixed(2)}〜${+k.b1.toFixed(2)}）`,
    `区間 ${sec}・場所 ${k.place}${k.place_beat != null ? '（拍 ' + (+k.place_beat.toFixed(2)) + '）' : ''}・${hand}`,
    `型（その手の形・x y）${k.seq_text}`,
    `曲の数 ${k.maps ?? '?'}（${[k.freq, k.hard].filter(Boolean).join('・')}）・決めたとおりに置けた ${k.placed ?? '?'} / ${k.total ?? k.seq.length}`,
    ...(k.own ? [] : ['（区間だけ作り直す前の版の報告から。今の譜面にもそのままある）']),
    ...(k.gone ? ['※ 今の譜面のその手の所は型どおりでない（NLM で直した等）'] : [])].join('\n');
}
function secOfBeat(b) {   // 帯「区間」と同じ切り方の、拍 b を含む区間 → [始まりの拍, 終わりの拍]
  const ss = tl.secs(), i = ss.findIndex(s => b >= s.beat - 1e-6 && (timeOf(b) < s.t1));
  if (i < 0) return null;
  return [ss[i].beat, i + 1 < ss.length ? ss[i + 1].beat : beatOf(ss[i].t1)];
}
function kimeHover(t, p) { const k = kimeAt(p); return k ? kimeText(k) + '\n（押すとこの区間を選ぶ）' : ''; }
function kimeClick(t, e, p) {
  const k = kimeAt(p), r = k && secOfBeat(k.b0); if (!r) return false;
  tl.selectRange(r[0], r[1], e.shiftKey);
  return true;
}
const kimesIn = s => kimes().filter(k => k.b0 >= s.b0 - 1e-6 && k.b0 < s.b1 - 1e-6);
function dumpKime() {
  let pre = document.getElementById('ktestOut');
  if (!pre) { pre = document.createElement('pre'); pre.id = 'ktestOut'; pre.style.display = 'none'; document.body.appendChild(pre); }
  pre.textContent = `${K.file}\n` + kimes().map(kimeText).join('\n\n----\n') + '\n\n----\n' + K.notes.join('\n');
}
async function kimeTest() {   // 確かめ用（見えない Edge で #ktest を開いて画像に写す）。後ろに &song=曲名 でその曲を開いてから
  const h = decodeURIComponent(location.hash), sm = h.match(/&song=([^&]+)/);
  if (sm && S.song !== sm[1] && A && S.songs.some(q => q.song === sm[1])) { if (!K.opening) { K.opening = true; await A.openSong(sm[1]); } return; }
  if (K.tested) return; K.tested = true;
  const ks = kimes(), arg = (h.match(/^#ktest(?:=([a-z0-9]+))?/) || [])[1] || '', k = ks[Math.max(0, (+arg || 1) - 1)];
  document.title = `ktest ${ks.length} ${K.file}`;
  dumpKime();
  if (!k) return;
  tl.showRange(timeOf(k.b0) - 3, timeOf(k.b1) + 3);
  if (arg === 'click') { const r = secOfBeat(k.b0); tl.selectRange(r[0], r[1]); document.title += ' sel ' + JSON.stringify(S.sel); }
}

// ---- 区間ごとの、画面で数える物（4: 意思入れ・案・残したクリップ） ----
function local(s) {
  const ov = (a0, a1) => a0 < s.b1 - 1e-6 && a1 > s.b0 + 1e-6;
  const rs = (S.W.ranges || []).filter(r => ov(r.b0, r.b1));
  const vars = [...new Set(rs.filter(r => r.set.variant != null).map(r => r.set.variant))];
  const dirs = rs.filter(r => Object.keys(r.set).some(k => k !== 'variant' && k !== 'comment'));
  const keep = S.view ? [] : (S.D.clips || []).filter(c => c.keep && ov(c.b0, c.b1));   // 派生を見ている間のクリップは派生の物＝数えない
  const holes = S.view ? [] : (S.D.holes || []).filter(([a, b]) => ov(a, b));
  return {dirs, vars, keep, holes, motif: dirs.some(r => r.set.motif), rest: dirs.some(r => r.set.rest)};
}
function marks(s) {   // 帯に書く短い印
  const out = [], L = local(s);
  if (s.flags.includes('differ')) out.push('≠');
  if (s.flags.includes('mono')) out.push('＝');
  const bad = s.reset + s.warn; if (bad) out.push('⚠' + bad);
  if (L.dirs.length) out.push('指示' + L.dirs.length);
  L.vars.forEach(v => out.push('案' + v));
  if (L.keep.length) out.push('残' + L.keep.length);
  if (L.holes.length) out.push('消');
  const km = kimesIn(s).length; if (km) out.push('決' + km);
  return out;
}

// ---- 帯 ----
function fillOf(s, lib) {
  if (lib.state !== 'ok' || s.near == null) return 'rgba(120,128,136,0.22)';
  const a = 0.08 + 0.82 * Math.max(0, Math.min(1, (s.near - LO) / (1 - LO)));   // 4振りの並びが人の譜面に出る割合 60% 以下→薄い・100%→濃い
  return `rgba(32,201,151,${a.toFixed(3)})`;
}
function lane(g, X, y, h, t0) {
  const r = C.res && C.D === S.D ? C.res : null;
  g.textBaseline = 'middle'; g.font = F(11);
  if (!r) {
    g.fillStyle = css('--textmute'); g.fillText(C.err ? '数えられなかった: ' + C.err : '区間ごとの数字を数えている…', Math.max(X(0), X(t0)) + 6, y + h / 2 + 1);
    g.textBaseline = 'alphabetic'; return;
  }
  const lib = r.library;
  r.sections.forEach(s => {
    const x0 = X(s.t0), x1 = X(s.t1);
    g.fillStyle = fillOf(s, lib); g.fillRect(x0, y + 1, Math.max(1, x1 - x0 - 1), h - 2);
    g.fillStyle = 'rgba(255,255,255,0.35)'; g.fillRect(x0, y + 1, 1.5, h - 2);
    const fl = s.flags;
    if (fl.length) { g.setLineDash([4, 3]); g.lineWidth = 2; g.strokeStyle = fl.includes('differ') ? '#ff9f1a' : '#d0a0ff';
      g.strokeRect(x0 + 1.5, y + 2, Math.max(1, x1 - x0 - 4), h - 4); g.setLineDash([]); g.lineWidth = 1; }
    if (x1 - x0 < 22) return;
    const near = lib.state === 'ok' ? (s.near == null ? '人 ·' : '人' + pct(s.near)) : lib.state === 'building' ? '人 …' : '';
    const t = [s.name, near, ...marks(s)].filter(Boolean).join(' ');
    g.save(); g.beginPath(); g.rect(x0, y, x1 - x0 - 2, h); g.clip();
    g.fillStyle = (s.reset + s.warn) ? '#ffd0d8' : css('--text'); g.fillText(t, x0 + 5, y + h / 2 + 1); g.restore();
  });
  if (C.busy || C.stale || lib.state !== 'ok') {   // 数え直している・作り直している・ライブラリが無い＝右の端に書く
    const msg = C.stale ? '作り直している…' : C.busy ? '数え直している…' : lib.state === 'building' ? 'ライブラリの並びを数えている…' : 'データベースが無い（人の譜面との近さは出せない）';
    g.font = F(10); const w = g.measureText(msg).width + 10, xr = g.canvas.clientWidth - 28 * UI.s - w;
    g.fillStyle = 'rgba(0,0,0,0.6)'; g.fillRect(xr, y + 2, w, h - 4); g.fillStyle = lib.state === 'unavailable' ? '#ffb347' : css('--textdim'); g.fillText(msg, xr + 5, y + h / 2 + 1);
  }
  g.textBaseline = 'alphabetic';
}
const secAt = t => (C.res && C.D === S.D ? C.res.sections.find(s => t >= s.t0 && t < s.t1) : null);

function hover(t) {
  const s = secAt(t);
  if (!s) return C.res ? '' : '区間ごとの数字を数えている…';
  const r = C.res, lib = r.library, L = s.lib, ref = lib.ref, S_ = r.sections, out = [];
  const nb = barIdx(s.b1 - 0.01) - barIdx(s.b0) + 1;
  out.push(`${s.name}${s.tags.length ? '（' + s.tags.join('') + '）' : ''}　${fmt(s.t0)}〜${fmt(s.t1)}（拍 ${+s.b0.toFixed(2)}〜${+s.b1.toFixed(2)}・${nb}小節）`);
  out.push('', `■ 人の譜面との近さ（ライブラリ: ${lib.label}${lib.songs ? '・' + lib.songs + ' 曲' : ''}）`);
  if (lib.state === 'unavailable') out.push('  出せない: ' + (lib.error || 'データベースが無い'));
  else if (lib.state === 'building') out.push('  ライブラリの並びを数えている…');
  else if (L) {
    const rq = q => (q ? `（人の譜面の${ref.beats}拍ごと: 10% ${pct1(q[0])}・中央 ${pct1(q[2])}・90% ${pct1(q[4])}）` : '');
    out.push(`  4振りの並びが人の譜面（${lib.min_songs}曲以上）に出る割合 ${pct(L.hit4)}${rq(ref && ref.hit4)}${s.near == null ? '・並びが少なく色は付けない' : '＝色の濃さ（' + pct(LO) + ' 以下で薄い〜100% で濃い）'}`);
    out.push(`  3振りの並びが出る割合 ${pct(L.hit3)}`);
    out.push(`  よくある度（並びが出る曲の割合の中央値）4振り ${pct1(L.med4)}${rq(ref && ref.med4)}・3振り ${pct1(L.med3)}`);
    if (L.rare.length) out.push('  人の譜面にほぼ無い並び（右手の形・列と段）: ' + L.rare.map(q => `${fmt(q.b * 60 / S.D.bpm - S.D.lead)} ${q.seq}（${q.songs} 曲）`).join('／'));
  }
  if (lib.note) out.push('  ' + lib.note);
  out.push('', '■ 曲の中での似かた（3振りの並びの重なり）');
  const nm = i => `${S_[i].name}（${fmt(S_[i].t0)}）`;
  if (s.same.length) out.push(`  同じ音楽の区間: ${s.same.map(nm).join('・')}` + (s.best_same ? `　一番近い ${nm(s.best_same.i)} ${pct(s.best_same.sim)}` : '　（並びが少なく比べられない）'));
  else out.push('  同じ音楽の区間は無い（区間の名前・流れの表の記号で見る）');
  if (s.i > 0) out.push(`  前の区間 ${nm(s.i - 1)} との重なり ${pct(s.prev_sim)}${s.prev_same_music ? '（同じ音楽）' : '（違う音楽）'}` +
    (ref && ref.prev ? `（人の譜面の隣どうし: 中央 ${pct(ref.prev[2])}・90% ${pct(ref.prev[4])}）` : ''));
  if (s.flags.includes('differ')) out.push(`  ≠ 同じ音楽なのに譜面が違う（一番近い同じ音楽の区間との重なりが ${pct(r.marks.same_low)} 未満・目安は仮）`);
  if (s.flags.includes('mono')) out.push(`  ＝ 違う音楽なのに前の区間とほぼ同じ（重なり ${pct(r.marks.prev_high)} 以上・目安は仮）`);
  out.push('', '■ 振り');
  out.push(`  ノーツ ${s.notes}・1秒 ${s.nps}・両手 ${pct(s.double_rate)}・3振りの並びの種類 ${s.kinds3}`);
  out.push(`  振りの交互の崩れ ${s.reset}（${s.pairs} のうち）・NLM の振りの警告と同じ決まり ${s.warn}・同じ手が 0.12 秒未満で続く ${s.fast}`);
  const lo = local(s);
  if (lo.dirs.length || lo.vars.length || lo.keep.length || lo.holes.length) {
    out.push('', '■ 意思入れ・NLM で直した所');
    if (lo.dirs.length) out.push(`  意思入れの指示 ${lo.dirs.length}${lo.motif ? '（同じ振りあり）' : ''}${lo.rest ? '（休みあり）' : ''}`);
    if (lo.vars.length) out.push('  選んだ案: ' + lo.vars.map(v => '案 ' + v).join('・'));
    if (lo.keep.length) out.push('  残すクリップ: ' + lo.keep.map(c => (c.label || c.id) + '（' + c.reason + '）').join('・'));
    if (lo.holes.length) out.push('  NLM で消した所（空のまま）がある');
  }
  const km = kimesIn(s);
  if (km.length) out.push('', `■ 決め（珍しい型）${km.length}`, ...km.map(k => `  ${fmt(timeOf(k.b0))} ${k.place}・${k.hand === 1 ? '右' : '左'} ${k.seq_text}（${k.maps ?? '?'} 曲・${k.freq}）${k.gone ? '・今の譜面では型どおりでない' : ''}`));
  if (S.view) out.push('', `（見ているのは ${diffText(S.view)}・数えたのは基準の ${diffText(S.D.base)} の譜面＝作り直す区間を選ぶ材料）`);
  out.push('', C.notesOf === S.D.notes ? '（押すとこの区間を選ぶ）' : '（見ている譜面が変わった＝数え直している）');
  return out.join('\n');
}
function click(t, e) {
  const s = secAt(t); if (!s) return false;
  tl.selectRange(s.b0, s.b1, e.shiftKey);
  return true;
}

function selfTest() {   // 確かめ用（見えない Edge で #ctest を開いて画像に写す）: 解析を畳んで比べるを開き、曲全体を見せ、3つ目の区間を選ぶ
  if (C.tested) return; C.tested = true;
  tl.openGroup('解析', false); tl.openGroup('比べる', true); tl.showRange(0, +(location.hash.split('=')[1] || S.D.dur));   // #ctest=秒 でそこまで   // 解析を畳んで帯が見えるように
  const s = C.res.sections[Math.min(3, C.res.sections.length - 1)]; if (s) tl.selectRange(s.b0, s.b1);
  document.title = 'ctest ' + C.res.sections.length + ' ' + C.res.library.state;
  const pre = document.createElement('pre'); pre.id = 'ctestOut'; pre.style.display = 'none';   // 重ねた時の数字（--dump-dom で見る）
  pre.textContent = C.res.sections.map(q => hover((q.t0 + q.t1) / 2)).join('\n\n----\n'); document.body.appendChild(pre);
}

export function init(app) {
  A = app;
  tl.addLane('比べる', '区間の点検', 30, lane, {click, hover});
  tl.addOverlay('作った譜面', drawKime, {hover: kimeHover, click: kimeClick});   // 決めの場所
  on('work', () => {
    if (S.D && S.D !== C.D) { C.res = null; K.list = null; later(); }     // 曲を開いた
    else if (S.D && libKey() !== C.libKey && C.res) later();   // ライブラリの設定を変えた
  });
  on('chart', later);          // 譜面を読み直した・別の案や履歴の版を見ている（S.D.notes が入れ替わった）
  on('generated', later);
  on('library', later);
  on('generating', v => { C.stale = !!v; tl.draw(); });
}
