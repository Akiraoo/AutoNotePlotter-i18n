// 譜面づくりのアプリの入り口: 曲を開く・上の操作の列・キー操作・作り直し（サーバーで compose を動かす）・NLM で開く。
import {S, $, fmt, beatOf, timeOf, api, on, emit, setWork, saveWork, undo, redo, canUndo, canRedo, commit, UI, setUI, lsGet, lsSet, diffText, locked} from './store.js';
import * as player from './player.js';
import * as tl from './timeline.js';
import * as insp from './inspector.js';
import * as pv from './preview.js';
import * as importer from './importer.js';
import * as versions from './versions.js';
import * as library from './library.js';
import * as rating from './rating.js';
import * as check from './check.js';
import * as repeats from './repeats.js';
import * as workio from './workio.js';
import * as pending from './pending.js';
import * as expand from './expand.js';
import * as setup from './setup.js';
import * as bsexport from './bsexport.js';
import * as replays from './replays.js';
import * as replaypane from './replaypane.js';
import * as update from './update.js';
import * as songpick from './songpick.js';

const {P, STEM} = player;

function status(msg, bad) { $('status').textContent = msg; $('status').classList.toggle('bad', !!bad); }
on('status', status);

// 曲の一覧（アーカイブした曲も入る＝曲を選ぶ窓が普段は隠す）。見えない選び #song は前からの口（確かめのページが値を変えて change を送る）
async function loadSongs() {
  S.songs = await api('GET', '/api/songs');
  $('song').replaceChildren(...S.songs.map(s => new Option(s.song, s.song)));
  if (S.song) $('song').value = S.song;
  songpick.refresh();
}
// 上の列の曲（見えない選び #song と、押すと曲を選ぶ窓が開く曲名 #songBtn・決まった幅で長い名前は省略＝全部はマウスを乗せた時）
function showSong(name) {
  $('song').value = name || ''; $('song').title = '曲: ' + (name || '');
  songpick.label(name);
}
// 曲を開く。読み込みの間（初めは解析の読み込みで数秒）は帯と 3D の上に「〇〇 を読み込んでいます…」（busy）。読み込みの間に別の曲を選んだら、
// 前の曲の読み込みは終わっても捨てる（後から選んだ曲が勝つ＝番号 OPEN.seq）。曲のデータと作業ファイルを両方読んでから一度に入れ替える
// （前は曲を入れ替えてから作業ファイルを読んでいて、続けて選ぶと前の曲の意思入れが次の曲の名前のまま残る間があった）。失敗は札と下の列に出し、
// 曲の選びの欄は今開いている曲に戻して、呼んだ側へ投げ直す
const OPEN = {seq: 0, end: null};
async function openSong(name) {
  const s = S.songs.find(q => q.song === name); if (!s) return;
  const my = ++OPEN.seq;
  if (OPEN.end) OPEN.end();   // 前に選んだ曲の読み込み中の札は消す（その読み込みは終わっても捨てる）
  const end = OPEN.end = busy(`${name} を読み込んでいます…`);
  try {
    if (S.file) await saveWork();
    if (my !== OPEN.seq) return;
    status(`${name} を読み込んでいる…（初めは解析の読み込みで数秒かかる）`);
    showSong(name);
    const D = await api('GET', '/api/song?file=' + encodeURIComponent(s.app_file));
    if (my !== OPEN.seq) return;   // 読み込みの間に別の曲を選んだ
    const W = await api('GET', '/api/work?file=' + encodeURIComponent(s.app_file));
    if (my !== OPEN.seq) return;
    D.notes0 = []; // v0.1 は比べる帯に出さない（D.notes4・D.notes5＝試作4・試作5 の版があれば・app/songdata.py）
    S.song = name; S.file = s.app_file; S.D = D; S.sel = []; S.cand = []; S.edit = null; S.panel = {}; S.t = 0;
    S.view = null;   // 曲を開いた時は基準の難易度を見る
    player.load(D);
    setWork(W);
    tl.reset(); tl.draw(); insp.refresh(); pv.setMap(); fileInfo(); renderDiffs();
    try { localStorage.setItem('automap-song', name); } catch (e) {}
    songpick.opened(name);   // 最近開いた順（画面の覚え automap-recent）
    status(`${name} を開いた` + (S.W.from ? `（意思入れは前の ${S.W.from} から引き継いだ）` : ''));
    end();
  } catch (e) {
    if (my !== OPEN.seq) return;
    end(`${name} を読み込めなかった: ${e.message}`);
    if (S.song) showSong(S.song);
    status(`${name} を読み込めなかった: ${e.message}`, true);
    throw e;
  } finally { if (OPEN.end === end) OPEN.end = null; }
}

// ---- 読み込み中の札（2026-11-09 利用者「曲のロードや切り替えで時間がかかる処理は、画面が空っぽのまま固まったかのように見える」）----
// busy(字) → 終わる関数 end(失敗の字?)。帯と 3D（#tl）の上を薄く覆い（その間は帯と 3D を触れない）、真ん中に小さな札（くるくる・字・
// 経過の秒数）。delay（既定 0.2 秒）より早く終われば出さない（ちらつかない）。重なった時は一番新しい物を出す。end() は何度呼んでもよい。
// end('…')＝失敗の札（赤い縁・「閉じる」・覆わない＝帯はすぐ触れる。次の busy か「閉じる」で消える）。ほかの受け持ちには app.busy で渡す
// （押してから数秒画面が変わらない操作に使う: 曲を開く・見る難易度・versions.js の版を見る・戻す・案を見る・選ぶ）。#tl の位置は versions.css が relative に
const BZ = {jobs: [], fail: null, tick: 0};
function busy(text, {delay = 200} = {}) {
  const job = {text, t0: Date.now(), on: false};
  job.timer = setTimeout(() => { job.on = true; busyDraw(); }, delay);
  BZ.jobs.push(job); BZ.fail = null; busyDraw();
  return fail => {
    clearTimeout(job.timer);
    const i = BZ.jobs.indexOf(job); if (i < 0) return;
    BZ.jobs.splice(i, 1);
    if (fail) BZ.fail = String(fail);
    busyDraw();
  };
}
function busyDraw() {
  let el = $('busy');
  if (!el) {
    el = document.createElement('div'); el.id = 'busy'; el.className = 'busy';
    el.innerHTML = '<div class="busyCard" role="status" aria-live="polite"><span class="genSpin busySpin"></span><span class="busyText"></span>' +
      '<span class="busySec"></span><button class="busyClose">閉じる</button></div>';
    el.querySelector('.busyClose').onclick = () => { BZ.fail = null; busyDraw(); };
    $('tl').appendChild(el);
  }
  const job = BZ.jobs.filter(j => j.on).pop();
  clearInterval(BZ.tick); BZ.tick = 0;
  el.classList.toggle('on', !!job || !!BZ.fail);
  el.classList.toggle('fail', !job && !!BZ.fail);
  const txt = el.querySelector('.busyText'), sec = el.querySelector('.busySec');
  if (job) {
    txt.textContent = job.text;
    const tick = () => { const n = Math.floor((Date.now() - job.t0) / 1000); sec.textContent = n >= 1 ? `${n} 秒` : ''; };
    tick(); BZ.tick = setInterval(tick, 500);
  } else if (BZ.fail) { txt.textContent = BZ.fail; sec.textContent = ''; }
}
function fileInfo() {
  const s = S.songs.find(q => q.song === S.song);
  $('fileInfo').innerHTML = s.app_exists ? `結果のファイル <b>${s.app_file}</b>` : `<b>${s.app_file}</b> はまだ無い（作り直すと作る。今見ているのは ${S.D.shown}）`;
  const nlmOk = setup.nlmOk();   // NLM の場所が決まっている（準備と設定）＝「NLM で開く」が使える
  $('nlm').disabled = !s.app_exists || !nlmOk;
  $('nlm').title = !nlmOk ? 'NLM の場所が決まっていません（「準備と設定」で NonLinearMapper.exe を選ぶと使えます）' : '結果のファイルを NLM で開く';
  $('bsExportBtn').disabled = !s.app_exists;
}

// ---- 見る難易度（docs/アプリ仕様.md 17 節） ----
// 上の列の「見る」: 基準と、ノーツのある派生の難易度。派生を選ぶと帯「作った譜面」（クリップの状態の色も）・3D・★がその難易度になる。
// 指示・作り直す・区間だけ作り直す・別の案・区間の点検はいつも基準に効く（その一言を出す）。作り直した後・履歴から戻した後は見ている
// 難易度のまま読み直す（無くなったら基準へ）。履歴の版・別の案を見ている間は基準だけ（版・案は基準の譜面）。
// 展開の窓は、派生を作り終えたら emit('diffs')（一覧を取り直す）・基準を置き直したら openSong（開き直す＝基準を見る）。
const DF = {seq: 0};
const baseOf = () => (S.D && S.D.base) || 'ExpertPlus';
const DIFF_RANK = ['ExpertPlus', 'Expert', 'Hard', 'Normal', 'Easy'];
function diffLabel(it) {
  const t = diffText(it.diff) + (it.role === 'base' ? '（基準）' : '（派生）');
  return t + (it.edited ? ` ✎${it.edited}` : '');   // ✎＝NLM で手で直したクリップの数
}
function renderDiffs() {
  const sel = $('viewDiff'); if (!sel || !S.D) return;
  const list = (S.D.diffs || []).filter(it => it.role === 'base' || it.notes > 0);
  if (!list.some(it => it.role === 'base')) list.push({diff: baseOf(), role: 'base', notes: 0, edited: 0});
  list.sort((a, b) => DIFF_RANK.indexOf(a.diff) - DIFF_RANK.indexOf(b.diff));   // 上＝難しい（展開の窓と同じ並び・2026-11-03 利用者）
  const cur = S.view || baseOf(), lock = !!versions.viewing();
  sel.innerHTML = list.map(it => `<option value="${it.diff}"${it.diff === cur ? ' selected' : ''}>${esc(diffLabel(it))}</option>`).join('');
  sel.disabled = lock || list.length < 2;
  sel.title = lock ? '履歴の版・別の案を見ている間は基準の難易度だけ（「見るのをやめる」で戻る）'
    : list.length < 2 ? '派生の難易度はまだ無い（「難易度を展開」で作る）'
    : list.map(it => `${diffText(it.diff)}: ${it.role === 'base' ? '基準' : '派生'}・ノーツ ${it.notes}${it.edited ? '・NLM で手で直したクリップ ' + it.edited : ''}${it.kept ? '・作り直しで残すクリップ ' + it.kept : ''}${it.export ? '' : '・書き出さない'}`).join('\n');
  const on_ = !!S.view, was = document.body.classList.contains('dfLock');
  $('viewNote').textContent = on_ ? '🔒' : '';   // 上の列は印だけ（すぐ下のロックの帯に言葉で出る・上の列を 1 段に収める 2026-11-09）
  $('viewNote').title = on_ ? `編集できない: ${diffText(S.view)}（派生）を見ている（帯「作った譜面」・3D・★）。指示・作り直す・ライブラリ・履歴・元に戻すは、基準の ${diffText(baseOf())} に戻ってから。派生を変える時は「難易度を展開」` : '';
  document.body.classList.toggle('dfViewing', on_);
  document.body.classList.toggle('dfLock', on_);
  const tag = $('dfTag'); if (tag) tag.textContent = on_ ? `🔒 ${diffText(S.view)}（派生）を見ている` : '';
  lockText();
  if (was !== on_) { emit('history'); insp.refresh(); tl.draw(); }   // 元に戻す・やり直す・右の欄のボタンの状態を取り直す
}
// ---- 派生を見ている間のロック（2026-11-03 利用者「展開した先の難易度を選んでいるときは、編集が基本的にできないようにボタンなどは
// 非活性化・基準の難易度に戻ってこないと編集できないようにロックして、そうなっている事が画面で全面的に分かるように」） ----
// 見え方: 窓の全体の枠（水色）・上の列の下の帯（何を見ているか・「基準に戻って編集する」・「難易度を展開…」）・右の欄（指示）と左下の
// 一覧を薄くして上に札・止めたボタン（class="lockable"）は薄く。止め方: lockable を押す・作業ファイルを変える操作（store.commit・元に戻す・
// やり直す）・作り直す・帯の量のラインと意思入れの操作は止めて、帯を光らせて知らせる（emit('locked')）。見る・再生・区間を選ぶ・3D・★・
// 「難易度を展開」はそのまま。履歴の版・別の案を見ている間は基準だけ（見る難易度を選べない）なので、ここには来ない
const LOCKABLE = ['gen', 'histBtn', 'libBtn', 'undo', 'redo', 'iRegen', 'iCands', 'iCandsRare', 'iCandsBand', 'wioLoad', 'wioClear'];
function lockUI() {
  const bar = document.createElement('div'); bar.id = 'lockBar'; bar.className = 'lockBar';
  bar.innerHTML = `<span class="lockIcon">🔒</span><span id="lockMsg"></span><span class="lockSpacer"></span>
    <button id="lockExpand" title="派生の量・型の範囲（★の帯・型の頻度・置き方の難しさ）を変えて、選んだ難易度だけ作り直す">難易度を展開…（派生を作り直す）</button>
    <button id="lockBack" class="main">基準の <span class="lockBase"></span> に戻って編集する</button>`;
  $('top').after(bar);
  [['insp', '右の欄の指示'], ['listPane', '付けた指示']].forEach(([id, what]) => {
    const c = document.createElement('div'); c.className = 'lockCover';
    c.innerHTML = `<b>🔒 <span class="lockView"></span>（派生）を見ている間は${what}を変えられない</b>
      <span class="sub">指示は基準の <span class="lockBase"></span> に付ける。派生は「難易度を展開」で作り直す</span>
      <button class="lockBackBtn">基準の <span class="lockBase"></span> に戻る</button>`;
    $(id).prepend(c);
  });
  const back = () => setView(null);
  $('lockBack').onclick = back;
  document.querySelectorAll('.lockBackBtn').forEach(b => b.onclick = back);
  $('lockExpand').onclick = () => $('expandBtn').click();
  LOCKABLE.forEach(id => { const el = $(id); if (el) el.classList.add('lockable'); });
  // 止めたボタン: 押す・選びを開く・Enter／Space を先に受けて止める（ほかの受け持ちの onclick まで届かない）
  const stop = e => { if (!locked() || !e.target.closest || !e.target.closest('.lockable')) return;
    if (e.type === 'keydown' && !['Enter', ' '].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation(); if (e.type !== 'mousedown') emit('locked'); };
  ['mousedown', 'click', 'keydown'].forEach(t => document.addEventListener(t, stop, true));
  on('locked', () => {
    status(`🔒 ${diffText(S.view)}（派生）を見ている間は編集できない。基準の ${diffText(baseOf())} に戻ってから（派生を変える時は「難易度を展開」）`, true);
    const b = $('lockBar'); b.classList.remove('flash'); void b.offsetWidth; b.classList.add('flash');
  });
}
function lockText() {
  if (!$('lockMsg')) return;
  $('lockMsg').innerHTML = S.view ? `<b>${esc(diffText(S.view))}（派生）を見ています</b>　編集はできません（指示・作り直す・ライブラリ・履歴・元に戻す）。` +
    `見る・再生・区間を選ぶ・3D・★はそのまま` : '';
  document.querySelectorAll('.lockBase').forEach(e => { e.textContent = diffText(baseOf()); });
  document.querySelectorAll('.lockView').forEach(e => { e.textContent = diffText(S.view); });
}
async function setView(d) {   // d＝難易度の名前（基準なら null に）
  const want = d && d !== baseOf() ? d : null;
  S.view = want;
  const end = busy(`${diffText(want || baseOf())} の譜面を読み込んでいます…`);
  try {
    await reloadChart();
    end();
    status(S.view ? `🔒 ${diffText(S.view)}（派生）を見ている＝編集できない（編集は基準の ${diffText(baseOf())} に戻ってから・派生は「難易度を展開」で作り直す）`
      : want ? `${diffText(want)} の譜面が無いので、基準の ${diffText(baseOf())} を見る` : `基準の ${diffText(baseOf())} を見ている`, !!want && !S.view);
  }
  catch (e) { end('その難易度を読めなかった: ' + e.message); status('その難易度を読めなかった: ' + e.message, true); }
}
on('diffs', () => { if (S.file) reloadChart().catch(e => status('難易度の一覧を読めなかった: ' + e.message, true)); });   // 展開の窓が派生を作った
on('chart', renderDiffs);   // 別の案・履歴の版を見た（基準だけ）・読み直した

// ---- 上の列 ----
function topbar() {
  $('song').onchange = e => openSong(e.target.value).catch(() => {});   // 失敗は openSong が札と下の列に出す
  $('viewDiff').onchange = e => setView(e.target.value);
  const tag = document.createElement('div'); tag.id = 'dfTag'; tag.className = 'dfTag'; $('tl').appendChild(tag);
  $('play').onclick = () => player.toggle();
  STEM.forEach((st, i) => { const b = document.createElement('button'); b.className = 'stem'; b.style.setProperty('--c', `var(${st.c})`);
    b.textContent = st.n; b.title = `キー ${i + 1}（Shift＋${i + 1} でこれだけ）`; b.onclick = () => { P.on[i] = !P.on[i]; player.applyOn(); }; $('stems').appendChild(b); });
  $('zin').onclick = () => tl.zoomBy(1 / 1.5); $('zout').onclick = () => tl.zoomBy(1.5);
  $('undo').onclick = undo; $('redo').onclick = redo;
  $('gen').onclick = e => e.shiftKey ? generate(undefined, true) : askGenerate();   // 作り直す（聞く窓・Shift＋クリック＝聞かずに全部作り直す）
  $('genAskPart').onclick = () => answerAsk(false); $('genAskAll').onclick = () => answerAsk(true); $('genAskNo').onclick = () => closeAsk();
  $('nlm').onclick = async () => { try { await api('POST', '/api/open-nlm', {file: S.file}); status('NLM で開いた'); } catch (e) { status(e.message, true); } };
  $('repClose').onclick = () => { $('rep').style.display = 'none'; };
  $('genOvHide').onclick = () => { GO.hidden = true; genOv(); };
  $('genOvStop').onclick = stopGenerate;
  $('genState').onclick = () => { if (GO.on) { GO.hidden = false; genOv(); } };   // 裏で続けている作り直しの窓をまた出す
  // 上の列の進み具合は空いている幅だけ（狭いと省略）＝全文はマウスを乗せた時。字を書くのはここと versions.js（別の案）なので、変わるたびに title をそろえる
  new MutationObserver(() => { const g = $('genState'), t = g.textContent;
    g.title = !t ? '' : t + (GO.on ? '\n（押すと作り直しの窓に戻る）' : ''); }).observe($('genState'), {childList: true, characterData: true, subtree: true});
  $('quit').onclick = async () => {   // 作業ファイルを保存してからサーバーを止める（app/stop.bat と同じ）
    if (!confirm('アプリを終わります（サーバーを止めます）。よいですか？')) return;
    await saveWork(); P.au.forEach(a => a.pause());
    try { await api('POST', '/api/shutdown', {}); } catch (e) {}
    document.body.innerHTML = '<div style="padding:3rem;font-size:1.3rem">アプリを終わりました。このタブを閉じてください。<br>また使う時は app\start.bat を起動します。</div>';
  };
  $('uiSize').value = String(UI.s); if (!$('uiSize').value) $('uiSize').value = '1.25';
  $('uiSize').onchange = e => { setUI(+e.target.value); layoutSizes(); };
  $('musVol').value = Math.round(lsGet('automap-musvol', 1) * 100); player.setVolume(+$('musVol').value / 100);
  $('musVol').oninput = e => { player.setVolume(+e.target.value / 100); lsSet('automap-musvol', +e.target.value / 100); };
  splitters();
  on('player', () => { $('play').textContent = player.busyPlaying() ? '⏸' : '▶';
    [...$('stems').children].forEach((b, i) => b.classList.toggle('off', !P.on[i])); });
  on('history', () => { $('undo').disabled = !canUndo(); $('redo').disabled = !canRedo(); });
  on('frame', () => { if (!S.D) return; const t = S.t;
    $('time').textContent = `${fmt(t)} / ${fmt(S.D.dur)}　拍 ${beatOf(t).toFixed(1)}`; });
}
// Space は画面のどこでも再生・停止（利用者 2026-10-26）。ボタン等に当たっている時に押すと、そのボタンが押されて選んでいる物がさらに
// 選ばれていた（ボタンは Space を離した時に押される）＝押す時も離す時も先に受けて止める。字を打つ欄の中だけは字のまま
const typing = el => !!el && (el.tagName === 'TEXTAREA' || el.isContentEditable ||
  (el.tagName === 'INPUT' && /^(text|search|number|email|url|tel|password)$/i.test(el.type || 'text')));
window.addEventListener('keydown', e => {
  if (e.code !== 'Space' || typing(e.target)) return;
  e.preventDefault(); e.stopPropagation();
  if (!e.repeat && S.D) player.toggle();
}, true);
window.addEventListener('keyup', e => { if (e.code === 'Space' && !typing(e.target)) { e.preventDefault(); e.stopPropagation(); } }, true);
document.addEventListener('keydown', e => {
  if (!S.D || e.target.closest('input, textarea, select')) return;
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); return; }
  if ((e.ctrlKey || e.metaKey) && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); redo(); return; }
  if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); saveWork(); return; }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (S.lineSel) { e.preventDefault(); tl.deleteKey(S.lineSel); return; }
    if (S.edit) { e.preventDefault(); const r = S.W.ranges.find(q => q.id === S.edit); if (r) emit('deleteDirective', r); return; }
  }
  if (e.key === 'Escape') { S.sel = []; S.cand = []; S.lineSel = null; S.edit = null; S.panel = {}; tl.hideMenu(); insp.refresh(); tl.draw(); return; }
  if (e.key === 'ArrowLeft') { player.seek(S.t - (e.shiftKey ? 1 : 5)); return; }
  if (e.key === 'ArrowRight') { player.seek(S.t + (e.shiftKey ? 1 : 5)); return; }
  if (e.key === 'Home') { player.seek(0); return; }
  const n = ['1', '2', '3', '4'].indexOf(e.key);
  if (n >= 0) { if (e.shiftKey) P.on.forEach((_, i) => { P.on[i] = i === n; }); else P.on[n] = !P.on[n]; player.applyOn(); }
  if (e.key === '0') { P.on.fill(true); player.applyOn(); }
});

// ---- 欄の大きさ（右の欄の幅・3D の高さ。ドラッグで変えて覚えておく） ----
function layoutSizes() {
  const side = lsGet('automap-side', 400 * UI.s);
  document.documentElement.style.setProperty('--side', Math.max(300, Math.min(innerWidth * 0.7, side)) + 'px');
  listRatio(lsGet(listKey(), null));
  fitLanes();
}
// 下の段の左右（付けた指示と 3D・2026-11-09 利用者「比率を変えられないのは理由があるのか」→ 理由は無かった）: 付けた指示の幅を下の段の幅
// （境目を除く）に対する割合で覚える（automap-listw・表示の大きさ・窓の幅が変わっても比率のまま）。null＝前の決め打ちの 1：1.7。
// 狭くても付けた指示は 15rem・3D は 36rem（上の「再生と音」の欄が畳んだ形で 1 段に入る幅）残す（app.css の #listPane の min-width・
// max-width・ドラッグもその間に止める）
// 左下の欄が「リプレイ」の時（js/replaypane.js）は別の比率を覚える（automap-listw-rp・既定は半分＝リプレイの 3D が見える幅）
const LIST_R = 1 / 2.7, RP_R = 0.5, LIST_MIN = 15, PV_MIN = 36;
const listRp = () => !!$('listPane') && $('listPane').classList.contains('rp');
const listKey = () => listRp() ? 'automap-listw-rp' : 'automap-listw';
function listRatio(r) { document.documentElement.style.setProperty('--listR', String(r == null ? (listRp() ? RP_R : LIST_R) : r)); }
on('listMode', () => listRatio(lsGet(listKey(), null)));
function listRatioAt(x) {   // 画面の横の位置 → 割合（両側の最小の幅の中に止める）
  const b = $('bottom').getBoundingClientRect(), sw = $('bsplit').offsetWidth, w = Math.max(1, b.width - sw);
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const lo = LIST_MIN * rem / w, hi = Math.max(lo, 1 - PV_MIN * rem / w);
  return Math.max(lo, Math.min(hi, (x - b.left - sw / 2) / w));
}
// 帯の高さ: 境目を動かしていれば（覚えておく）その高さ、無ければ帯の中身の高さ（タイムラインの 6 割まで）。残りは 3D
function fitLanes() {
  const tl = $('tl').getBoundingClientRect(), man = lsGet('automap-lanesh', null), content = $('lanes').clientHeight || 400;
  const fixed = $('ruler').offsetHeight + $('ovw').offsetHeight + $('hsplit').offsetHeight;
  const room = Math.max(120, tl.height - fixed - 140);
  const h = man != null ? Math.min(room, Math.max(100, man)) : Math.min(content + 2, (tl.height - fixed) * 0.5);
  document.documentElement.style.setProperty('--lanesH', Math.round(h) + 'px');
}
on('lanesDrawn', () => { if (lsGet('automap-lanesh', null) == null) fitLanes(); });
function splitters() {
  layoutSizes();
  const drag = (el, move, done) => el.addEventListener('mousedown', e => { e.preventDefault(); el.classList.add('drag');
    const mv = ev => move(ev), up = () => { el.classList.remove('drag'); window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up); done(); };
    window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up); });
  let side = 0, lh = 0;
  drag($('vsplit'), e => { side = Math.max(300, Math.min(innerWidth * 0.7, innerWidth - e.clientX - 4)); document.documentElement.style.setProperty('--side', side + 'px'); },
       () => { if (side) lsSet('automap-side', side); });
  drag($('hsplit'), e => { const r = $('lanesWrap').getBoundingClientRect(), tl = $('tl').getBoundingClientRect();
         lh = Math.max(100, Math.min(tl.bottom - r.top - $('ovw').offsetHeight - 140, e.clientY - r.top - $('ovw').offsetHeight));
         document.documentElement.style.setProperty('--lanesH', lh + 'px'); },
       () => { if (lh) lsSet('automap-lanesh', lh); });
  $('hsplit').ondblclick = () => { lsSet('automap-lanesh', null); fitLanes(); };   // ダブルクリックで自動（帯の中身の高さ）に戻す
  let lr = null;
  drag($('bsplit'), e => { lr = listRatioAt(e.clientX); listRatio(lr); }, () => { if (lr != null) lsSet(listKey(), +lr.toFixed(4)); lr = null; });
  $('bsplit').ondblclick = () => { lsSet(listKey(), null); listRatio(null); };   // ダブルクリックで元の比率（1：1.7）に戻す
  window.addEventListener('resize', layoutSizes);
}

// ---- 作り直し ----
// 「作り直す」を押すと聞く窓（案 D・2026-11-03 利用者「『寄せない』のチェックは意味が分かりにくい」）: 「変えた所だけ作り直す」（前の譜面に
// 寄せる＝いつも）か「全部作り直す」（寄せない）。指示の読み込み・全部外すの後（S.freshNext）は「全部」を選んだ状態にして訳を出す。
// まだ結果のファイルが無い曲（初めて作る）は寄せる前の譜面が無いので聞かずに作る。Shift＋クリックは聞かずに全部。
const ASK = {on: false, all: false};
function hasResult() { const s = S.songs.find(q => q.song === S.song); return !!(s && s.app_exists); }
function askGenerate() {
  if (!S.file || $('gen').disabled) return;
  if (locked()) { emit('locked'); return; }   // 派生を見ている間は作り直さない（基準に戻ってから）
  if (!hasResult()) { generate(); return; }
  ASK.on = true; ASK.all = !!S.freshNext;
  $('genAskNote').textContent = S.freshNext ? 'おすすめは「全部作り直す」（指示を読み込んだ・全部外した後なので、入れ直した指示を前と同じに効かせる）' : '';
  markAsk(); $('genAsk').style.display = 'flex'; (ASK.all ? $('genAskAll') : $('genAskPart')).focus();
}
function markAsk() { $('genAskPart').classList.toggle('on', !ASK.all); $('genAskAll').classList.toggle('on', ASK.all); }
function closeAsk() { ASK.on = false; $('genAsk').style.display = 'none'; }
function answerAsk(all) { closeAsk(); generate(undefined, all); }
window.addEventListener('keydown', e => {   // 聞く窓の中: Enter＝選んでいる方・Esc＝やめる・上下の矢印で選び替え
  if (!ASK.on) return;
  if (e.key === 'Escape') { e.preventDefault(); closeAsk(); }
  else if (e.key === 'Enter') { e.preventDefault(); answerAsk(document.activeElement === $('genAskAll') || (document.activeElement !== $('genAskPart') && ASK.all)); }
  else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); ASK.all = e.key === 'ArrowDown'; markAsk(); (ASK.all ? $('genAskAll') : $('genAskPart')).focus(); }
  e.stopPropagation();
}, true);
// fresh＝前の譜面に寄せない（全部を新しく・聞く窓の「全部作り直す」か Shift＋クリック）。既定は、前の作り直しから
// 指示を変えていない所を前の譜面に弱く寄せる（変えた区間とつなぎ目だけ変わる・docs/アプリ仕様.md 11 節）。
// 作っている間は真ん中に大きな窓（docs/アプリ仕様.md 16 節・利用者 2026-10-26: 上の小さな字だけでは計算中と分かりにくい）。経った秒・前に
// かかった秒から見込んだ棒・compose の最後の行。「裏で続ける」で隠すとほかの操作ができる（上の「作り直している…」を押すとまた出る）
const GO = {on: false, hidden: false, id: null, stopping: false};
function genOv() {
  $('genOv').style.display = GO.on && !GO.hidden ? 'flex' : 'none';
  const b = $('genOvStop'); b.disabled = !GO.id || GO.stopping; b.textContent = GO.stopping ? 'やめています…' : 'やめる（前の譜面のまま）';
}
// やめる（2026-11-03 利用者「譜面造りの途中でキャンセル出来るようなボタン」）: compose を止め、結果のファイル・報告は作り直しの前に戻す
// （server.cancel_job・start_generate）。止まったかは作り直しの見張り（generate の繰り返し）が job.cancelled で知る
async function stopGenerate() {
  if (!GO.id || GO.stopping) return;
  GO.stopping = true; genOv();
  try { await api('POST', '/api/job/cancel', {id: GO.id}); }
  catch (e) { GO.stopping = false; genOv(); status('やめられなかった: ' + e.message, true); }
}
const tookKey = only => `${S.song}|${only ? 'only' : 'all'}`;
function genProgress(sec, est, line) {
  $('genOvTime').textContent = `${sec} 秒`;
  $('genOvEst').textContent = est ? `（前は ${Math.round(est)} 秒）` : '';
  $('genOvBar').parentElement.classList.toggle('indet', !est);
  $('genOvBar').style.width = est ? Math.min(95, sec / est * 100).toFixed(1) + '%' : '';
  $('genOvLog').textContent = line;
}
async function generate(only, fresh = false) {   // only＝[拍の始まり, 終わり]: 選んだ区間だけ作り直す（外は今の譜面のまま）
  if (!S.file || $('gen').disabled) return;
  if (locked()) { emit('locked'); return; }
  await saveWork();
  const how = fresh ? '（前の譜面に寄せない）' : '';
  $('gen').disabled = true; $('genState').textContent = (only ? '選んだ区間だけ作り直している…' : '作り直している…') + how;
  emit('generating', true);
  const t0 = Date.now(), est = (lsGet('automap-took', {}) || {})[tookKey(only)];
  $('genOvTitle').textContent = only ? '選んだ区間だけ作り直しています' : '譜面を作り直しています';
  $('genOvSub').textContent = only ? `${fmt(timeOf(only[0]))}〜${fmt(timeOf(only[1]))}（外は今の譜面のまま）`
    : fresh ? '前の譜面に寄せない（全部を新しく作る）' : '指示を変えた所だけ新しく作り、ほかは前の譜面に寄せる';
  GO.on = true; GO.hidden = false; GO.id = null; GO.stopping = false; genProgress(0, est, ''); genOv();
  try {
    const body = only ? {file: S.file, only} : {file: S.file};
    if (fresh) body.opts = {anchor: false};
    const {id} = await api('POST', '/api/generate', body);
    GO.id = id; genOv();
    let j;
    for (;;) {
      await new Promise(r => setTimeout(r, 1000));
      j = await api('GET', '/api/job?id=' + id);
      const last = (j.log || '').trim().split('\n').pop() || '', sec = Math.round((Date.now() - t0) / 1000);
      $('genState').textContent = `${only ? '選んだ区間だけ' : ''}作り直している… ${sec} 秒${how}　${last.slice(0, 60)}`;   // 狭いと後ろから省略される＝秒を前に
      genProgress(sec, est, last.slice(0, 120));
      if (j.state !== 'running') break;
    }
    if (j.cancelled) { $('genState').textContent = '作り直しをやめた（譜面は前のまま）'; status('作り直しをやめた。結果のファイル・報告は作り直しの前のまま'); return; }
    if (j.state !== 'done') { $('genState').textContent = '作り直しに失敗した'; showReport('作り直しに失敗した', '<pre>' + esc(j.log || '') + '</pre>'); return; }
    if (j.took) { const t = lsGet('automap-took', {}) || {}; t[tookKey(only)] = j.took; lsSet('automap-took', t); }
    await reloadChart();
    const nb = ((S.D.diffs || []).find(x => x.role === 'base') || {}).notes ?? S.D.notes.length;   // 基準の難易度のノーツ（派生を見ていても）
    $('genState').textContent = `${only ? '選んだ区間だけ' : ''}作り直した${how}（${j.took} 秒・ノーツ ${nb}）`;
    showReport(only ? `選んだ区間（${fmt(timeOf(only[0]))}〜${fmt(timeOf(only[1]))}）だけ作り直した結果` : '作り直した結果', reportHTML(j.report || ''));
    emit('generated', {job: j, only});
  } catch (e) { $('genState').textContent = ''; status('作り直せなかった: ' + e.message, true); }
  finally { GO.on = false; GO.id = null; GO.stopping = false; genOv(); $('gen').disabled = false; S.freshNext = false; emit('freshNext', false); emit('generating', false); }
}
on('generateOnly', r => generate(r));
// 結果のファイルの譜面を読み直して帯と 3D に出す（作り直した後・履歴から戻した後・別の案を選んだ後・見る難易度を変えた時）。
// 見ている難易度（S.view）のまま。その難易度が無くなった（ノーツが 0 になった・消えた）ら基準へ
async function reloadChart() {
  const my = ++DF.seq, f = encodeURIComponent(S.file);
  let c = null;
  if (S.view) {
    try { c = await api('GET', `/api/chart?file=${f}&diff=${encodeURIComponent(S.view)}`); } catch (e) { c = null; }
    if (c && !(c.diffs || []).some(it => it.diff === S.view && it.notes > 0)) c = null;
    if (!c) { status(`${diffText(S.view)} の譜面が無くなったので、基準の難易度を見る`); S.view = null; }
  }
  if (!c) c = await api('GET', '/api/chart?file=' + f);
  if (my !== DF.seq) return;
  S.D.notes = c.notes; S.D.clips = c.clips; S.D.holes = c.holes;
  S.D.key = c.key; S.D.diff = c.diff; S.D.base = c.base; S.D.diffs = c.diffs;
  await loadSongs(); showSong(S.song); fileInfo();
  emit('chart'); tl.draw();
}
const esc = s => s.replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
function reportHTML(md) {   // 報告（<結果>.report.md）の、意思入れ・同じ振り・NLM で直した所・振りの数字の節だけを表にして見せる
  const want = /^## (意思入れ|同じ振り|NLM で直した所|残した|打ち方の数字|比べ)/;
  const out = []; let on_ = false;
  md.split('\n').forEach(l => { if (l.startsWith('## ')) on_ = want.test(l); if (on_ || /^- (打点|\*\*選んだ区間|型の出どころ|量の目安|前の譜面に寄せ)/.test(l)) out.push(l.replace(/\*\*/g, '')); });
  let html = '', tbl = null;
  const flush = () => { if (tbl) { html += '<table>' + tbl.join('') + '</table>'; tbl = null; } };
  out.forEach(l => {
    if (l.startsWith('|')) { if (/^\|[-| ]+\|$/.test(l)) return; const cells = l.split('|').slice(1, -1).map(c => esc(c.trim()));
      (tbl = tbl || []).push('<tr>' + cells.map(c => (tbl.length ? '<td>' : '<th>') + c + (tbl.length ? '</td>' : '</th>')).join('') + '</tr>'); return; }
    flush();
    if (l.startsWith('## ')) html += '<h3>' + esc(l.slice(3)) + '</h3>';
    else if (l.startsWith('- ')) html += '<div class="li">' + esc(l.slice(2)) + '</div>';
    else if (l.trim()) html += '<p>' + esc(l) + '</p>';
  });
  flush();
  return html || '<p>（報告が無い）</p>';
}
function showReport(title, html) { $('repTitle').textContent = title; $('repBody').innerHTML = html; $('rep').style.display = 'flex'; }

// ---- 始め ----
(async () => {
  window.anpBoot && anpBoot.set('画面を作る');   // 起動の段（index.html の起動の見張り・窓のアプリが記録に出す）
  setUI(UI.s);
  topbar(); tl.init(); insp.build();
  const boot = busy('アプリを準備しています…', {delay: 0});   // 最初の曲を開くまで（3D の準備・曲の一覧・最初の曲は openSong が自分の札を重ねる）
  let bootFail = null;
  window.anpBoot && anpBoot.set('3D の準備');
  await pv.init();
  // 曲の取り込み・別の案と履歴に渡す口（それぞれ importer.js・versions.js が受け持つ）
  const app = {loadSongs, openSong, reloadChart, status, showReport, reportHTML, esc, saveWork, busy, generate: () => askGenerate(),
    fileInfo: () => { if (S.song && S.D && S.songs.some(q => q.song === S.song)) fileInfo(); }};
  importer.init(app); versions.init(app); library.init(app); rating.init(app);
  repeats.init(app);   // 同じ音楽の区間（自動の同じ振り）を帯「作った譜面」の下の端に（決めの枠より先に足す＝下の端の帯ではこちらの見出しが先）
  check.init(app); workio.init(app); pending.init(app); expand.init(app); setup.init(app);
  bsexport.init(app);
  replays.init(app);   // 遊んだリプレイを BL のリプレイアプリで見る（上の列の「リプレイ」・docs/アプリ仕様.md 26 節）
  replaypane.init();   // 左下の欄の「リプレイ」（付けた指示と切り替え・リプレイと再生位置をそろえる）
  update.init(app);   // アプリの更新（上の列の版のボタン・docs/アプリ仕様.md 21 節）
  songpick.init(app);   // 曲を選ぶ窓（上の列の曲名・Ctrl+O）
  lockUI();   // 派生を見ている間のロック（ほかの受け持ちがボタンを作った後）
  try {
    window.anpBoot && anpBoot.set('曲の一覧');
    await loadSongs();
    // 最後に開いた曲: 最近開いた順の頭（画面の覚え＝アプリの設定にある・窓のアプリが別の番号で開いても同じ）・無ければこのブラウザの覚え
    let last = (lsGet('automap-recent', []) || [])[0] || null;
    if (!last) { try { last = localStorage.getItem('automap-song'); } catch (e) {} }
    const first = S.songs.find(s => s.song === last) || S.songs[0];
    window.anpBoot && anpBoot.set('最初の曲を開く');
    if (first) await openSong(first.song); else status('曲が無い（out/ の結果のファイルと cache/ の分けた音がそろった曲が要る）', true);
  } catch (e) { status('読み込めなかった: ' + e.message, true); bootFail = '読み込めなかった: ' + e.message; }
  boot(BZ.fail ? null : bootFail);   // 曲を開けなかった時は openSong の失敗の札のまま
  window.anpBoot && anpBoot.done();   // 起動の処理が最後まで動いた（曲を開けなかった時も＝字で知らせている・読み込み直さない）
  // 準備（作業の場所・音を分ける部品・型のライブラリ）が揃っているかを起動のたびに確かめ、足りなければ準備の窓（docs/アプリ仕様.md 21 節）
  if (location.hash.startsWith('#sutest')) await setup.selfTest(location.hash.split('=')[1] || 'first');
  else await setup.check();
  app.fileInfo();   // 「NLM で開く」は NLM の場所が決まっている時だけ（準備の様子を読んだ後に）
  // アプリの更新: 配布物で「起動した時に確かめる」がオンなら新しい版を確かめる（待たない・失敗は黙る）。#uptest=… は作り物の答えで
  if (location.hash.startsWith('#uptest')) await update.selfTest(location.hash.split('=')[1] || 'new'); else update.autoCheck();
  if (location.hash.startsWith('#bxtest')) await bsexport.selfTest(location.hash.split('=')[1] || 'ok');   // Beat Saber へ書き出す窓
  if (location.hash.startsWith('#rltest')) await replays.selfTest(location.hash.split('=')[1] || 'list');   // リプレイを見る窓（=list・=empty・=nodir・=open）
  if (location.hash.startsWith('#rstest')) await replaypane.selfTest(location.hash.split('=')[1] || 'fake');   // 左下の欄のリプレイと同期（=fake・=real）
  if (location.hash.startsWith('#sptest')) await songpick.selfTest(decodeURIComponent(location.hash.slice(8)));   // 曲を選ぶ窓（=arcview・=q=字）
  if (location.hash.startsWith('#bstest')) {   // 下の段の境目（付けた指示と 3D）のドラッグ: #bstest=割合[&hold（離さない＝ドラッグ中を画像に）|&dbl（離した後にダブルクリック）]
    const [f, ...o] = (location.hash.split('=')[1] || '0.6').split('&'), b = $('bottom').getBoundingClientRect(), bs = $('bsplit');
    const at = x => ({clientX: b.left + b.width * x, clientY: b.top + 40, bubbles: true});
    bs.dispatchEvent(new MouseEvent('mousedown', at(LIST_R)));
    for (let i = 1; i <= 6; i++) { window.dispatchEvent(new MouseEvent('mousemove', at(LIST_R + (+f - LIST_R) * i / 6))); await new Promise(r => setTimeout(r, 80)); }
    if (!o.includes('hold')) window.dispatchEvent(new MouseEvent('mouseup', at(+f)));
    if (o.includes('dbl')) bs.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
    await new Promise(r => setTimeout(r, 400));
    const w = id => Math.round($(id).getBoundingClientRect().width);
    const r = `listPane=${w('listPane')} pv=${w('pv')} bottom=${w('bottom')} --listR=${getComputedStyle(document.documentElement).getPropertyValue('--listR')} 覚え=${JSON.stringify(lsGet('automap-listw', null))} drag=${bs.classList.contains('drag')}` +
      ` 3Dの上の欄=${$('pvBar') ? $('pvBar').scrollWidth + '/' + $('pvBar').clientWidth + ($('pvBar').classList.contains('tight') ? '（畳んだ）' : '') : '-'}`;
    document.title = 'bstest ' + r; const el = document.createElement('pre'); el.id = 'bstestOut'; el.style.display = 'none'; el.textContent = r; document.body.appendChild(el);
  }
  if (location.hash.startsWith('#test')) selfTest();
  if (location.hash.startsWith('#ptest') && S.D) pending.selfTest(location.hash.split('=')[1] || '');   // 未反映の知らせ（=fold・=nofile・=lib）
  if (location.hash.startsWith('#dtest') && S.D) diffTest(decodeURIComponent(location.hash.slice(location.hash.indexOf('=') + 1 || location.hash.length)));   // 見る難易度（=Expert 等・&song=曲名）
  if (location.hash.startsWith('#cktest') && S.D) {   // 切る音の表が今の曲の物か（曲を切り替えた後も）→ document.title と #cktestOut
    const want = () => { const ns = S.D.notes.slice().sort((a, b) => a[0] - b[0]); let n = 0;
      for (let i = 0; i < ns.length;) { const t = ns[i][0]; while (i < ns.length && Math.abs(ns[i][0] - t) < 0.005) i++; n++; } return {n, first: ns.length ? ns[0][0] : null}; };
    const look = tag => { const c = pv.clickInfo(), w = want(); return `${tag}: 曲 ${S.song} 表 ${c.n}/${w.n} 最初 ${c.first}/${w.first} ${c.song === S.file && c.n === w.n && c.first === w.first ? 'OK' : 'NG'}`; };
    const out = [look('開いた曲')];
    const other = S.songs.find(q => q.song !== S.song);
    if (other) { await openSong(other.song); out.push(look('切り替えた曲')); }
    document.title = out.join(' ／ '); const el = document.createElement('pre'); el.id = 'cktestOut'; el.textContent = out.join(' ／ '); document.body.appendChild(el);
  }
  if (location.hash.startsWith('#asktest') && S.D) {   // 作り直す時に聞く窓（=fresh で指示を読み込んだ後のおすすめ）
    if (location.hash.includes('=fresh')) S.freshNext = true;
    askGenerate();
  }
  if (location.hash.startsWith('#pastetest')) {   // カバー画像の貼り付け（作り物の画像）→ document.title と #pastetestOut
    const r = await importer.pasteTest(); const el = document.createElement('pre'); el.id = 'pastetestOut'; el.textContent = JSON.stringify(r); document.body.appendChild(el);
  }
  if (location.hash.startsWith('#pvcam') && S.D) {   // 3D の見え方の確かめ（#pvcam=秒&h=高さ&d=距離&z=大きさ&cam=視点・その秒の譜面を出す）→ document.title と #pvcamOut
    const [sec, ...kv] = decodeURIComponent(location.hash.slice(7)).split('&'), o = Object.fromEntries(kv.map(x => x.split('=')));
    S.readonly = true; S.t = +(sec || 30);
    const r = JSON.stringify(pv.camTest(o)); document.title = 'pvcam ' + r;
    const el = document.createElement('pre'); el.id = 'pvcamOut'; el.style.display = 'none'; el.textContent = r; document.body.appendChild(el);
  }
  if (location.hash.startsWith('#gtest') && S.D) {   // 作り直しの間の窓（作り直さずに出すだけ・=noest で見込み無し）
    const noest = location.hash.includes('=noest');
    $('genOvTitle').textContent = '譜面を作り直しています'; $('genOvSub').textContent = '指示を変えた所だけ新しく作り、ほかは前の譜面に寄せる';
    GO.on = true; GO.id = 'gtest'; genProgress(23, noest ? null : 41, '== 作り直す'); genOv();
  }
})();
window.addEventListener('beforeunload', () => { saveWork(); });

// 確かめ用（見えない Edge）: #dtest=Expert[&song=曲名]＝その難易度を見る（帯・3D・★）→ document.title と #dtestOut（--dump-dom）に
// 見ている難易度・ノーツ・3D の難易度・選びの中身・★の字。=base で基準に戻すだけ
async function diffTest(arg) {
  const [d, ...rest] = arg.split('&'), sm = rest.find(x => x.startsWith('song='));
  if (sm && S.song !== sm.slice(5) && S.songs.some(q => q.song === sm.slice(5))) await openSong(sm.slice(5));
  S.readonly = true;
  await setView(d === 'base' ? null : d);
  const first = `view=${S.view} notes=${S.D.notes.length}`;
  if (rest.includes('reload')) await reloadChart();   // 作り直した後・戻した後と同じ読み直し（見ている難易度のまま）
  const B = S.D.mus.beats; tl.showRange(timeOf(B[16]), timeOf(B[24])); player.seek(timeOf(B[18]));
  const out = () => [`view=${S.view} base=${S.D.base} key=${S.D.key} notes=${S.D.notes.length} clips=${(S.D.clips || []).length}（選んだ直後 ${first}）`,
    `status=${$('status').textContent}`,
    `select=${[...$('viewDiff').options].map(o => (o.selected ? '*' : '') + o.textContent).join(' | ')} disabled=${$('viewDiff').disabled}`,
    `note=${$('viewNote').textContent}`, `tag=${($('dfTag') || {}).textContent}`, `star=${$('starInfo').textContent} / ${$('starInfo').title.replace(/\n/g, ' ')}`,
    `pvNjs=${($('pvNjs') || {}).value}`].join('\n');
  document.title = 'dtest ' + out().split('\n')[0];
  let pre = $('dtestOut'); if (!pre) { pre = document.createElement('pre'); pre.id = 'dtestOut'; pre.style.display = 'none'; document.body.appendChild(pre); }
  pre.textContent = out();
  setTimeout(() => { pre.textContent = out(); }, 8000);   // ★は後から来る
}
function selfTest() {   // 確かめ用（見えない Edge で開いて画像に写す）: #test＝区間を選び・指示を付け・量のラインに点を置く（保存はしない）
  S.readonly = true;
  const B = S.D.mus.beats;
  tl.selectRange(B[20], B[24]); S.panel = {amount: 1, hands: 1}; document.getElementById('iAdd').click();
  commit(W => { W.line.push({b: B[24], k: 1.3, smooth: false}, {b: B[40], k: 0.8, smooth: true}); });
  tl.showRange(timeOf(B[16]), timeOf(B[44])); player.seek(timeOf(B[22]));
  const mf = S.W.ranges.find(r => r.set.motif && r.set.motif.mode === 'arrange');   // 同じ振りがあれば、その形を光らせて写す
  if (mf) { S.hoverId = mf.id; tl.showRange(timeOf(mf.b0) - 20, timeOf(mf.b0) + 50); }
  const cam = decodeURIComponent(location.hash.split('=')[1] || '');   // #test=視点の名前（3D の視点を変えて写す）
  if (cam && document.getElementById('pvCam')) { const c = document.getElementById('pvCam'); c.value = cam; c.dispatchEvent(new Event('change')); player.seek(timeOf(B[29]) - 0.3); }
}
