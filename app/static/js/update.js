// アプリの更新（app/update.py・docs/アプリ仕様.md 21 節・NLM の update-dialog.js と同じ流れ）。main.js が init(app) と autoCheck() を呼ぶ。
// - 上の列の版のボタン（#updBtn）で「更新」の窓: 今の版・「更新を確認」・「起動した時に確かめる」のオン・オフ（設定の update_check）。
// - 起動した時（配布物で、オンの時だけ・通信の失敗は何も出さない）に新しい版があれば、右上に知らせ（変更点を見て更新する・あとで）。
//   「この版は飛ばす」にした版（設定の update_skip）とそれより古い版は、起動した時には知らせない（窓の「更新を確認」ではいつでも出る）。
// - 「更新する」: ダウンロード（/api/update/download・進み具合は /api/job）→ 作業ファイルを保存 → /api/update/apply（新しい版の exe に
//   差し替えを任せる）→ /api/shutdown（窓のアプリはサーバーが止まると窓を閉じる）。新しい版が置き換えてから起動し直す。
// - 開発の PC（配布物でない）では確かめない（窓に「開発用の環境では更新しません」）。
// - 強い知らせ（2026-11-03 利用者）: 今の版から最新の版までに急ぎの版がある（update.json の urgent）・今の版が使ってはいけない版
//   （ng.app）の時は、起動のたびに目立つ知らせを出し「この版は飛ばす」を出さない（飛ばした版でも出す）。ネットにつながらない起動
//   （と起動時に確かめない設定）は、前に確かめた時に控えた物（/api/update/status の self_ng・urgent）で出す。
// - 確かめるたびにサーバーが NG を設定に控える。音を分ける部品の NG が変わった（ng_changed）時は、準備の確かめをし直す（onChecked）。
// 外から来る文字（変更点・理由）は textContent で入れる。言葉の決まり: ダウンロード・更新・再起動（「取ってくる」は使わない）。
// 確かめ: #uptest（=new・=win・=run・=latest・=dev・=done・=error・=busy・=manual・=urgent・=urgent-win・=selfng・=selfng-win・=selfngonly・
//   =offline）＝作り物の答えで窓・知らせを出す（サーバーに書かない）→ #uptestOut
import {$, api} from './store.js';
import * as player from './player.js';

let A = null;        // main.js の口（status・saveWork）
let ST = null;       // /api/update/status
let FOUND = null;    // 最後に見つけた新しい版（/api/update/check の答え・今の版が NG の時は新しい版が無くても）
let JOB = null;      // ダウンロードの作業の id
let FAKE = null;     // #uptest の作り物
const HOOKS = [];    // 確かめた後に呼ぶ（準備の窓が NG の変わりを受け取る）
const strong = j => !!(j && (j.urgent || j.self_ng));
const day = s => String(s || '').slice(0, 10);
const mb = n => (n / 1e6).toFixed(1);
const vt = v => { const m = /^v(\d+)\.(\d+)\.(\d+)$/.exec(v || ''); return m ? m.slice(1).map(Number) : null; };
const vgt = (a, b) => { const x = vt(a), y = vt(b); if (!x) return false; if (!y) return true;
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i]; return false; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function call(method, url, body) {
  if (FAKE) return FAKE(method, url, body);
  return api(method, url, body);
}
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function btn(row, label, cls, fn) { const b = el('button', cls, label); b.onclick = fn; row.appendChild(b); return b; }

// ---- 窓 ----
function build() {
  const d = el('div', 'modal up'); d.id = 'upDlg';
  d.innerHTML = `<div class="dlg">
  <div class="dlgHead"><b id="upTitle">アプリの更新</b><button id="upClose">閉じる</button></div>
  <div class="dlgBody">
    <div class="upCur">今の版: <b id="upCur"></b></div>
    <div id="upBody" class="upBody"></div>
    <div class="upFoot"><label class="upAuto" title="起動した時に、配布元（GitHub）に新しい版があるかを確かめます（通信は版の情報を読むだけ）">
      <input type="checkbox" id="upAuto"> 起動した時に新しい版があるか確かめる</label><span id="upMsg" class="sub"></span>
      <span id="upBtns" class="upBtns"></span></div>
  </div></div>`;
  document.body.appendChild(d);
  $('upClose').onclick = close;
  d.addEventListener('mousedown', e => { if (e.target === d && !JOB) close(); });
  $('upAuto').onchange = async e => {
    try { ST = await call('POST', '/api/update/settings', {auto_check: e.target.checked}); msg(e.target.checked ? '起動した時に確かめます' : '起動した時には確かめません'); }
    catch (err) { msg('設定を書けませんでした: ' + err.message, true); e.target.checked = !e.target.checked; }
  };
}
function msg(text, bad) { const m = $('upMsg'); if (!m) return; m.textContent = text || ''; m.classList.toggle('bad', !!bad); }
function body() { const b = $('upBody'); b.textContent = ''; $('upBtns').textContent = ''; msg(''); return b; }
function close() { if (JOB) return; const d = $('upDlg'); if (d) d.style.display = 'none'; }

export async function open(show) {
  if (!$('upDlg')) build();
  $('upDlg').style.display = 'flex';
  try { ST = await call('GET', '/api/update/status'); } catch (e) { ST = null; }
  $('upCur').textContent = ST ? ST.current : '?';
  $('upAuto').checked = !!(ST && ST.auto_check);
  $('upAuto').disabled = !ST || !ST.distributed;
  if (JOB) return;
  if (show) return show();
  idle();
}
function idle() {
  const b = body();
  if (ST && !ST.distributed) {
    b.appendChild(el('p', 'upNote', '開発用の環境（配布物でない）では更新しません。更新を確かめるのは、配布物（AutoNotePlotter.exe から起動したアプリ）だけです。'));
    return;
  }
  b.appendChild(el('p', 'sub', '配布元（GitHub）に新しい版があるかを確かめます。新しい版があれば、変更点を見てから更新できます。'));
  if (FOUND && (FOUND.newer || FOUND.self_ng)) return showNew(FOUND);
  btn($('upBtns'), '更新を確認', 'main', manualCheck).focus();
}

async function manualCheck() {
  const b = body();
  b.appendChild(el('p', '', '確かめています…'));
  let j;
  try { j = await call('GET', '/api/update/check'); } catch (e) { j = {ok: false, message: e.message}; }
  if (!j.ok) {
    const b2 = body();
    b2.appendChild(el('p', 'bad', '確かめられませんでした: ' + (j.message || j.error)));
    btn($('upBtns'), 'もう一度確かめる', '', manualCheck);
    return;
  }
  fire(j);
  if (j.newer || j.self_ng) { FOUND = j; topButton(); return showNew(j); }
  FOUND = null; topButton();
  const b2 = body();
  b2.appendChild(el('p', 'upOk', `最新の版です（${j.current}）。`));
  btn($('upBtns'), '更新を確認', '', manualCheck);
}

function fire(j) { for (const f of HOOKS) { try { f(j); } catch (e) {} } }
const titleOf = j => j.self_ng ? `この版（${j.current}）は更新が必要です` : j.urgent ? `急ぎの更新 ${j.latest} があります` : `新しい版 ${j.latest} があります`;

// 急ぎ・今の版が NG の訳（強い知らせと窓の頭）
function warnBox(j) {
  const w = el('div', 'upWarn');
  if (j.self_ng) w.appendChild(el('div', '', `この版には問題が見つかりました${j.ng_why ? '：' + j.ng_why : ''}。新しい版に更新してください。`));
  if (j.urgent) w.appendChild(el('div', '', `急ぎの更新です${j.urgent_why ? '：' + j.urgent_why : ''}。できるだけ早く更新してください。`));
  if (j.offline) w.appendChild(el('div', 'sub', `前回${j.at ? ` ${day(j.at)} に` : ''}確かめた時の情報です。インターネットにつないでから「更新を確認」してください。`));
  return w;
}

// 変更点（今の版より新しい版の分）＋「更新する／あとで／この版は飛ばす」（急ぎ・今の版が NG の時は飛ばすを出さない）
function showNew(j) {
  $('upTitle').textContent = titleOf(j);
  const b = body();
  if (strong(j)) b.appendChild(warnBox(j));
  if (!j.newer) {   // 今の版が NG で、直した版がまだ無い
    b.appendChild(el('p', 'upHint', '直した版はまだ配布されていません。配布元のページで知らせを確かめてください（直した版が出たら、起動した時に知らせます）。'));
    btn($('upBtns'), '閉じる', '', close);
    btn($('upBtns'), '配布元のページを開く', 'main', async () => { try { await call('POST', '/api/update/open-releases', {}); } catch (e) { msg(e.message, true); } });
    return;
  }
  const box = el('div', 'upNotes'); b.appendChild(box);
  for (const n of j.notes || []) {
    box.appendChild(el('div', 'upVer', n.version));
    const ul = el('ul'); for (const s of n.ja || []) ul.appendChild(el('li', '', s)); box.appendChild(ul);
  }
  if (!(j.notes || []).length) box.appendChild(el('p', 'sub', '変更点の情報がありません。'));
  const row = $('upBtns');
  if (j.auto === 'ok') {
    b.appendChild(el('p', 'upHint', `「更新する」を押すと、ダウンロード（${mb(j.size)}MB）してから、アプリを終わって新しい版に置き換え、再起動します（1〜2 分）。` +
      '作業フォルダ（作った譜面・分けた音）・設定・音を分ける部品はそのまま残ります。前の版は、アプリのフォルダの中の「_previous_版」に 1 つだけ残ります。'));
    if (!strong(j)) btn(row, 'この版は飛ばす', '', () => skip(j.latest)).title = '起動した時にはこの版を知らせません（この窓の「更新を確認」からはいつでも更新できます）';
    btn(row, 'あとで', '', () => { $('upTitle').textContent = 'アプリの更新'; close(); });
    btn(row, '更新する', 'main', () => run(j)).focus();
  } else {
    const why = {dev: '開発用の環境（配布物でない）では更新しません。', readonly: 'アプリのフォルダに書き込めないため、自動では更新できません（Program Files などに置いた時）。',
      manual: 'この版は自動では更新できません。'}[j.auto] || 'この環境では自動で更新できません。';
    b.appendChild(el('p', 'upHint', why + '配布元のページから zip をダウンロードして、展開した物で置き換えてください（作業フォルダ・設定はアプリのフォルダの外にあるので残ります）。'));
    btn(row, 'あとで', '', close);
    btn(row, '配布元のページを開く', 'main', async () => { try { await call('POST', '/api/update/open-releases', {}); } catch (e) { msg(e.message, true); } });
  }
}

async function skip(v) {
  try { ST = await call('POST', '/api/update/skip', {version: v}); } catch (e) { msg(e.message, true); return; }
  hideBar(); close();
  if (A) A.status(`${v} は起動した時には知らせません（「${ST ? ST.current : ''}」のボタン →「更新を確認」からはいつでも更新できます）`);
}

// ---- ダウンロード → 差し替え役の起動 → 終わる ----
async function run(j) {
  hideBar();
  const b = body();
  // 作り直し・取り込みなどの途中は差し替えない（サーバーも断る）
  let jobs = [];
  try { jobs = (await call('GET', '/api/jobs')).filter(x => x.kind !== 'update'); } catch (e) {}
  if (jobs.length) {
    b.appendChild(el('p', 'bad', '作り直し・曲の取り込みなどの作業の途中です。終わってから、もう一度「更新する」を押してください。'));
    btn($('upBtns'), '戻る', '', () => showNew(j));
    return;
  }
  $('upTitle').textContent = `${j.latest} に更新しています`;
  const text = el('p', '', 'ダウンロードを始めています…'); b.appendChild(text);
  const bar = el('div', 'upBar'), fill = el('div'); bar.appendChild(fill); b.appendChild(bar);
  b.appendChild(el('p', 'sub', 'ダウンロードが終わると、作業ファイルを保存してからアプリを終わり、新しい版に置き換えて再起動します。'));
  const fail = t => { JOB = null; const b2 = body(); b2.appendChild(el('p', 'bad', '更新できませんでした: ' + t));
    btn($('upBtns'), '閉じる', '', () => { $('upTitle').textContent = 'アプリの更新'; close(); }); btn($('upBtns'), 'もう一度', 'main', () => run(j)); };
  let r;
  try { r = await call('POST', '/api/update/download', {}); } catch (e) { return fail(e.message); }
  if (!r.ok) return fail(r.message || r.error);
  JOB = r.id;
  const stop = btn($('upBtns'), 'やめる', '', async () => { stop.disabled = true; try { await call('POST', '/api/job/cancel', {id: JOB}); } catch (e) {} });
  let p;
  for (;;) {
    try { p = await call('GET', '/api/job?id=' + encodeURIComponent(JOB)); } catch (e) { return fail(e.message); }
    const g = p.progress || {};
    if (g.stage === 'download' && g.total) {
      fill.style.width = (100 * (g.done || 0) / g.total).toFixed(1) + '%';
      text.textContent = `ダウンロードしています… ${mb(g.done || 0)} / ${mb(g.total)}MB`;
    } else if (g.stage === 'extract') { fill.style.width = '100%'; fill.className = 'busy'; text.textContent = '確かめて展開しています…'; stop.disabled = true; }
    if (p.state !== 'running') break;
    await sleep(400);
  }
  if (p.state !== 'done') {
    if (p.cancelled) { JOB = null; const b2 = body(); b2.appendChild(el('p', '', 'ダウンロードをやめました。')); btn($('upBtns'), '閉じる', '', close); return; }
    return fail(p.message || (p.log || '').trim().split('\n').pop());
  }
  stop.disabled = true;
  text.textContent = '作業ファイルを保存して、アプリを終わります…';
  try { if (A && A.saveWork) await A.saveWork(); } catch (e) {}
  let a;
  try { a = await call('POST', '/api/update/apply', {}); } catch (e) { return fail(e.message); }
  if (!a.ok) return fail(a.message || a.error);
  try { player.P.au.forEach(x => x.pause()); } catch (e) {}
  document.querySelectorAll('audio').forEach(x => { try { x.pause(); } catch (e) {} });
  if (FAKE) { text.textContent = '（確かめ）ここでアプリを終わります'; JOB = null; return; }
  try { await call('POST', '/api/shutdown', {}); } catch (e) {}
  document.body.innerHTML = '<div style="padding:3rem;font-size:1.3rem;line-height:1.8">更新のためアプリを終わりました。<br>' +
    '新しい版に置き換えてから、自動で再起動します（少しかかります）。<br><span style="color:#8a8a8a">このタブは閉じてかまいません。</span></div>';
}

// ---- 右上の知らせ（起動した時の新しい版・更新した直後）----
function bar() {
  let b = $('upNote');
  if (!b) { b = el('div', 'upNotice'); b.id = 'upNote'; document.body.appendChild(b); }
  const top = $('top'); b.style.top = ((top ? top.getBoundingClientRect().bottom : 40) + 8) + 'px';
  b.textContent = ''; b.className = 'upNotice'; b.style.display = 'block';
  return b;
}
function hideBar() { const b = $('upNote'); if (b) b.style.display = 'none'; }
function noticeNew(j) {
  const b = bar();
  b.appendChild(el('div', 'upNoticeHead', `新しい版 ${j.latest} があります`));
  b.appendChild(el('div', 'sub', `今の版は ${j.current} です。変更点を見てから更新できます。`));
  const row = el('div', 'upBtns'); b.appendChild(row);
  btn(row, 'あとで', '', hideBar);
  btn(row, '変更点を見る・更新する', 'main', () => { hideBar(); open(() => showNew(j)); });
}
// 急ぎ・今の版が NG: 起動のたびに出す（「この版は飛ばす」は無い）。offline＝前に控えた情報から
function noticeStrong(j) {
  const b = bar();
  b.classList.add('upStrong');
  b.appendChild(el('div', 'upNoticeHead', '⚠ ' + (j.offline && !j.self_ng ? `急ぎの更新 ${j.latest || ''} があります` : titleOf(j))));
  b.appendChild(warnBox(j));
  const row = el('div', 'upBtns'); b.appendChild(row);
  btn(row, 'あとで', '', hideBar);
  if (j.offline) btn(row, '更新を確認', 'main', () => { hideBar(); open(manualCheck); });
  else btn(row, j.newer ? '内容を見る・更新する' : '内容を見る', 'main', () => { hideBar(); open(() => showNew(j)); });
}
function noticeDone(u) {
  const b = bar();
  b.appendChild(el('div', 'upNoticeHead', `${u.to} に更新しました`));
  b.appendChild(el('div', 'sub', `前の版（${u.from}）から更新しました。前の版はアプリのフォルダの中の「_previous_${u.from}」に残っています。`));
  const row = el('div', 'upBtns'); b.appendChild(row);
  btn(row, '閉じる', '', hideBar);
}
function topButton() {
  const b = $('updBtn'); if (!b || !ST) return;
  const has = !!(FOUND && FOUND.newer);
  const latest = has ? FOUND.latest : ST.distributed && ST.urgent ? ST.known_latest : null;   // 控えの急ぎの版（開発の PC では出さない）
  const warn = !!ST.distributed && (FOUND ? strong(FOUND) : !!(ST.self_ng || ST.urgent));
  b.textContent = (warn ? '⚠ ' : '') + (latest ? `${ST.current} → ${latest}` : ST.current);
  b.classList.toggle('upHas', has || !!latest);
  b.classList.toggle('upUrgent', warn);
  b.title = warn ? (FOUND && FOUND.self_ng || !FOUND && ST.self_ng ? 'この版には問題が見つかりました（押すと内容と「更新する」）' : `急ぎの更新 ${latest || ''} があります（押すと内容と「更新する」）`)
    : has ? `新しい版 ${FOUND.latest} があります（押すと変更点と「更新する」）` : 'アプリの版と更新（更新を確認・起動した時に確かめるか）';
}

// 起動した時: 更新した直後なら知らせ、配布物で「起動した時に確かめる」がオンなら新しい版を確かめる（失敗は何も出さない）。
// 確かめられない時（ネット無し・確かめない設定）は、前に控えた「今の版が NG・急ぎの新しい版」だけ強い知らせで出す
export async function autoCheck() {
  try { ST = await call('GET', '/api/update/status'); } catch (e) { return; }
  topButton();
  if (ST.justUpdated) { noticeDone(ST.justUpdated); return; }
  if (!ST.distributed) return;
  let j = null;
  if (ST.auto_check) { try { j = await call('GET', '/api/update/check'); } catch (e) { j = null; } }
  if (j && j.ok) {
    fire(j);
    FOUND = j.newer || j.self_ng ? j : null; topButton();
    if (strong(j)) return noticeStrong(j);   // 急ぎ・今の版が NG は「この版は飛ばす」にした版でも知らせる
    if (!j.newer) return;
    if (ST.skip && !vgt(j.latest, ST.skip)) return;   // 「この版は飛ばす」にした版（とそれより古い版）は知らせない
    return noticeNew(j);
  }
  if (ST.self_ng || ST.urgent) noticeStrong({offline: true, current: ST.current, latest: ST.known_latest, newer: !!ST.known_latest,
    self_ng: ST.self_ng, urgent: ST.urgent, urgent_why: ST.urgent_why, ng_why: ST.ng_why, at: ST.ng_at});
}

// 窓を開いて最新の版を確かめる（準備の窓の「アプリの更新を確かめる」）
export async function openCheck() { hideBar(); await open(manualCheck); }

// 確かめた後に呼ぶ関数を足す（fn(/api/update/check の答え)）。準備の窓が、音を分ける部品の NG が変わった時に確かめ直す
export function onChecked(fn) { HOOKS.push(fn); }

export function init(app) {
  A = app;
  const b = $('updBtn'); if (b) b.onclick = () => open();
}

// ---- 確かめ（#uptest=new|win|run|latest|dev|done|error|busy|manual|urgent|urgent-win|selfng|selfng-win|selfngonly|offline）----
export async function selfTest(kind) {
  const [k, sub] = String(kind || 'new').split('-');   // urgent-win＝急ぎの知らせから窓を開いた所
  const base = {ok: true, current: 'v1.0.0', distributed: true, auto_check: true, skip: null, justUpdated: null, ready: null, job: null,
    self_ng: false, ng_why: '', ng_at: null, known_latest: null, urgent: false, urgent_why: ''};
  const notes = [{version: 'v1.1.0', ja: ['難易度の展開を速くした', '「更新」の窓を足した']}, {version: 'v1.0.1', ja: ['曲の取り込みの不具合を直した']}];
  const NGWHY = '曲の取り込みで、分けた音が少しずれる不具合があります';
  let found = {ok: true, current: 'v1.0.0', latest: 'v1.1.0', newer: true, notes, size: 181.4e6, auto: kind === 'manual' ? 'readonly' : 'ok', ready: false,
    urgent: k === 'urgent', urgent_why: k === 'urgent' ? '音を分ける部品の脆弱性を直しました' : '', self_ng: k.startsWith('selfng'), ng_why: k.startsWith('selfng') ? NGWHY : '',
    ng_changed: false};
  if (k === 'selfngonly') found = {...found, latest: 'v1.0.0', newer: false, notes: []};
  const st = {...base, distributed: kind !== 'dev', justUpdated: kind === 'done' ? {from: 'v1.0.0', to: 'v1.1.0'} : null,
    ...(k === 'offline' ? {self_ng: true, ng_why: NGWHY, ng_at: '2026-11-02T21:04:00', known_latest: 'v1.0.1', urgent: true, urgent_why: 'この不具合を直しました'} : {})};
  let polls = 0;
  FAKE = async (m, url, b) => {
    if (url.startsWith('/api/update/status')) return st;
    if (url.startsWith('/api/update/check')) return kind === 'error' ? {ok: false, error: 'notFound', message: '配布元にまだ更新の情報がありません（リリースがまだ無いか、更新の情報が付いていません）。'}
      : k === 'offline' ? {ok: false, error: 'network', message: 'インターネットにつながらないか、配布元（GitHub）に届きませんでした。ネットの接続を確かめてください。'}
      : kind === 'latest' ? {...found, latest: 'v1.0.0', newer: false, notes: []} : found;
    if (url.startsWith('/api/update/settings')) { st.auto_check = !!b.auto_check; return st; }
    if (url.startsWith('/api/update/skip')) { st.skip = b.version; return st; }
    if (url.startsWith('/api/jobs')) return kind === 'busy' ? [{id: 'g', kind: 'generate', state: 'running'}] : [];
    if (url.startsWith('/api/update/download')) return {ok: true, id: 'fake'};
    if (url.startsWith('/api/job?')) { polls++; return polls < 4 ? {id: 'fake', state: 'running', progress: {stage: 'download', done: polls * 45e6, total: 181.4e6}}
      : {id: 'fake', state: 'done', progress: {stage: 'ready', done: 181.4e6, total: 181.4e6}}; }
    if (url.startsWith('/api/update/apply')) return {ok: true, version: 'v1.1.0'};
    return {ok: true};
  };
  await autoCheck();
  if (kind === 'error' || kind === 'latest' || kind === 'dev') { await open(); if (kind !== 'dev') await manualCheck(); }
  if (kind === 'busy' || kind === 'run') { await open(() => showNew(found)); await run(found); }
  if (kind === 'win' || kind === 'manual' || sub === 'win') { hideBar(); await open(() => showNew(found)); }
  const out = () => {
    const n = $('upNote'), d = $('upDlg');
    return [`button=${($('updBtn') || {}).textContent}`, `notice=${n && n.style.display !== 'none' ? n.textContent : '-'}`,
      `dialog=${d && d.style.display === 'flex' ? $('upTitle').textContent + ' | ' + $('upBody').textContent + ' | ' + $('upBtns').textContent : '-'}`].join('\n');
  };
  let pre = $('uptestOut'); if (!pre) { pre = el('pre'); pre.id = 'uptestOut'; pre.style.display = 'none'; document.body.appendChild(pre); }
  pre.textContent = out();
  document.title = 'uptest ' + kind;
}
