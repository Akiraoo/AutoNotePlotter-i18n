// 難易度の展開（app/expand.py・docs/アプリ仕様.md 17 節）の画面。main.js が init(app) を呼ぶ。
// 上の列の「難易度を展開」→ ① 今の難易度の一覧 ② 今の譜面（基準）をどこに置く ③ 上と下をいくつ ④ 派生ごとの量と型の範囲 → 展開する。
// 派生は「展開する」を押した時だけ作り直す（基準を作り直しても派生はそのまま）。始める前に作業ファイルの diff（基準）・expand（今の設定＝
// 次に開いた時の初めの値）を commit → 保存してから頼む（PUT /api/work は作業ファイルを丸ごと置き換える＝サーバーでは書かない）。
// 縦に並ぶ一覧（① 今の難易度・④ 派生ごとの行・進み具合・結果）は全部、上＝一番難しい（Expert+）・下＝一番易しい（Easy）。基準の行も
// その並びの中の場所に（2026-11-02 利用者「基準の置き場所で Expert+ が真ん中に出て変な感じ」）。横の並び（② ③）も難しい方から。
// 量の既定の刻み（1段ごとに ±何%）は窓の「既定の刻み」で変えられ、「既定にする」で app/config.local.json の expand_step_pct に書く。
// 派生は並べて作る（サーバーが job.par に派生ごとの進み具合）。
// 確かめ用: #xtest&song=曲名（窓を出すだけ・&base=…&up=…&down=… で選んだ所・&step=15 で刻み・&ask で入れ替えの確かめ・&run で
// 進み具合の見本・&res で結果の見本・&make=Normal,Easy で作り直す難易度・&freq=定番（null＝既定）&hard=ふつう で行の型の範囲・
// &dry でサーバーの確かめ（作らない）→ #xtestOut・&view=Normal でその派生を見ている時に開く・&prep で派生の既定を待っている「準備中」・
// &loading で一覧を読んでいる間の窓・&done で展開し終えた後の下の列（「閉じる」を強調）・&pcts=121,122,…（&pctrow=難易度）で量を矢印で
// 押したように変えて欄の位置を毎回 → #xtestPos・&go で本当に展開して終わった後の下の列と★ → #xtestGo＝写しの場所のサーバーでだけ）。
// 2026-11-09 の直し: 窓を開いてから派生の行が使えるまで（POST /api/expand/plan＝型のライブラリで数える・初めは 4〜5 秒）は「準備中」・
// 量を変えても欄が動かない（renderRows の上の説明）・★は作り終えた派生からサーバーが先に測る（進み具合の表の★・結果の表はすぐ）・
// 展開し終えたら「閉じる」を強調（renderFoot）。
import {$, api, S, on, emit, commit, saveWork} from './store.js';
import {labelShort} from './library.js';

let A = null;          // main.js から渡された口
let INFO = null;       // GET /api/expand（難易度の一覧・基準・前に展開した設定）
let LIB = null;        // GET /api/library（★の帯・新しい曲の既定）
let X = null;          // 窓で選んでいる物 {base, up, down, step（量の既定の刻み %）, rows: {難易度: {pct, mode: 'plan'|'band', stars, make, freq, hard}}}
// 選んだ難易度だけ作り直す（2026-11-03 利用者「展開で作り直す時に特定の難易度だけ作り直しできるように」）: 行の make（既定は作り直す。派生を
// 見ている時に窓を開いたら、見ている難易度だけ）。作り直さない行は今の譜面のまま（サーバーへ送らない・作業ファイルの expand には前に
// 作った時の設定を残す）。下の難易度を作り直さずに、それより上（基準との間）を作り直すと入れ子がずれ得る＝行に知らせる。
// 型の頻度・置き方の難しさ（2026-11-03 利用者・A 案「真横に切るノーツは結構いやらしい・★の高い型に多いので型の範囲を調整したい」）:
// 行の freq・hard（undefined＝基準と同じ＝既定の型の範囲の値・null＝既定（頻度）／全部（難しさ）・値＝その上限）。★の帯（mode）の上に重ねる
let PLAN = {};         // 基準と刻みごとの派生の既定 {'基準|刻み': {難易度: {ratio, library, note, short}}}
let RUN = null;        // 動いている展開 {id, t0, base, src, moved}
let RES = null;        // 終わった展開の作業（結果を出す）
let DONE_SIG = null;   // 展開し終えた時の窓の設定（sigOf）。同じ設定のままなら「閉じる」を強調する（renderFoot）
let HOLD = false;      // 確かめ用（#xtest&prep）: 派生の既定を聞かない＝「準備中」のまま
const COUNTS = new Map();   // 型の範囲 → /api/library/count の答え
const ckey = f => JSON.stringify([f, f && f.years === 'auto' ? S.file : null]);   // 時期が自動の数は曲ごと
const STARS = new Map();    // 難易度 → ★（今の一覧）
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
const T = d => (INFO && INFO.text[d]) || d;
const ORDER = () => (INFO && INFO.order) || ['Easy', 'Normal', 'Hard', 'Expert', 'ExpertPlus'];
const rowOf = d => INFO && INFO.diffs.find(r => r.diff === d);
const nps = v => v == null ? '—' : (+v).toFixed(2);
const HARD = () => ORDER().slice().reverse();   // 画面の並び（上・左＝一番難しい）
const byHard = (a, b) => ORDER().indexOf(b) - ORDER().indexOf(a);
const STEP0 = () => (INFO && INFO.step_pct) || 10;   // 設定の刻み（%）
const stepRatio = (base, d, step) => {   // 既定の量の割合（1段ごとに ±step%・足し算・受け付ける範囲の端まで）＝diffs.ratio と同じ
  const rr = (INFO && INFO.ratio_range) || [0.2, 2.5];
  return Math.round(Math.min(rr[1], Math.max(rr[0], 1 + step / 100 * (ORDER().indexOf(d) - ORDER().indexOf(base)))) * 10000) / 10000;
};

function build() {
  const d = document.createElement('div');
  d.id = 'xpDlg'; d.className = 'modal xp';
  d.innerHTML = `<div class="dlg">
  <div class="dlgHead"><b>難易度を展開</b><span class="sub" id="xpSong"></span><button id="xpClose">閉じる</button></div>
  <div class="dlgBody">
    <div class="xpLoadMsg"><span class="genSpin"></span><span><b>準備中</b>…難易度の一覧を読んでいる</span></div>
    <div class="xpSec"><h4>① 今の難易度</h4><table class="xpTbl" id="xpList"></table></div>
    <div class="xpSec"><h4>② 今の譜面（基準）をどこに置く</h4><div class="seg" id="xpBase"></div><div class="xpNote" id="xpBaseNote"></div></div>
    <div class="xpSec"><h4>③ 上と下をいくつ作る</h4>
      <div class="xpUD"><span class="xpKey">上（難しく）</span><div class="seg" id="xpUp"></div>
        <span class="xpKey">下（易しく）</span><div class="seg" id="xpDown"></div></div></div>
    <div class="xpSec"><h4>④ 派生ごとの量と型の範囲（作り直す難易度を選ぶ）</h4>
      <div class="xpMakeBar"><span class="xpKey">作り直す</span><button id="xpMakeAll">全部</button><button id="xpMakeView">見ている難易度だけ</button>
        <span class="sub" id="xpMakeNote"></span></div>
      <div class="xpStep">既定の刻み <input type="number" id="xpStep" min="1" max="50" step="1"> %
        <span class="sub">（量の既定＝1段下ごとに −刻み・1段上ごとに ＋刻み。行で直した量はそのまま）</span>
        <button id="xpStepSave" title="今の刻みを既定にする（app/config.local.json の expand_step_pct に書く・次に開いた時もこの刻み）">既定にする</button>
        <span class="sub" id="xpStepNote"></span></div>
      <div id="xpRows"></div></div>
    <div id="xpAsk" class="xpAsk"></div>
    <div id="xpRun" class="xpRun"></div>
    <div id="xpRes" class="xpRes"></div>
    <div class="hint">派生は「展開する」を押した時だけ作り直す（基準を作り直しても派生はそのまま・「作り直す」を外した難易度は今のまま）。
      型の頻度・置き方の難しさを選ばない行は、基準のライブラリの設定と同じ。派生は基準の打点から作る（下は弱い打点から間引き、
      上は拾った候補から足す・置き方は基準に寄せる）。意思入れは基準にだけ付ける。もう譜面がある難易度は、作ったままのクリップだけ入れ替え、
      NLM で直したクリップ・名前に「固定」・利用者のクリップは残す（その範囲には作らない）。展開の前の結果のファイルは out/old/ に控える（履歴にも残る）。</div>
    <div class="xpFoot"><span class="sub" id="xpSum"></span><span class="xpSpacer"></span>
      <button id="xpCancel">閉じる</button><button id="xpGo" class="main">展開する</button></div>
  </div></div>`;
  document.body.appendChild(d);
  d.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Escape' && !askOpen()) close(); });
  d.addEventListener('mousedown', e => { if (e.target === d) d.dataset.down = '1'; });
  d.addEventListener('click', e => { if (e.target === d && d.dataset.down === '1') close(); d.dataset.down = ''; });
  $('xpClose').onclick = close; $('xpCancel').onclick = close;
  $('xpGo').onclick = go;
  $('xpStep').onchange = e => { const v = parseFloat(e.target.value);
    if (isFinite(v) && v >= INFO.step_limits[0] && v <= INFO.step_limits[1]) X.step = Math.round(v * 10) / 10; else e.target.value = X.step;
    render(); };
  $('xpStepSave').onclick = saveStep;
  $('xpMakeAll').onclick = () => { targetsOf().forEach(d => { rowState(d).make = true; }); render(); };
  $('xpMakeView').onclick = () => { targetsOf().forEach(d => { rowState(d).make = d === S.view; }); render(); };
}
async function saveStep() {   // 今の刻みを既定に（設定のほかの項目はサーバーがそのまま残す）
  try {
    const r = await api('POST', '/api/expand/step', {step_pct: X.step});
    INFO.step_pct = r.step_pct;
    A.status(`派生の量の既定の刻みを ${r.step_pct}% にした（app/config.local.json）`);
  } catch (e) { A.status('既定にできなかった: ' + e.message, true); }
  render();
}

// ---- ① 今の難易度 ----
function contentText(r, short = false) {   // 難易度の中身 → 説明
  if (!r || !r.exists) return 'まだ無い';
  if (!r.notes) return r.lights ? 'ノーツ無し（ライトだけ）' : '空';
  const c = r.clips || {}, parts = [];
  if (r.base) parts.push('<b class="xpTag base">基準</b>');
  else if (r.kind === 'auto') parts.push(r.derived || r.report ? '<b class="xpTag der">派生</b>' : '<b class="xpTag der">作った譜面</b>');
  if (r.kind === 'user') parts.push('<b class="xpTag user">利用者の譜面</b>');
  if (c.edited) parts.push(`<span class="xpTag edit">NLM で直したクリップ ${c.edited}</span>`);
  if (c.fixed) parts.push(`<span class="xpTag edit">固定 ${c.fixed}</span>`);
  if (c.user && r.kind !== 'user') parts.push(`<span class="xpTag user">利用者のクリップ ${c.user}</span>`);
  if (c.legacy) parts.push(`<span class="xpTag edit">前の形式 ${c.legacy}</span>`);
  return parts.join(short ? ' ' : '');
}
function listHTML() {
  const rows = HARD().map(rowOf).filter(r => r && r.exists);
  if (!rows.length) return '<tr><td>結果のファイルがまだ無い（先に作り直して基準の譜面を作る）</td></tr>';
  return '<tr><th>難易度</th><th>ノーツ</th><th>1秒のノーツ</th><th>★</th><th>中身</th><th>書き出す</th><th>NJS</th></tr>' +
    rows.map(r => {
      const st = STARS.get(r.diff);
      const star = !r.notes ? '—' : st == null ? '<span class="sub">…</span>' : st === false ? '<span class="sub">?</span>' : (+st).toFixed(2);
      return `<tr class="${r.base ? 'xpBaseRow' : ''}"><td><b>${esc(T(r.diff))}</b></td><td>${r.notes || 0}</td><td>${nps(r.nps)}</td><td>${star}</td>
        <td>${contentText(r, true)}</td><td>${r.export ? '○' : '<span class="sub">—</span>'}</td><td>${r.njs ?? ''}${njsTag(r)}</td></tr>`;
    }).join('');
}
// NJS の札（3D で決めた基準の NJS・NLM で決めた値・app/njsbase.py）
const njsTag = r => r.njs_decided != null && !r.njs_user
  ? ' <span class="xpTag base" title="3D で決めた基準の NJS（これから作る派生は 決めた値＋式の差）">3D で決めた</span>'
  : r.njs_user ? ` <span class="xpTag edit" title="NLM で直した NJS（作り直し・展開で触らない）${r.base ? '・基準の NJS に使う（これから作る派生はこの値＋式の差）' : ''}` +
    `${r.njs_decided != null ? '・3D で決めた ' + r.njs_decided + ' より後に直した＝NLM の値が勝つ' : ''}">NLM</span>` : '';
let RGEN = 0;   // 一覧の★を聞き直した回（STARS.clear の後に、前に聞いた古い答えを入れない）
async function rateAll() {   // 一覧の★（測った答えがあればすぐ・無ければ少し待つ。見ている難易度の答えか view_diff で確かめる）。難易度ごとに同時に聞く
  const gen = RGEN;          // （前は 1 つずつで、測っていない難易度が 5 つあると最後の★まで 6〜8 秒）
  const rows = (INFO.diffs || []).filter(r => r.exists && r.notes && !STARS.has(r.diff));
  rows.forEach(r => STARS.set(r.diff, null));
  await Promise.all(rows.map(async r => {
    let v = false;
    for (let i = 0; i < 6; i++) {
      try {
        const a = await api('GET', `/api/rating?wait=5&file=${encodeURIComponent(S.file)}&diff=${r.diff}`);
        if (a.state === 'running') continue;
        v = a.state === 'done' && a.stars != null && (a.view_diff == null ? r.base : a.view_diff === r.diff) ? a.stars : false;
      } catch (e) { v = false; }
      break;
    }
    if (gen !== RGEN) return;
    STARS.set(r.diff, v);
    if ($('xpList')) $('xpList').innerHTML = listHTML();
  }));
}
const restars = () => { RGEN++; STARS.clear(); };

// ---- ② ③ 基準の置き場所・上と下の数 ----
const idx = d => ORDER().indexOf(d);
const targetsOf = (x = X) => {   // 置き場所と上・下の数 → 派生の難易度（難しい順＝画面の並び。作る順はサーバーが決める）
  const o = ORDER(), i = idx(x.base), out = [];
  for (let k = 1; k <= x.up && i + k < o.length; k++) out.push(o[i + k]);
  for (let k = 1; k <= x.down && i - k >= 0; k++) out.push(o[i - k]);
  return out.sort(byHard);
};
// 置き直した後の各難易度の中身（入れ替える時は今の基準の場所へ置き場所の中身が来る）
function after(d) {
  const from = INFO.base;
  if (X.base === from) return rowOf(d);
  if (d === X.base) return Object.assign({}, rowOf(from), {base: true});
  if (d === from) { const r = rowOf(X.base); return r && r.exists && (r.notes || r.lights) ? Object.assign({}, r, {base: false, moved: true}) : null; }
  return rowOf(d);
}
function seg(id, items, cur, pick) {   // 並んだボタン（1つ選ぶ）。items＝[{v, t, sub, title, dis}]
  const el = $(id);
  el.innerHTML = items.map((it, i) => `<button data-i="${i}" class="${same(it.v, cur) ? 'on' : ''}" ${it.dis ? 'disabled' : ''} title="${esc(it.title || '')}">${esc(it.t)}${it.sub != null ? `<small>${esc(it.sub)}</small>` : ''}</button>`).join('');
  el.querySelectorAll('button').forEach(b => b.onclick = () => { pick(items[+b.dataset.i].v); render(); });
}
function renderBase() {
  const from = INFO.base;
  seg('xpBase', HARD().map(d => { const r = rowOf(d);
    return {v: d, t: T(d), sub: d === from ? '今の基準' : r && r.notes ? `譜面あり ${r.notes}` : '',
            title: d === from ? '今の基準（意思入れで作り直している難易度）' : r && r.notes ? `${T(d)} にはもう譜面がある（置くと入れ替えるか聞く）` : `${T(d)} は空`}; }),
      X.base, v => { X.base = v; clampUD(); });
  const occ = rowOf(X.base);
  $('xpBaseNote').innerHTML = X.base === from ? `基準は <b>${esc(T(from))}</b> のまま（NJS は難易度の設定・無ければ NLM の既定）。`
    : `基準（今の ${esc(T(from))} の譜面）を <b>${esc(T(X.base))}</b> へ置き直す（クリップ・ライト・NJS・書き出す印ごと）。` +
      (occ && occ.exists && (occ.notes || occ.lights) ? `<br><span class="warnTxt">${esc(T(X.base))} にはもう譜面がある（${occ.notes} ノーツ・${contentText(occ, true).replace(/<[^>]+>/g, '')}）
        ＝展開する時に、入れ替える（今の ${esc(T(X.base))} の譜面は ${esc(T(from))} へ）か聞く。</span>` : '') +
      '<br><span class="sub">意思入れ・作り直し・別の案・履歴は、置き直した難易度で続ける。</span>';
  if (INFO.njs_base_used != null) $('xpBaseNote').innerHTML += `<br><span class="xpNjsBase${INFO.njs_base_from === 'nlm' ? ' nlm' : ''}">基準の NJS は ` +
    (INFO.njs_base_from === 'nlm' ? `NLM で直した <b>${INFO.njs_base_used}</b>（NLM の値を使う${INFO.njs_base != null ? `・3D で決めた ${INFO.njs_base} より後` : ''}）`
      : `3D で決めた <b>${INFO.njs_base_used}</b>`) +
    '（これから作る派生の NJS は この値＋（派生の式 − 基準の式）・作ってある派生はそのまま・3D の「譜面に使う」で変える）</span>';
}
function clampUD() {
  const i = idx(X.base), n = ORDER().length;
  X.up = Math.min(X.up, n - 1 - i); X.down = Math.min(X.down, i);
}
function renderUD() {
  const i = idx(X.base), n = ORDER().length, o = ORDER();
  const nums = (max, dir) => Array.from({length: max + 1}, (_, k) => ({v: k, t: String(k),
    sub: k ? (dir > 0 ? o.slice(i + 1, i + 1 + k) : o.slice(i - k, i)).reverse().map(T).join('・') : 'なし'}));   // 難しい方から
  seg('xpUp', nums(n - 1 - i, 1), X.up, v => { X.up = v; });
  seg('xpDown', nums(i, -1), X.down, v => { X.down = v; });
}

// ---- ④ 派生ごとの行 ----
const planKey = () => `${X.base}|${X.step}`;
const planOf = d => (PLAN[planKey()] || {})[d];
function rowState(d) {
  if (!X.rows[d]) X.rows[d] = {pct: null, mode: 'plan', stars: null, make: true, freq: undefined, hard: undefined};
  if (X.rows[d].make === undefined) X.rows[d].make = true;
  return X.rows[d];
}
const FREQS = () => (LIB && LIB.freq) || ['定番', 'よくある', '珍しい'];   // automap/library_db.FREQ・HARD（/api/library）
const HARDS = () => (LIB && LIB.hard) || ['やさしい', 'ふつう', '難しい'];
function baseLibOf(d) {   // 行の型の範囲の元（★の帯まで・型の頻度と難しさを重ねる前）。null＝既定を数えられなかった（曲の設定）・undefined＝まだ数えている
  const r = rowState(d), pl = planOf(d);
  if (r.mode === 'band' && r.stars) return Object.assign({}, (pl && pl.library) || (LIB && LIB.default) || {}, {stars: [...r.stars]});
  return pl ? (pl.library ? Object.assign({}, pl.library) : null) : undefined;
}
function libOf(d) {   // 行の型の範囲（絞り込み・null＝曲の設定）＝元に型の頻度・置き方の難しさを重ねた物（形は library_use.normalize と同じ）
  const r = rowState(d), f = baseLibOf(d);
  if (!f) return f;
  if (r.freq !== undefined) { if (r.freq) f.freq = r.freq; else delete f.freq; }
  if (r.hard !== undefined) { if (r.hard && r.hard !== HARDS()[HARDS().length - 1]) f.hard = r.hard; else delete f.hard; }
  return f;
}
const makeOf = (x = X) => targetsOf(x).filter(d => rowState(d).make !== false);   // 作り直す派生（画面の並び）
const prevOf = d => ((INFO && INFO.expand && INFO.expand.targets) || []).find(t => t.diff === d);   // 前に展開した時のその派生の設定
const ratioOf = d => { const r = rowState(d), pl = planOf(d); return r.pct != null ? r.pct / 100 : pl ? pl.ratio : null; };
function keepText(d) {   // その難易度にもう譜面がある時の扱い
  const r = after(d);
  if (!r || !r.exists || !r.notes) return '<span class="sub">空＝新しく作る（書き出す印も付ける）</span>';
  const c = r.clips || {}, src = r.moved ? `（今の ${esc(T(X.base))} の譜面が入れ替わって来る）` : '';
  if (r.kind === 'user') return `<span class="warnTxt">利用者の譜面（クリップ ${c.user}）は残す＝その範囲には作らない</span>${src}<br><span class="sub">作り直したいなら NLM でクリップを消すか、別の難易度へ</span>`;
  const keep = [c.edited ? `NLM で直したクリップ ${c.edited}` : '', c.fixed ? `「固定」${c.fixed}` : '', c.user ? `利用者のクリップ ${c.user}` : '',
                c.legacy ? `前の形式のクリップ ${c.legacy}（直したか分からない）` : ''].filter(Boolean);
  return `作ったままのクリップ ${c.app || 0} は入れ替える${src}` + (keep.length ? `<br><span class="warnTxt">${keep.join('・')} は残す（その範囲には作らない）</span>` : '');
}
function libOptions(d) {
  const r = rowState(d), pl = planOf(d), bands = (LIB && LIB.bands) || [];
  const opts = [`<option value="plan" ${r.mode === 'plan' ? 'selected' : ''}>既定: ${esc(pl ? pl.short : '数えている…')}</option>`];
  bands.filter(b => b.stars).forEach(b => opts.push(`<option value="band:${b.stars.join(',')}" ${r.mode === 'band' && same(r.stars, b.stars) ? 'selected' : ''}>★${esc(b.name)}</option>`));
  if (r.mode === 'band' && r.stars && !bands.some(b => same(b.stars, r.stars))) opts.push(`<option value="band:${r.stars.join(',')}" selected>★${r.stars[0]}〜${r.stars[1]}</option>`);
  return opts.join('');
}
function overSelects(d) {   // 型の頻度・置き方の難しさ（基準と同じ＝選ばない）。既定を数えている間は選べない
  const r = rowState(d), b = baseLibOf(d), dis = !b ? 'disabled' : '', fq = FREQS(), hd = HARDS();
  const bf = b && b.freq ? b.freq + 'まで' : '既定', bh = b && b.hard ? b.hard + 'まで' : '全部';
  // 選んでいる値（'inherit'＝基準と同じ。null の「既定」と見分ける＝same() は undefined と null を同じに見る）
  const cf = r.freq === undefined ? 'inherit' : r.freq, ch = r.hard === undefined ? 'inherit' : r.hard === null ? hd[2] : r.hard;
  const opt = (v, t, cur) => `<option value='${JSON.stringify(v)}' ${JSON.stringify(v) === JSON.stringify(cur) ? 'selected' : ''}>${esc(t)}</option>`;
  const fOpts = [opt('inherit', `基準と同じ（${bf}）`, cf), opt(fq[0], fq[0] + 'まで（多くの曲に出る型だけ）', cf),
    opt(fq[1], fq[1] + 'まで', cf), opt(null, '既定（曲の数に合わせる）', cf), opt(fq[2], fq[2] + 'まで（少ない曲の型も）', cf)].join('');
  const hOpts = [opt('inherit', `基準と同じ（${bh}）`, ch), opt(hd[0], hd[0] + 'まで（下から 1/3）', ch),
    opt(hd[1], hd[1] + 'まで（下から 2/3）', ch), opt(hd[2], hd[2] + 'まで（全部）', ch)].join('');
  return `<div class="xpOver"><label title="テーマに使う型を、多くの曲に出る型に絞る（珍しい型ほど置き方が独特）">型の頻度 <select class="xpFreq" ${dis}>${fOpts}</select></label>
    <label title="置き方の難しさ＝型の形（移動・向きの曲がり（90° の曲がり＝真横の振りへの切り替えなど）・斜め・腕の交差・上の段）＋振りの速さ＋★。絞り込みの中で下から 1/3・2/3 で区切る">置き方の難しさ <select class="xpHard" ${dis}>${hOpts}</select></label></div>`;
}
function skipText(d) {   // 作り直さない行の説明（今の譜面のまま・前に作った時の設定・入れ子がずれる知らせ）
  const r = after(d), p = prevOf(d);
  const now = !r || !r.exists || !r.notes ? `<b>作らない</b>（${esc(T(d))} はまだ無い）` : `<b>今のまま</b>（ノーツ ${r.notes}）`;
  const was = p ? `<div class="sub">前に作った時: 量 ${p.ratio != null ? Math.round(p.ratio * 1000) / 10 + '%' : '?'}・${esc(labelShort(p.library))}</div>` : '';
  return now + was + nestWarn(d);
}
function nestWarn(d) {   // 作り直さない下の派生と基準の間に、作り直す派生がある＝入れ子（下の打点が1つ上にもある）がずれ得る
  if (rowState(d).make !== false || idx(d) > idx(X.base)) return '';
  const mid = makeOf().filter(e => idx(e) < idx(X.base) && idx(e) > idx(d));
  return mid.length ? `<div class="warnTxt">${mid.map(T).join('・')} を作り直すので、${esc(T(d))} の打点が ${mid.map(T).join('・')} に無いことがある（${esc(T(d))} も作り直すとそろう）</div>` : '';
}
function countText(f) {
  if (f === undefined) return '<span class="sub">既定を数えている…</span>';
  const k = ckey(f), c = COUNTS.get(k);
  if (!c) { recount(f); return '<span class="sub">数えている…</span>'; }
  if (c.available === false) return `<span class="bad">数えられない（${esc(c.error)}）</span>`;
  return `${f ? esc(c.short || labelShort(f)) + '：' : ''}曲 <b>${c.songs}</b>・テーマに使える型 <b>${c.themes}</b>` + (c.warn ? `<br><span class="warnTxt">${esc(c.warn)}</span>` : '');
}
async function recount(f) {
  const k = ckey(f);
  if (COUNTS.has(k)) return;
  COUNTS.set(k, null);
  try { COUNTS.set(k, await api('POST', '/api/library/count', {library: f, file: S.file})); }   // 時期が自動ならこの曲の時期で（compose と同じ）
  catch (e) { COUNTS.set(k, {available: false, error: e.message}); }
  if (COUNTS.get(k) === null) COUNTS.delete(k);
  renderRows();
}
// 量の欄（2026-11-09 利用者「％を変えると位置がずれて同じ場所でクリックを続けられない」）: 前は 1 回目に変えると「既定」のボタンが出て
// 「（既定 120%・直した値）」が 2 行に折り返し、自動の列の幅が組み直され（量の列 247→262px）、真ん中寄せの欄が 33px 上へ動き、表を作り直して
// 欄の選びも外れていた。→ 列の幅は固定（colgroup・table-layout: fixed）・欄は上寄せ・下の 2 行は 1 行ずつ折り返さない（等幅の数字）・
// 「既定」のボタンは場所を取ったまま見えなくする・量を変えた時は表を作り直さずにその行の字だけ書き換える（updPct）
const pctNum = v => Math.round(v * 1000) / 10;
const pctBad = d => { const v = ratioOf(d); return v != null && (v < INFO.ratio_range[0] || v > INFO.ratio_range[1]); };
function pctLines(d) {   // 量の欄の下の 2 行（1秒のノーツの見込み・既定）
  const pl = planOf(d), ratio = ratioOf(d), r = rowState(d), b = after(X.base), bn = b && b.nps;
  const rr = INFO.ratio_range;
  return [bn && ratio ? `1秒 ${nps(bn)} → 約 <b>${nps(bn * ratio)}</b>` : `1秒 ${nps(bn)} → <span class="sub">—</span>`,
    pctBad(d) ? `<span class="bad">${Math.round(rr[0] * 100)}〜${Math.round(rr[1] * 100)}% の間で</span>`
      : pl ? `既定 ${pctNum(pl.ratio)}%${r.pct != null ? '<span class="xpMod">・直した値</span>' : ''}` : '既定を数えている…'];
}
function updPct(tr, d) {   // 量を変えた行の字だけ書き換える（表を作り直さない＝欄の場所・選び・押し続けている矢印はそのまま）
  const r = rowState(d), pl = planOf(d), [a, b] = pctLines(d), rs = tr.querySelector('.xpReset');
  tr.querySelector('.xpPctNps').innerHTML = a; tr.querySelector('.xpPctDef').innerHTML = b;
  tr.querySelector('.xpPct').classList.toggle('xpBadIn', pctBad(d));
  rs.style.visibility = r.pct != null && pl ? 'visible' : 'hidden';
  if (pl) rs.title = `既定（${pctNum(pl.ratio)}%）に戻す`;
  renderFoot();
}
const plansReady = () => targetsOf().every(d => planOf(d));
function renderRows() {
  const ts = targetsOf(), el = $('xpRows'), b = after(X.base);
  if (!ts.length) { el.classList.remove('xpWait', 'xpWaitShow'); el.innerHTML = '<div class="sub">作る難易度が無い（③ で上か下を 1 つ以上）' + (X.base !== INFO.base ? '。置き直すだけなら「展開する」で置き直す' : '') + '</div>'; return; }
  // 作り直すと欄が入れ替わる＝量の欄を選んでいたら、作り直した後も同じ行の欄を選ぶ（矢印のキーで続けて変えられる）
  const fa = document.activeElement, ftr = fa && fa.classList && fa.classList.contains('xpPct') ? fa.closest('#xpRows tr[data-d]') : null;
  const fd = ftr ? ftr.dataset.d : null;
  const bn = b && b.nps;
  const baseRow = `<tr class="xpBaseRow"><td><b>${esc(T(X.base))}</b><div class="sub">基準</div></td>
      <td><div class="xpPctLine">100%</div><div class="sub xpPctNps">1秒 ${nps(bn)}</div><div class="sub xpPctDef">今の譜面のまま</div></td>
      <td><span class="sub">曲の設定（${esc(INFO.library_short || '')}）</span></td>
      <td class="xpKeep"><span class="sub">${X.base !== INFO.base ? `今の ${esc(T(INFO.base))} の譜面をここへ置き直す` : '指示・作り直しはこの難易度に効く'}</span></td></tr>`;
  const all = [...ts, X.base].sort(byHard);   // 上＝一番難しい。基準の行もその並びの中に
  const ready = plansReady();
  el.innerHTML = `<table class="xpTbl xpRowsTbl"><colgroup><col class="xpC1"><col class="xpC2"><col><col class="xpC4"></colgroup>
    <tr><th>難易度</th><th>量<span class="sub">（基準の1秒のノーツに対する割合）</span></th><th>型の範囲</th><th>もう譜面がある時</th></tr>` +
    all.map(d => d === X.base ? baseRow : (() => {
      const pl = planOf(d), ratio = ratioOf(d), r = rowState(d), f = libOf(d), up = idx(d) > idx(X.base), mk = r.make !== false;
      const pct = ratio != null ? pctNum(ratio) : '';
      const head = `<td><b>${esc(T(d))}</b><div class="sub">${up ? '上' : '下'} ${Math.abs(idx(d) - idx(X.base))} 段${d === S.view ? '・見ている' : ''}</div>
          <label class="xpMake" title="外すと、この難易度は今の譜面のまま（作り直さない）"><input type="checkbox" class="xpMk" ${mk ? 'checked' : ''}> 作り直す</label></td>`;
      if (!mk) return `<tr data-d="${d}" class="xpSkip">${head}<td colspan="3">${skipText(d)}</td></tr>`;
      const [la, lb] = pctLines(d);
      return `<tr data-d="${d}">${head}
        <td><div class="xpPctLine"><input type="number" class="xpPct${pctBad(d) ? ' xpBadIn' : ''}" min="${Math.round(INFO.ratio_range[0] * 100)}" max="${Math.round(INFO.ratio_range[1] * 100)}" step="1" value="${pct}"> %
            <button class="xpReset" title="${pl ? `既定（${pctNum(pl.ratio)}%）に戻す` : ''}" style="visibility:${r.pct != null && pl ? 'visible' : 'hidden'}">既定</button></div>
          <div class="sub xpPctNps">${la}</div><div class="sub xpPctDef">${lb}</div></td>
        <td><select class="xpLib">${libOptions(d)}</select>${overSelects(d)}<div class="xpCount">${countText(f)}</div>
          <div class="sub xpPlanNote">${pl && r.mode === 'plan' ? esc(pl.note || '') : ''}</div></td>
        <td class="xpKeep">${keepText(d)}${nestWarn(d)}</td></tr>`;
    })()).join('') + '</table>' +
    // 派生の既定（POST /api/expand/plan・型のライブラリで数える）を待つ間は、行を薄く見せて上に「準備中」（行の場所はそのまま取っておく）
    (ready ? '' : `<div class="xpWaitMsg"><span class="genSpin"></span><div><b>準備中</b>…派生ごとの既定（量の割合・型の範囲）を型のライブラリで数えている
      <div class="sub">この曲で初めて開いた時・基準の置き場所や刻みを変えた時は数秒（2 回目からはすぐ）</div></div></div>`);
  el.classList.toggle('xpWait', !ready);
  if (ready) el.classList.remove('xpWaitShow');
  else setTimeout(() => { if (el.classList.contains('xpWait')) el.classList.add('xpWaitShow'); }, 200);   // すぐ返る時はちらつかせない
  el.querySelectorAll('tr[data-d]').forEach(tr => {
    const d = tr.dataset.d, r = rowState(d), q = s => tr.querySelector(s);
    q('.xpMk').onchange = e => { r.make = e.target.checked; render(); };
    if (r.make === false) return;
    const pin = q('.xpPct'), rs = q('.xpReset');
    // 矢印・打ち込みのたびに（input）: 数なら量にして字だけ書き換える（打ちかけの欄はそのまま）。決めた時（change）: 数でなければ既定に戻す
    pin.oninput = e => { const v = parseFloat(e.target.value); if (isFinite(v)) { r.pct = v; updPct(tr, d); } };
    pin.onchange = e => { const v = parseFloat(e.target.value); r.pct = isFinite(v) ? v : null;
      if (r.pct == null) { const x = ratioOf(d); e.target.value = x != null ? pctNum(x) : ''; }
      updPct(tr, d); };
    rs.onclick = () => { r.pct = null; const x = ratioOf(d); pin.value = x != null ? pctNum(x) : ''; updPct(tr, d); };
    q('.xpLib').onchange = e => { const v = e.target.value;
      if (v.startsWith('band:')) { r.mode = 'band'; r.stars = v.slice(5).split(',').map(Number); } else { r.mode = v; r.stars = null; } render(); };
    const pick = v => { v = JSON.parse(v); return v === 'inherit' ? undefined : v; };
    q('.xpFreq').onchange = e => { r.freq = pick(e.target.value); render(); };
    q('.xpHard').onchange = e => { r.hard = pick(e.target.value); render(); };
  });
  if (fd) { const n = el.querySelector(`tr[data-d="${fd}"] .xpPct`); if (n) n.focus({preventScroll: true}); }
  const mk = makeOf(), skip = ts.filter(d => !mk.includes(d));
  $('xpMakeNote').textContent = !skip.length ? '全部の派生を作り直す' : !mk.length ? '作り直す派生が無い（行の「作り直す」に印を付ける）'
    : `作り直す: ${mk.map(T).join('・')}・今のまま: ${skip.map(T).join('・')}`;
  $('xpMakeView').disabled = !S.view || !ts.includes(S.view);
  $('xpMakeView').title = S.view && ts.includes(S.view) ? `見ている ${T(S.view)} だけを作り直す` : '派生を見ている時に使う（上の列の「見る」で派生を選ぶ）';
}
const PLANNING = new Set();   // 数えている（基準|刻み|難易度）
async function loadPlans() {   // 置き場所の基準・刻みでの派生の既定（量の割合・型の範囲）を聞く（型の範囲はサーバーが覚える＝刻みを変えても速い）
  const base = X.base, step = X.step, key = planKey();
  const ts = targetsOf().filter(d => !(PLAN[key] || {})[d] && !PLANNING.has(key + '|' + d));
  if (!ts.length || HOLD) return;
  ts.forEach(d => PLANNING.add(key + '|' + d));
  try {
    const r = await api('POST', '/api/expand/plan', {file: S.file, base, targets: ts, step_pct: step});
    PLAN[key] = Object.assign(PLAN[key] || {}, r.plans);
  } catch (e) {   // 数えられない＝量は刻みの既定・型は曲の設定（もう一度数えに行かない）
    A.status('派生の既定を数えられなかった: ' + e.message, true);
    PLAN[key] = PLAN[key] || {};
    ts.forEach(d => { PLAN[key][d] = {ratio: stepRatio(base, d, step), library: null, short: '曲の設定', note: '既定を数えられなかった: ' + e.message}; });
  } finally { ts.forEach(d => PLANNING.delete(key + '|' + d)); }
  if (key === planKey()) render();
}

function render() {
  if (!INFO) return;
  $('xpSong').textContent = `${S.song}・基準 ${T(INFO.base)}・型 ${INFO.library_short || ''}`;
  $('xpList').innerHTML = listHTML();
  renderBase(); renderUD(); renderRows(); loadPlans();
  if (document.activeElement !== $('xpStep')) $('xpStep').value = X.step;
  $('xpStep').min = INFO.step_limits[0]; $('xpStep').max = INFO.step_limits[1];
  $('xpStepSave').disabled = X.step === STEP0();
  $('xpStepNote').textContent = X.step === STEP0() ? `（今の既定 ${STEP0()}%${STEP0() === INFO.step_default ? '' : `・最初の既定は ${INFO.step_default}%`}）`
    : `（今の既定は ${STEP0()}%・この展開だけ ${X.step}% にする時は「既定にする」を押さなくてよい）`;
  renderFoot();
}
// 展開が終わった後のボタン（2026-11-09 利用者「展開が終わったら『展開する』の色を落として『閉じる』に色を」）: 展開し終えた時の設定
// （DONE_SIG）のままなら「閉じる」を強調（次に押すのは閉じる）・設定を変えた・もう一度始めた・窓を開き直したら「展開する」を強調に戻す。
// やめた・失敗した時は「展開する」のまま
const sigOf = () => JSON.stringify([X.base, X.up, X.down, X.step, X.rows]);
function renderFoot() {   // 下の列（何を作るか・「展開する」を押せるか・どちらのボタンを強調するか）
  if (!INFO || !X) return;
  const ts = makeOf(), skip = targetsOf().filter(d => !ts.includes(d)), moving = X.base !== INFO.base;
  const fresh = !!DONE_SIG && !RUN && DONE_SIG === sigOf();
  $('xpSum').textContent = (fresh ? 'この設定で展開した・' : '') + (!ts.length && !moving ? '' : [moving ? `基準を ${T(INFO.base)} → ${T(X.base)}` : '',
    ts.length ? `作る: ${ts.map(T).join('・')}` : '', skip.length ? `今のまま: ${skip.map(T).join('・')}` : ''].filter(Boolean).join('・'));
  const bad = ts.some(d => { const v = ratioOf(d); return v == null || v < INFO.ratio_range[0] || v > INFO.ratio_range[1] || libOf(d) === undefined; });
  $('xpGo').disabled = !!RUN || !INFO.exists || (!ts.length && !moving) || bad || INFO.busy;
  $('xpGo').title = !INFO.exists ? '結果のファイルがまだ無い（先に作り直す）' : INFO.busy ? 'この曲は今作り直している'
    : bad ? (plansReady() ? '量の割合か型の範囲がまだ決まっていない' : '準備中（派生の既定を数えている）')
    : !ts.length && !moving ? '作り直す派生が無い（④ の行の「作り直す」に印を付ける）' : fresh ? 'この設定ではもう展開した（もう一度作り直す時だけ押す）' : '';
  $('xpGo').classList.toggle('main', !fresh);
  $('xpCancel').classList.toggle('main', fresh);
}

// ---- 窓 ----
async function load() {
  INFO = await api('GET', '/api/expand?file=' + encodeURIComponent(S.file));
  if (!LIB) { try { LIB = await api('GET', '/api/library'); } catch (e) { LIB = {bands: [], default: null}; } }
}
function initX() {   // 初めの値: 前に展開した設定（作業ファイルの expand）・無ければ基準のまま・下を 2 つ
  const e = INFO.expand, base = INFO.base, rows = {};
  ((e && e.targets) || []).forEach(t => { const o = t.over || {};
    rows[t.diff] = {pct: t.ratio != null && !t.auto_ratio ? Math.round(t.ratio * 1000) / 10 : null,
                    mode: t.mode === 'band' ? 'band' : 'plan', stars: t.mode === 'band' && t.library ? t.library.stars : null, make: true,   // 前の「今の型」の行は既定に
                    freq: 'freq' in o ? o.freq : undefined, hard: 'hard' in o ? o.hard : undefined}; });
  X = {base, up: 0, down: 0, rows, step: STEP0()};
  if (e && e.base === base) { X.up = e.up || 0; X.down = e.down || 0; }
  else if (!e) X.down = Math.min(2, idx(base));
  clampUD();
  // 派生を見ている時に開いた＝見ている難易度だけ作り直す（ほかは今のまま・「全部」で戻せる）
  if (S.view && targetsOf().includes(S.view)) targetsOf().forEach(d => { rowState(d).make = d === S.view; });
}
async function open() {
  if (!S.file) return;
  if (!$('xpDlg')) build();
  const dlg = $('xpDlg'), shown = dlg.style.display === 'flex';
  // 一覧（GET /api/expand・初めは GET /api/library も）はふつう 0.1 秒ほど。遅い時（作り直しで混んでいる等）だけ、先に窓を出して「準備中」
  const slow = shown ? null : setTimeout(() => { dlg.classList.add('xpLoad'); dlg.style.display = 'flex'; }, 250);
  try { await load(); } catch (e) { clearTimeout(slow); dlg.classList.remove('xpLoad'); if (!shown) close(); A.status('難易度の一覧を読めなかった: ' + e.message, true); return; }
  finally { clearTimeout(slow); }
  restars();
  initX();
  DONE_SIG = null;   // 開き直した＝次に押すのは「展開する」
  $('xpAsk').innerHTML = ''; $('xpAsk').style.display = 'none';
  if (!RUN) { $('xpRun').innerHTML = ''; }
  $('xpRes').innerHTML = RES ? resultHTML(RES) : '';
  render();
  dlg.classList.remove('xpLoad');
  dlg.style.display = 'flex';
  rateAll();
  if (!RUN) {   // 画面を開き直した時: 動いている展開があれば続きを見る
    try { const j = (await api('GET', '/api/expand/jobs?file=' + encodeURIComponent(S.file))).find(q => q.state === 'running');
      if (j) follow(j.id, {base: j.base, src: j.src}); } catch (e) {}
  }
}
function close() { if ($('xpDlg')) $('xpDlg').style.display = 'none'; }

// 窓の中の確かめ（入れ替える／やめる）→ Promise<bool>
const askOpen = () => $('xpAsk') && $('xpAsk').style.display !== 'none';
function ask(html, yes, no) {
  return new Promise(res => {
    const el = $('xpAsk');
    el.innerHTML = `<div class="xpAskMsg">${html}</div><div class="xpAskBtns"><button id="xpAskNo">${esc(no)}</button><button id="xpAskYes" class="main">${esc(yes)}</button></div>`;
    el.style.display = 'block';
    const done = v => { el.style.display = 'none'; el.innerHTML = ''; res(v); };
    $('xpAskYes').onclick = () => done(true); $('xpAskNo').onclick = () => done(false);
    el.scrollIntoView({block: 'nearest'});
  });
}

// ---- 展開する ----
function request(swap) {   // 作り直す派生だけ（作り直さない派生は送らない＝今の譜面のまま・入れ子の相手なら作る側がその譜面を読む）
  return {file: S.file, from: INFO.base, base: X.base, swap: !!swap,
          targets: makeOf().map(d => ({diff: d, ratio: Math.round(ratioOf(d) * 10000) / 10000, library: libOf(d) ?? null}))};
}
function settingOf() {   // 作業ファイルの expand（次に開いた時の初めの値）: 作り直す派生は今の設定・作り直さない派生は前に作った時の設定のまま
  return {at: new Date().toISOString().slice(0, 19), from: INFO.base, base: X.base, up: X.up, down: X.down, step_pct: X.step,
          targets: targetsOf().map(d => {
            const r = rowState(d), pl = planOf(d);
            if (r.make === false) return prevOf(d) || null;
            const over = {}; if (r.freq !== undefined) over.freq = r.freq; if (r.hard !== undefined) over.hard = r.hard;
            return Object.assign({diff: d, ratio: ratioOf(d), auto_ratio: r.pct == null, mode: r.mode, library: libOf(d) ?? null,
                                  note: r.mode === 'plan' && pl ? pl.note : undefined}, Object.keys(over).length ? {over} : {});
          }).filter(Boolean)};
}
async function go() {
  if (RUN || $('xpGo').disabled) return;
  let body = request(false);
  let dry;
  try { dry = await api('POST', '/api/expand/start', Object.assign({dry: true}, body)); }
  catch (e) { A.status('展開できない: ' + e.message, true); $('xpRun').innerHTML = `<div class="bad">展開できない: ${esc(e.message)}</div>`; return; }
  if (dry.need_swap) {
    const occ = rowOf(X.base);
    const ok = await ask(`<b>${esc(T(X.base))}</b> にはもう譜面があります（${occ ? occ.notes : '?'} ノーツ・${occ ? contentText(occ, true) : ''}）。<br>
      入れ替えると、今の ${esc(T(X.base))} の譜面は <b>${esc(T(INFO.base))}</b> へ移ります（消えません）。` +
      (makeOf().includes(INFO.base) ? `<br><span class="warnTxt">${esc(T(INFO.base))} も派生として作るので、移った譜面の作ったままのクリップは入れ替わります（NLM で直した所・利用者のクリップは残る）。</span>` : ''),
      '入れ替えて展開する', 'やめる');
    if (!ok) { A.status('難易度の展開をやめた'); return; }
    body = request(true);
    try { dry = await api('POST', '/api/expand/start', Object.assign({dry: true}, body)); }
    catch (e) { A.status('展開できない: ' + e.message, true); return; }
  }
  // 作業ファイルに基準（diff）と今の設定（expand）を入れて保存してから始める
  const prevDiff = S.W.diff, moving = X.base !== INFO.base;
  const setting = settingOf();
  commit(W => { if (moving) W.diff = X.base; W.expand = setting; }, {force: true});   // 派生を見ていても書く（展開の窓は派生を直す所）
  await saveWork();
  let id;
  try { ({id} = await api('POST', '/api/expand/start', body)); }
  catch (e) {
    if (moving) { commit(W => { W.diff = prevDiff; }, {force: true}); await saveWork(); }
    A.status('展開を始められなかった: ' + e.message, true); $('xpRun').innerHTML = `<div class="bad">展開を始められなかった: ${esc(e.message)}</div>`; return;
  }
  follow(id, {base: X.base, src: INFO.base, prevDiff});
}
const ST = {waiting: '待っている', running: '作っている', done: 'できた', error: '失敗', cancelled: 'やめた', skipped: '作らない'};
function parHTML(j) {   // 派生ごとの進み具合（並べて作る・上＝一番難しい・基準の行もその並びの中に）
  const rows = j.par || [], base = j.base;
  if (!rows.length) return '';
  const now = Date.now() / 1000;
  // ★: 作り終えた派生から測り始める（app/expand._prerate・2026-11-09 利用者「計算の終わった難易度は先に★を」）＝結果のファイルへ
  // 入れる前の譜面の★（入れた後も同じ中身＝結果の表には測り直さずに出る）。stars: 無い＝測らない・null＝測っている・false＝測れない
  const star = r => r.state !== 'done' || r.stars === undefined ? '' : r.stars === null ? '<span class="sub">測っている…</span>'
    : r.stars === false ? '<span class="sub">?</span>' : `<b>${(+r.stars).toFixed(2)}</b>`;
  return `<table class="xpTbl xpPar"><tr><th>難易度</th><th>進み具合</th><th>量</th><th>時間</th><th title="作り終えた派生から測る">★</th><th>今していること</th></tr>` +
    [...rows.map(r => r.diff), base].sort(byHard).map(d => {
      if (d === base) return `<tr class="xpBaseRow"><td><b>${esc(T(d))}</b></td><td><span class="xpSt base">基準</span></td><td>100%</td><td></td><td></td>
        <td class="sub">${j.moved ? `${esc(T(j.src))} から置き直した` : '今の譜面のまま（作り直さない）'}</td></tr>`;
      const r = rows.find(x => x.diff === d);
      const t = r.state === 'running' && r.started ? Math.max(0, Math.round(now - r.started)) : r.took != null ? Math.round(r.took) : null;
      const what = r.state === 'waiting' ? (r.after && r.after.length ? `${r.after.join('・')} ができるのを待っている（入れ子の相手）` : '始めるところ')
        : r.error || r.last || '';
      const note = r.with && r.with.length ? `<div class="sub">入れ子の相手 ${esc(r.with.join('・'))} は待たずに見込む</div>` : '';
      return `<tr><td><b>${esc(T(d))}</b></td><td><span class="xpSt ${r.state}">${r.state === 'running' ? '<span class="genSpin"></span>' : ''}${ST[r.state] || r.state}</span></td>
        <td>${Math.round(r.ratio * 1000) / 10}%</td><td>${t != null ? t + ' 秒' : ''}</td><td class="xpParStar">${star(r)}</td>
        <td class="xpLast ${r.state === 'error' || r.state === 'skipped' ? 'bad' : ''}">${esc(String(what).slice(0, 140))}${note}</td></tr>`;
    }).join('') + '</table>';
}
function runHTML(j, sec) {
  const steps = j.steps || [], last = (j.log || '').trim().split('\n').filter(l => !l.startsWith('== ')).pop() || '';
  return `<div class="xpRunHead"><span class="genSpin"></span><b>難易度を展開しています</b><span class="sub">${sec} 秒</span>
      <span class="xpSpacer"></span><button id="xpStop" title="作っている派生を全部止める（作り終えた派生は入れる・展開の前の控えは out/old/）">やめる（作り終えた派生は残す）</button></div>
    <ol class="xpSteps">${steps.map((s, i) => `<li class="${i < j.step ? 'done' : i === j.step ? 'now' : ''}">${i < j.step ? '✓' : i === j.step ? '▶' : '・'} ${esc(s)}</li>`).join('')}</ol>
    ${(j.par || []).length ? parHTML(j) : `<div class="genLog">${esc(last.slice(0, 160))}</div>`}`;
}
async function follow(id, meta) {
  RUN = Object.assign({id, t0: Date.now()}, meta); RES = null; DONE_SIG = null;
  if ($('xpRes')) $('xpRes').innerHTML = '';
  emit('generating', true); if ($('gen')) $('gen').disabled = true;
  if ($('expandBtn')) $('expandBtn').classList.add('xpBusy');
  render();
  let j;
  try {
    for (;;) {
      j = await api('GET', '/api/job?id=' + id);
      const sec = Math.round((Date.now() - RUN.t0) / 1000);
      if ($('xpRun')) { $('xpRun').innerHTML = j.state === 'running' ? runHTML(j, sec) : ''; const b = $('xpStop'); if (b) b.onclick = () => stop(id); }
      if ($('expandBtn')) $('expandBtn').textContent = j.state === 'running' ? `難易度を展開している… ${sec} 秒` : '難易度を展開';
      if (j.state !== 'running') break;
      await new Promise(r => setTimeout(r, 1000));
    }
  } catch (e) { j = {state: 'error', log: String(e.message), steps: [], step: 0}; }
  finally { if ($('expandBtn')) { $('expandBtn').textContent = '難易度を展開'; $('expandBtn').classList.remove('xpBusy'); } }
  // 基準の置き直し: 置き直したなら作業ファイルの diff を置き直した難易度に（展開の間に元に戻されていても）・置き直す前に止まったら戻す
  const moving = RUN.base && RUN.src && RUN.base !== RUN.src;
  if (moving && j.moved && S.W.diff !== RUN.base) { S.W.diff = RUN.base; await saveWork(); }
  if (moving && !j.moved && S.W.diff === RUN.base) { commit(W => { W.diff = RUN.prevDiff ?? RUN.src; }, {force: true}); await saveWork(); }
  RUN = null; RES = j;
  if ($('gen')) $('gen').disabled = false;
  emit('generating', false);
  try {
    if (moving && j.moved) await A.openSong(S.song);   // 基準が変わった＝帯・意思入れ・3D を開き直す
    else if ((j.made || []).length || j.restored) await A.reloadChart();   // restored＝読めなくなった結果のファイルを展開の前の控えに戻した
  } catch (e) { A.status('読み直せなかった: ' + e.message, true); }
  emit('diffs'); emit('generated', {job: j, expand: true});
  A.status(j.state === 'done' ? `難易度を展開した（${(j.made || []).map(T).join('・') || '置き直しだけ'}・${j.took} 秒）`
           : `難易度の展開が止まった（${(j.made || []).length ? '作れた: ' + j.made.map(T).join('・') : '派生は作っていない'}）`, j.state !== 'done');
  if ($('xpDlg') && $('xpDlg').style.display !== 'none') {
    try { await load(); } catch (e) {}
    restars(); render(); rateAll();
    $('xpRes').innerHTML = resultHTML(j); rateResults(j);
  } else if (j.state !== 'done' || (j.made || []).length) { await open(); $('xpRes').innerHTML = resultHTML(j); rateResults(j); }
  // 展開できた＝この窓で次に押すのは「閉じる」（強調を入れ替え・Enter も閉じる）。設定を変えると「展開する」に戻る（renderFoot）
  if (j.state === 'done' && $('xpDlg') && $('xpDlg').style.display !== 'none' && X) {
    DONE_SIG = sigOf(); renderFoot();
    $('xpCancel').focus({preventScroll: true});
  }
}
async function stop(id) {
  if (!confirm('展開をやめますか？（今の段で止める。作り終えた派生はそのまま残る）')) return;
  try { await api('POST', '/api/expand/cancel', {id}); } catch (e) { A.status('やめられなかった: ' + e.message, true); }
}

// ---- 結果 ----
function resultHTML(j) {
  const rs = j.results || [], ok = j.state === 'done';
  // 止まった訳: 記録の最後の行（compose が失敗した時は、その前の compose の最後の言葉も）
  const ls = (j.log || '').trim().split('\n').filter(l => l.trim() && !l.startsWith('== '));
  const why = ok ? '' : /^失敗した/.test(ls[ls.length - 1] || '') && ls.length > 1 && !(j.par || []).length ? `${ls[ls.length - 2]}（${ls[ls.length - 1]}）` : (ls.pop() || '');
  const head = ok ? `<b>展開した</b>（${j.took ?? '?'} 秒${j.moved ? `・基準を ${esc(T(j.src))} → ${esc(T(j.base))}` : ''}）`
    : `<b class="bad">展開が止まった</b>（${esc(j.steps && j.steps[j.step] || '')}）: ${esc(why)}`;
  // 上＝一番難しい・基準の行もその並びの中に・作れなかった派生も（訳）
  const bad = (j.par || []).filter(r => !rs.some(x => x.diff === r.diff));
  const base = j.base, br = rowOf(base);
  const ds = [...rs.map(r => r.diff), ...bad.map(r => r.diff), ...(base ? [base] : [])].sort(byHard);
  const tbl = rs.length || bad.length ? `<table class="xpTbl"><tr><th>難易度</th><th>ノーツ</th><th>1秒のノーツ</th><th>基準に対する割合</th><th>★</th><th>崩れ</th><th>NLM の警告</th></tr>` +
    ds.map(d => {
      if (d === base) return `<tr class="xpBaseRow"><td><b>${esc(T(d))}</b> <b class="xpTag base">基準</b></td><td>${br && br.notes != null ? br.notes : '?'}</td>
        <td>${nps(br && br.nps)}</td><td>100%</td><td class="xpStar" data-d="${d}"><span class="sub">…</span></td><td colspan="2" class="sub">作り直していない</td></tr>`;
      const r = rs.find(x => x.diff === d);
      if (!r) { const q = bad.find(x => x.diff === d);
        return `<tr><td><b>${esc(T(d))}</b></td><td colspan="6" class="bad">${esc(ST[q.state] || q.state)}${q.error ? '：' + esc(q.error) : ''}（入れていない）</td></tr>`; }
      const n = r.nums || {}, warn = +(n.warn || 0), brk = n.broken || '';
      return `<tr><td><b>${esc(r.text)}</b></td><td>${r.notes ?? '?'}</td><td>${nps(r.nps)}</td>
        <td>${r.got != null ? Math.round(r.got * 100) + '%' : '—'}<span class="sub">（狙い ${Math.round(r.want * 1000) / 10}%）</span></td>
        <td class="xpStar" data-d="${r.diff}"><span class="sub">…</span></td>
        <td class="${brk && brk !== '0%' ? 'bad' : ''}">${esc(brk || '—')}</td><td class="${warn ? 'bad' : ''}">${esc(n.warn ?? '—')}</td></tr>`; }).join('') + '</table>' : '';
  const det = rs.slice().sort((a, b) => byHard(a.diff, b.diff)).map(r => {
    const lines = [...(r.derive || []), ...(r.head || []).filter(l => /^(打点|量|間引|足し|型の出どころ|出力|派生)/.test(l))];
    return `<details class="xpDet"><summary>${esc(r.text)} の報告の大事な行${r.no_report ? '（報告が無い）' : ''}</summary>
      ${lines.length ? lines.map(l => `<div class="li">${esc(l)}</div>`).join('') : '<div class="sub">（大事な行が無い）</div>'}
      ${r.report ? `<details><summary class="sub">報告の全部</summary><pre>${esc(r.report)}</pre></details>` : ''}</details>`;
  }).join('');
  const back = j.backup ? `<div class="sub">展開の前の控え: out/old/${esc(j.backup.split(/[\\/]/).pop())}（履歴の窓からも戻せる）</div>` : '';
  const log = ok ? '' : `<details class="xpDet" open><summary>記録</summary><pre>${esc((j.log || '').slice(-4000))}</pre></details>`;
  return `<div class="xpResHead">${head}</div>${tbl}${det}${back}${log}`;
}
async function rateResults(j) {   // 結果の表の★（作った派生ごと・基準も）。難易度ごとに同時に聞く（作業の間に先に測ってあればすぐ返る）
  await Promise.all([...(j.results || []), ...(j.base ? [{diff: j.base}] : [])].map(async r => {
    const cell = () => document.querySelector(`#xpRes .xpStar[data-d="${r.diff}"]`);
    for (let i = 0; i < 6; i++) {
      let a;
      try { a = await api('GET', `/api/rating?wait=5&file=${encodeURIComponent(S.file)}&diff=${r.diff}`); } catch (e) { a = {state: 'done', error: e.message}; }
      if (a.state === 'running') continue;
      const c = cell(); if (!c) return;
      c.innerHTML = a.state === 'done' && a.stars != null && a.view_diff === r.diff ? (+a.stars).toFixed(2)
        : `<span class="sub" title="${esc(a.error || '')}">${a.state === 'unavailable' ? '測れない' : '?'}</span>`;
      break;
    }
  }));
}

// ---- 確かめ用（見えない Edge で写す）: #xtest&song=曲名[&up=1&down=2&base=Expert][&ask][&run][&res] ----
function selfTest(h) {
  const g = k => { const m = h.match(new RegExp('&' + k + '=([^&]+)')); return m ? decodeURIComponent(m[1]) : null; };
  S.readonly = true;   // 本物の作業ファイルを書き換えない
  const view = g('view') ? (S.view = g('view'), A.reloadChart()) : Promise.resolve();   // &view=Normal＝その派生を見ている時に開く（ロックも）
  if (/&prep/.test(h)) HOLD = true;   // 派生の既定を聞かない＝「準備中」のまま
  view.then(open).then(async () => {
    if (/&loading/.test(h)) $('xpDlg').classList.add('xpLoad');   // 一覧を読んでいる間の窓
    if (g('base')) X.base = g('base');
    if (g('up') != null) X.up = +g('up');
    if (g('down') != null) X.down = +g('down');
    if (g('step') != null) X.step = +g('step');
    clampUD();
    if (g('make') != null) { const ms = g('make').split(','); targetsOf().forEach(d => { rowState(d).make = ms.includes(d); }); }
    targetsOf().forEach(d => { const r = rowState(d);
      if (g('freq') != null) r.freq = g('freq') === 'null' ? null : g('freq');
      if (g('hard') != null) r.hard = g('hard'); });
    render();
    await new Promise(r => setTimeout(r, 2500));
    render();
    if (/&dry/.test(h)) {   // サーバーの確かめ（作らない）: 送る中身と答え → #xtestOut
      const body = request(false); let ans;
      try { ans = await api('POST', '/api/expand/start', Object.assign({dry: true}, body)); } catch (e) { ans = {error: e.message}; }
      const pre = document.createElement('pre'); pre.id = 'xtestOut'; pre.style.display = 'none';
      pre.textContent = JSON.stringify({sent: body.targets, setting: settingOf().targets, answer: ans}); document.body.appendChild(pre);
    }
    if (/&ask/.test(h)) ask(`<b>${esc(T(X.base))}</b> にはもう譜面があります（確かめの見本）。入れ替えると、今の ${esc(T(X.base))} の譜面は <b>${esc(T(INFO.base))}</b> へ移ります。`, '入れ替えて展開する', 'やめる');
    const ts = targetsOf(), now = Date.now() / 1000;
    if (/&run/.test(h)) {   // 進み具合の見本: 1つ目はできた・2つ目は作っている・3つ目は待っている（入れ子の相手を見込むなら作っている）
      const par = ts.map((d, i) => ({diff: d, text: T(d), ratio: ratioOf(d) || 1, after: i === 2 ? [T(ts[1])] : [], with: i === 1 && idx(d) < idx(X.base) ? [T(ts[0])] : [],
        state: ['done', 'running', 'waiting'][i] || 'running', started: now - 20 + i, took: i === 0 ? 31.4 : null,
        last: i === 0 ? '' : 'flow: 打点 520（両手同時 40）・ビーム 64', error: null, stars: i === 0 ? 4.21 : undefined}));
      if (par.length > 3) Object.assign(par[3], {state: 'done', took: 18.2, stars: null});   // 4 つ目はできて★を測っている
      $('xpRun').innerHTML = runHTML({steps: ['控え', `${ts.map(T).join('・')} を作る（並べて）`], step: 1, base: X.base, src: INFO.base, par,
        log: '== 派生を作る\n[Expert] 打点 520（両手同時 40）'}, 23);
    }
    if (/&res/.test(h)) $('xpRes').innerHTML = resultHTML({state: 'done', took: 41.2, steps: [], step: 0, base: X.base, backup: 'x/old/曲.intent-s1.展開前.20261102-120000.nlmf',
      par: ts.map((d, i) => ({diff: d, state: i === ts.length - 1 && /&fail/.test(h) ? 'error' : 'done', error: i === ts.length - 1 && /&fail/.test(h) ? '失敗した（終了コード 1）' : null})),
      results: ts.filter((d, i) => !(i === ts.length - 1 && /&fail/.test(h))).map((d, i) => ({diff: d, text: T(d), notes: 400 - i * 80, nps: 3.2 - i * 0.6,
        got: ratioOf(d), want: ratioOf(d), nums: {broken: '0%', warn: '0'}, derive: ['基準の打点 763 → 595（弱い打点から間引いた）'], head: ['打点 595（両手同時 30）']}))});
    document.title = `xtest base=${X.base} up=${X.up} down=${X.down} step=${X.step} targets=${ts.join(',')} make=${makeOf().join(',')} ratios=${ts.map(d => ratioOf(d)).join(',')} plans=${Object.keys(PLAN[planKey()] || {}).join(',')}`;
    if (/&go(&|$)/.test(h)) {   // 本当に展開する（写しの場所のサーバーでだけ）→ 終わった後の下の列・結果の表の★ → #xtestGo
      await go();
      while (RUN || !RES) await new Promise(r => setTimeout(r, 500));
      await new Promise(r => setTimeout(r, 3000));
      const pre = document.createElement('pre'); pre.id = 'xtestGo'; pre.style.display = 'none';
      pre.textContent = JSON.stringify({state: RES.state, made: RES.made, par: (RES.par || []).map(r => [r.diff, r.stars]),
        stars: [...document.querySelectorAll('#xpRes .xpStar')].map(c => [c.dataset.d, c.textContent]),
        main: $('xpGo').classList.contains('main') ? '展開する' : $('xpCancel').classList.contains('main') ? '閉じる' : '-',
        focus: document.activeElement && document.activeElement.id, sum: $('xpSum').textContent});
      document.body.appendChild(pre);
      $('xpGo').scrollIntoView({block: 'end'});
    }
    if (/&done/.test(h)) { DONE_SIG = sigOf(); renderFoot(); $('xpCancel').focus({preventScroll: true}); $('xpGo').scrollIntoView({block: 'end'}); }   // 展開し終えた後の下の列（「閉じる」を強調）
    else if (/&run/.test(h)) $('xpRun').scrollIntoView({block: 'start'});
    if (g('pcts') != null) {   // &pcts=121,122,130,…＝行（&pctrow=難易度・無ければ一番上の行）の量を矢印で押したように変え、毎回の欄と行の位置 → #xtestPos
      const row = g('pctrow') || makeOf()[0], pos = [];
      const at = () => { const tr = document.querySelector(`#xpRows tr[data-d="${row}"]`), inp = tr && tr.querySelector('.xpPct');
        const r = inp ? inp.getBoundingClientRect() : {}, t = tr ? tr.getBoundingClientRect() : {}, rs = tr && tr.querySelector('.xpReset');
        const nx = tr && tr.nextElementSibling ? tr.nextElementSibling.getBoundingClientRect().top : null, cols = [...document.querySelectorAll('#xpRows tr:nth-child(1) th, #xpRows tbody tr:first-child th')].map(th => Math.round(th.getBoundingClientRect().width));
        return {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), rowTop: Math.round(t.top), rowH: Math.round(t.height), next: nx && Math.round(nx),
          reset: rs ? getComputedStyle(rs).visibility : 'none', focus: document.activeElement === inp, cols, value: inp && inp.value,
          sub: tr && [...tr.querySelectorAll('.xpPctNps,.xpPctDef')].map(e => e.textContent).join('｜'),
          main: $('xpGo').classList.contains('main') ? '展開する' : $('xpCancel').classList.contains('main') ? '閉じる' : '-'}; };
      $('xpRows').scrollIntoView({block: 'start'});
      pos.push(Object.assign({v: 'start'}, at()));
      for (const v of g('pcts').split(',')) {
        const inp = document.querySelector(`#xpRows tr[data-d="${row}"] .xpPct`);
        inp.focus(); inp.value = v;
        inp.dispatchEvent(new Event('input', {bubbles: true})); inp.dispatchEvent(new Event('change', {bubbles: true}));
        await new Promise(r => setTimeout(r, 60));
        pos.push(Object.assign({v}, at()));
      }
      const pre = document.createElement('pre'); pre.id = 'xtestPos'; pre.style.display = 'none';
      pre.textContent = JSON.stringify(pos); document.body.appendChild(pre);
    }
  });
}

export function init(app) {
  A = app;
  if ($('expandBtn')) $('expandBtn').onclick = open;
  on('work', () => { if ($('xpDlg') && $('xpDlg').style.display !== 'none' && !RUN && S.file && INFO && INFO.file !== S.file) close(); });   // 曲を替えたら閉じる
  if (location.hash.startsWith('#xtest')) {
    const h = decodeURIComponent(location.hash), m = h.match(/&song=([^&]+)/);
    let done = false;
    on('work', () => {
      if (!S.D || done) return;
      if (m && S.song !== m[1] && S.songs.some(q => q.song === m[1])) { A.openSong(m[1]); return; }
      done = true; setTimeout(() => selfTest(h), 300);
    });
  }
}
