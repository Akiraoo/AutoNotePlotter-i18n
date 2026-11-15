// 曲を選ぶ窓（2026-11-09 利用者「曲が 20〜30 曲を超えると上の列の選びが使いにくい」→ 小さい窓。機能を増やしすぎない＝手間を抑える）。
// main.js が init(app) を呼ぶ。上の列の曲名（#songBtn）を押すか Ctrl+O で開く。
// - 検索（曲名・アーティスト・曲の名前＝out/ のファイルの頭。全角半角・大文字小文字・カタカナひらがなをそろえて、空白で区切った語を全部含む曲）
// - 並び: 最近開いた順（既定・画面の覚え automap-recent＝開いた曲の名前の並び・RECENT_MAX まで。開いたことの無い曲はその後ろに更新日の順）・
//   名前順・更新日順（結果のファイルの更新時刻）。選んだ並びは automap-songsort に覚える
// - 1 行: カバーの小さな画像（書き出しの窓の受け口 /api/bsexport/cover＝今のカバー・loading=lazy・無い曲は空の枠）・曲名・アーティスト
//   （結果のファイルの曲の情報＝server.read_song_info）・最終更新日
// - アーカイブ: 作業ファイルに印を付けるだけ（POST /api/songs/archive・ファイルは動かさない）。アーカイブした曲は普段の一覧に出ず、
//   「アーカイブ」に切り替えた時だけ出る（そこから戻す）。開いている曲もアーカイブできる（開いたまま・上の列の曲名が薄くなる）
// - ★・作った難易度・書き出したかは出さない（ほかの所とのつながりを増やさない・2026-11-09 利用者と決めた）
// 曲を開くのは main.js の openSong（読み込み中の札・後から選んだ曲が勝つ）。見えない選び #song は前からの口（確かめのページの &song=・
// #zmtest 等が値を変えて change を送る）のまま＝main.js の showSong が今の曲に合わせ続ける。
// 確かめ: #sptest（窓を開く・検索・並び替え・選ぶ・アーカイブ・開いている曲の保存で印が消えない・戻す → document.title と #sptestOut）・
// #sptest=arcview（1 曲アーカイブしてアーカイブの一覧を出したまま＝画像用・戻さない）・#sptest=q=字（検索した所で止める）
import {$, S, api, lsGet, lsSet} from './store.js';

let A = null;   // main.js から渡された口
const RECENT_MAX = 100;
const SORTS = [['recent', '最近開いた順'], ['name', '名前順'], ['mtime', '更新日順']];
const SP = {open: false, sort: 'recent', arc: false, sel: null, rows: [], imgs: new Map(), seq: 0};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const norm = s => String(s ?? '').normalize('NFKC').toLowerCase().replace(/[ァ-ヶ]/g, c => String.fromCharCode(c.charCodeAt(0) - 0x60));
const two = n => String(n).padStart(2, '0');
const dateText = t => { if (!t) return ''; const d = new Date(t * 1000);
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`; };
const recent = () => { const r = lsGet('automap-recent', []); return Array.isArray(r) ? r : []; };
const songOf = name => S.songs.find(q => q.song === name);
const modalOpen = () => [...document.querySelectorAll('.modal')].some(m => m.id !== 'spDlg' && getComputedStyle(m).display !== 'none');

export function init(app) {
  A = app;
  const s = lsGet('automap-songsort', 'recent'); SP.sort = SORTS.some(([k]) => k === s) ? s : 'recent';
  const d = document.createElement('div'); d.id = 'spDlg'; d.className = 'modal sp';
  d.innerHTML = `<div class="dlg spDlg" role="dialog" aria-modal="true" aria-labelledby="spHead">
    <div class="dlgHead"><b id="spHead">曲を選ぶ</b><span class="sub" id="spCount"></span><button id="spClose">閉じる</button></div>
    <div class="spBar">
      <input type="search" id="spQ" placeholder="曲名・アーティストで探す" autocomplete="off" spellcheck="false" aria-controls="spList">
      <div class="seg spSort" id="spSort">${SORTS.map(([k, t]) => `<button data-k="${k}" tabindex="-1">${t}</button>`).join('')}</div>
      <label class="spArcCk" title="アーカイブした曲だけを出す（戻すのもここから）"><input type="checkbox" id="spArc" tabindex="-1">アーカイブ<span id="spArcN" class="sub"></span></label>
    </div>
    <div id="spList" class="spList" role="listbox" aria-label="曲"></div>
    <div class="spFoot sub">↑↓＝選ぶ・Enter＝開く・Esc＝閉じる・Ctrl+O＝この窓。アーカイブは作業ファイルに印を付けるだけ（ファイルは動かさない・「アーカイブ」に切り替えると見えて戻せる）</div>
  </div>`;
  document.body.appendChild(d);
  d.addEventListener('keydown', key);
  d.addEventListener('mousedown', e => { if (e.target === d) d.dataset.down = '1'; });
  d.addEventListener('click', e => { if (e.target === d && d.dataset.down === '1') close(); d.dataset.down = ''; });
  $('spClose').onclick = close;
  $('spQ').addEventListener('input', () => { SP.sel = null; render(); });
  $('spSort').onclick = e => { const b = e.target.closest('button[data-k]'); if (!b) return; setSort(b.dataset.k); $('spQ').focus(); };
  $('spArc').onchange = e => { SP.arc = e.target.checked; SP.sel = null; render(); $('spQ').focus(); };
  $('spList').addEventListener('click', e => {
    const row = e.target.closest('.spRow'); if (!row) return;
    const name = row.dataset.song, ab = e.target.closest('.spArcBtn');
    if (ab) { e.stopPropagation(); archive(name, !SP.arc); return; }
    choose(name);
  });
  $('songBtn').onclick = () => open();
  // Ctrl+O＝この窓（ほかの窓が開いている時は効かない。ほかの窓は字を打つ所で keydown を止めるので、ここまで来ない）
  document.addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || e.key.toLowerCase() !== 'o') return;
    e.preventDefault();
    if (!SP.open && !modalOpen()) open();
  });
}

// 上の列の曲名（main.js の showSong が呼ぶ）
export function label(name) {
  const b = $('songBtn'); if (!b) return;
  const s = name ? songOf(name) : null, arc = !!(s && s.archived);
  b.querySelector('.songBtnName').textContent = name || '曲を選ぶ';
  b.classList.toggle('arc', arc);
  b.title = (name ? `曲: ${name}` + (s && s.artist ? `（${s.artist}）` : '') + (arc ? '・アーカイブした曲' : '') + '\n' : '') + '押すと曲を選ぶ窓（検索・並び替え・アーカイブ・Ctrl+O）';
}
// 曲を開いた（main.js の openSong が開き終えた時）→ 最近開いた順の頭に
export function opened(name) {
  const r = recent().filter(x => x !== name); r.unshift(name);
  lsSet('automap-recent', r.slice(0, RECENT_MAX));
  if (SP.open) render();
}
// 曲の一覧を読み直した（main.js の loadSongs）
export function refresh() { if (SP.open) render(); label(S.song); }
export const isOpen = () => SP.open;

export function open() {
  if (SP.open) return;
  SP.open = true; SP.sel = null;
  $('spDlg').style.display = 'flex';
  $('spQ').value = ''; $('spArc').checked = SP.arc = false;
  render();
  $('spQ').focus();
  const my = ++SP.seq;   // 一覧は開いた時に読み直す（NLM で保存した・ほかの窓で直した更新日・カバー）＝先に今の一覧で出して、届いたら出し直す
  A.loadSongs().then(() => { if (SP.open && my === SP.seq) render(); }).catch(() => {});
}
export function close() {
  if (!SP.open) return;
  SP.open = false; $('spDlg').style.display = 'none';
  const b = $('songBtn'); if (b && document.activeElement && $('spDlg').contains(document.activeElement)) b.focus();
}
function setSort(k) {
  if (!SORTS.some(([x]) => x === k)) return;
  SP.sort = k; lsSet('automap-songsort', k); render();
}

// 出す曲（検索・アーカイブの切り替え・並び）
function list() {
  const words = norm($('spQ').value).split(/\s+/).filter(Boolean);
  const hit = s => { const h = norm(`${s.title} ${s.artist} ${s.song}`); return words.every(w => h.includes(w)); };
  const all = S.songs.filter(hit), rows = all.filter(s => !!s.archived === SP.arc);
  const name = s => s.title || s.song;
  if (SP.sort === 'name') rows.sort((a, b) => name(a).localeCompare(name(b), 'ja', {numeric: true, sensitivity: 'base'}) || a.song.localeCompare(b.song, 'ja'));
  else if (SP.sort === 'mtime') rows.sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
  else { const at = new Map(recent().map((x, i) => [x, i]));
    rows.sort((a, b) => (at.has(a.song) ? at.get(a.song) : 1e9) - (at.has(b.song) ? at.get(b.song) : 1e9) || (b.mtime || 0) - (a.mtime || 0)); }
  return {rows, other: all.length - rows.length, words};
}
function coverImg(s) {   // カバーの小さな画像（曲とファイルの印ごとに 1 つ作って使い回す＝並び替え・検索のたびに読み直さない）
  if (!s.cover) return null;
  const k = `${s.song}|${s.base_file}|${s.cover_v}`;
  let img = SP.imgs.get(k);
  if (!img) {
    img = new Image(); img.loading = 'lazy'; img.decoding = 'async'; img.alt = ''; img.draggable = false;
    img.onerror = () => { img.hidden = true; };
    img.src = window.anpUrl(`/api/bsexport/cover?file=${encodeURIComponent(s.base_file)}&v=${encodeURIComponent(s.cover_v)}`);   // ?k=＝合言葉（js/key.js）
    SP.imgs.set(k, img);
  }
  return img;
}
function render() {
  const {rows, other, words} = list();
  SP.rows = rows.map(s => s.song);
  if (!SP.rows.includes(SP.sel)) SP.sel = SP.rows.includes(S.song) && !words.length ? S.song : (SP.rows[0] ?? null);
  const nArc = S.songs.filter(s => s.archived).length;
  $('spCount').textContent = SP.arc ? `アーカイブ ${nArc} 曲` : `${S.songs.length - nArc} 曲` + (nArc ? `（ほかにアーカイブ ${nArc}）` : '');
  $('spArcN').textContent = nArc ? ` ${nArc}` : '';
  $('spSort').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.k === SP.sort));
  $('spDlg').classList.toggle('arcView', SP.arc);
  const L = $('spList');
  if (!rows.length) {
    L.innerHTML = `<div class="spEmpty">${SP.arc ? (words.length ? '一致するアーカイブした曲が無い' : 'アーカイブした曲は無い') : (words.length ? '一致する曲が無い' : '曲が無い')}` +
      (other ? `<span class="sub">${SP.arc ? '普段の一覧' : 'アーカイブ'}の中に一致する曲が ${other} 曲（「アーカイブ」を切り替えると見える）</span>` : '') + '</div>';
    return;
  }
  L.innerHTML = rows.map(s => {
    const cur = s.song === S.song, title = s.title || s.song;
    const tip = `${s.song}` + (s.artist ? `\nアーティスト: ${s.artist}` : '') + `\n結果のファイル: ${s.app_exists ? s.app_file : s.base_file + '（まだ作り直していない）'}` +
      `\n最終更新: ${dateText(s.mtime)}` + (cur ? '\n（今開いている曲）' : '');
    return `<div class="spRow${cur ? ' cur' : ''}${s.song === SP.sel ? ' sel' : ''}" role="option" aria-selected="${s.song === SP.sel}" data-song="${esc(s.song)}" title="${esc(tip)}">
      <span class="spCover"></span>
      <span class="spText"><span class="spTitle">${esc(title)}${cur ? '<span class="spCur">開いている</span>' : ''}</span>
        <span class="spArtist">${esc(s.artist || (title !== s.song ? s.song : ''))}</span></span>
      <span class="spDate">${esc(dateText(s.mtime))}</span>
      <button class="spArcBtn" tabindex="-1" title="${SP.arc ? '普段の一覧に戻す' : 'アーカイブする（普段の一覧に出さない・作業ファイルに印を付けるだけ・「アーカイブ」に切り替えると戻せる）'}">${SP.arc ? '戻す' : 'アーカイブ'}</button>
    </div>`;
  }).join('');
  L.querySelectorAll('.spRow').forEach((el, i) => { const img = coverImg(rows[i]); if (img) el.querySelector('.spCover').appendChild(img); });
  showSel(false);
}
function showSel(scroll = true) {
  $('spList').querySelectorAll('.spRow').forEach(el => { const on = el.dataset.song === SP.sel; el.classList.toggle('sel', on); el.setAttribute('aria-selected', on); });
  const el = [...$('spList').querySelectorAll('.spRow')].find(x => x.dataset.song === SP.sel);
  if (el && scroll !== false) el.scrollIntoView({block: 'nearest'});
  else if (el) requestAnimationFrame(() => el.scrollIntoView({block: 'nearest'}));
}
function move(d) {
  if (!SP.rows.length) return;
  const i = SP.rows.indexOf(SP.sel);
  SP.sel = SP.rows[Math.max(0, Math.min(SP.rows.length - 1, (i < 0 ? (d > 0 ? -1 : SP.rows.length) : i) + d))];
  showSel();
}
function key(e) {
  e.stopPropagation();   // 帯の操作（矢印＝再生位置・Delete・Ctrl+Z 等）に届けない
  if (e.key === 'Escape') { e.preventDefault(); close(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); move(e.key === 'ArrowDown' ? 1 : -1); return; }
  if (e.key === 'PageDown' || e.key === 'PageUp') { e.preventDefault(); move((e.key === 'PageDown' ? 1 : -1) * 8); return; }
  if (e.key === 'Enter' && !e.isComposing && (e.target === $('spQ') || e.target.closest('.spRow') || e.target === $('spDlg'))) {
    e.preventDefault(); if (SP.sel) choose(SP.sel); return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'o') { e.preventDefault(); close(); }
}
function choose(name) {
  close();
  if (name === S.song) return;
  A.openSong(name).catch(() => {});   // 失敗は openSong が札と下の列に出す
}
async function archive(name, on) {
  try {
    await api('POST', '/api/songs/archive', {song: name, on});
    const s = songOf(name); if (s) s.archived = on;
    const i = SP.rows.indexOf(name);
    if (SP.sel === name) SP.sel = SP.rows[i + 1] ?? SP.rows[i - 1] ?? null;   // 消えた行の次へ
    render(); label(S.song);
    A.status(on ? `${name} をアーカイブした（普段の一覧に出さない・曲を選ぶ窓の「アーカイブ」で見える・戻せる）` : `${name} を普段の一覧に戻した`);
    return true;
  } catch (e) { A.status('アーカイブを変えられなかった: ' + e.message, true); return false; }
}

// ---- 確かめ（見えない Edge）: #sptest[=arcview|q=字] → document.title と #sptestOut ----
export async function selfTest(arg = '') {
  const out = [], sleep = ms => new Promise(r => setTimeout(r, ms));
  const ok = (cond, what) => { out.push((cond ? 'OK ' : 'NG ') + what); return cond; };
  const shown = () => [...$('spList').querySelectorAll('.spRow')].map(el => el.dataset.song);
  const type = async q => { $('spQ').value = q; $('spQ').dispatchEvent(new Event('input')); await sleep(30); };
  const press = k => $('spQ').dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
  const done = () => { const t = out.join('\n'); document.title = 'sptest ' + (out.some(x => x.startsWith('NG')) ? 'NG' : 'OK') + ' ' + out.length;
    let pre = $('sptestOut'); if (!pre) { pre = document.createElement('pre'); pre.id = 'sptestOut'; pre.style.display = 'none'; document.body.appendChild(pre); } pre.textContent = t; };
  // 窓を開く（ボタンを押す）
  $('songBtn').click(); await sleep(400);
  ok(SP.open && getComputedStyle($('spDlg')).display !== 'none', `窓が開いた（曲 ${S.songs.length}・出ている行 ${shown().length}）`);
  ok(document.activeElement === $('spQ'), '検索の欄に字が打てる');
  const cur = shown()[0];
  ok(SP.sort !== 'recent' || cur === S.song, `最近開いた順の頭は今の曲（${cur}）`);
  ok(shown().every(n => !songOf(n).archived), 'アーカイブした曲は普段の一覧に出ない');
  if (arg.startsWith('q=')) { await type(decodeURIComponent(arg.slice(2))); out.push(`検索「${arg.slice(2)}」: ${shown().join('・')}`); done(); return; }
  // 検索（アーティストの頭 2 字・曲名の一部）
  const withArt = S.songs.find(s => s.artist && !s.archived);
  if (withArt) {
    const q = withArt.artist.slice(0, 2);
    await type(q.toUpperCase());
    const got = shown();
    ok(got.includes(withArt.song) && got.every(n => norm(`${songOf(n).title} ${songOf(n).artist} ${n}`).includes(norm(q))), `検索「${q.toUpperCase()}」→ ${got.length} 曲（${got.slice(0, 4).join('・')}）`);
  }
  await type('zzzzqqqq'); ok(shown().length === 0 && $('spList').textContent.includes('一致する曲が無い'), '一致しない検索は「一致する曲が無い」');
  await type('');
  // 並び替え
  $('spSort').querySelector('[data-k=name]').click(); await sleep(30);
  const nm = shown().map(n => songOf(n).title || n);
  ok(nm.every((x, i) => !i || nm[i - 1].localeCompare(x, 'ja', {numeric: true, sensitivity: 'base'}) <= 0), `名前順: ${nm.slice(0, 4).join('・')}…`);
  $('spSort').querySelector('[data-k=mtime]').click(); await sleep(30);
  const mt = shown().map(n => songOf(n).mtime);
  ok(mt.every((x, i) => !i || mt[i - 1] >= x), `更新日順: ${shown().slice(0, 3).map(n => `${n}（${dateText(songOf(n).mtime)}）`).join('・')}`);
  ok(lsGet('automap-songsort') === 'mtime', '並びを覚えた');
  $('spSort').querySelector('[data-k=recent]').click(); await sleep(30);
  // ↑↓
  const s0 = SP.sel; press('ArrowDown'); press('ArrowDown'); press('ArrowUp');
  ok(SP.rows.length < 2 || (SP.sel === SP.rows[Math.min(1, SP.rows.length - 1)] && SP.sel !== s0), `↓↓↑ で 2 行目（${SP.sel}）`);
  // アーカイブ（今の曲でない曲）→ 普段の一覧から消え、アーカイブの一覧に出る → 戻す
  const other = S.songs.find(s => s.song !== S.song && !s.archived);
  if (other) {
    if (arg === 'arcview') { await archive(other.song, true); $('spArc').click(); await sleep(50); out.push(`アーカイブの一覧: ${shown().join('・')}`); done(); return; }
    ok(await archive(other.song, true) && !shown().includes(other.song), `${other.song} をアーカイブ → 普段の一覧から消えた`);
    await A.loadSongs(); ok(songOf(other.song).archived === true, '一覧を読み直しても印がある');
    $('spArc').click(); await sleep(30);
    ok(shown().includes(other.song) && shown().every(n => songOf(n).archived), `アーカイブの一覧に出た（${shown().join('・')}）`);
    ok(await archive(other.song, false) && !shown().includes(other.song), '戻す → アーカイブの一覧から消えた');
    $('spArc').click(); await sleep(30);
    ok(shown().includes(other.song), '普段の一覧に戻った');
  }
  // 開いている曲をアーカイブ → 開いたまま・画面の保存（PUT /api/work）でも印が消えない → 戻す
  if (S.song && !S.readonly) {
    const me = S.song;
    await archive(me, true);
    ok(S.song === me && $('songBtn').classList.contains('arc'), '開いている曲をアーカイブしても開いたまま（上の列の曲名が薄い）');
    await A.saveWork(); await A.loadSongs();
    ok(songOf(me).archived === true, '画面の保存の後も印が残る');
    await archive(me, false); await A.loadSongs();
    ok(songOf(me).archived === false && !$('songBtn').classList.contains('arc'), '戻した');
  }
  // Esc で閉じる・Ctrl+O で開く・Enter で開く（今の曲＝閉じるだけ）
  press('Escape'); await sleep(30); ok(!SP.open, 'Esc で閉じた');
  document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'o', ctrlKey: true, bubbles: true, cancelable: true})); await sleep(30);
  ok(SP.open, 'Ctrl+O で開いた');
  done();
}
