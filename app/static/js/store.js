// アプリの状態: 曲のデータ（サーバーから）・作業ファイル（意思入れ・量のライン・自動の休み）・選んでいる所・元に戻す/やり直す。
// 作業ファイルを変える操作は必ず commit() を通す（元に戻せる・少し待ってからサーバーへ保存する）。

export const $ = id => document.getElementById(id);
export const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
export const fmt = t => { const neg = t < 0; t = Math.abs(t); const m = Math.floor(t / 60), s = t - m * 60;
  return (neg ? '−' : '') + m + ':' + (s < 10 ? '0' : '') + s.toFixed(1); };
export const SIGN = v => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v);
// 画面の覚え（3D の窓の設定・切る音・表示の大きさ・欄の幅…）: アプリの設定（/api/prefs＝設定ファイルの ui_prefs）に覚え、ブラウザ（localStorage）
// にも写す。読む時はアプリの設定を先に。ブラウザの覚えはアドレスの番号ごとで、窓のアプリは 8765 が使われていると次の番号で開くので、前は
// 起動のたびに視点などが消えたように見えた（2026-11-08 利用者「起動するたびに 3D の窓の設定と視点を覚えていない」）。
// 最初の 1 回（アプリの設定が空）は、このブラウザの覚えをアプリの設定へ写す
const PREFS = await (async () => {
  try {
    const r = await fetch('/api/prefs', {headers: {'X-Automap': '1'}});
    return r.ok ? await r.json() : {};
  } catch (e) { return {}; }
})();
let prefQ = {}, prefT = null;
function prefFlush(keep) {
  clearTimeout(prefT); prefT = null;
  const b = prefQ; prefQ = {};
  if (!Object.keys(b).length) return;
  fetch('/api/prefs', {method: 'POST', keepalive: !!keep, headers: {'Content-Type': 'application/json', 'X-Automap': '1'}, body: JSON.stringify(b)}).catch(() => {});
}
function prefPut(k, v) { PREFS[k] = v; prefQ[k] = v; clearTimeout(prefT); prefT = setTimeout(prefFlush, 400); }
const ls = (k, d) => {
  if (Object.prototype.hasOwnProperty.call(PREFS, k)) return PREFS[k];
  try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; }
};
export const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} prefPut(k, v); };
export const lsGet = ls;
if (!Object.keys(PREFS).length) {   // 最初の 1 回: このブラウザの覚えをアプリの設定へ
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith('automap-')) { try { prefPut(k, JSON.parse(localStorage.getItem(k))); } catch (e) {} }
    }
  } catch (e) {}
}
addEventListener('pagehide', () => prefFlush(true));
// 表示の大きさ（文字・帯の高さ・欄の幅）。ブラウザの拡大の代わり（ブラウザで拡大すると 3D の窓だけ見え方が変わった）
export const UI = {s: ls('automap-ui', 1.25)};
export function setUI(s) { UI.s = s; document.documentElement.style.setProperty('--u', s); lsSet('automap-ui', s); emit('ui'); }

export const S = {
  songs: [], song: null, file: null,   // 曲の一覧・開いている曲・アプリの結果のファイル（out/ の中の名前）
  D: null,                              // 曲のデータ（server.py の song_data）
  W: {ranges: [], line: [], auto_rest: {on: false, b: null}},
  sel: [], edit: null, panel: {}, cand: [], lineSel: null,
  t: 0,                                 // 今の時刻（元の音源の秒）
  view: null,                           // 見ている難易度（帯「作った譜面」・3D・★）。null＝基準（S.D.base）。派生を見ている間は編集できない（locked）
};
// 難易度の画面の名前（automap/diffs.py の TEXT と同じ）
export const DIFF_TEXT = {Easy: 'Easy', Normal: 'Normal', Hard: 'Hard', Expert: 'Expert', ExpertPlus: 'Expert+'};
export const diffText = d => DIFF_TEXT[d] || d || '';
let nextId = 1;

export const beatOf = t => (t + S.D.lead) * S.D.bpm / 60;
export const timeOf = b => b * 60 / S.D.bpm - S.D.lead;
export const BEATS = () => S.D.mus.beats;
export function barIdx(b) { const B = BEATS(); let lo = 0, hi = B.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (B[m] <= b + 1e-6) lo = m; else hi = m - 1; } return lo; }
export function barEndBeat(i) { const B = BEATS(); return i + 1 < B.length ? B[i + 1] : B[B.length - 1] + 4; }
export function nearestBar(b) { const i = barIdx(b), a = BEATS()[i], e = barEndBeat(i); return b - a < e - b ? a : e; }
export function rangeText([b0, b1]) {
  const n = barIdx(b1 - 0.01) - barIdx(b0) + 1;
  return `${fmt(timeOf(b0))}〜${fmt(timeOf(b1))}（拍 ${+b0.toFixed(2)}〜${+b1.toFixed(2)}・${n}小節）`;
}

// ---- 同じ振りの形（intent.apply の決まりと同じ）→ {byId: Map(id → {group, form 'A'|'B', n 回目, key, link 形に付いた指示か, arr アレンジか, last グループの最後の回か}),
//      members: Map(key → [id])} ----。W＝作業ファイル（既定は今の物・「これにする」で控える写しにも使う）
export function motifForms(W = S.W) {
  const groups = new Map(), byId = new Map(), members = new Map();
  W.ranges.forEach(r => { const m = r.set.motif; if (m && m.group && !r.set.rest) { if (!groups.has(m.group)) groups.set(m.group, []); groups.get(m.group).push(r); } });
  [...groups.entries()].forEach(([g, rs], gi) => {
    rs.sort((a, b) => a.b0 - b.b0 || a.id - b.id);
    const arrange = (rs[0].set.motif.mode === 'arrange');
    rs.forEach((r, i) => {
      const form = arrange && i % 2 === 1 ? 'B' : 'A', n = arrange ? Math.floor(i / 2) + 1 : i + 1, key = g + '|' + form;
      byId.set(r.id, {group: g, form, n, key, gi, link: false, arr: arrange, last: i === rs.length - 1});
      if (!members.has(key)) members.set(key, []); members.get(key).push(r.id);
      W.ranges.forEach(q => {   // 形の区間の中に収まる、同じ振りでない指示＝その形に付く
        if (q.set.motif || q.set.rest || byId.has(q.id) || q.b0 < r.b0 - 1e-6 || q.b1 > r.b1 + 1e-6) return;
        byId.set(q.id, {group: g, form, n, key, gi, link: true, arr: arrange}); members.get(key).push(q.id);
      });
    });
  });
  return {byId, members};
}
// 形の回（同じ振りの指示の区間・形に付いた指示は入れない）の id を回の順に
export const formRuns = (MF, key) => (MF.members.get(key) || []).filter(id => !MF.byId.get(id).link);
// 形の設定＝各回の同じ振りの指示の motif 以外の項目（docs/アプリ仕様.md 15 節）
export const withoutMotif = set => { const o = Object.assign({}, set); delete o.motif; return o; };
// 形の回ごとに違う項目 → [{k, vals: [{v（無ければ undefined）, ids}]}]（全部の回で同じなら空）
export function formDiff(MF, key, W = S.W) {
  const rs = formRuns(MF, key).map(id => W.ranges.find(q => q.id === id)).filter(Boolean), out = [];
  [...new Set(rs.flatMap(r => Object.keys(withoutMotif(r.set))))].forEach(k => {
    const m = new Map();
    rs.forEach(r => { const v = r.set[k], s = v === undefined ? '' : stable(v); if (!m.has(s)) m.set(s, {v, ids: []}); m.get(s).ids.push(r.id); });
    if (m.size > 1) out.push({k, vals: [...m.values()]});
  });
  return out;
}
// 同じ振りの回を消す時の選び（帯の右クリック・一覧の「消す」・指示の欄の「消す」・Delete）→ [[名前, する事]]。回でなければ null
export function formDeleteItems(r, MF = motifForms()) {
  const f = MF.byId.get(r.id); if (!f || f.link) return null;
  const runs = formRuns(MF, f.key), other = formRuns(MF, f.group + '|' + (f.form === 'A' ? 'B' : 'A'));
  const links = (MF.members.get(f.key) || []).length - runs.length;
  const glinks = links + (MF.members.get(f.group + '|' + (f.form === 'A' ? 'B' : 'A')) || []).length - other.length;
  return [[`この回（${f.form}${f.n}）だけ消す${f.arr && !f.last ? '（後ろの回の A・B が入れ替わる）' : ''}`, () => emit('deleteDirective', r, 'one')],
          [`形 ${f.form} の全部を消す（${runs.length} 回${links ? '・形に付いた指示 ' + links + ' 個も' : ''}）`, () => emit('deleteDirective', r, 'form')],
          [`グループ「${f.group}」の全部を消す（同じ振りをやめる・${runs.length + other.length} 回${glinks ? '・付いた指示 ' + glinks + ' 個も' : ''}）`, () => emit('deleteDirective', r, 'group')]];
}
// 形の色: グループごとの色合い。A＝濃い・B＝明るい（帯では B に斜めの縞）
export function formColor(f, light = 0) {
  const h = (f.gi * 137.508 + 280) % 360;
  return f.form === 'A' ? `hsl(${h},62%,${40 + light}%)` : `hsl(${h},70%,${60 + light}%)`;
}
export const formLabel = f => `${f.form}${f.n} ${f.group}`;

// ---- 知らせ合い ----
const subs = {};
export function on(ev, fn) { (subs[ev] = subs[ev] || []).push(fn); }
export function emit(ev, ...a) { (subs[ev] || []).forEach(fn => fn(...a)); }

// ---- 作業ファイル・元に戻す ----
const undoStack = [], redoStack = [];
const snap = () => JSON.stringify(S.W);
export const stable = v => v && typeof v === 'object' && !Array.isArray(v) ? '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}' : JSON.stringify(v);
export const rangeKey = r => stable([r.b0, r.b1]) + stable(r.set || {});   // 全く同じ区間・指示（2回付けた）を見分ける（指示の並び順によらない）
export function setWork(w) {
  const seen = new Set(), rs = (w.ranges || []).filter(r => { const k = rangeKey(r); if (seen.has(k)) return false; seen.add(k); return true; });
  S.W = {ranges: rs.map(r => ({id: nextId++, b0: r.b0, b1: r.b1, set: r.set || {}})),
         line: (w.line || []).map(k => ({b: k.b, k: k.k, smooth: !!k.smooth})),
         auto_rest: w.auto_rest || {on: false, b: null}, from: w.from, library: w.library || null,   // library＝曲ごとのライブラリの設定（library.js・サーバーが読み替える＝無い曲も新しい曲の既定が入る）
         amount: w.amount && w.amount.mode && w.amount.mode !== 'auto' ? w.amount : null,           // amount＝量の目安（library.js・null＝自動＝今のまま）
         diff: w.diff || null, expand: w.expand || null};   // diff＝基準の難易度（null＝ExpertPlus）・expand＝最後に展開した設定（expand.js・docs/アプリ仕様.md 17 節）
  S.W.njs = w.njs && typeof w.njs.base === 'number' ? {base: w.njs.base} : null;   // njs＝3D で決めた基準の NJS（preview.js・app/njsbase.py・null＝式のまま）
  undoStack.length = 0; redoStack.length = 0; S.edit = null; S.lineSel = null;
  emit('work'); emit('history');
}
// 派生の難易度を見ている間は編集できない（2026-11-03 利用者「展開した先の難易度を選んでいるときは編集ができないように・基準の難易度に
// 戻ってこないと編集できないようにロック」）: 作業ファイルを変える操作（commit・元に戻す・やり直す）を止めて emit('locked')（main.js が
// 知らせる）。画面の側でも、編集の口（class="lockable"・右の欄と一覧の覆い）を main.js が止める。展開の窓が書く基準（diff）と展開の設定
// （expand）は派生を見ていても書く（opts.force）
export const locked = () => !!S.view;
export function commit(fn, opts = {}) {   // fn(W) で変える。opts.before: ドラッグの始めに取った控え（ドラッグの1回を1つの操作に）
  if (locked() && !opts.force) { if (opts.before != null) restore(opts.before); emit('locked'); emit('work'); return false; }
  const before = opts.before ?? snap();
  fn(S.W);
  if (snap() === before) { emit('work'); return; }
  undoStack.push(before); if (undoStack.length > 300) undoStack.shift();
  redoStack.length = 0;
  changed();
}
export function takeSnap() { return snap(); }
function restore(s) { const w = JSON.parse(s); S.W = w; S.lineSel = null; if (!S.W.ranges.some(r => r.id === S.edit)) S.edit = null; }
export function undo() { if (locked()) { emit('locked'); return; } if (!undoStack.length) return; redoStack.push(snap()); restore(undoStack.pop()); changed(); }
export function redo() { if (locked()) { emit('locked'); return; } if (!redoStack.length) return; undoStack.push(snap()); restore(redoStack.pop()); changed(); }
export const canUndo = () => undoStack.length > 0 && !locked(), canRedo = () => redoStack.length > 0 && !locked();
export function newId() { return nextId++; }

let saveTimer = null;
function changed() { emit('work'); emit('history'); clearTimeout(saveTimer); saveTimer = setTimeout(saveWork, 600); if (!S.readonly) emit('status', '保存を待っている…'); }
// 作業ファイルに書く形（区間は始まりの順・同じ始まりは付けた順のまま＝重なる「案」は後の物が勝つ）
export const workBody = (W = S.W) => ({ranges: W.ranges.map(r => ({b0: r.b0, b1: r.b1, set: r.set})).sort((a, b) => a.b0 - b.b0),
                                      line: W.line.slice().sort((a, b) => a.b - b.b), auto_rest: W.auto_rest,
                                      ...(W.library ? {library: W.library} : {}), ...(W.amount ? {amount: W.amount} : {}),
                                      ...(W.diff ? {diff: W.diff} : {}), ...(W.expand ? {expand: W.expand} : {}),
                                      ...(W.njs ? {njs: W.njs} : {})});
export async function saveWork() {
  clearTimeout(saveTimer); saveTimer = null;
  if (!S.file || S.readonly) return;   // readonly＝確かめ用（#test）。本物の作業ファイルを書き換えない
  const body = workBody();
  // keepalive＝窓を閉じる・読み込み直す途中でも送り切る（2026-11-09: 前は閉じる時の保存の送信がページと一緒に切れ得た＝閉じる直前の変更が
  // 落ちる隙間があった）。keepalive で送れるのは 64KB まで（作業ファイルは今 6KB ほど）＝大きい時だけ普通に送る
  const keepalive = new TextEncoder().encode(JSON.stringify(body)).length < 60000;
  try { await api('PUT', '/api/work?file=' + encodeURIComponent(S.file), body, {keepalive}); emit('status', '作業ファイルに保存した'); emit('saved'); }
  catch (e) { emit('status', '保存できなかった: ' + e.message, true); }
}
addEventListener('pagehide', () => { if (saveTimer) saveWork(); });   // 保存を待っている間（変えてから 0.6 秒）に閉じた時も書く

// ---- サーバー ----
export async function api(method, url, body, opt = {}) {
  const r = await fetch(url, {method, keepalive: !!opt.keepalive, headers: body !== undefined ? {'Content-Type': 'application/json', 'X-Automap': '1'} : {'X-Automap': '1'},
                              body: body !== undefined ? JSON.stringify(body) : undefined});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}
