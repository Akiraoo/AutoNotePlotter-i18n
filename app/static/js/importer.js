// 新しい曲の取り込み（app/importer.py）の画面。main.js が init(app) を呼ぶ。
// 上の列の「＋ 曲を取り込む」→ 音源を選ぶ（この PC のファイルの窓か、場所を文字で）→ 曲名・名前・BPM 等とカバー画像を確かめる →
// 取り込む（音を分ける・曲の解析・元のプロジェクト・基本設定を待つ・最初の譜面を段ごとに）→ 終わったら曲の一覧を読み直して開く。
// 「取り込む」を押すと作業は始まり、窓はすぐ基本設定（型のライブラリ＝library.js の filterPanel と同じ欄）になる（docs/アプリ仕様.md 17 節）。
// 決めると POST /api/import/settings → 待つ段で止まっていればすぐ最初の譜面へ。最初の譜面の段が始まるまでは「設定を変える」で決め直せる。
// 初めの値は前に基本設定で決めた物（ブラウザに覚える）、無ければ新しい曲の既定（library_use.DEFAULT）。
// 取り込みの途中で窓を閉じても続く（ボタンに進み具合・設定を待っている時は目立つ形）。画面を開き直した時は動いている取り込みを
// /api/jobs から拾い、決めていなければ基本設定、決めていれば進み具合を出し直す。
import {$, api, S, lsGet, lsSet} from './store.js';
import {filterPanel, libraryInfo, labelShort} from './library.js';

const WAIT = '基本設定を待つ';   // 段の名前（app/importer.py の WAIT_LABEL と同じ）
const STEPS = ['音を分ける', '曲の解析', '元のプロジェクトを作る', WAIT, '最初の譜面を作る'];
const LS_LIB = 'automap-import-library';   // 前に基本設定で決めた型のライブラリ {library: 絞り込み, v: 2}（前の null＝今の型は新しい曲の既定に）
let A = null;            // main.js から渡された口（loadSongs・openSong・status・showReport・reportHTML・esc）
let P = null;            // 読んだ音源（/api/import/probe の答え）
let X = null;            // 今の名前の同じ名前の物（conflicts）
let CP = null;           // カバー画像の選び方（coverPicker・選んだ画像は CP.get()＝null はなし）
let job = null;         // 動いている（見ている）取り込み {id, song}（fake＝#iwtest の作り物）
let J = null;            // 最後に聞いた取り込みの様子（/api/job の答え。settings＝届いた基本設定・settings_locked＝もう変えられない）
let LIB = null, LIB_FOR = null;   // 基本設定の窓の絞り込みの欄（library.js の filterPanel）と、欄を読んだ取り込みの id
let FAKE = null;         // #iwtest の作り物の取り込みの様子
let timer = 0, nameTimer = 0;
const escA = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const mmss = s => s == null ? '?' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
// 基本設定の段の様子: 段がある・まだ決め直せる（最初の譜面の段より前）・まだ決めていない・待つ段で止まっている
const hasWait = j => !!j && (j.steps || []).includes(WAIT);
const canSet = j => hasWait(j) && j.state === 'running' && !j.settings_locked && j.step <= j.steps.indexOf(WAIT);
const needSet = j => canSet(j) && !j.settings;
const atWait = j => !!j && j.state === 'running' && (j.steps || [])[j.step] === WAIT;
const setShort = s => s ? (s.short || labelShort(s.library)) : '';

function build() {
  const d = document.createElement('div');
  d.id = 'impDlg'; d.className = 'modal imp';
  d.innerHTML = `<div class="dlg">
  <div class="dlgHead"><b>曲を取り込む</b><span class="sub" id="impHeadSub"></span><button id="impClose">閉じる</button></div>
  <div class="dlgBody">
    <section id="impPick">
      <div class="impRow"><input id="impPath" spellcheck="false" placeholder="音源のファイルの場所（flac・wav・mp3・ogg・m4a）">
        <button id="impBrowse" title="この PC のファイルの窓で選ぶ">選ぶ…</button><button id="impRead" title="入れた場所の音源を読む">読む</button></div>
      <div class="sub">「選ぶ…」でファイルの窓が開く（後ろに隠れたらタスクバーを見る）。場所を貼り付けて「読む」でもよい（エクスプローラーの「パスのコピー」）。</div>
      <div id="impPickMsg" class="impMsg"></div>
    </section>
    <section id="impConfirm" hidden>
      <div id="impInfo" class="impInfo"></div>
      <div class="impGrid">
        <label for="impName">名前</label><div><input id="impName" spellcheck="false"><div class="sub" id="impNameNote">ファイル名と分けた音のフォルダ名（out/名前.nlmf・cache/名前/）</div></div>
        <label for="impTitle">曲名</label><input id="impTitle">
        <label for="impArtist">アーティスト</label><input id="impArtist">
        <label for="impBpm">BPM</label><div class="impNums"><input id="impBpm" inputmode="decimal" placeholder="自動">
          <label for="impLead">無音追加</label><input id="impLead" inputmode="numeric" placeholder="自動"> ms
          <span class="sub">空なら曲の解析の推定（後から NLM で直せる）</span></div>
        <label>カバー画像</label><div><div id="impCovers" class="impCovers"></div></div>
      </div>
      <div id="impExists"></div>
      <div class="sub">「取り込む」を押すとすぐ作業を始め、窓は基本設定（最初の譜面の型のライブラリ）になる。音を分ける・曲の解析の間に決める。</div>
      <div class="impFoot"><span class="sub" id="impEta"></span><button id="impBack">音源を選び直す</button><button id="impStart" class="main">取り込む</button></div>
    </section>
    <section id="impSet" hidden>
      <div id="impMini" class="impMini"></div>
      <div class="impSetHead"><b>基本設定: 型のライブラリ</b><span class="sub">最初の譜面の振りの型を、どの譜面から取るか（使うノーツの並びの範囲）</span></div>
      <div id="impLib"></div>
      <div class="sub">量の目安（1秒のノーツ）は自動のまま。後で上の「ライブラリ」の窓で変えられる（譜面の★はほぼノーツの量で決まり、ここで選ぶのは型の範囲）。</div>
      <div class="impFoot"><span class="sub" id="impSetMsg"></span>
        <button id="impSetDefault" title="新しく取り込む曲の既定（ランク譜面・時期は曲ごとに自動・既定の★の帯・Expert／Expert+）">新しい曲の既定に戻す</button>
        <button id="impSetCancel">取り込みをやめる</button><button id="impSetOk" class="main">この設定で作る</button></div>
    </section>
    <section id="impRun" hidden>
      <div id="impRunHead" class="impRunHead"></div>
      <ol id="impSteps" class="impSteps"></ol>
      <div id="impLast" class="impLast"></div>
      <div id="impRunSet" class="impRunSet" hidden><span id="impRunSetText"></span><button id="impChange" hidden>設定を変える</button></div>
      <pre id="impLog" class="impLog" hidden></pre>
      <div class="impFoot"><span class="sub" id="impRunNote">窓を閉じても取り込みは続く（上のボタンに進み具合）</span>
        <button id="impLogBtn">記録を見る</button><button id="impCancel">やめる</button><button id="impRetry" hidden>設定に戻る</button>
        <button id="impOpen" class="main" hidden>開く</button></div>
    </section>
  </div></div>`;
  document.body.appendChild(d);
  CP = coverPicker($('impCovers'), {prefix: 'impCov', say: (m, bad) => A.status(m, bad)});
  d.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Escape') close(); if (e.key === 'Enter' && e.target.id === 'impPath') read(); });
  d.addEventListener('mousedown', e => { if (e.target === d) d.dataset.down = '1'; });
  d.addEventListener('click', e => { if (e.target === d && d.dataset.down === '1') close(); d.dataset.down = ''; });
  $('impClose').onclick = close;
  $('impBrowse').onclick = browse;
  $('impRead').onclick = () => read();
  $('impBack').onclick = () => show('pick');
  $('impStart').onclick = start;
  $('impName').oninput = () => { clearTimeout(nameTimer); nameTimer = setTimeout(checkName, 300); };
  $('impBpm').oninput = $('impLead').oninput = eta;
  $('impLogBtn').onclick = () => { const l = $('impLog'); l.hidden = !l.hidden; $('impLogBtn').textContent = l.hidden ? '記録を見る' : '記録を隠す'; if (!l.hidden) l.scrollTop = l.scrollHeight; };
  $('impCancel').onclick = cancel;
  $('impRetry').onclick = retry;
  $('impOpen').onclick = () => { if (job) finish(job.song); };
  $('impSetOk').onclick = decideSettings;
  $('impSetDefault').onclick = () => { if (LIB && LIB.info) LIB.set(LIB.info.default); };
  $('impSetCancel').onclick = cancel;
  $('impChange').onclick = () => openSettings(true);
}

function show(which) {
  $('impDlg').style.display = 'flex';
  ['pick', 'confirm', 'set', 'run'].forEach(k => { $('imp' + k[0].toUpperCase() + k.slice(1)).hidden = k !== which; });
  $('impDlg').classList.toggle('wide', which === 'set');
  $('impHeadSub').textContent = which === 'run' ? '' : which === 'set' ? '最初の譜面の基本設定を決めて「この設定で作る」（その間も音を分ける・解析は進む）'
    : which === 'confirm' ? '中身を確かめて「取り込む」' : '音源を選ぶ';
  if (which === 'pick') setTimeout(() => $('impPath').focus(), 0);
}
function close() { $('impDlg').style.display = 'none'; }
function retry() {   // 失敗した・やめた後: 設定に戻る（済んだ段の結果ができているかもしれないので、同じ名前の物を調べ直す）
  job = null; J = null;
  show(P ? 'confirm' : 'pick');
  if (P) checkName();
}
function open() {
  if (job && job.ended) { retry(); return; }
  if (job) { if (needSet(J)) openSettings(); else { show('run'); runView(J); } poll(); return; }
  show(P ? 'confirm' : 'pick');
}
function msg(id, text, bad) { const m = $(id); m.textContent = text || ''; m.classList.toggle('bad', !!bad); }

// ---- 音源を選ぶ ----
async function browse() {
  msg('impPickMsg', 'ファイルの窓を開いている…（選ぶか閉じるまで待つ）');
  $('impBrowse').disabled = true;
  try {
    const r = await api('POST', '/api/import/pick', {kind: 'audio'});
    if (!r.path) { msg('impPickMsg', ''); return; }
    $('impPath').value = r.path;
    await read();
  } catch (e) { msg('impPickMsg', e.message, true); }
  finally { $('impBrowse').disabled = false; }
}
async function read(path) {
  const p = (path ?? $('impPath').value).trim();
  if (!p) { msg('impPickMsg', '音源の場所を入れるか「選ぶ…」', true); return; }
  msg('impPickMsg', '音源を読んでいる…');
  try {
    P = await api('POST', '/api/import/probe', {path: p});
    $('impPath').value = P.path;
    msg('impPickMsg', '');
    fill();
    show('confirm');
  } catch (e) { P = null; msg('impPickMsg', e.message, true); }
}

// ---- 確かめる ----
function fill() {
  $('impInfo').innerHTML = `<b>${escA(P.file)}</b><span>長さ ${mmss(P.seconds)}</span><span>${escA(P.format.toUpperCase())}${P.sr ? '・' + (P.sr / 1000) + 'kHz' : ''}${P.channels ? '・' + P.channels + 'ch' : ''}</span>`
    + (P.tagged ? '<span class="sub">曲名・アーティストは音源のタグから</span>' : '<span class="sub">タグが無いので曲名はファイル名から</span>')
    + (P.ffmpeg ? '<span class="sub">この形式は ffmpeg で読む</span>' : '');
  $('impName').value = P.name; $('impTitle').value = P.title; $('impArtist').value = P.artist || '';
  $('impBpm').value = ''; $('impLead').value = '';
  CP.set(P.covers || [], (P.covers || [])[0] || null);
  X = P.exists; exists();
}
// ---- カバー画像の選び方（取り込みの窓と、Beat Saber に書き出す窓＝bsexport.js で使い回す・2026-11-09 利用者「書き出す窓から変えられるように」） ----
// 候補の画像の札（選んでいる物に枠）・「なし」・「別の画像…」（この PC のファイルの窓＝/api/import/pick）・「貼り付け」（クリップボード・Ctrl+V は
// onPasteImage）。札の画像は /api/import/cover?path=（サーバーが見せてよいと覚えた画像だけ＝候補・窓で選んだ物・貼り付けた物）。
// opts: prefix＝「別の画像」「貼り付け」の札の id の頭（`${prefix}More`・`${prefix}Paste`）・none＝「なし」の札を出すか（真偽か関数・既定は出す）・
//   api＝サーバーへの口（確かめの作り物に替えられる）・url(c)・name(c)＝札の画像と名前・pick(c)＝選んだ時（async 可・false＝選び替えない・
//   {covers, sel}＝その並びと選んだ物で出し直す＝サーバーが写した先の場所に替わる時・ほか＝c を選ぶ）・say(文, bad)＝知らせ・
//   locked()＝真なら押せない。→ {set(候補, 選んだ物), get, list, paste(blob), render}
const coverName = c => { const n = String(c).split(/[\\/]/).pop(); return n.startsWith('貼り付け-') ? '貼り付けた画像' : n; };
export function coverPicker(host, o = {}) {
  const prefix = o.prefix || 'cov', call = o.api || api, say = o.say || (() => {});
  const url = o.url || (c => `/api/import/cover?path=${encodeURIComponent(c)}`), name = o.name || coverName;
  const st = {covers: [], sel: null, busy: false};
  function render() {
    const none = typeof o.none === 'function' ? o.none() : o.none !== false;
    host.innerHTML = st.covers.map(c => `<button class="impCov${c === st.sel ? ' on' : ''}" data-c="${escA(c)}" title="${escA(c)}">
        <img src="${escA(window.anpUrl(url(c)))}" alt=""><span>${escA(name(c))}</span></button>`).join('')
      + (none ? `<button class="impCov none${st.sel ? '' : ' on'}" data-c=""><span>なし</span></button>` : '')
      + `<button class="impCov more" id="${prefix}More" title="ほかの画像を選ぶ（jpg・png）"><span>別の画像…</span></button>
    <button class="impCov more" id="${prefix}Paste" title="クリップボードの画像を使う（画面キャプチャ等・Ctrl+V でもよい）。真ん中から正方形に切り出し、1024px 以下の jpg にする"><span>貼り付け</span><span>（Ctrl+V）</span></button>`;
    host.querySelectorAll('.impCov[data-c]').forEach(b => { b.onclick = () => choose(b.dataset.c || null); });
    host.querySelector(`#${prefix}More`).onclick = more;
    host.querySelector(`#${prefix}Paste`).onclick = fromClipboard;
    const off = st.busy || !!(o.locked && o.locked());
    host.querySelectorAll('button').forEach(b => { b.disabled = off; });
  }
  async function choose(c, add) {   // add: 'front'＝候補の先頭へ（貼り付け）・'new'＝無ければ先頭に足す（別の画像）
    if (st.busy || (o.locked && o.locked())) return false;
    if (c === st.sel) return true;
    st.busy = true; render();
    try {
      const r = o.pick ? await o.pick(c) : true;
      if (r === false) return false;
      if (r && typeof r === 'object') { st.covers = [...r.covers]; st.sel = r.sel ?? null; return true; }
      if (c && add === 'front') st.covers = [c, ...st.covers.filter(x => x !== c)];
      else if (c && add === 'new' && !st.covers.includes(c)) st.covers.unshift(c);
      st.sel = c;
      return true;
    } catch (e) { say(e.message, true); return false; }
    finally { st.busy = false; render(); }
  }
  async function more() {
    try { const r = await call('POST', '/api/import/pick', {kind: 'image'}); if (r.path) await choose(r.path, 'new'); }
    catch (e) { say(e.message, true); }
  }
  async function paste(blob) {
    try {
      const r = await squareJpeg(blob);
      const {path} = await call('POST', '/api/import/paste', {data: r.data});
      if (!(await choose(path, 'front'))) return null;
      say(`クリップボードの画像をカバーにした（${r.w}×${r.h}${r.w !== r.h ? ' → 真ん中から正方形に切り出し' : ''}・${r.size}px の jpg）`);
      return path;
    } catch (e) { say('貼り付けた画像を使えなかった: ' + e.message, true); return null; }
  }
  async function fromClipboard() {
    try {
      const items = await navigator.clipboard.read();
      for (const it of items) {
        const t = it.types.find(x => x.startsWith('image/'));
        if (t) return paste(await it.getType(t));
      }
      say('クリップボードに画像が無い（画面キャプチャ等でコピーしてから）', true);
    } catch (e) { say('クリップボードを読めなかった。窓の中で Ctrl+V を押して貼り付ける（' + e.message + '）', true); }
  }
  return {set(covers, sel) { st.covers = [...covers]; st.sel = sel ?? null; render(); }, get: () => st.sel, list: () => [...st.covers], paste, render};
}
// ---- カバー画像の貼り付け（2026-11-03 利用者「クリップボードに上がっている画像をそのまま取り込む・画面キャプチャから」） ----
// 取り込みの窓の確かめの段で Ctrl+V（画像が入っている時だけ受ける＝文字の貼り付けはそのまま）か「貼り付け」のボタン。
// Beat Saber のカバーは正方形で出るので真ん中から正方形に切り出し、1 辺 1024px 以下の jpg にして送る（/api/import/paste・
// サーバーは一時的な場所に書き、候補に足す）。確かめは #pastetest（作り物の画像を貼る）
const COVER_MAX = 1024;
export async function squareJpeg(blob) {
  const bmp = await createImageBitmap(blob);
  const s = Math.min(bmp.width, bmp.height), size = Math.min(COVER_MAX, s);
  const cv = document.createElement('canvas'); cv.width = cv.height = size;
  const g = cv.getContext('2d'); g.fillStyle = '#000'; g.fillRect(0, 0, size, size);
  g.drawImage(bmp, (bmp.width - s) / 2, (bmp.height - s) / 2, s, s, 0, 0, size, size);
  return {data: cv.toDataURL('image/jpeg', 0.92), w: bmp.width, h: bmp.height, size};
}
// Ctrl+V の画像を受ける（active() が真の時だけ・画像が無い＝文字の貼り付け（名前・曲名の欄）はそのまま）
export function onPasteImage(active, fn) {
  document.addEventListener('paste', e => {
    if (!active()) return;
    const it = [...(e.clipboardData ? e.clipboardData.items : [])].find(x => x.kind === 'file' && x.type.startsWith('image/'));
    if (!it) return;
    e.preventDefault();
    fn(it.getAsFile());
  });
}
const usePasted = blob => P ? CP.paste(blob) : null;
const confirming = () => $('impDlg') && $('impDlg').style.display === 'flex' && $('impConfirm') && !$('impConfirm').hidden;
onPasteImage(confirming, usePasted);
// 確かめ用の作り物の横長の画像（1600×900・真ん中に白い正方形）。bsexport.js の確かめも使う
export async function testImage() {
  const cv = document.createElement('canvas'); cv.width = 1600; cv.height = 900;
  const g = cv.getContext('2d'); g.fillStyle = '#c33'; g.fillRect(0, 0, 1600, 900); g.fillStyle = '#fff'; g.fillRect(350, 0, 900, 900);
  return new Promise(r => cv.toBlob(r, 'image/png'));
}
// 確かめ用（#pastetest）: 作り物の横長の画像を貼ったことにする → 候補の先頭が貼り付けた画像で選ばれているか
export async function pasteTest() {
  P = P || {covers: [], name: 'x'};
  const path = await usePasted(await testImage());
  return {path, selected: CP.get() === path, first: CP.list()[0] === path};
}

async function checkName() {
  const n = $('impName').value.trim();
  if (!n) { $('impNameNote').textContent = '名前が空'; $('impStart').disabled = true; return; }
  try { X = await api('POST', '/api/import/check', {name: n}); exists(); } catch (e) { $('impNameNote').textContent = e.message; }
}
function exists() {
  const n = $('impName').value.trim();
  $('impNameNote').innerHTML = X.name !== n ? `ファイル名には <b>${escA(X.name)}</b> を使う（使えない文字・「.」は _ に）` : 'ファイル名と分けた音のフォルダ名（out/名前.nlmf・cache/名前/）';
  const box = [];
  if (X.blocked) {
    const listed = S.songs.some(s => s.song === X.name);
    box.push(`<div class="impWarn bad">「${escA(X.name)}」はもう取り込んである（${X.results.map(escA).join('・')}）。上書きしないので、名前を変えるか一覧から開く。
      ${listed ? `<button id="impOpenOld">「${escA(X.name)}」を開く</button>` : ''}</div>`);
  }
  if (X.project) {
    const pj = X.project, other = pj.song && P && pj.song.replace(/\.[^.]*$/, '') !== P.file.replace(/\.[^.]*$/, '');
    box.push(`<div class="impWarn">元のプロジェクト <b>${escA(pj.file)}</b> がもうある（BPM ${pj.bpm ?? '?'}・無音追加 ${pj.lead ?? '?'} ms・マーカー ${pj.markers}${pj.song ? '・音源 ' + escA(pj.song) : ''}）→ 使い回す。
      ${other ? '<br><b>音源の名前が違う＝別の曲かも（名前を変える）</b>' : ''}
      <label class="impChk"><input type="checkbox" id="impRemake"> 作り直す（曲の解析からやり直す・前の物は out/old/ に控え）</label></div>`);
  }
  if (X.stems) {
    const st = X.stems, diff = P && st.seconds && Math.abs(st.seconds - P.seconds) > 0.5;
    box.push(`<div class="impWarn">分けた音がもうある（元の音源 ${escA(st.source)}・${mmss(st.seconds)}）→ 使い回す。${diff ? '<br><b>長さが違う＝別の曲かも（名前を変える）</b>' : ''}</div>`);
  }
  $('impExists').innerHTML = box.join('');
  if ($('impOpenOld')) $('impOpenOld').onclick = () => { close(); A.openSong(X.name); };
  if ($('impRemake')) $('impRemake').onchange = eta;
  eta();
}
function eta() {
  const remake = !!($('impRemake') && $('impRemake').checked), mk = !X.project || remake;
  $('impBpm').disabled = $('impLead').disabled = !mk;
  if (!mk) { $('impBpm').value = ''; $('impLead').value = ''; }
  const parts = [];
  if (!X.stems) parts.push('音を分ける 1 分');
  if (mk) parts.push('曲の解析 1 分');
  parts.push('最初の譜面 1 分');
  $('impEta').textContent = 'かかる時間の目安: ' + parts.join('・') + 'ほど';
  $('impStart').disabled = !!X.blocked || !$('impName').value.trim();
}

// ---- 取り込む ----
async function start() {
  if ($('impStart').disabled) return;
  $('impStart').disabled = true;
  const body = {path: P.path, name: $('impName').value.trim(), title: $('impTitle').value.trim(), artist: $('impArtist').value.trim(),
                bpm: $('impBpm').value.trim(), lead: $('impLead').value.trim(), cover: CP.get(), remake: !!($('impRemake') && $('impRemake').checked)};
  try {
    const r = await api('POST', '/api/import/start', body);
    job = {id: r.id, song: r.song};
    J = {id: r.id, kind: 'import', song: r.song, state: 'running', steps: STEPS, step: 0, started: Date.now() / 1000, log: ''};   // 最初の答えまでの仮
    badge(J); openSettings(true); poll();
  } catch (e) { A.status(e.message, true); $('impNameNote').textContent = e.message; $('impNameNote').classList.add('bad'); setTimeout(() => $('impNameNote').classList.remove('bad'), 4000); eta(); }
}

// ---- 基本設定（型のライブラリ） ----
const sameF = (a, b) => { const k = o => JSON.stringify(Object.keys(o || {}).sort().map(x => [x, o[x]])); return k(a) === k(b); };
function initialLib(info) {   // 決め直す時は今の設定、まだなら前に決めた物（ブラウザに覚えた）、無ければ新しい曲の既定
  if (J && J.settings) return J.settings.library;
  const m = lsGet(LS_LIB, null);
  let f = m && m.library ? m.library : info.default;
  // 時期の自動の前（v 無し）に覚えた物が前の既定（2020 年以降）のままなら、新しい既定（時期は曲ごとに自動）にする（2026-11-03）
  if (m && !m.v && info.legacy_default && sameF(f, info.legacy_default)) f = info.default;
  // 年は毎回「自動」（新しい決め方）から始める（2026-11-15 利用者「年数を選ぶのは既定は自動にしておいてくれ」）: 前に「年を選ぶ」で
  // 取り込んでいても、覚えた物の年は使わない（★の帯・難易度・頻度・難しさは覚えた物のまま）。前の決め方の自動（auto_v 無し）も新しい決め方に
  if (f) { f = Object.assign({}, f, {years: 'auto', auto_v: 2}); delete f.year_set; }
  return f;   // データベースが使えない PC でも決めた物（最初の譜面は止まる＝欄の上に知らせ）
}
async function openSettings(reload) {   // reload＝欄を今の設定（無ければ初めの値）で出し直す。無い時は前に開いた時の選びかけのまま
  show('set');
  miniView(J);
  msg('impSetMsg', '');
  $('impSetOk').textContent = J && J.settings ? 'この設定に変える' : 'この設定で作る';
  if (LIB && LIB_FOR === job.id && !reload) return;
  $('impSetOk').disabled = true;
  if (!LIB) LIB = filterPanel($('impLib'), {prefix: 'impLib', who: () => ({song: job ? job.song : ''})});   // 時期の自動は取り込む曲の名前で
  try { LIB.info = await libraryInfo(); }
  catch (e) { msg('impSetMsg', '型のライブラリを読めなかった: ' + e.message, true); LIB_FOR = null; return; }
  LIB.load(LIB.info, initialLib(LIB.info));
  LIB_FOR = job.id;
  $('impSetOk').disabled = false;
  if (job.fake) document.title = 'iwtest init=' + JSON.stringify(LIB.get());
}
async function decideSettings() {
  if (!job || !LIB || LIB_FOR !== job.id || $('impSetOk').disabled) return;
  const f = LIB.get(), again = !!(J && J.settings);
  $('impSetOk').disabled = true;
  try {
    let st;
    if (job.fake) { st = {library: f, short: labelShort(f)}; FAKE.settings = st; }
    else st = (await api('POST', '/api/import/settings', {id: job.id, library: f})).settings;
    lsSet(LS_LIB, {library: f, v: 2});   // 次に取り込む曲の初めの値（v 2＝時期の自動の後に決めた物）
    J.settings = st;
    badge(J); show('run'); runView(J);
    A.status(`基本設定: 型のライブラリ「${setShort(st)}」` + (again ? 'に変えた' : '')
             + (atWait(J) ? '。最初の譜面を作り始める' : '。曲の解析が終わり次第、最初の譜面を作る'));
    if (job.fake) document.title = `iwtest decided=${JSON.stringify(f)} run=${!$('impRun').hidden} badge=${$('importBtn').textContent}`;
    else poll();
  } catch (e) { msg('impSetMsg', e.message, true); poll(); }
  finally { $('impSetOk').disabled = false; }
}

// 段ごとの説明（その段がまだ何も書いていない時に出す）
const HINT = {'音源を手元に写す': 'NAS 等の上の音源は NLM が開いただけでは読めないので、分けた音のフォルダ（source）へ写している',
              '音を分ける': '歌・ドラム・ベース・その他の音に分けている（GPU で 1 分ほど・曲の解析も同時に進める）',
              '曲の解析': 'テンポの推定と構成の解析（30〜60 秒・音を分けるのと同時に進めている）',
              [WAIT]: '基本設定（型のライブラリ）を待っている', '最初の譜面を作る': '曲の流れの表と打点から最初の譜面を作っている（30 秒ほど）'};
// 今の段（記録の最後の「== 段の名前」より後ろ）の最後の行。音を分ける段は tools/separate.py の Progress が全体の割合と残りを 1 行で書き直す
// （「音を分ける 38%・残り約 0:35（8 回の計算のうち 3 回済み・4 回目 60%）」・前は Demucs の棒（tqdm）を読み替えていて、計算の回ごとに
// 100% と残り 0 をくり返した・2026-11-11 利用者）
function lastLine(log) {
  const segs = (log || '').split(/(?:^|\n)== ([^\n]*)\n?/);   // [前, 名前1, 中身1, 名前2, 中身2…]
  const label = segs.length > 1 ? segs[segs.length - 2] : '', body = segs[segs.length - 1];
  const ls = body.split(/[\r\n]+/).map(s => s.trim()).filter(s => s && !s.startsWith('$ '));
  return ls.length ? ls[ls.length - 1] : (HINT[label] || '');
}
// 裏で同時に動いている段（j.bg＝段の名前 → running・done・error・stopped・app/importer.py の _side_start）: まだその段に入っていなくても印を付ける
const BG_MARK = {running: 'now', done: 'done', error: 'bad'};
function stepsHTML(j) {   // 段の並び（済んだ ✓・今 ●・待っている ●（橙）・失敗 ×・まだ ・）
  const steps = j ? j.steps : STEPS, st = j ? j.state : 'running', at = j ? j.step : 0;
  return steps.map((s, i) => {
    const bg = j && j.bg && j.bg[s], later = (bg === 'running' && st !== 'running') ? 'todo' : (BG_MARK[bg] || 'todo');
    const k = st === 'done' || i < at ? 'done' : i === at ? (st !== 'running' ? 'bad' : s === WAIT && !j.settings ? 'wait' : 'now') : later;
    return `<li class="${k}"><span class="mk">${k === 'done' ? '✓' : k === 'now' || k === 'wait' ? '●' : k === 'bad' ? '×' : '・'}</span>${escA(s)}</li>`;
  }).join('');
}
function miniView(j) {   // 基本設定の窓の上の、段の進み具合（小さく）
  const el = j ? Math.round(j.took ?? (Date.now() / 1000 - j.started)) : 0;
  const note = atWait(j) && !j.settings ? '<span class="impMiniWait">解析まで済んだ。基本設定を待っている（決めるとすぐ最初の譜面を作る）</span>'
    : `<span class="sub impMiniLast">${escA(lastLine(j && j.log).slice(0, 120))}</span>`;
  $('impMini').innerHTML = `<div class="impMiniHead"><b>${escA(job ? job.song : '')}</b><span>を取り込んでいる</span><span class="sub">${mmss(el)}</span>${note}</div>
    <ol class="impSteps mini">${stepsHTML(j)}</ol>`;
}
function runView(j) {
  const st = j ? j.state : 'running';
  const el = j ? Math.round(j.took ?? (Date.now() / 1000 - j.started)) : 0;
  $('impRunHead').innerHTML = `<b>${escA(job ? job.song : '')}</b> を取り込んで${st === 'running' ? 'いる' : st === 'done' ? 'できた' : (j && j.cancel ? 'いたが、やめた' : 'いたが、失敗した')}`
    + `<span class="sub">${mmss(el)}</span>`;
  $('impSteps').innerHTML = stepsHTML(j);
  const last = j ? lastLine(j.log) : '';
  $('impLast').textContent = st === 'done' ? '' : last.slice(0, 160);
  $('impLast').classList.toggle('bad', st === 'error');
  const sw = !j || hasWait(j);   // 基本設定の段がある取り込み
  $('impRunSet').hidden = !sw;
  $('impRunSetText').innerHTML = j && j.settings ? `基本設定: 型のライブラリ <b>${escA(setShort(j.settings))}</b>` + (canSet(j) ? '<span class="sub">（最初の譜面の段までは変えられる）</span>' : '')
    : '基本設定: まだ決めていない';
  $('impChange').hidden = !canSet(j);
  $('impLog').textContent = j ? j.log : '';
  if (st === 'error' && $('impLog').hidden) $('impLogBtn').click();
  if (!$('impLog').hidden) $('impLog').scrollTop = $('impLog').scrollHeight;
  $('impCancel').hidden = st !== 'running';
  $('impRetry').hidden = st !== 'error';
  $('impOpen').hidden = st !== 'done';
  $('impRunNote').textContent = st === 'running' ? '窓を閉じても取り込みは続く（上のボタンに進み具合）' : st === 'done' ? '曲の一覧に入れた' : '';
}
function badge(j) {   // 上のボタン: 取り込み中は進み具合・まだ決めていなければ「基本設定がまだ」・待つ段で止まっていれば目立つ形（赤く点滅）
  const b = $('importBtn');
  const run = !!j && j.state === 'running', wait = run && needSet(j), stop = wait && atWait(j);
  b.classList.toggle('impBusy', run && !stop);
  b.classList.toggle('impWait', stop);
  b.textContent = !run ? '＋ 曲を取り込む' : stop ? `基本設定を待っている ${j.step + 1}/${j.steps.length}`
    : `取り込み中 ${j.step + 1}/${j.steps.length}…` + (wait ? '（基本設定がまだ）' : '');
  b.title = wait ? '押して最初の譜面の基本設定（型のライブラリ）を決める' : run ? '押して取り込みの進み具合を見る'
    : '新しい曲を取り込む（音を分ける・曲の解析・最初の譜面）';
}
async function poll() {
  clearTimeout(timer);
  if (!job) return;
  let j;
  if (job.fake) j = FAKE;
  else {
    try { j = await api('GET', '/api/job?id=' + job.id); }
    catch (e) { badge(null); job = null; J = null; A.status('取り込みの様子が分からなくなった（サーバーを起動し直した？）', true); return; }
  }
  J = j;
  badge(j);
  const shown = $('impDlg').style.display === 'flex';
  if (shown && !$('impSet').hidden) {
    if (canSet(j)) miniView(j);
    else {   // 最初の譜面を作り始めた・終わった・失敗した → 進み具合へ
      show('run'); runView(j);
      if (j.state === 'running') A.status('もう最初の譜面を作り始めたので、基本設定は変えられない（できた後で上の「ライブラリ」の窓で変える）');
    }
  } else if (shown && !$('impRun').hidden) runView(j);
  if (job.fake) return;
  if (j.state === 'running') { timer = setTimeout(poll, 1000); return; }
  if (j.state === 'done') {
    A.status(`「${job.song}」を取り込んだ（${mmss(j.took)}）`);
    const dlgOpen = $('impDlg').style.display === 'flex';
    await finish(job.song, j, !dlgOpen);
  } else {
    A.status(`「${job.song}」の取り込み${j.cancel ? 'をやめた' : 'に失敗した: ' + lastLine(j.log).slice(0, 80)}`, !j.cancel);
    job.ended = true;   // 次に「＋ 曲を取り込む」を押すと設定に戻る
    if ($('impDlg').style.display !== 'flex') { show('run'); runView(j); }
  }
}
async function finish(song, j, quiet) {
  const report = j && j.report;
  job = null; J = null; P = null;
  try { await A.loadSongs(); await A.openSong(song); }
  catch (e) { A.status('取り込んだ曲を開けなかった: ' + e.message, true); return; }
  close();
  if (report && !quiet) A.showReport(`「${song}」を取り込んだ（最初の譜面）`, A.reportHTML(report));
}
async function cancel() {
  if (!job || job.fake || !confirm(`「${job.song}」の取り込みをやめますか？（済んだ段の結果は残り、次に同じ名前で取り込むと使い回す）`)) return;
  try { await api('POST', '/api/import/cancel', {id: job.id}); } catch (e) { A.status(e.message, true); }
  poll();
}

// 確かめ用（見えない Edge）: 本物の取り込みをせず、作り物の取り込みで基本設定の窓を出す。#iwtest＝曲の解析の途中・
// #iwtest=wait＝解析が済んで待っている（上のボタンが目立つ形）・#iwtest=ok＝少し後に「この設定で作る」を押して進み具合へ・
// #iwtest=bg＝音を分けている間に曲の解析も裏で動いている（段の印が 2 つ ●・題名に段ごとの印）。
// 初めの値・決めた物は題名に（--dump-dom で読む）。サーバーには何も送らない（ブラウザに覚える初めの値だけは書く）
function fakeTest(kind) {
  const now = Date.now() / 1000, at = kind === 'wait' ? 3 : kind === 'bg' ? 0 : 1;
  const log = kind === 'bg' ? ['== 音を分ける', '$ python.exe separate.py …', '分ける準備（部品とモデル htdemucs_ft を読み込む）',
                               '曲の全体を 8 回計算して平均する（4 つのモデル・それぞれ 2 回ずらして）',
                               '\r音を分ける 37%・残り約 0:24（8 回の計算のうち 2 回済み・3 回目 96%）\r音を分ける 38%・残り約 0:23（8 回の計算のうち 3 回済み）']
    : ['== 音を分ける', '分けた音がもうある（使い回す）: こだま', '== 曲の解析', '$ python.exe -m automap.analyze_song …', 'テンポの推定と構成の解析をしている…'];
  if (at === 3) log.push('== 元のプロジェクトを作る', '元のプロジェクト: こだま.nlmf（マーカー 14）', '== ' + WAIT, '基本設定（型のライブラリ）を待っている（取り込みの窓で「この設定で作る」）');
  FAKE = {id: 'iwtest', kind: 'import', song: 'こだま（確かめ）', state: 'running', steps: STEPS, step: at, started: now - (at === 3 ? 108 : at ? 41 : 18), log: log.join('\n') + '\n'};
  if (kind === 'bg') FAKE.bg = {'曲の解析': 'running'};
  job = {id: FAKE.id, song: FAKE.song, fake: true}; J = FAKE;
  badge(FAKE);
  openSettings(true).then(() => {
    if (kind === 'ok') setTimeout(() => $('impSetOk').click(), 1500);
    if (kind === 'bg') document.title = 'iwtest bg ' + [...document.querySelectorAll('#impMini li')].map(li => li.className).join(',');
  });
}

export function init(app) {
  A = app;
  build();
  $('importBtn').onclick = open;
  // 画面を開き直した時: 動いている取り込みがあれば、決めていなければ基本設定、決めていれば進み具合を出し直す
  (async () => {
    try {
      const js = await api('GET', '/api/jobs');
      const j = js.find(q => q.kind === 'import');
      if (j) { job = {id: j.id, song: j.song}; J = j; badge(j); if (needSet(j)) openSettings(true); else { show('run'); runView(j); } poll(); }
    } catch (e) {}
    // 確かめ用（見えない Edge）: #import=<音源の場所> で、その音源を読んで確かめる窓を出す（取り込みはしない）
    const m = location.hash.match(/^#import=(.+)$/);
    if (m && !job) { show('pick'); $('impPath').value = decodeURIComponent(m[1]); read(); }
    const w = location.hash.match(/^#iwtest(?:=(\w+))?/);
    if (w && !job) fakeTest(w[1] || '');
  })();
}
