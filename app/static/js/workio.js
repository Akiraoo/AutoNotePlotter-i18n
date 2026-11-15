// 付けた指示の読み込み・全部外す（app/workio.py）の画面。main.js が init(app) を呼ぶ。
// 付けた指示の一覧（左下の #listPane）の見出しに「読み込む…」「全部外す」。どちらも作業ファイルを commit で変える＝Ctrl+Z で戻せる・すぐ保存。
// 全部外す: 窓で確かめてから区間の指示を全部外す（量のライン・自動の休みも外すかは選べる）。ライブラリ・量の目安（曲の設定）は触らない。
//   「次の作り直しは前の譜面に寄せない」（既定で入）＝次に作り直す時の聞く窓で「全部作り直す」を選んだ状態にする（S.freshNext）。
// 読み込む: 窓の上に読み込める物（控え・作業ファイル・前の形式の表・履歴の版＝GET /api/workio/sources）→ 選ぶとその中の指示の一覧
//   （チェック・同じ振りはグループごとにまとめて選ぶ＝手本と写しを片方だけ入れると壊れる）と、量のライン・自動の休み・ライブラリ・
//   量の目安を入れるか（既定は指示と量のラインだけ）。「選んだ物を足す」＝今の指示に足す（全く同じ区間・指示は足さない＝store.rangeKey）・
//   「置き換える」＝今の指示を外して入れる。量のライン等は、入れると今の物と入れ替える。足した指示には新しい id（store.newId）。
//   拍は今の曲の目盛りに合わせ直してサーバーが返す（目盛りが違う時だけ・窓に知らせる）。「次の作り直しは前の譜面に寄せない」（今の指示が
//   無い＝全部外した後に入れ直す時は既定で入）: 寄せると、入れ直した同じ振りの写しの合い方が前より下がった（確かめで 24/24→22/24）。
// 確かめ用の入口（main.js は触らない＝location.hash を自分で見る）: #wtest=<手順>[;<手順>…]（手順の結果は body の data-wtest に JSON）
//   clear＝全部外す（量のライン・自動の休みも）・add:<場所の一部>＝その読み込める物の全部を足す・pick:<場所の一部>＝最初の同じ振りの
//   グループと量のラインだけ足す・replace:<場所の一部>＝全部で置き換える・undo＝元に戻す・open:<場所の一部>＝窓を開いたままにする（画像に写す）・
//   dlg＝「全部外す」の窓を開いたままにする・ro＝作業ファイルに保存しない（先頭に書く）。例 #wtest=ro;clear;add:saved/;undo;open:saved/
import {S, $, fmt, timeOf, api, on, emit, commit, newId, rangeKey, motifForms, formColor, formLabel, undo, saveWork} from './store.js';
import {summary} from './inspector.js';
import {labelShort, amountShort} from './library.js';
import {draw} from './timeline.js';

let A = null;   // main.js から渡された口
const IO = {list: null, src: null, sel: new Set(), opt: {}, cur: null};   // 一覧・選んだ読み込む物の中身・選んだ指示の番号・入れる物・選んだ場所
const enc = encodeURIComponent;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const restText = ar => !ar || !ar.on ? '切' : '入（' + (ar.b == null ? '曲の7割あたり' : fmt(timeOf(ar.b))) + '）';

export function init(app) {
  A = app;
  const head = document.querySelector('#listPane .cardHead');
  if (head) {
    const ops = document.createElement('span'); ops.className = 'wioOps';
    ops.innerHTML = '<button id="wioLoad" title="控えた作業ファイル・履歴の版・前の形式の意思入れの表から、指示を選んで足す・置き換える（Ctrl+Z で戻せる）">読み込む…</button>'
      + '<button id="wioClear" title="付けた指示を全部外す（確かめてから・Ctrl+Z で戻せる）">全部外す</button>';
    head.appendChild(ops);
  }
  document.body.appendChild(dialog('wioClearDlg', '付けた指示を全部外す', 'wioClearBody'));
  document.body.appendChild(dialog('wioLoadDlg', '指示を読み込む', 'wioLoadBody', '<span class="sub" id="wioLoadSub"></span>'));
  $('wioLoad').onclick = openLoad;
  $('wioClear').onclick = openClear;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { close('wioClearDlg'); close('wioLoadDlg'); } });
  on('work', () => { if (S.D && IO.D !== S.D) { IO.D = S.D; IO.list = null; IO.src = null; close('wioLoadDlg'); close('wioClearDlg'); } });
  if (location.hash.startsWith('#wtest')) selfTest();
}

function dialog(id, title, body, extra = '') {
  const d = document.createElement('div');
  d.id = id; d.className = 'modal wioModal';
  d.innerHTML = `<div class="dlg wioDlg"><div class="dlgHead"><b>${title}</b>${extra}<button data-close="${id}">閉じる</button></div><div class="dlgBody" id="${body}"></div></div>`;
  d.addEventListener('mousedown', e => { if (e.target === d) close(id); });
  d.querySelector('[data-close]').onclick = () => close(id);
  return d;
}
const close = id => { const d = $(id); if (d) d.style.display = 'none'; };
const show = id => { $(id).style.display = 'flex'; };

// ---- 全部外す ----
function openClear() {
  if (!S.D) return;
  const W = S.W, nr = W.ranges.length, nl = W.line.length, ar = W.auto_rest && W.auto_rest.on;
  $('wioClearBody').innerHTML = `
   <p>今付けている物: 区間の指示 <b>${nr}</b> 個・量のラインの点 <b>${nl}</b> 個・自動の休み ${restText(W.auto_rest)}</p>
   <label class="ck"><input type="checkbox" id="wioCR" ${nr ? 'checked' : 'disabled'}> 区間の指示を外す（${nr} 個・同じ振り・案・そのまま残す も）</label>
   <label class="ck"><input type="checkbox" id="wioCL" ${nl ? 'checked' : 'disabled'}> 量のラインも外す（${nl} 点）</label>
   <label class="ck"><input type="checkbox" id="wioCA" ${ar ? '' : 'disabled'}> 自動の休みも切る</label>
   <label class="ck"><input type="checkbox" id="wioCF" checked> 次の作り直しは「全部作り直す」をおすすめにする（作り直す時に聞く窓で選んだ状態にする）</label>
   <div class="hint">ライブラリ・量の目安（曲の設定）はそのまま。外した後も Ctrl+Z（↶）で戻せる。前の指示を控えておきたい時は、先に out/saved/ へ作業ファイルを写しておくと「読み込む…」から選んで入れ直せる（履歴の版からも入れ直せる）。</div>
   <div class="bar act"><button class="main" id="wioCGo" ${nr || nl || ar ? '' : 'disabled'}>外す</button><button id="wioCNo">やめる</button></div>`;
  $('wioCNo').onclick = () => close('wioClearDlg');
  $('wioCGo').onclick = () => clearAll({ranges: $('wioCR').checked, line: $('wioCL').checked, rest: $('wioCA').checked, fresh: $('wioCF').checked});
  show('wioClearDlg');
}
export function clearAll(o) {
  const n = {r: o.ranges ? S.W.ranges.length : 0, l: o.line ? S.W.line.length : 0};
  commit(W => {
    if (o.ranges) W.ranges = [];
    if (o.line) W.line = [];
    if (o.rest) W.auto_rest = {on: false, b: W.auto_rest ? W.auto_rest.b : null};
  });
  if (o.ranges) { S.edit = null; S.panel = {}; }
  if (o.fresh) { S.freshNext = true; emit('freshNext', true); }
  close('wioClearDlg'); draw();
  emit('status', `指示を外した（区間 ${n.r} 個・量のラインの点 ${n.l} 個${o.rest ? '・自動の休み' : ''}）。Ctrl+Z で戻せる` + (o.fresh ? '。次の作り直しは「全部作り直す」がおすすめ' : ''));
  return n;
}

// ---- 読み込む ----
async function openLoad() {
  if (!S.file) return;
  show('wioLoadDlg');
  $('wioLoadBody').innerHTML = '<p class="sub">読み込める物を探している…</p>';
  try { IO.list = await api('GET', '/api/workio/sources?file=' + enc(S.file)); }
  catch (e) { $('wioLoadBody').innerHTML = `<p class="bad">読み込める物の一覧を取れなかった: ${esc(e.message)}</p>`; return; }
  $('wioLoadSub').textContent = `${S.song}・${IO.list.sources.length} 個`;
  renderLoad();
}
function srcRow(e) {
  const extra = [e.line ? `量のライン ${e.line} 点` : '', e.auto_rest ? '自動の休み' : '', e.library ? 'ライブラリ' : '', e.amount ? '量の目安' : ''].filter(Boolean).join('・');
  const g = e.groups.length ? `同じ振り ${e.groups.map(esc).join('・')}` : '';
  return `<tr class="wioSrc${IO.cur === e.src ? ' sel' : ''}" data-src="${esc(e.src)}">
    <td>${esc(e.kind_text)}${e.same > 1 ? `<span class="sub">（同じ中身 ${e.same} 版）</span>` : ''}</td>
    <td title="${esc(e.src)}">${esc(e.kind === 'history' ? (e.title || e.vid) : e.where + '/' + e.name)}</td>
    <td>${esc(e.at.slice(0, 16))}</td><td class="num">${e.n}</td><td>${[g, extra].filter(Boolean).join('／') || '<span class="sub">—</span>'}</td></tr>`;
}
function renderLoad() {
  const L = IO.list;
  const rows = L.sources.length ? `<table class="wioTbl"><tr><th>種類</th><th>どこ・どの版</th><th>いつ</th><th class="num">指示</th><th>ほか</th></tr>${L.sources.map(srcRow).join('')}</table>`
    : `<p class="hint">この曲の読み込める物が無い（out/saved/ の下の ${esc(L.song)}.*.automap.json・${esc(L.song)}.intent.json、out/${esc(L.song)}.intent.json、履歴の版）。</p>`;
  $('wioLoadBody').innerHTML = `<div class="wioSrcs">${rows}</div><div id="wioPick"></div>`;
  $('wioLoadBody').querySelectorAll('tr.wioSrc').forEach(tr => tr.onclick = () => pickSource(tr.dataset.src));
  if (IO.src && IO.src.src === IO.cur) renderPick();
}
export async function pickSource(src) {
  IO.cur = src;
  $('wioLoadBody').querySelectorAll('tr.wioSrc').forEach(tr => tr.classList.toggle('sel', tr.dataset.src === src));
  $('wioPick').innerHTML = '<p class="sub">読んでいる…</p>';
  try { IO.src = await api('GET', `/api/workio/source?file=${enc(S.file)}&src=${enc(src)}`); }
  catch (e) { $('wioPick').innerHTML = `<p class="bad">読めなかった: ${esc(e.message)}</p>`; return; }
  IO.src.ranges.forEach((r, i) => { r.id = i + 1; });
  IO.sel = new Set(IO.src.ranges.map(r => r.id));   // 既定は全部
  IO.opt = {line: IO.src.line.length > 0, rest: false, library: false, amount: false, fresh: !S.W.ranges.length};   // 今の指示が無い（全部外した後に入れ直す）時は、次の作り直しを寄せない
  renderPick();
}
// 読み込む物の中の同じ振りの形（store.motifForms を読み込む物の指示で数える）
function formsOf(ranges) { const keep = S.W; S.W = {ranges}; try { return motifForms(); } finally { S.W = keep; } }
const groupOf = r => (r.set.motif && r.set.motif.group && !r.set.rest) ? r.set.motif.group : null;
function renderPick() {
  const s = IO.src, MF = formsOf(s.ranges), have = new Set(S.W.ranges.map(rangeKey));
  const rs = s.ranges.slice().sort((a, b) => a.b0 - b.b0 || a.id - b.id);
  const fchip = f => f ? `<span class="chip form" style="background:${formColor(f)}">${f.link ? '→ ' : ''}${esc(formLabel(f))}</span>` : '';
  const items = rs.map(r => { const f = MF.byId.get(r.id), g = groupOf(r), dup = have.has(rangeKey(r));
    return `<label class="wioItem${dup ? ' dup' : ''}"${f ? ` style="border-left:4px solid ${formColor(f)}"` : ''}>
      <input type="checkbox" data-r="${r.id}" ${IO.sel.has(r.id) ? 'checked' : ''}>
      <span class="when">${fmt(timeOf(r.b0))}〜${fmt(timeOf(r.b1))}<span class="sub">（拍 ${+r.b0.toFixed(2)}〜${+r.b1.toFixed(2)}）</span></span>
      <span class="chips">${fchip(f)}${summary(r.set).filter(t => !(g && t.startsWith('同じ振り'))).map(t => `<span class="chip">${esc(t)}</span>`).join('')}
      ${g ? '<span class="sub">（グループごとに選ぶ）</span>' : ''}${dup ? '<span class="sub">（今も同じ指示がある＝足さない）</span>' : ''}</span></label>`; }).join('');
  const curGroups = new Set(S.W.ranges.map(groupOf).filter(Boolean));
  const clash = [...new Set(s.ranges.filter(r => IO.sel.has(r.id) && !have.has(rangeKey(r))).map(groupOf).filter(g => g && curGroups.has(g)))];
  const opt = (k, label, val, has = true) => `<label class="ck"><input type="checkbox" data-o="${k}" ${IO.opt[k] ? 'checked' : ''} ${has ? '' : 'disabled'}> ${label}<span class="sub">（${val}）</span></label>`;
  $('wioPick').innerHTML = `
   <div class="wioHead"><b>${esc(s.kind_text)} ${esc(s.name)}</b> の中身<span class="sub">（指示 ${s.ranges.length} 個・選んでいる ${IO.sel.size} 個）</span>
     <button id="wioAll">全部選ぶ</button><button id="wioNone">全部やめる</button></div>
   ${s.grid_note ? `<div class="wioNote${s.regrid ? ' warn' : ''}">${esc(s.grid_note)}</div>` : ''}
   <div class="wioItems">${items || '<p class="hint">区間の指示は無い。</p>'}</div>
   <div class="wioOpts">
    ${opt('line', '量のライン（今のラインと入れ替える）', s.line.length ? s.line.length + ' 点' : '無し＝入れると今のラインを消す', true)}
    ${opt('rest', '自動の休み', restText(s.auto_rest))}
    ${opt('library', 'ライブラリの設定', labelShort(s.library))}
    ${opt('amount', '量の目安', amountShort(s.amount))}
   </div><div class="wioOpts">
    ${opt('fresh', '次の作り直しは「全部作り直す」をおすすめに', '作り直す時に聞く窓で「全部作り直す」を選んだ状態にする。入れ直した指示を前と同じに効かせる時はこれ')}
   </div>
   ${clash.length ? `<div class="wioNote warn">同じ振りのグループ「${clash.map(esc).join('」「')}」は今の指示にもある＝足すと1つのグループになる（手本と写しが混ざる）。今の物を消してから足すか、置き換える。</div>` : ''}
   <div class="hint">足す＝今の指示はそのままで、選んだ指示を足す。置き換える＝今の区間の指示を全部外してから入れる。量のライン・自動の休み・ライブラリ・量の目安は、チェックした物だけ今の物と入れ替える。どちらも Ctrl+Z で戻せる。</div>
   <div class="bar act"><button class="main" id="wioAdd">選んだ物を足す</button><button id="wioRep">置き換える</button></div>`;
  const box = $('wioPick');
  box.querySelectorAll('input[data-r]').forEach(x => x.onchange = () => toggle(+x.dataset.r, x.checked));
  box.querySelectorAll('input[data-o]').forEach(x => x.onchange = () => { IO.opt[x.dataset.o] = x.checked; });
  $('wioAll').onclick = () => { IO.sel = new Set(s.ranges.map(r => r.id)); renderPick(); };
  $('wioNone').onclick = () => { IO.sel = new Set(); renderPick(); };
  $('wioAdd').onclick = () => apply('add');
  $('wioRep').onclick = () => { if (S.W.ranges.length && !confirm(`今の区間の指示 ${S.W.ranges.length} 個を外して、選んだ ${IO.sel.size} 個を入れます。よいですか？（Ctrl+Z で戻せる）`)) return; apply('replace'); };
}
// 同じ振りは、グループの全部（形に付いた指示はそれぞれ）をまとめて選ぶ・やめる
function toggle(id, on_) {
  const r = IO.src.ranges.find(q => q.id === id), g = r && groupOf(r);
  const ids = g ? IO.src.ranges.filter(q => groupOf(q) === g).map(q => q.id) : [id];
  ids.forEach(i => on_ ? IO.sel.add(i) : IO.sel.delete(i));
  renderPick();
}
export function apply(mode) {
  const s = IO.src; if (!s) return null;
  const pick = s.ranges.filter(r => IO.sel.has(r.id)), o = IO.opt;
  let added = 0, same = 0, removed = 0;
  commit(W => {
    if (mode === 'replace') { removed = W.ranges.length; W.ranges = []; }
    const have = new Set(W.ranges.map(rangeKey));
    pick.forEach(r => { const k = rangeKey(r); if (have.has(k)) { same++; return; } have.add(k);
      W.ranges.push({id: newId(), b0: r.b0, b1: r.b1, set: JSON.parse(JSON.stringify(r.set))}); added++; });
    if (o.line) W.line = s.line.map(k => ({b: k.b, k: k.k, smooth: !!k.smooth}));
    if (o.rest) W.auto_rest = Object.assign({on: false, b: null}, s.auto_rest);
    if (o.library) W.library = s.library || null;
    if (o.amount) W.amount = s.amount && s.amount.mode && s.amount.mode !== 'auto' ? s.amount : null;
  });
  if (mode === 'replace') { S.edit = null; S.panel = {}; }
  if (o.fresh) { S.freshNext = true; emit('freshNext', true); }
  close('wioLoadDlg'); draw();
  const more = [o.line ? '量のライン' : '', o.rest ? '自動の休み' : '', o.library ? 'ライブラリ' : '', o.amount ? '量の目安' : ''].filter(Boolean);
  emit('status', `${s.name} から指示を${mode === 'replace' ? `置き換えた（外した ${removed} 個・` : '足した（'}入れた ${added} 個${same ? `・同じ指示が今もあって足さなかった ${same} 個` : ''}${more.length ? '・' + more.join('・') + 'も入れた' : ''}）。Ctrl+Z で戻せる` + (o.fresh ? '。次の作り直しは「全部作り直す」がおすすめ' : ''));
  return {added, same, removed};
}

// ---- 確かめ用（#wtest=…） ----
async function selfTest() {
  const steps = decodeURIComponent(location.hash.replace(/^#wtest=?/, '')).split(';').filter(Boolean);
  const out = [];
  const put = () => { document.body.dataset.wtest = JSON.stringify(out); };
  for (let i = 0; i < 200 && !(S.D && S.file); i++) await sleep(100);
  await sleep(300);
  const state = () => ({ranges: S.W.ranges.length, line: S.W.line.length, rest: !!(S.W.auto_rest && S.W.auto_rest.on),
                        groups: [...new Set(S.W.ranges.map(groupOf).filter(Boolean))]});
  out.push({step: 'start', file: S.file, ...state()}); put();
  const find = async part => { IO.list = await api('GET', '/api/workio/sources?file=' + enc(S.file));
    const e = IO.list.sources.find(q => q.src.includes(part)); if (!e) throw new Error('無い: ' + part); return e; };
  try {
    for (const st of steps) {
      const [op, arg] = st.split(':');
      if (op === 'ro') { S.readonly = true; continue; }
      if (op === 'clear') { const n = clearAll({ranges: true, line: true, rest: true, fresh: true}); out.push({step: st, removed: n, ...state()}); }
      if (op === 'undo') { undo(); out.push({step: st, ...state()}); }
      if (op === 'dlg') { openClear(); out.push({step: st}); put(); continue; }
      if (op === 'add' || op === 'pick' || op === 'replace' || op === 'open') {
        const e = await find(arg || '');
        show('wioLoadDlg'); renderLoad(); await pickSource(e.src);
        if (op === 'pick') { const g = IO.src.ranges.map(groupOf).find(Boolean);
          IO.sel = new Set(IO.src.ranges.filter(r => groupOf(r) === g).map(r => r.id)); IO.opt = {line: true}; renderPick(); }
        if (op === 'open') { out.push({step: st, src: e.src, n: IO.src.ranges.length, sel: IO.sel.size, regrid: IO.src.regrid, note: IO.src.grid_note, sources: IO.list.sources.map(q => q.src)}); put(); continue; }
        const r = apply(op === 'replace' ? 'replace' : 'add');
        out.push({step: st, src: e.src, ...r, ...state()});
      }
      if (!S.readonly) await saveWork();
      put();
    }
  } catch (e) { out.push({step: 'error', error: String(e && e.message || e)}); }
  put();
}
