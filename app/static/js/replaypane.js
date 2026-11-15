// 左下の欄の「リプレイ」（「付けた指示」と切り替え・2026-11-15 利用者「プレイ履歴をアプリ内で表示して、全部の再生位置を同期させて見たい」
// 「左下の指示の一覧の所を切り替えて、履歴表示させるか指示の一覧を表示するか切り替え出来るように」「プレイ履歴のスライダーを動かしたら、
// 本体のスライダーも動かして」「無理のあるプレイや少ないノーツの所に指示を入れるのにプレイ履歴を見ながら同期をとりながら」・docs/アプリ仕様.md 26 節）。
// - この曲のリプレイ（GET /api/replays?file=・新しい順）を選ぶと、BL のリプレイアプリを欄の中の iframe に開く（POST /api/replays/open の
//   使い捨ての鍵の場所）。iframe はアプリと別の番号（GET /api/blrview＝別のオリジン・app/server.py の ViewerH）から出す＝BL のリプレイアプリ
//   からアプリの画面・合言葉に触れない（別のタブで開く時の noopener と同じ守り）。sandbox で上の窓（アプリの画面）を動かせない。
// - やり取りは窓どうしの伝言だけ（static/blrembed/bridge.js・相手のオリジンと窓を確かめる・送る先のオリジンも決める）。
// - 「同期」の間（player.setLink）: 時刻の元はリプレイ。リプレイの再生・停止・帯の棒を動かす → アプリの帯・3D・時刻が付いてくる（player.follow）。
//   アプリで位置を変える（帯・ルーラー・キー・指示の ▶）→ リプレイも動く（送るのは 0.12 秒に 1 回まで・動き終わるまでリプレイの前の時刻は
//   使わない）。アプリの ▶・Space はリプレイを再生・停止する。音はリプレイの音（切る音入り）＝アプリの分けた音は鳴らさない。
//   つないだ時（開いた・欄を出した・同期を入れた）はリプレイをアプリの位置へ動かす。欄を「付けた指示」に戻すとリプレイを止めて外す。
// - 時刻: リプレイ（song.egg）の秒＝アプリの時刻（元の音源の秒）＋無音追加（S.D.lead）。書き出しは無音追加を音に焼き込む（automap/bs_export.py）。
//   遊んだ後に無音追加・Music の配置を変えた版はその分ずれる。
// 確かめ: #rstest（=fake＝作り物の窓で伝言のやり取り・=real＝この曲の一番新しいリプレイを本当に開いて動かす）→ #rstestOut
import {S, $, api, on, emit, lsGet, lsSet, fmt, DIFF_TEXT} from './store.js';
import * as player from './player.js';
import {reveal} from './timeline.js';

const P = player.P;
const R = {mode: 'list', song: null, rows: null, cur: null, want: null, origin: null, frame: null, ready: false, dur: 0, sync: true,
  hold: null, pend: null, timer: 0, hello: 0, lseq: 0, oseq: 0, t: null, playing: false, note: '', log: null, base: null, raf: 0, dt: 16, lastTick: 0};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const when = t => { const d = new Date(t * 1000), p = n => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`; };
const lead = () => (S.D && S.D.lead) || 0;
const post = m => { if (R.frame && R.frame.contentWindow && R.origin) R.frame.contentWindow.postMessage(Object.assign({anp: 'blr'}, m), R.origin); };
const L = {play: () => post({cmd: 'play'}), pause: () => post({cmd: 'pause'}), seek: t => seekReplay(t + lead())};   // player.setLink に渡す口
const linked = () => P.link === L;
// 欄の状態の印（#rpPane の data-state＝none・loading・ready・linked／data-t＝リプレイの秒）。「同期」の字はつないでいる間だけ緑（.on）
function mark() { const p = $('rpPane'); if (!p) return; p.dataset.state = linked() ? 'linked' : R.ready ? 'ready' : R.frame ? 'loading' : 'none';
  $('rpSync').parentElement.classList.toggle('on', linked()); }

function build() {
  $('rpPane').innerHTML = `<div class="rpBar"><select id="rpSel" title="この曲を遊んだリプレイ（新しい順）"></select>
    <label class="ck rpSync" title="同期: リプレイの再生・停止・時刻の棒にアプリの帯・3D・時刻が付いてくる。アプリの帯・キー・▶ でリプレイも動く（音はリプレイの音）"><input type="checkbox" id="rpSync"> 同期</label>
    <button id="rpReload" title="リプレイの一覧を読み直す（遊んだ直後など）・読み込めていない時は開き直す">↻</button>
    <button id="rpTab" title="このリプレイを別のタブで大きく開く（同期しない）">別のタブ</button></div>
    <div id="rpMsg" class="rpMsg" hidden></div>
    <div id="rpBox" class="rpBox"><div id="rpEmpty" class="rpEmpty sub"></div></div>`;
  document.querySelectorAll('#listPane .lpTabs button').forEach(b => { b.onclick = () => setMode(b.dataset.lp); });
  $('rpSel').onchange = () => { const r = (R.rows || []).find(x => x.id === $('rpSel').value); if (r) openRow(r); };
  R.sync = lsGet('automap-rpsync', true) !== false; $('rpSync').checked = R.sync;
  $('rpSync').onchange = () => { R.sync = $('rpSync').checked; lsSet('automap-rpsync', R.sync); if (R.sync) link(); else unlink(false); };
  $('rpReload').onclick = () => (R.cur && R.frame && !R.ready) ? openRow(R.cur) : loadList();   // 読み込めていない時は開き直す
  $('rpTab').onclick = openTab;
  window.addEventListener('message', onMessage);
}
function msg(t, bad) { const m = $('rpMsg'); m.hidden = !t; m.textContent = t || ''; m.classList.toggle('bad', !!bad); }
function empty(t, bad) { const e = $('rpEmpty'); e.hidden = !t; e.textContent = t || ''; e.classList.toggle('bad', !!bad); }

// ---- 欄の切り替え（覚える automap-lpane） ----
export function setMode(m) {
  m = m === 'replay' ? 'replay' : 'list';
  R.mode = m; lsSet('automap-lpane', m);
  document.querySelectorAll('#listPane .lpTabs button').forEach(b => b.classList.toggle('on', b.dataset.lp === m));
  $('iList').hidden = m !== 'list'; $('rpPane').hidden = m !== 'replay';
  $('listPane').classList.toggle('rp', m === 'replay');
  emit('listMode', m);   // 欄の幅（main.js がリプレイの時の比率に）
  if (m === 'replay') { if (S.file && (R.song !== S.file || !R.rows)) loadList(); else link(); }
  else unlink(true);
}

// ---- この曲のリプレイ ----
async function loadList() {
  if (!S.file) { empty('曲を開くと、この曲のリプレイが出ます'); return; }
  const file = S.file, seq = ++R.lseq;
  if (R.song !== file) { teardown(); R.song = file; R.rows = null; R.cur = null; $('rpSel').innerHTML = ''; }
  msg('リプレイを探しています…');
  try {
    const d = await api('GET', '/api/replays?file=' + encodeURIComponent(file));
    if (seq !== R.lseq || file !== S.file) return;
    R.rows = d.replays || [];
    msg('');
    $('rpSel').innerHTML = R.rows.map(r => {
      const acc = r.acc != null ? (r.acc * 100).toFixed(2) + '%' : '-';
      const miss = [r.misses ? `ミス ${r.misses}` : '', r.bad ? `バッド ${r.bad}` : '', r.fail ? '失敗' : '', r.exit ? 'やめた' : ''].filter(Boolean).join('・') || 'ミスなし';
      return `<option value="${esc(r.id)}"${r.map === 'none' ? ' disabled' : ''}>${esc(when(r.at))}　${esc(DIFF_TEXT[r.diff] || r.diff)}　${acc}　${esc(miss)}${r.modifiers ? '　' + esc(r.modifiers) : ''}</option>`;
    }).join('');
    if (!d.dirs || !d.dirs.length) { empty('リプレイの置き場が見つかりません（上の列の「リプレイ」の窓で場所を入れる）'); return; }
    if (!d.viewer) { empty('BL のリプレイアプリ（app/static/blreplay/）がありません。tools/blreplay_fetch.py で写してください', true); return; }
    if (!R.rows.length) { empty('この曲のリプレイはまだありません。Beat Saber に書き出して遊ぶと、ここに出ます（遊んだ後は ↻）'); return; }
    const pick = R.rows.find(r => r.id === R.want && r.map !== 'none') || (R.cur && R.rows.find(r => r.id === R.cur.id)) || R.rows.find(r => r.map !== 'none');
    R.want = null;
    if (!pick) { empty('どのリプレイも遊んだ時の譜面が見つかりません（この曲をまだ Beat Saber に書き出していない）'); return; }
    if (R.cur && R.cur.id === pick.id && R.frame) { $('rpSel').value = pick.id; link(); return; }
    openRow(pick);
  } catch (e) { if (seq === R.lseq) msg('リプレイの一覧を読めなかった: ' + e.message, true); }
}

async function openRow(r) {
  const seq = ++R.oseq, file = S.file;
  teardown(); R.cur = r; $('rpSel').value = r.id; msg('');
  matchDiff(r);
  empty('BL のリプレイアプリを開いています…');
  try {
    if (!R.origin) R.origin = (await api('GET', '/api/blrview')).origin;
    const o = await api('POST', '/api/replays/open', {file, id: r.id});
    if (seq !== R.oseq || file !== S.file) return;
    R.note = o.note || '';
    $('rpSel').title = `この曲を遊んだリプレイ（新しい順）\n今の物: ${R.note}`;
    frame(R.origin, o, S.t + lead());
  } catch (e) { if (seq === R.oseq) empty('開けなかった: ' + e.message, true); }
}
const viewUrl = (org, o, egg) => `${org}/static/blreplay/index.html?link=${encodeURIComponent(org + o.link)}`
  + (o.mapLink ? `&mapLink=${encodeURIComponent(org + o.mapLink)}` : '') + `&time=${Math.max(0, Math.round(egg * 1000))}`;   // time＝開いた時の位置（ミリ秒・止めたまま）

function frame(org, o, egg) {
  const f = document.createElement('iframe');
  f.className = 'rpFrame'; f.title = 'BL のリプレイアプリ';
  // 自動再生（アプリの ▶ でリプレイの音を始める）と全画面を渡す。許す先は * にする: Chromium の許しのリストは IPv6 の名前（[::1]）の
  // オリジンに合わず、既定（src のオリジン）も名前を書いても許されなかった（2026-11-15 に見えない Edge で確かめた・127.0.0.1 なら合う）。
  // 中身はこちらのリプレイの窓だけ（sandbox で上の窓は動かせない）
  f.allow = 'autoplay *; fullscreen *'; f.allowFullscreen = true; f.referrerPolicy = 'no-referrer';
  // 上の窓を動かさない（allow-top-navigation を付けない）・BeatLeader のページへのリンクは別のタブで
  f.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-pointer-lock allow-modals allow-downloads');
  f.src = viewUrl(org, o, egg);
  empty(''); $('rpBox').appendChild(f);
  R.frame = f; R.ready = false; mark();
  clearTimeout(R.wd);   // 読み込めない（BL のリプレイアプリが止まった等）時は知らせる＝↻ で開き直せる
  R.wd = setTimeout(() => { if (R.frame === f && !R.ready) msg('BL のリプレイアプリが 25 秒たっても読み込めていません。↻ で開き直してください', true); }, 25000);
  clearInterval(R.hello); R.hello = setInterval(() => post({cmd: 'hello'}), 300);   // 伝言の受け手が動き始めるまで呼ぶ（ready まで）
}
// アプリの「見る」（帯「作った譜面」・3D・★に出す難易度・上の列の #viewDiff）を開いたリプレイの難易度に合わせる（2026-11-15 利用者「一覧から
// ここで開くをしたら難易度指定がずれていた。難易度指定を合わせて開いてくれ」）。リプレイを開くたび（ここで見る・選ぶ欄・欄を出した時の
// 一番新しい物）。派生の難易度なら見ている間は編集できない（main.js の setView・ロック）＝指示は基準に戻って付ける。その難易度の譜面が
// 今の曲に無い・履歴の版や別の案を見ている（選べない）時は今のまま（知らせる）
function matchDiff(r) {
  const sel = $('viewDiff'), d = r && r.diff;
  if (!sel || !d || sel.value === d) return;
  const name = DIFF_TEXT[d] || d;
  if (![...sel.options].some(o => o.value === d)) { msg(`このリプレイの難易度（${name}）の譜面は今の曲に無いので、帯・3D は ${DIFF_TEXT[sel.value] || sel.value} のまま`); return; }
  if (sel.disabled) { msg(`履歴の版・別の案を見ている間は難易度を変えられないので、帯・3D は ${DIFF_TEXT[sel.value] || sel.value} のまま（リプレイは ${name}）`); return; }
  sel.value = d;
  sel.dispatchEvent(new Event('change'));   // main.js の setView（譜面を読み直す）
}
function teardown() {
  unlink(false);
  clearInterval(R.hello); R.hello = 0; clearTimeout(R.timer); R.timer = 0;
  if (R.frame) { R.frame.remove(); R.frame = null; }
  R.ready = false; R.hold = null; R.pend = null; R.t = null; R.playing = false; R.base = null; cancelAnimationFrame(R.raf); R.raf = 0;
  R.stopEnd = null; R.stopSent = false; clearTimeout(R.wd);
  empty(''); mark();
}

async function openTab() {   // 別のタブで大きく（アプリと同じ番号・noopener＝前からの「BL のリプレイで見る」と同じ）
  if (!R.cur || !S.file) return;
  try {
    const o = await api('POST', '/api/replays/open', {file: S.file, id: R.cur.id});
    if (linked() && R.playing) L.pause();
    window.open(viewUrl(location.origin, o, S.t + lead()), '_blank', 'noopener');
  } catch (e) { msg('開けなかった: ' + e.message, true); }
}

// ---- 同期 ----
function link() {
  if (!R.ready || !R.sync || R.mode !== 'replay' || !S.D || linked()) { mark(); return; }
  player.setLink(L);
  seekReplay(S.t + lead());   // つないだ時はリプレイをアプリの位置へ
  mark();
}
function unlink(pause) {
  if (!linked()) { mark(); return; }
  if (pause) L.pause();
  cancelAnimationFrame(R.raf); R.raf = 0;
  player.setLink(null);
  mark();
}
function seekReplay(egg) {
  if (R.dur) egg = Math.min(egg, R.dur - 0.01);
  R.pend = Math.max(0, egg);
  if (!R.timer) fire();
}
function fire() {   // 位置を送る（0.12 秒に 1 回まで・最後の位置は必ず送る）
  const t = R.pend; R.pend = null;
  post({cmd: 'seek', t});
  R.hold = {t, until: performance.now() + 1000};   // 動き終わるまで（その位置の時刻が来るか 1 秒）リプレイの前の時刻は使わない
  R.timer = setTimeout(() => { R.timer = 0; if (R.pend != null) fire(); }, 120);
}
function onMessage(e) {
  if (!R.frame || e.source !== R.frame.contentWindow || e.origin !== R.origin) return;
  const d = e.data;
  if (!d || d.anp !== 'blr') return;
  if (R.log) R.log.push(d.ev);
  if (d.ev === 'hi') { clearInterval(R.hello); R.hello = 0; return; }
  if (d.ev === 'ready') {
    R.ready = true; R.dur = +d.dur || 0; clearInterval(R.hello); R.hello = 0;
    // 記録が曲の終わりより前で終わっている（途中でやめた・失敗して落ちた）＝そこで止める（2026-11-15 利用者「途中でキャンセルしたプレイは、
    // キャンセルしたところで再生を止めてほしい」）。end＝.bsor の最後のフレームの時刻（app/replays.py・automap/bsor.py）。ノーフェイルの失敗は
    // 記録が終わりまで続くので止めない
    const e = R.cur && R.cur.end;
    R.stopEnd = e != null && R.dur && e < R.dur - 1 ? e : null;
    if (R.stopEnd != null) msg(`${R.cur.exit ? '途中でやめた' : R.cur.fail ? '失敗した' : '記録が途中で終わった'}プレイ: ${fmt(R.stopEnd - lead())}（リプレイの ${R.stopEnd.toFixed(1)} 秒）まで。そこで止めます`);
    link(); return;
  }
  if (d.ev !== 'time' || !isFinite(d.t)) return;
  R.t = +d.t; R.playing = !!d.playing; $('rpPane').dataset.t = R.t.toFixed(3);
  if (R.stopEnd != null && R.playing && R.t >= R.stopEnd) {   // 記録が終わった所で止める（同期を外していても）
    if (!R.stopSent) { R.stopSent = true; L.pause(); }
  } else if (!R.playing || R.t < R.stopEnd) R.stopSent = false;
  // 先読みの元（読んだ時刻・その時の壁の時計・速さ）。再生中はアプリの毎コマで「元＋経った時間×速さ」にする（tickFollow）＝伝言が届くまでの
  // 遅れ（1 コマ分・10〜20ms）とリプレイとアプリのコマのずれを埋める。速さはミスでスロー（BL の slow-mo）・速さの棒で変わる
  R.base = {t: R.t, at: isFinite(d.at) ? +d.at : wall(), sp: isFinite(d.speed) && d.speed > 0 ? +d.speed : 1};
  if (!linked()) return;
  if (R.hold) {
    if ((R.pend == null && Math.abs(R.t - R.hold.t) < 0.3) || performance.now() > R.hold.until) R.hold = null;
    else return;
  }
  if (!R.playing) { cancelAnimationFrame(R.raf); R.raf = 0; player.follow(R.t - lead(), false); reveal(); return; }   // 止めたままリプレイの棒で動かした＝帯もそこへ
  if (!R.raf) { player.follow(R.t - lead(), true); R.raf = requestAnimationFrame(tickFollow); }
}
const wall = () => performance.timeOrigin + performance.now();   // 壁の時計（ミリ秒）＝リプレイの窓の bridge.js と同じ物差し
// 1 コマ先を読む: アプリの 3D は自分のコマの頭で S.t を読んで描く（ここより先に動く）＝ここで決めた時刻は次のコマで描かれる。アプリの
// コマの間（R.dt・ならした値）だけ先を読んで、3D がリプレイと同じ時刻を描くようにする（2026-11-15・帯は 1 コマ先になるが見た目に出ない）
function tickFollow(now) {
  R.raf = 0;
  if (!linked() || !R.playing || !R.base) { R.lastTick = 0; return; }
  if (R.lastTick) R.dt = R.dt * 0.9 + Math.min(50, Math.max(1, now - R.lastTick)) * 0.1;
  R.lastTick = now;
  if (!R.hold) {
    const age = Math.max(0, Math.min(0.25, (wall() - R.base.at + R.dt) / 1000));   // 伝言が途切れても 0.25 秒より先は読まない
    player.follow(R.base.t + age * R.base.sp - lead(), true);
  }
  R.raf = requestAnimationFrame(tickFollow);
}


export function init() {
  build();
  on('song', () => {   // 曲を開いた（player.load）: 前の曲のリプレイを閉じる。リプレイの欄なら、この曲の一覧を読む
    teardown(); R.song = null; R.rows = null; R.cur = null; $('rpSel').innerHTML = '';
    if (R.mode === 'replay') loadList();
  });
  on('replayPane', id => {   // リプレイの窓の「ここで見る」（js/replays.js）
    const r = R.song === S.file && (R.rows || []).find(x => x.id === id);
    if (R.mode !== 'replay') { R.want = id; setMode('replay'); if (!r) return; }
    if (r) openRow(r); else { R.want = id; loadList(); }
  });
  setMode(lsGet('automap-lpane', 'list'));
}

// ---- 確かめ（#rstest=fake|real） ----
// fake: 欄の中に作り物の窓（この画面と同じオリジンの空のページ・伝言の受け手の代わりをここで書く）を置き、つなぐ・アプリで動かす・リプレイで
//   動かす・再生・止める・外すの伝言と S.t を確かめる。real: この曲の一番新しいリプレイを本当に開き、ready を待ってアプリで動かし、リプレイの
//   時刻が付いてくるか・リプレイを動かして帯が付いてくるかを見る（BL のリプレイアプリ・譜面の読み込みに数秒）。
export async function selfTest(kind) {
  kind = String(kind || 'fake').split('&')[0];
  const out = [], sleep = ms => new Promise(r => setTimeout(r, ms));
  const until = async (fn, ms) => { const t0 = Date.now(); while (!fn()) { if (Date.now() - t0 > ms) return false; await sleep(50); } return true; };
  const show = () => { const el = document.createElement('pre'); el.id = 'rstestOut'; el.style.display = 'none'; el.textContent = out.join('\n'); document.body.appendChild(el); document.title = 'rstest ' + out[0]; };
  if (!S.D) { out.push('曲が無い'); show(); return; }
  if (kind === 'fake') {
    setMode('replay');
    await until(() => R.rows !== null || $('rpEmpty').textContent, 5000);
    R.lseq++; R.oseq++; teardown(); R.origin = location.origin; R.log = [];   // 読み始めた本物の一覧・窓は捨てる
    R.song = S.file; R.rows = R.rows || [];
    const sent = [];
    const f = document.createElement('iframe'); f.className = 'rpFrame'; $('rpBox').appendChild(f); R.frame = f;
    await sleep(100);
    f.contentWindow.addEventListener('message', e => { if (e.data && e.data.anp === 'blr') sent.push(e.data); });
    const say = m => window.dispatchEvent(new MessageEvent('message', {data: Object.assign({anp: 'blr'}, m), origin: R.origin, source: f.contentWindow}));
    player.seek(10);
    say({ev: 'ready', dur: S.D.dur + lead()});
    await sleep(50);
    out.push(`つないだ=${linked()} 送った seek=${JSON.stringify(sent.filter(m => m.cmd === 'seek').map(m => +m.t.toFixed(3)))} 期待=${(10 + lead()).toFixed(3)}`);
    say({ev: 'time', t: 3, playing: false});   // 動き終わる前の古い時刻（使わない）
    out.push(`古い時刻を使わない: S.t=${S.t.toFixed(3)}`);
    say({ev: 'time', t: 10 + lead(), playing: false});
    say({ev: 'time', t: 20 + lead(), playing: true});
    out.push(`リプレイで動かす: S.t=${S.t.toFixed(3)} 再生中=${player.busyPlaying()} ▶=${$('play').textContent}`);
    sent.length = 0; player.seek(30); player.seek(31); player.seek(32); await sleep(400);
    out.push(`アプリで動かす（3 回続けて）: 送った=${JSON.stringify(sent.map(m => m.cmd + (m.t != null ? ':' + m.t.toFixed(2) : '')))}`);
    sent.length = 0; player.toggle(); await sleep(50);
    out.push(`▶/Space（再生中）→ ${JSON.stringify(sent.map(m => m.cmd))}`);
    say({ev: 'time', t: 32 + lead(), playing: false});
    sent.length = 0; player.playRange(40, 41); await sleep(200);
    say({ev: 'time', t: 39.7 + lead(), playing: false});
    say({ev: 'time', t: 39.8 + lead(), playing: true});
    say({ev: 'time', t: 41.3 + lead(), playing: true});
    await sleep(50);
    out.push(`区間の再生: 送った=${JSON.stringify(sent.map(m => m.cmd + (m.t != null ? ':' + m.t.toFixed(2) : '')))}`);
    sent.length = 0; setMode('list'); await sleep(50);
    out.push(`欄を戻す: つないだ=${linked()} 送った=${JSON.stringify(sent.map(m => m.cmd))} 自分の音の位置=${P.au[0] ? P.au[0].currentTime.toFixed(2) : '-'} S.t=${S.t.toFixed(2)}`);
    say({ev: 'time', t: 50, playing: true});
    out.push(`外した後のリプレイの時刻は使わない: S.t=${S.t.toFixed(2)}`);
    const bad = document.createElement('iframe'); document.body.appendChild(bad);
    setMode('replay'); R.frame = f; R.ready = true; link();
    window.dispatchEvent(new MessageEvent('message', {data: {anp: 'blr', ev: 'time', t: 70, playing: false}, origin: 'http://evil.example', source: f.contentWindow}));
    window.dispatchEvent(new MessageEvent('message', {data: {anp: 'blr', ev: 'time', t: 71, playing: false}, origin: R.origin, source: bad.contentWindow}));
    await sleep(1100); say({ev: 'time', t: 72 + lead(), playing: false});
    out.push(`ほかのオリジン・ほかの窓の伝言は使わない: S.t=${S.t.toFixed(2)}（72 のはず）`);
    teardown(); setMode('list'); bad.remove(); R.log = null; R.origin = null;
    out.unshift('fake ok');
    show(); return;
  }
  // real
  setMode('replay');
  const ok = await until(() => R.ready, 60000);
  out.push(`ready=${ok} 開いたリプレイ=${R.cur ? R.cur.id : '-'} 長さ=${R.dur.toFixed(1)} 知らせ=${R.note || $('rpEmpty').textContent}`);
  if (!ok) { show(); return; }
  await sleep(1500);
  const t1 = Math.min(S.D.dur - 5, 30);
  player.seek(t1);
  await until(() => R.hold === null && R.t != null && Math.abs(R.t - (t1 + lead())) < 0.3, 8000);
  await sleep(300);
  out.push(`アプリで ${t1} 秒へ: リプレイ=${R.t != null ? (R.t - lead()).toFixed(3) : '-'} S.t=${S.t.toFixed(3)}`);
  post({cmd: 'seek', t: 60 + lead()});   // リプレイの側で動かした時と同じ（bridge が song-controls の seek を呼ぶ）
  await until(() => Math.abs(S.t - 60) < 0.3, 8000);
  await sleep(300);
  out.push(`リプレイで 60 秒へ: S.t=${S.t.toFixed(3)} リプレイ=${(R.t - lead()).toFixed(3)}`);
  player.play();
  await until(() => R.playing, 8000);
  await sleep(2000);
  out.push(`再生: リプレイ再生中=${R.playing} S.t=${S.t.toFixed(2)} リプレイ=${(R.t - lead()).toFixed(2)} ▶=${$('play').textContent}`);
  player.pause();
  await until(() => !R.playing, 8000);
  out.push(`止める: リプレイ再生中=${R.playing}`);
  out.unshift('real ' + (ok ? 'ok' : 'ng'));
  show();
}
