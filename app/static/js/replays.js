// 遊んだリプレイ（BeatLeader の .bsor）を BL のリプレイアプリで見る（app/replays.py・docs/アプリ仕様.md 26 節）。main.js が init(app) を呼ぶ。
// 2026-11-12 利用者「自分のプレイのリプレイを見れるようにしたい。サーバに譜面がないから BL の WEB リプレイで見れなくてつらい」
// 「出来れば、BL のリプレイアプリを使いたい」「ローカルに持って来てうまいこと動かせないかな」。
// 上の列の「リプレイ」→ 窓の上の切り替え:
//   「この曲」＝今の曲のリプレイ（GET /api/replays?file=）・「全部の履歴」＝どの曲のリプレイも（GET /api/replays/all・2026-11-15 利用者「全体の
//   履歴も表示出来るように」・曲名で探す・ANP の曲だけ・100 件ずつ・ANP の曲は「曲を開く」）。開いた切り替えは覚える（曲が無い時は全部の履歴）。
// 「BL のリプレイで見る」＝サーバーが使い捨ての鍵でリプレイと遊んだ時の譜面の zip を用意し（POST /api/replays/open）、アプリの中の BL の
// リプレイアプリ（/static/blreplay/・tools/blreplay_fetch.py で写した物）を ?link=…&mapLink=… で別のタブ（窓のアプリは既定のブラウザ）に開く。
// ANP の曲でない譜面（BeatSaver の譜面）は手元の曲のフォルダに同じ譜面があればそれを、無ければサーバーが BeatSaver から取った zip を渡す。開くタブには前のページを渡さない（noopener＝BL のリプレイアプリからアプリの画面・合言葉に触れない）。
// 「ここで見る」（ANP の曲のリプレイ・2026-11-15）＝左下の欄の「リプレイ」に開き、再生位置をアプリとそろえる（js/replaypane.js・emit('replayPane', id)）。
// ほかの ANP の曲の物はその曲を開いてから（showHere）。ボタンは控えめな緑＝「BL のリプレイで見る」と見分けて先に選べる。
// 確かめ: #rltest（=list・=empty・=nodir・=open・=all・=allq）＝作り物の中身で窓を出す（サーバーに聞かない）→ #rltestOut（--dump-dom）
import {$, api, S, DIFF_TEXT, lsGet, lsSet, emit} from './store.js';

let A = null, FAKE = null, DATA = null;
const V = {tab: 'song', q: '', anp: false, n: 100};   // 全部の履歴: 探す字・ANP の曲だけ・出す数
const PAGE = 100;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const call = (m, u, b) => FAKE ? FAKE(m, u, b) : api(m, u, b);
const SRC = {saved: ['遊んだ時の譜面', '書き出した時に控えた譜面（遊んだ時と同じ）'],
  folder: ['遊んだ時の譜面', 'Beat Saber の曲のフォルダの今の譜面（遊んだ後にまだ書き出し直していない＝遊んだ時と同じ）'],
  rebuild: ['記録から組み立て', '遊んだ時の譜面の控えが無いので、リプレイの記録のノーツから組み立てる（壁・アーク・チェーンは出ない・音とライトは今の書き出しの物）'],
  none: ['譜面が無い', 'この曲をまだ Beat Saber に書き出していない（音が無いので開けない）'],
  other: ['BeatSaver の譜面', '開く時に手元の曲のフォルダ（CustomLevels）から同じ譜面を探す。無ければ BeatSaver から取る（ネットが要る・消された版は開けない）']};
const MOD = {DA: '消える矢印', FS: '速い曲', SF: 'とても速い曲', SS: '遅い曲', GN: 'ゴーストノーツ', NA: '矢印なし', NB: 'ボムなし',
  NF: 'ノーフェイル', NO: '壁なし', PM: 'プロモード', SC: '小さいノーツ', IF: '1 ミスで終わり', BE: 'バッテリー', OD: '古いドット', SA: '厳しい角度', OP: '1 本セイバー'};

function build() {
  const d = document.createElement('div');
  d.id = 'rlDlg'; d.className = 'modal rl';
  d.innerHTML = `<div class="dlg">
  <div class="dlgHead"><b>リプレイを見る</b><span class="rlTabs"><button data-tab="song" title="今開いている曲のリプレイ">この曲</button><button data-tab="all"
    title="どの曲のリプレイも新しい順に（ANP で作った曲もほかの譜面も）">全部の履歴</button></span><span class="sub" id="rlHeadSub"></span><button id="rlClose">閉じる</button></div>
  <div class="dlgBody">
    <p class="sub">Beat Saber で遊んだリプレイ（BeatLeader の .bsor）を、BL のリプレイアプリで見ます。BeatSaver に無い譜面でも、
      遊んだ時の譜面をアプリから渡すので見られます（別のタブ・窓のアプリでは既定のブラウザで開きます）。
      ANP で作った曲のリプレイは「ここで見る」で左下の欄に開き、再生位置をアプリの帯・3D とそろえて見られます（ほかの曲の物は、その曲を開いてから）。</p>
    <div id="rlTools" class="rlTools" hidden><input id="rlQ" type="search" spellcheck="false" placeholder="曲名・作者名で探す">
      <label class="ck"><input type="checkbox" id="rlAnp"> ANP で作った曲だけ</label><span class="sub" id="rlCount"></span></div>
    <div id="rlMsg" class="rlMsg" hidden></div>
    <div id="rlList"></div>
    <section class="rlDirs"><h3>リプレイの置き場</h3><div id="rlDirs" class="sub"></div>
      <div class="rlRow"><input id="rlDir" spellcheck="false" placeholder="例: C:\\Program Files (x86)\\Steam\\steamapps\\common\\Beat Saber\\UserData\\BeatLeader\\Replays">
        <button id="rlDirSet">この場所にする</button><button id="rlDirAuto" title="Beat Saber の曲のフォルダから探す（BSManager・Steam・Oculus）">自動に戻す</button></div></section>
    <p class="sub">プレイヤーの名前とアイコンは、BL のリプレイアプリが BeatLeader から読みます（ネットに繋がっていなければ出ないだけ）。</p>
  </div></div>`;
  document.body.appendChild(d);
  $('rlClose').onclick = close;
  d.addEventListener('mousedown', e => { if (e.target === d) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && shown()) close(); });
  d.querySelectorAll('.rlTabs button').forEach(b => { b.onclick = () => { if (!b.disabled) { if (!FAKE) lsSet('automap-rltab', b.dataset.tab); load(b.dataset.tab); } }; });
  $('rlQ').oninput = () => { V.q = $('rlQ').value; V.n = PAGE; render(); };
  $('rlAnp').onchange = () => { V.anp = $('rlAnp').checked; if (!FAKE) lsSet('automap-rlanp', V.anp); V.n = PAGE; render(); };
  $('rlDirSet').onclick = () => setDir($('rlDir').value);
  $('rlDirAuto').onclick = () => setDir('');
}
const shown = () => !!$('rlDlg') && $('rlDlg').style.display === 'flex';
function close() { if ($('rlDlg')) $('rlDlg').style.display = 'none'; }
function msg(t, bad) { const m = $('rlMsg'); m.hidden = !t; m.textContent = t || ''; m.classList.toggle('bad', !!bad); }

async function open(tab) {
  if (!$('rlDlg')) build();
  $('rlDlg').style.display = 'flex';
  V.anp = !!lsGet('automap-rlanp', false); $('rlAnp').checked = V.anp;
  await load(tab || lsGet('automap-rltab', 'song'));
}

async function load(tab) {
  const hasSong = !!(S.file || FAKE);
  if (tab === 'song' && !hasSong) tab = 'all';
  V.tab = tab; V.n = PAGE;
  $('rlDlg').querySelectorAll('.rlTabs button').forEach(b => {
    b.classList.toggle('on', b.dataset.tab === tab); if (b.dataset.tab === 'song') b.disabled = !hasSong; });
  $('rlHeadSub').textContent = tab === 'song' ? (S.song || '') : '';
  $('rlTools').hidden = tab !== 'all';
  $('rlList').innerHTML = `<p class="sub">${tab === 'all' ? '全部のリプレイを読んでいます（初めては数秒）…' : '探しています…'}</p>`;
  msg('');
  try {
    const d = await call('GET', tab === 'all' ? '/api/replays/all' : '/api/replays?file=' + encodeURIComponent(S.file));
    if (V.tab !== tab) return;   // 読んでいる間に切り替えた
    DATA = d; render();
  } catch (e) { $('rlList').innerHTML = ''; msg('読めなかった: ' + e.message, true); }
}

const when = t => { const d = new Date(t * 1000), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; };
const mods = s => String(s || '').split(',').filter(Boolean).map(m => `<span class="rlMod" title="${esc(MOD[m] || m)}">${esc(m)}</span>`).join('');
const fold = s => String(s || '').normalize('NFKC').toLowerCase();
const fmtT = t => { const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(1).padStart(4, '0')}`; };   // 曲の秒 → 1:23.4
// 左下の欄で見られるリプレイ: 今開いている曲の物と、ほかの ANP の曲（アプリの曲の一覧にある）の物（押すとその曲を開いてから左下の欄に開く・2026-11-15）
const here = r => V.tab === 'song' ? !!S.file : !!r.anp && (S.songs || []).some(s => s.song === r.anp.song);
const otherSong = r => V.tab === 'all' && !!r.anp && r.anp.file !== S.file;

function filtered() {
  const D = DATA;
  if (V.tab !== 'all') return D.replays;
  const q = fold(V.q).trim();
  return D.replays.filter(r => (!V.anp || r.anp) && (!q || fold(r.song).includes(q) || fold(r.mapper).includes(q) || (r.anp && fold(r.anp.song).includes(q))));
}

function render() {
  const D = DATA, all = V.tab === 'all';
  $('rlDirs').innerHTML = D.dirs.length ? D.dirs.map(x => `<div>${esc(x)}</div>`).join('') + (D.auto ? '<div>（自動で見つけた場所）</div>' : '')
    : 'リプレイの置き場が見つかりません。BeatLeader の mod の Replays フォルダ（&lt;Beat Saber&gt;\\UserData\\BeatLeader\\Replays）を入れてください。';
  if (!D.viewer) msg('BL のリプレイアプリ（app/static/blreplay/）がありません。tools/blreplay_fetch.py で写してください', true);
  const list = filtered();
  if (all) $('rlCount').textContent = `${list.length} 個` + (list.length !== D.replays.length ? `（全部で ${D.replays.length} 個）` : '')
    + `・ANP の曲 ${D.replays.filter(r => r.anp).length} 個`;
  if (!list.length) {
    $('rlList').innerHTML = `<p class="sub">${!D.dirs.length ? '' : all ? (D.replays.length ? '合うリプレイがありません。' : 'リプレイがありません。')
      : 'この曲のリプレイはまだありません' + (D.other ? `（ほかの曲のリプレイ ${D.other} 個＝「全部の履歴」）` : '') + '。Beat Saber に書き出して遊ぶと、ここに出ます。'}</p>`;
    return;
  }
  const songs = new Set((S.songs || []).map(s => s.song));
  const rows = list.slice(0, V.n).map((r, i) => {
    const src = SRC[r.map] || SRC.none;
    const acc = r.acc != null ? (r.acc * 100).toFixed(2) + '%' : '-';
    const miss = [r.misses ? `ミス ${r.misses}` : '', r.bad ? `バッド ${r.bad}` : '', r.bombs ? `ボム ${r.bombs}` : '', r.walls ? `壁 ${r.walls}` : '']
      .filter(Boolean).map(x => `<span>${x}</span>`).join('') || 'なし';   // 1 つずつ 1 行（横幅が足りない時に字が縦に並ばない・2026-11-15）
    const song = !all ? '' : `<td class="rlSong"><div class="rlSongRow"><span class="rlCov"><img class="rlCover" alt="" draggable="false" data-src="${esc(coverUrl(r))}"></span>
      <div><div><b>${esc(r.song)}</b>${r.anp ? '<span class="rlAnp" title="ANP で作った曲">ANP</span>' : ''}</div>
      <div class="sub">${esc(r.mapper)}${r.anp && songs.has(r.anp.song) && r.anp.song !== S.song
        ? ` <a href="#" class="rlGo" data-i="${i}" title="この曲をアプリで開く">曲を開く</a>` : ''}</div></div></div></td>`;
    return `<tr><td>${esc(when(r.at))}</td>${song}<td>${esc(DIFF_TEXT[r.diff] || r.diff)}${r.mode && r.mode !== 'Standard' ? ' ' + esc(r.mode) : ''}</td>
      <td class="num rlStar" data-i="${i}" data-id="${esc(r.id)}">${starText(STAR.get(r.id))}</td>
      <td class="num" title="点 ${esc(r.score)}（精度の目安＝点÷満点・修飾の掛け算も入る）">${acc}</td><td class="rlMiss">${miss}</td>
      <td class="rlMods">${mods(r.modifiers)}${r.fail ? '<span class="rlMod bad" title="途中で失敗した">失敗</span>' : ''}${r.exit
        ? `<span class="rlMod quit" title="途中でやめた（ポーズからメニュー・やり直し）。${r.end != null ? fmtT(r.end) + ' まで遊んだ・左下の欄ではそこで止まる' : ''}">やめた</span>` : ''}</td>
      <td title="${esc(src[1])}" class="rlSrc ${esc(r.map)}">${esc(src[0])}</td>
      <td class="rlBtns">${here(r) ? `<button class="rlHere" data-i="${i}" ${r.map === 'none' || !D.viewer ? 'disabled' : ''}
        title="${otherSong(r) ? `この曲（${esc(r.anp.song)}）をアプリで開いてから、` : ''}左下の欄（付けた指示と切り替え）に開き、再生位置をアプリの帯・3D とそろえる">ここで見る</button>` : ''}<button class="rlOpen" data-i="${i}" ${r.map === 'none' || !D.viewer ? 'disabled' : ''}>BL のリプレイで見る</button></td></tr>`;
  }).join('');
  const more = list.length > V.n ? `<button id="rlMore">もっと見る（残り ${list.length - V.n} 個）</button>` : '';
  $('rlList').innerHTML = `<table class="rlTbl"><thead><tr><th>遊んだ日時</th>${all ? '<th>曲</th>' : ''}<th>難易度</th>
    <th title="${esc(STAR_TIP)}">★</th><th>精度</th><th>ミス</th>
    <th>修飾</th><th>譜面</th><th></th></tr></thead><tbody>${rows}</tbody></table>${more}`;
  $('rlList').querySelectorAll('.rlOpen').forEach(b => { b.onclick = () => openOne(list[+b.dataset.i], b); });
  $('rlList').querySelectorAll('.rlHere').forEach(b => { b.onclick = () => showHere(list[+b.dataset.i]); });
  $('rlList').querySelectorAll('.rlGo').forEach(a => { a.onclick = e => { e.preventDefault(); goSong(list[+a.dataset.i]); }; });
  if ($('rlMore')) $('rlMore').onclick = () => { V.n += PAGE; render(); };
  if (all) covers();
  starsWatch(list);
}

// ---- 一覧の★（2026-11-15 利用者「一覧に難易度も表示して」→ ★） ----
// 遊んだ時の譜面の★（nlm-rating＝BeatLeader の★の近似・アプリの★と同じ物差し・修飾なし）。カバーと同じく、見えている行と上下の半ページの行だけ
// まとめて頼む（POST /api/replays/stars・app/replays.py の stars）。サーバーは測っていない物を裏で測り始めて pending で返す → 少し待って聞き直す。
// 測った★はサーバーが作業の場所の cache に控え、画面も覚える（STAR）＝描き直しではすぐ出す。測れない物（遊んだ時の譜面が手元に無い等）は —
const STAR_TIP = '遊んだ時の譜面の★（BeatLeader の★の近似＝nlm-rating・修飾なし）。— は遊んだ時の譜面が手元に無い・測れなかった';
const STAR = new Map();   // リプレイ → ★｜null
const SQ = new Map();     // 頼む物: リプレイ → ANP の曲の結果のファイル（無ければ null）
let SO = null, STimer = 0, SErr = '';
const starText = v => v === undefined ? '<span class="sub">…</span>' : v == null ? `<span class="sub" title="${esc(SErr || STAR_TIP)}">—</span>` : '★' + v.toFixed(2);
function starsWatch(list) {
  if (SO) SO.disconnect();
  if (FAKE) return;
  const cells = [...$('rlList').querySelectorAll('td.rlStar')].filter(td => !STAR.has(td.dataset.id));
  if (!cells.length) return;
  SO = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    SO.unobserve(e.target);
    const r = list[+e.target.dataset.i];
    if (r && !STAR.has(r.id)) { SQ.set(r.id, r.anp ? r.anp.file : null); askSoon(80); }
  }), {root: $('rlDlg').querySelector('.dlgBody'), rootMargin: '50% 0px'});
  cells.forEach(td => SO.observe(td));
}
function askSoon(ms) { if (!STimer) STimer = setTimeout(askStars, ms); }
async function askStars() {
  STimer = 0;
  if (!shown()) { SQ.clear(); return; }   // 窓を閉じた＝頼まない（裏で測り始めた分はサーバーが控える）
  const items = [...SQ].map(([id, file]) => file ? {id, file} : {id});
  SQ.clear();
  if (!items.length) return;
  let d;
  try { d = await api('POST', '/api/replays/stars', {items}); } catch (e) { return; }
  if (d.error) { SErr = d.error; items.forEach(x => STAR.set(x.id, null)); }
  Object.entries(d.stars || {}).forEach(([id, v]) => STAR.set(id, v));
  const files = new Map(items.map(x => [x.id, x.file || null]));
  (d.pending || []).forEach(id => SQ.set(id, files.get(id) || null));
  $('rlList').querySelectorAll('td.rlStar').forEach(td => { if (STAR.has(td.dataset.id)) td.innerHTML = starText(STAR.get(td.dataset.id)); });
  if (SQ.size) askSoon(1200);
}

// ---- 全部の履歴のカバー画像（2026-11-15 利用者「一覧だとカバー画像が欲しくなる。キャッシュしつつ 1 ページ半分だけ画像を随時取得する」） ----
// 見えている行と、その上下の半ページ（窓の中の流す欄の高さの半分）に入った行だけ画像を頼む（IntersectionObserver の rootMargin 50%）＝流すと
// 順に読む。サーバー（GET /api/replays/cover・app/replays.py の cover）は作業の場所の cache/.replay-covers に控える＝2 回目からは手元から。
// 一度読めた画像は覚えて（COV）描き直し（探す・もっと見る）ではすぐ出す。<img> は合言葉を頭に付けられないので anpUrl（?k=）
const coverUrl = r => '/api/replays/cover?id=' + encodeURIComponent(r.id) + (r.anp ? '&file=' + encodeURIComponent(r.anp.file) : '');
const COV = new Map();   // 頼む場所 → 'ok'｜'none'
let CO = null;
function covers() {
  if (CO) CO.disconnect();
  const imgs = [...$('rlList').querySelectorAll('img.rlCover')];
  const load = img => {
    const u = img.dataset.src;
    img.onload = () => { COV.set(u, 'ok'); img.classList.add('on'); };
    img.onerror = () => { COV.set(u, 'none'); img.classList.add('none'); };   // 見せない（枠の地の色だけ）
    img.src = window.anpUrl(u);
  };
  const wait = [];
  imgs.forEach(img => { const st = COV.get(img.dataset.src); if (st === 'none') img.classList.add('none'); else if (st === 'ok') load(img); else wait.push(img); });
  if (FAKE || !wait.length) return;
  CO = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { CO.unobserve(e.target); load(e.target); } }),
    {root: $('rlDlg').querySelector('.dlgBody'), rootMargin: '50% 0px'});
  wait.forEach(img => CO.observe(img));
}

// 「ここで見る」: ほかの ANP の曲の物は、その曲を開いてから（作業ファイルを保存して開き直す＝openSong）左下の欄にそのリプレイを開く
async function showHere(r) {
  if (FAKE) { msg('ここで見る: ' + r.id + (otherSong(r) ? `（${r.anp.song} を開いてから）` : '')); return; }
  close();
  if (otherSong(r)) {
    if (!A || !A.openSong) return;
    try { await A.openSong(r.anp.song); } catch (e) { return; }   // 開けなかった時は openSong が札と下の列に出す
    if (S.song !== r.anp.song) return;                              // 開いている間にほかの曲を選んだ
  }
  emit('replayPane', r.id);
}

async function goSong(r) {
  if (!A || !A.openSong) return;
  close();
  await A.openSong(r.anp.song);
}

async function openOne(r, btn) {
  btn.disabled = true;
  msg('用意しています…');
  try {
    const file = V.tab === 'song' ? S.file : (r.anp ? r.anp.file : undefined);
    const o = await call('POST', '/api/replays/open', file ? {file, id: r.id} : {id: r.id});
    const org = location.origin;
    const url = `${org}/static/blreplay/index.html?link=${encodeURIComponent(org + o.link)}`
      + (o.mapLink ? `&mapLink=${encodeURIComponent(org + o.mapLink)}` : '');
    if (!FAKE) window.open(url, '_blank', 'noopener');
    $('rlMsg').hidden = false; $('rlMsg').classList.remove('bad');
    $('rlMsg').innerHTML = `${esc(when(r.at))} の ${esc(r.song || '')} ${esc(DIFF_TEXT[r.diff] || r.diff)} を開きました（${esc(o.note)}）。
      開かなかった時は <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">ここ</a> から。`;
  } catch (e) { msg('開けなかった: ' + e.message, true); }
  btn.disabled = false;
}

async function setDir(v) {
  try { await call('POST', '/api/replays/dir', {dir: v}); $('rlDir').value = ''; await load(V.tab); }
  catch (e) { msg(e.message, true); }
}

export function init(app) {
  A = app;
  const b = $('replayBtn'); if (b) b.onclick = () => open();
}

// ---- 確かめ（#rltest=list|empty|nodir|open|all|allq） ----
// all＝全部の履歴（作り物 230 個・ANP の曲 3 個）・allq＝その上で「ANP で作った曲だけ」と曲名で探す
export async function selfTest(kind) {
  kind = String(kind || 'list').split('&')[0];
  const rows = [
    {id: '0/a.bsor', at: 1794394711, diff: 'Expert', mode: 'Standard', score: 605925, modifiers: '', fail: false, map: 'folder', acc: 0.9083, misses: 0, bad: 4, bombs: 0, walls: 0,
      song: '桃源郷', mapper: 'Oz-Co2', anp: {file: '桃源郷.intent-s1.nlmf', song: '桃源郷'}},
    {id: '0/b.bsor', at: 1793792686, diff: 'Expert', mode: 'Standard', score: 512000, modifiers: 'FS,NF', fail: false, map: 'rebuild', acc: 0.8721, misses: 5, bad: 2, bombs: 1, walls: 0,
      song: '桃源郷', mapper: '', anp: {file: '桃源郷.intent-s1.nlmf', song: '桃源郷'}},
    {id: '0/c.bsor', at: 1792538093, diff: 'ExpertPlus', mode: 'Standard', score: 120000, modifiers: '', fail: true, map: 'saved', acc: 0.7712, misses: 31, bad: 9, bombs: 0, walls: 2,
      song: 'ハロ (collaboration tracks)', mapper: 'Oz-Co2', anp: {file: 'ハロ (collaboration tracks).intent-s1.nlmf', song: 'ハロ (collaboration tracks)'}}];
  const others = Array.from({length: 227}, (_, i) => ({id: `0/o${i}.bsor`, at: 1792000000 - i * 3600, diff: ['Hard', 'Expert', 'ExpertPlus'][i % 3], mode: 'Standard',
    score: 400000 + i, modifiers: i % 7 ? '' : 'FS', fail: i % 11 === 0, map: 'other', acc: 0.8 + (i % 15) / 100, misses: i % 9, bad: i % 4, bombs: 0, walls: 0,
    song: ['ナツノリズム', 'カミサマ・ネコサマ', 'オリオンをなぞる'][i % 3], mapper: ['someone', 'mapper2'][i % 2], anp: null}));
  const all = kind === 'all' || kind === 'allq';
  const data = {dirs: kind === 'nodir' ? [] : ['D:\\BSManager\\BSInstances\\1.40.8\\UserData\\BeatLeader\\Replays'], auto: true,
    replays: kind === 'list' || kind === 'open' ? rows.slice(0, 2) : all ? [...rows, ...others] : [], other: 812, viewer: true};
  FAKE = async (m, u) => {
    if (u.startsWith('/api/replays/open')) return {link: '/blr/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/a.bsor', mapLink: '/blr/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/map.zip', source: 'folder', note: '遊んだ時の譜面（Beat Saber の曲のフォルダ）'};
    if (u.startsWith('/api/replays')) return data;
    return {};
  };
  await open(all ? 'all' : 'song');
  if (kind === 'allq') { $('rlAnp').checked = true; $('rlAnp').onchange(); $('rlQ').value = 'ハロ'; $('rlQ').oninput(); }
  if (kind === 'open') { $('rlList').querySelector('.rlOpen').click(); await new Promise(r => setTimeout(r, 200)); }
  const out = [`行 ${$('rlList').querySelectorAll('tbody tr').length}`, `数: ${$('rlCount').textContent}`, `もっと見る: ${$('rlMore') ? $('rlMore').textContent : '-'}`,
    $('rlList').innerText.replace(/\s+/g, ' ').trim().slice(0, 600), `知らせ: ${$('rlMsg').hidden ? '-' : $('rlMsg').innerText.trim()}`];
  const el = document.createElement('pre'); el.id = 'rltestOut'; el.style.display = 'none'; el.textContent = out.join('\n'); document.body.appendChild(el);
  document.title = 'rltest ' + out[0];
}
