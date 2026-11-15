// 準備と設定（app/setup.py・docs/アプリ仕様.md 21 節）。main.js が init(app) と check() を呼ぶ。
// 利用者と決めたこと（2026-11-03）: 音を分ける部品は初回の設定画面でインストールする・起動のたびに揃っているかを確かめ、足りなければ
// 続きからインストールし直す案内を出す（部品が無いと動かない）・インストールの前に必要な容量とインストール先を必ず予告する・何に使うかを
// 必ず説明する（ノーツの置き方は BeatLeader のランク譜面の型で自動で決める＝音を分ける部品は曲を理解するための物）・★を測る部品
// （nlm-rating）も必須。大きさは「ダウンロード」と「展開後」を分けて書く（2026-11-03 利用者「意味が分からない」）。
// 版の 2 段（2026-11-03 利用者）: 音を分ける部品の版が、このアプリの版で動作を確かめた組と違っても、最低の版以上で使ってはいけない版
// （NG）でなければ止めない＝2. の欄に「おすすめの状態ではありません」（変わる部品・差分のダウンロード量・更新する／あとで）と上の列の
// 「準備と設定」に小さな印。最低の版より古い・NG・入っていない・壊れている時は今と同じく止める（必須の更新・訳つき）。確かめた組そのものに
// NG がある時は部品の入れ直しでは直らない＝「アプリの更新が必要です」から更新の窓へ（update.js）。NG はアプリの更新の確かめが設定に控える。
// 言葉の決まり: ダウンロード・インストール・展開後・インストール先・空き容量・更新（「取ってくる」「入れる」は使わない）。
// 確かめ: #sutest（=first・=resume・=running・=ok・=dev・=move・=rec・=must・=appng・=planng）＝作り物の様子で窓を出す（サーバーに書かない）
//   → #sutestOut（--dump-dom）
import {$, api} from './store.js';
import * as update from './update.js';

let A = null;          // main.js の口（status・loadSongs）
let ST = null;         // /api/setup/status の答え
let PLAN = null;       // /api/setup/plan の答え（今のインストール先・種類）
let PLAN_ERR = '';
let VARIANT = null;    // 選んだ種類（cu128・cu126・cpu）
let SEP_EDITED = false;   // インストール先を自分で変えた（作業フォルダを変えても既定に戻さない）
let JOB = null, timer = 0;
let FAKE = null;       // #sutest の作り物
let REINSTALL = false; // インストール済みの時に「インストールし直す…」を押した（インストールの欄を開く）
let TOLD_REC = false;  // おすすめの更新を下の列で知らせた（起動して 1 回だけ）
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const gb = n => n == null ? '?' : n >= 100e9 ? `${Math.round(n / 1e9)}GB` : n >= 1e9 ? `${(n / 1e9).toFixed(1)}GB` : `${Math.max(1, Math.round(n / 1e6))}MB`;
const GPU = v => v && v !== 'cpu';
const VTEXT = v => GPU(v) ? 'GPU 版' : 'CPU 版';
const VSUB = v => GPU(v) ? 'NVIDIA のグラフィックボードで計算します。4 分の曲を約 1 分で分けます'
  : 'グラフィックボードを使いません。4 分の曲を約 5 分で分けます（GPU 版より遅い）';
// ダウンロードする物の名前と用途（sep_install.plan の key ごと。知らない key は道具の文のまま）
const ITEM = {
  torch: ['PyTorch', '音を分ける計算に使う部品（GPU 版はグラフィックボードで速く計算する）'],
  libs: ['Demucs と、それが使う小さな部品', '曲を歌・ドラム・ベース・その他の4つの音に分けるプログラム（Meta が公開している物）'],
  weights: ['Demucs の学習済みモデル（htdemucs_ft）', '4つの音を聞き分けるためのデータ（Demucs の作者が公開している物）'],
  pip: ['pip', '部品をインストールする道具（インストールの時だけ使い、終わったら消す）'],
  python: ['Python', '上の部品を動かすためのもの（アプリに入っている Python をコピーするので、ダウンロードしない）'],
};
const itemText = it => ITEM[it.key] || [it.name, it.what];

async function call(method, url, body) {
  if (FAKE) return FAKE.api(method, url, body);
  return api(method, url, body);
}

function build() {
  const d = document.createElement('div');
  d.id = 'suDlg'; d.className = 'modal su';
  d.innerHTML = `<div class="dlg">
  <div class="dlgHead"><b>Auto Note Plotter の準備</b><span class="sub" id="suHeadSub"></span><button id="suClose">閉じる</button></div>
  <div class="dlgBody">
    <div id="suAlert" class="suAlert" hidden></div>
    <section class="suAbout">
      <h3>このアプリのしくみ</h3>
      <p>Auto Note Plotter は、Beat Saber の譜面を自動で作るアプリです。</p>
      <p><b>ノーツの置き方</b>（どこに置くか・左右どちらの手で切るか・どの向きに切るか）は、<b>BeatLeader のランク譜面から集めた「型」</b>
        （人が作った譜面によく出てくる、数回の振りのまとまり）を組み合わせて、決まりと計算で自動的に決めます。ノーツを置くのに AI（学習済みのモデル）は使いません。</p>
      <p>ノーツを置く前に<b>曲を理解します</b>。曲を「歌・ドラム・ベース・その他」の4つの音に分けて、歌が入る所・ドラムが鳴る所・盛り上がる所を調べ、
        ノーツを置くタイミングの手がかりにします。</p>
      <p>学習済みのモデルを使うのは、次の2つの部品だけです。<b>どちらも譜面は作りません</b>。</p>
      <ul><li><b>音を分ける部品</b>（Demucs・PyTorch）: 曲を4つの音に分ける、曲を理解するための部品</li>
        <li><b>★を測る部品</b>（nlm-rating）: できた譜面の難しさ（★）を BeatLeader と同じ計算で見積もる部品（BeatLeader の計算に入っている学習済みのモデルをそのまま使います）</li></ul>
    </section>
    <section class="suSec" id="suWork">
      <h3><span class="suMark" id="suWorkMark"></span>1. 作業フォルダ</h3>
      <p class="sub">作った譜面（NLM のプロジェクトファイル .nlmf）と、曲を分けた音（歌・ドラムなど）を保存するフォルダです。1 曲につき約 100MB 使います。</p>
      <div class="suRow" id="suWorkSetRow"><input id="suWorkPath" spellcheck="false" placeholder="例 D:\\AutoNotePlotter"><button id="suWorkPick">フォルダを選ぶ…</button>
        <button id="suWorkSet" class="main">このフォルダにする</button></div>
      <div id="suWorkMsg" class="suMsg"></div>
      <div class="suRow" id="suWorkNow" hidden><span class="sub">作業フォルダを別の場所（別のドライブなど）へ移したい時は</span><button id="suMoveOpen">作業フォルダを引っ越す…</button></div>
      <div id="suMove" class="suMove" hidden>
        <p class="sub">作業フォルダの中身（作った譜面・分けた音・音を分ける部品）を全部、新しいフォルダへ移します。同じドライブの中ならすぐ終わります。
          別のドライブなら、全部コピーして確かめてから元を消します（途中で止めても元はそのまま残ります）。作った譜面の中に書かれた場所も新しい場所に直します。</p>
        <div class="suRow"><label for="suMovePath">引っ越し先</label><input id="suMovePath" spellcheck="false" placeholder="例 E:\\AutoNotePlotter（空のフォルダか、まだ無い名前）">
          <button id="suMovePick">フォルダを選ぶ…</button></div>
        <div id="suMovePlan" class="suNotice"></div>
        <div id="suMoveRun" class="suRun" hidden><div id="suMoveLabel" class="suRunLabel"></div><div class="suBar"><div id="suMoveBar"></div></div>
          <div class="sub" id="suMoveMsg"></div></div>
        <div class="suRow suActs"><span class="sub" id="suMoveNote"></span><button id="suMoveCancel">やめる</button><button id="suMoveGo" class="main" disabled>引っ越す</button></div>
      </div>
    </section>
    <section class="suSec" id="suSep">
      <h3><span class="suMark" id="suSepMark"></span>2. 音を分ける部品（曲を理解するための部品）</h3>
      <p class="sub">曲を歌・ドラム・ベース・その他の4つの音に分けて、ノーツを置くタイミングの手がかり（歌の始まり・ドラムの音・盛り上がり）を取り出します。
        ノーツの置き方は決めません。この部品が無いと、新しい曲を取り込めません。</p>
      <div id="suSepState"></div>
      <div id="suUpd" class="suUpd" hidden></div>
      <div id="suSepSetup">
        <div id="suGpu" class="suGpu"></div>
        <div id="suVariants" class="suVariants"></div>
        <div class="suRow"><label for="suSepPath">インストール先</label><input id="suSepPath" spellcheck="false"><button id="suSepPick">フォルダを選ぶ…</button></div>
        <table id="suItems" class="suItems"></table>
        <div id="suNotice" class="suNotice"></div>
        <div class="suRow suActs"><span class="sub" id="suSepNote"></span><button id="suInstall" class="main">インストールする</button></div>
      </div>
      <div id="suRun" class="suRun" hidden>
        <div id="suRunLabel" class="suRunLabel"></div>
        <div class="suBar"><div id="suBarIn"></div></div>
        <div class="suRow"><span class="sub" id="suRunMsg"></span><button id="suStop" title="一時停止しても、次に「続きからインストールする」でダウンロード済みの所から再開できます">一時停止（あとで続きから）</button></div>
      </div>
    </section>
    <section class="suSec" id="suRat">
      <h3><span class="suMark" id="suRatMark"></span>3. ★を測る部品（nlm-rating）</h3>
      <p class="sub">できた譜面の難しさ（★）を、BeatLeader と同じ計算で見積もります。ノーツの速さ（NJS）を決める時と、難易度（Expert・Hard など）を
        作り分ける時の目安に使います。アプリに同梱しているので、インストールは要りません。</p>
      <div id="suRatState"></div>
      <div class="suRow" id="suRatRow" hidden><label for="suRating">nlm-rating</label><input id="suRating" spellcheck="false" placeholder="nlm-rating.exe の場所">
        <button data-pick="suRating">ファイルを選ぶ…</button><button data-save="nlm_rating_exe" data-from="suRating">決める</button></div>
    </section>
    <section class="suSec" id="suLib">
      <h3><span class="suMark" id="suLibMark"></span>4. 型のライブラリ</h3>
      <div id="suLibState"></div>
    </section>
    <section class="suSec" id="suOpt">
      <h3><span class="suMark" id="suNlmMark"></span>5. NLM（なくてもアプリは動きます）</h3>
      <p class="sub">作った譜面を NLM（Non-Linear Mapper）で開いて、手直し・ライティングをします。Beat Saber への書き出しは、NLM が無くてもこのアプリからできます（上の「Beat Saber に書き出す」）。</p>
      <div class="suRow"><label for="suNlm">NLM</label><input id="suNlm" spellcheck="false" placeholder="NonLinearMapper.exe の場所">
        <button data-pick="suNlm">ファイルを選ぶ…</button><button data-save="nlm_exe" data-from="suNlm">決める</button></div>
      <div id="suOptMsg" class="suMsg"></div>
    </section>
    <div class="suFoot"><span id="suFootMsg" class="sub"></span><button id="suStart" class="main">始める</button></div>
  </div></div>`;
  document.body.appendChild(d);
  $('suClose').onclick = close;
  $('suWorkPick').onclick = () => pick('folder', 'suWorkPath');
  $('suSepPick').onclick = () => pick('folder', 'suSepPath', () => { SEP_EDITED = true; loadPlan(); });
  $('suWorkSet').onclick = setWork;
  $('suMoveOpen').onclick = () => { $('suMove').hidden = false; $('suWorkNow').hidden = true; $('suMovePath').focus(); movePlan(); };
  $('suMoveCancel').onclick = () => { if (MOVE) return; $('suMove').hidden = true; render(); };
  $('suMovePick').onclick = () => pick('folder', 'suMovePath', movePlan);
  $('suMovePath').oninput = () => { clearTimeout(moveTimer); moveTimer = setTimeout(movePlan, 400); };
  $('suMoveGo').onclick = moveGo;
  $('suSepPath').onchange = () => { SEP_EDITED = true; loadPlan(); };
  $('suInstall').onclick = () => install(VARIANT, $('suSepPath').value);
  $('suStop').onclick = stop;
  $('suStart').onclick = finish;
  d.querySelectorAll('[data-pick]').forEach(b => { b.onclick = () => pick('exe', b.dataset.pick); });
  d.querySelectorAll('[data-save]').forEach(b => { b.onclick = () => saveOpt(b.dataset.save, $(b.dataset.from).value); });
}

async function pick(kind, inputId, then) {
  try {
    const r = await call('POST', '/api/setup/pick', {kind, initial: $(inputId).value});
    if (r.path) { $(inputId).value = r.path; if (then) then(); }
  } catch (e) { msg(inputId === 'suWorkPath' ? 'suWorkMsg' : 'suOptMsg', '選ぶ窓を出せませんでした（場所を文字で入れてください）: ' + e.message, true); }
}

function msg(id, text, bad) { const el = $(id); el.textContent = text || ''; el.classList.toggle('bad', !!bad); }

// ---- 作業フォルダの引っ越し（app/relocate.py・2026-11-03 利用者「作業フォルダを後から動かす事ができるような仕組みとメニュー」） ----
let MOVE = null, moveTimer = 0;
async function movePlan() {
  const dir = $('suMovePath').value.trim();
  if (!dir) { $('suMovePlan').innerHTML = '<span class="sub">引っ越し先のフォルダを選んでください</span>'; $('suMoveGo').disabled = true; return; }
  try {
    const p = await call('GET', `/api/setup/move-plan?dir=${encodeURIComponent(dir)}`);
    const ok = !(p.problems || []).length;
    $('suMovePlan').className = 'suNotice' + (ok ? '' : ' bad');
    $('suMovePlan').innerHTML = `<div>移す量: <b>約 ${gb(p.bytes)}</b>（${(p.files || 0).toLocaleString()} 個のファイル）</div>
      <div>今の場所: ${esc(p.old || '')}</div><div>引っ越し先: <b>${esc(p.new || '')}</b>${p.free != null ? `（空き容量 ${gb(p.free)}）` : ''}</div>
      <div class="sub">${p.same_drive ? '同じドライブの中なので、名前を変えるだけですぐ終わります。' : '別のドライブなので、全部コピーしてから元を消します（量によっては数分かかります）。'}</div>` +
      (p.problems || []).map(x => `<div class="bad">${esc(x)}</div>`).join('') + (p.warnings || []).map(x => `<div class="sub">注意: ${esc(x)}</div>`).join('');
    $('suMoveGo').disabled = !ok || !!MOVE;
  } catch (e) { $('suMovePlan').innerHTML = `<span class="bad">${esc(e.message)}</span>`; $('suMoveGo').disabled = true; }
}

async function moveGo() {
  try {
    const r = await call('POST', '/api/setup/move', {new_dir: $('suMovePath').value.trim()});
    MOVE = r.id; $('suMoveGo').disabled = true; $('suMoveRun').hidden = false; $('suMoveCancel').disabled = true;
    const tick = async () => {
      let j;
      try { j = await call('GET', `/api/job?id=${MOVE}`); } catch (e) { setTimeout(tick, 1000); return; }
      const p = j.progress || {};
      $('suMoveLabel').textContent = p.label || (j.steps || [])[j.step] || '引っ越しています…';
      const pct = p.total ? Math.min(100, 100 * (p.done || 0) / p.total) : null;
      $('suMoveBar').style.width = pct == null ? '100%' : pct.toFixed(1) + '%';
      $('suMoveBar').classList.toggle('busy', pct == null);
      $('suMoveMsg').textContent = p.total > 1e6 ? `${gb(p.done)} / ${gb(p.total)}` : '';
      if (j.state === 'running') { setTimeout(tick, 500); return; }
      MOVE = null; $('suMoveCancel').disabled = false;
      $('suMoveLabel').innerHTML = j.state === 'done' ? '<b class="ok">引っ越しました</b>' : '<b class="bad">引っ越せませんでした</b>';
      $('suMoveMsg').textContent = String(j.log || '').trim().split('\n').slice(-3).join(' / ');
      ST = await call('GET', '/api/setup/status'); render();
      if (j.state === 'done' && A) { A.loadSongs().catch(() => {}); A.status('作業フォルダを引っ越しました: ' + (ST.work.dir || '')); }
    };
    tick();
  } catch (e) { $('suMoveNote').textContent = e.message; }
}

async function setWork() {
  try {
    ST = await call('POST', '/api/setup/settings', {work_dir: $('suWorkPath').value});
    if (!SEP_EDITED) $('suSepPath').value = ST.default_sep;
    render(); loadPlan();
    if (A) A.loadSongs().catch(() => {});
  } catch (e) { msg('suWorkMsg', e.message, true); }
}

async function saveOpt(key, value) {
  try { ST = await call('POST', '/api/setup/settings', {[key]: value}); render(); msg('suOptMsg', value ? '決めました' : '外しました'); if (A && A.fileInfo) A.fileInfo(); }
  catch (e) { msg('suOptMsg', e.message, true); }
}

async function loadPlan() {
  const dir = $('suSepPath').value.trim();
  PLAN = null; PLAN_ERR = '';
  if (!dir) { PLAN_ERR = 'インストール先を決めてください'; return renderSep(); }
  try {
    const q = `/api/setup/plan?dir=${encodeURIComponent(dir)}` + (VARIANT ? `&variant=${VARIANT}` : '');
    PLAN = await call('GET', q);
    VARIANT = PLAN.variant;
  } catch (e) { PLAN_ERR = 'ダウンロードの量を調べられませんでした: ' + e.message; }
  renderSep();
}

// ---- 描く ----
function mark(id, ok) { const el = $(id); el.textContent = ok ? '✓' : '！'; el.className = 'suMark ' + (ok ? 'ok' : 'bad'); }
const date = s => String(s || '').slice(0, 10);

function render() {
  if (!ST) return;
  const w = ST.work;
  mark('suWorkMark', w.ok);
  const settled = w.ok && !w.dev && !!w.dir;   // 決まった後は引っ越しで動かす（ただ切り替えると前の曲が一覧から消える）
  $('suWorkSetRow').hidden = settled;
  $('suWorkNow').hidden = !settled || !$('suMove').hidden;
  if (document.activeElement !== $('suWorkPath')) $('suWorkPath').value = w.dir && !w.dev ? w.dir : (w.dev ? '' : ST.default_work);
  $('suWorkPath').placeholder = w.dev ? '開発用の PC（リポジトリの out・cache フォルダを使用中）' : '例 D:\\AutoNotePlotter';
  msg('suWorkMsg', w.ok ? `✓ ${w.dev ? '開発用の PC（リポジトリの out・cache フォルダを使用中）' : esc(w.dir)}（空き容量 ${gb(w.free)}）`
    : `${w.why || ''}${w.dir ? '' : '（フォルダを選んで「このフォルダにする」）'}`, !w.ok);
  if (!SEP_EDITED && !$('suSepPath').value) $('suSepPath').value = (ST.sep.pending && ST.sep.pending.dir) || ST.default_sep;
  const r = ST.rating;
  mark('suRatMark', r.ok);
  $('suRatState').innerHTML = r.ok
    ? `<p>✓ ${r.bundled ? 'アプリに同梱' : '使えます'}（nlm-rating${r.version ? ' ' + esc(r.version) : ''}${r.bundled ? '' : '・' + esc(r.path)}）</p>`
    : `<p class="bad">見つかりません。アプリをインストールし直してください（parts\\nlm-rating フォルダに入っています）。</p>`;
  $('suRatRow').hidden = r.ok && r.bundled;
  if (document.activeElement !== $('suRating')) $('suRating').value = r.path || '';
  const lib = ST.library;
  mark('suLibMark', lib.ok);
  $('suLibState').innerHTML = lib.ok
    ? `<p>✓ ${lib.dist ? `アプリに同梱（BeatLeader のランク譜面 ${lib.maps ? lib.maps.toLocaleString() + ' 曲' : ''}から集めた型・作成日 ${esc(date(lib.made_at || lib.built_at))}）`
        : `開発用の型のデータベースを使用中（${esc(lib.path)}）`}。ノーツの置き方は、この型から選びます。</p>`
    : `<p class="bad">見つかりません。アプリをインストールし直してください（data フォルダに入っています）。<br><span class="sub">${esc(lib.why || '')}</span></p>`;
  mark('suNlmMark', ST.nlm.ok);
  if (!ST.nlm.ok) { $('suNlmMark').textContent = '・'; $('suNlmMark').className = 'suMark'; }   // なくても動く＝警告にしない
  if (document.activeElement !== $('suNlm')) $('suNlm').value = ST.nlm.path || '';
  renderSep();
  const miss = [!w.ok && '作業フォルダ', !ST.sep.ok && '音を分ける部品', !r.ok && '★を測る部品', !lib.ok && '型のライブラリ'].filter(Boolean);
  $('suStart').disabled = !ST.ready;
  $('suFootMsg').textContent = ST.ready ? '準備ができました' : `まだ足りない物: ${miss.join('・')}（揃うと始められます）`;
  $('suHeadSub').textContent = ST.ready ? (ST.setup_done ? '準備はできています' : '最初に 1 回だけ必要です') : '足りない物があります';
  const al = $('suAlert');
  const um = updMode(ST.sep);
  const resume = !ST.sep.ok && ST.sep.pending && !um;
  al.hidden = ST.ready || !(ST.setup_done || resume || ST.sep.kind);
  al.innerHTML = um === 'app' ? 'アプリの更新が必要です（このアプリの版がインストールする音を分ける部品に、使ってはいけない版が見つかりました）。'
      + '更新するまで新しい曲を取り込めないので、下の「アプリの更新を確かめる」から更新してください。'
    : um === 'required' ? `音を分ける部品の更新が必要です（${esc(reqWhy(ST.sep))}）。更新するまで新しい曲を取り込めないので、下の「更新する」から更新してください。`
    : resume ? `前回、音を分ける部品のインストールが途中で止まりました${resumeText(ST.sep.resume)}。下の「続きからインストールする」で、ダウンロード済みの所から再開します。`
    : `足りない物があります（${miss.join('・')}）。揃うまで新しい曲を取り込めないので、下の手順で直してください。`;
  topButton();
}

// ---- 音を分ける部品の更新（sep_install.check の stage・changes・update_bytes・partial・app_update・ng_set） ----
// 'app'＝確かめた組そのものに NG（アプリの更新）・'required'＝入っているパックの部品を直す必要がある・'recommended'＝おすすめ・null＝出さない
// （パックが無い・途中で止まった・Python やパックの作りが変わった＝今までの「インストール」の欄）
function updMode(s) {
  if (!s || s.kind !== 'pack') return null;
  if (s.app_update) return 'app';
  if (!s.partial || !(s.changes || []).length || !s.stage || s.stage === 'none') return null;
  return s.stage === 'required' ? 'required' : 'recommended';
}
const WHY = {diff: '違う版', ng: '使ってはいけない版', missing: '入っていない', broken: '壊れている', kind: 'GPU 版・CPU 版が違う', model: '版が変わった'};
const whyText = c => c.why === 'older' ? `古すぎる（${c.min} 以上が要る）` : WHY[c.why] || c.why;
const vshow = v => v || 'なし';
const sz = n => n < 1e6 ? `${Math.max(1, Math.round(n / 1e3))}KB` : gb(n);   // 小さな部品は KB で
function reqWhy(s) {
  const cs = s.changes || [], has = w => cs.some(c => c.required && c.why === w);
  return [has('ng') && '使ってはいけない版が入っている', has('older') && '古すぎる版が入っている',
    (has('missing') || has('broken') || has('kind') || has('model')) && '足りない・壊れた部品がある'].filter(Boolean).join('・') || '部品を直す必要がある';
}

function renderUpd(s, mode) {
  const box = $('suUpd');
  box.hidden = !mode || !!JOB || REINSTALL;
  if (box.hidden) { box.innerHTML = ''; return; }
  box.className = 'suUpd ' + mode;
  const cs = s.changes || [];
  const at = ST.ng && ST.ng.at ? `（配布元の情報・${esc(date(ST.ng.at))} に確かめた）` : '（配布元の情報）';
  const ngLine = s.ng_why && (mode === 'app' || cs.some(c => c.why === 'ng')) ? `<div class="suUpdWhy">使ってはいけない理由: ${esc(s.ng_why)}<span class="sub">${at}</span></div>` : '';
  let head, lead;
  if (mode === 'app') {
    head = '⚠ アプリの更新が必要です';
    lead = `このアプリの版がインストールする音を分ける部品に、使ってはいけない版が見つかりました。部品をインストールし直しても同じ版が入るので直りません。
      アプリを新しい版に更新してください。更新するまで新しい曲を取り込めません。`;
  } else if (mode === 'required') {
    head = '⚠ 音を分ける部品の更新が必要です';
    lead = `${esc(reqWhy(s))}ので、下の部品をダウンロードして入れ替えます。更新するまで新しい曲を取り込めません。`;
  } else {
    head = 'おすすめの状態ではありません';
    lead = '音を分ける部品に、このアプリの版で動作を確かめた版と違う物があります。今のままでも使えますが、確かめた組に揃えるのをおすすめします（あとでもかまいません）。';
  }
  const ngs = (s.ng_set || []).map(x => `${x.name} ${x.version}`).join('・');
  const table = mode === 'app' ? `<div>使ってはいけない版: <b>${esc(ngs)}</b></div>`
    : `<table class="suItems suUpdTab"><tr><th>部品</th><th>今の版</th><th></th><th>確かめた版</th><th>訳</th><th class="num">ダウンロード</th></tr>` +
      cs.map(c => `<tr class="${c.required ? 'req' : ''}"><td>${esc(c.label || c.name)}</td><td>${esc(vshow(c.have))}</td><td>→</td><td>${esc(c.want)}</td>
        <td>${esc(whyText(c))}</td><td class="num">${c.size ? sz(c.size) : '－'}</td></tr>`).join('') + '</table>';
  const amount = mode === 'app' ? '' : `<div class="sub">ダウンロードする量: <b>約 ${gb(s.update_bytes)}</b>（変わる部品だけをダウンロードして入れ替えます・インストール先 ${esc(s.dir || '')}）。
    更新の途中は新しい曲を取り込めません。途中で止めても、次は続きからダウンロードします。</div>`;
  const go = mode === 'app' ? '<button id="suUpdApp" class="main">アプリの更新を確かめる</button>'
    : `<button id="suUpdGo" class="main">${s.resume ? '続きから更新する' : '更新する'}（約 ${gb(s.update_bytes)} をダウンロード）</button>`;
  box.innerHTML = `<div class="suUpdHead">${head}</div><p>${lead}</p>${ngLine}${table}${amount}
    <div class="suRow suActs"><span class="sub" id="suUpdNote"></span>${mode === 'recommended' ? '<button id="suUpdLater">あとで</button>' : ''}${go}</div>`;
  const g = $('suUpdGo'); if (g) g.onclick = () => install(s.variant, s.dir, 'suUpdNote');
  const l = $('suUpdLater'); if (l) l.onclick = close;
  const a = $('suUpdApp'); if (a) a.onclick = () => { close(); update.openCheck(); };
}

function resumeText(r) {   // sep_install.check の resume（stage・label・downloaded_bytes・download_bytes）
  if (!r) return '';
  const got = r.downloaded_bytes, all = r.download_bytes;
  const dl = all ? `・ダウンロード済み ${gb(got || 0)} / ${gb(all)}` : '';
  return `（次の段: ${esc(r.label || r.stage || '')}${dl}）`;
}

function gpuLine(g) {
  if (!g) return '';
  if (!g.nvidia) return `NVIDIA のグラフィックボードが見つからないので、CPU 版をインストールします。`;
  const name = `この PC のグラフィックボード: <b>${esc(g.name || 'NVIDIA')}</b>`;
  return GPU(g.variant) ? `${name} → GPU 版が使えます（おすすめ）`
    : `${name} → グラフィックボードのドライバーが古いので、CPU 版をすすめます（ドライバーを新しくすると GPU 版が使えます）`;
}

function renderSep() {
  if (!ST) return;
  const s = ST.sep, running = !!JOB, um = updMode(s);
  mark('suSepMark', s.ok);
  if (s.ok && um === 'recommended') { $('suSepMark').textContent = '●'; $('suSepMark').className = 'suMark rec'; }   // 使えるがおすすめの更新あり
  const warn = (s.warnings || []).map(w => `<p class="bad">注意: ${esc(w)}</p>`).join('');
  const where = `${VTEXT(s.variant)}・${esc(s.dir || '')}${s.installed_at ? '・' + esc(date(s.installed_at)) : ''}`;
  $('suSepState').innerHTML = (s.ok
    ? `<p>✓ ${s.kind === 'dev' ? '開発用の環境（.venv-sep）を使用中' : `インストール済み（${where}）`}${
        s.kind === 'pack' && !REINSTALL && !running ? ' <button id="suReinstall">インストールし直す…</button>' : ''}</p>`
    : um ? `<p>インストール済み（${where}）</p>`   // 何を直すかは下の更新の欄
    : (s.missing || []).length && (s.kind || s.pending) ? `<p class="bad">足りない物: ${esc(s.missing.join('・'))}</p>` : '') + warn;
  renderUpd(s, um);
  $('suSepSetup').hidden = (s.ok && (s.kind === 'dev' || !REINSTALL)) || running || (!!um && !REINSTALL);   // インストール済みなら畳む（押した時だけ開く）
  const ri = $('suReinstall'); if (ri) ri.onclick = () => { REINSTALL = true; renderSep(); };
  $('suRun').hidden = !running;
  const P = PLAN, g = P && P.gpu;
  $('suGpu').innerHTML = gpuLine(g);
  $('suGpu').title = g && g.why ? g.why : '';
  const opts = !g ? [] : g.nvidia ? [GPU(g.variant) ? g.variant : 'cu128', 'cpu'] : ['cpu'];
  $('suVariants').innerHTML = opts.map(v => `<label class="suVar${v === VARIANT ? ' on' : ''}"><input type="radio" name="suVar" value="${v}"${v === VARIANT ? ' checked' : ''}>
    <b>${VTEXT(v)}${g && v === g.variant ? '（おすすめ）' : ''}</b><span class="sub">${VSUB(v)}</span></label>`).join('');
  $('suVariants').querySelectorAll('input').forEach(r => { r.onchange = () => { VARIANT = r.value; loadPlan(); }; });
  $('suItems').innerHTML = P ? `<tr><th>ダウンロードする物</th><th>何に使うか</th><th>ダウンロード元</th><th class="num">ダウンロード</th><th class="num">展開後</th></tr>` +
    P.items.filter(it => it.key !== 'python').map(it => { const [name, what] = itemText(it);   // Python はダウンロードしない＝一覧に出さない（2026-11-03 利用者）
      return `<tr><td>${esc(name)}</td><td>${esc(what)}</td><td class="suSrc">${it.download ? esc(it.source || '') : 'アプリの中からコピー'}</td>
      <td class="num">${it.download ? gb(it.download) : '－'}</td><td class="num">${gb(it.install)}</td></tr>`; }).join('') : '';
  const ngSet = P && P.ng_set && P.ng_set.length ? P.ng_set : null;   // インストールする組の中の使ってはいけない版＝アプリの更新が要る
  const enough = P ? P.enough !== false && !(P.problems || []).length && !ngSet : true;
  const peak = P ? (P.peak_bytes || (P.download_bytes || 0) + (P.install_bytes || 0)) : 0;
  $('suNotice').className = 'suNotice' + (P && !enough ? ' bad' : '');
  $('suNotice').innerHTML = P ? `${ngSet ? `<div class="bad"><b>アプリの更新が必要です</b>: このアプリの版がインストールする部品に、使ってはいけない版があります
      （${esc(ngSet.map(x => `${x.name} ${x.version}`).join('・'))}${ST.ng && ST.ng.why ? '・' + esc(ST.ng.why) : ''}）。アプリを新しい版に更新してからインストールしてください。
      <button id="suPlanApp">アプリの更新を確かめる</button></div>` : ''}<b>インストールの前に確かめてください</b>
    <div>ダウンロードする量: <b>約 ${gb(P.download_bytes)}</b>${P.estimated ? '（見積もり）' : ''}</div>
    <div>インストール後に使う容量: <b>約 ${gb(P.install_bytes)}</b><span class="sub">（インストール中は、ダウンロードした物も一時的に置くので最大 約 ${gb(peak)}）</span></div>
    <div>インストール先: <b>${esc(P.dir)}</b></div>
    <div>そのドライブの空き容量: <b>${gb(P.free_bytes)}</b>${P.enough !== false ? '' : '（足りません。別のドライブを選ぶか、空きを作ってください）'}</div>
    ${[...(P.problems || []).map(x => `<div class="bad">${esc(x)}</div>`), ...(P.warnings || []).map(x => `<div class="bad">注意: ${esc(x)}</div>`)].join('')}
    <div class="sub">ダウンロード元は PyTorch・PyPI（Python の部品の公式の配布サイト）・Hugging Face（学習済みモデルの公式の配布サイト）です。
      インストールした後は、インターネットにつながっていなくても動きます。途中で止めても、次は続きからダウンロードします。</div>`
    : `<span class="${PLAN_ERR ? 'bad' : 'sub'}">${esc(PLAN_ERR || 'ダウンロードの量を調べています…')}</span>`;
  const pa = $('suPlanApp'); if (pa) pa.onclick = () => { close(); update.openCheck(); };
  const resume = !s.ok && s.pending;
  $('suInstall').textContent = resume ? '続きからインストールする' : s.ok ? 'インストールし直す' : `インストールする（約 ${P ? gb(P.download_bytes) : '?'} をダウンロード）`;
  $('suInstall').disabled = !P || !enough || !ST.work.ok;
  if (!ST.work.ok) $('suSepNote').textContent = '先に作業フォルダを決めてください';
}

// ---- インストール（入っているパックの更新も同じ＝違う部品だけダウンロードして入れ替える） ----
async function install(variant, dir, noteId = 'suSepNote') {
  try {
    const r = await call('POST', '/api/setup/install', {dir, variant});
    watch(r.id);
  } catch (e) { $(noteId).textContent = e.message; }
}

function watch(id) {
  JOB = {id}; renderSep();
  clearTimeout(timer);
  const tick = async () => {
    let j;
    try { j = await call('GET', `/api/job?id=${id}`); } catch (e) { timer = setTimeout(tick, 1500); return; }
    const p = j.progress || {};
    $('suRunLabel').textContent = (p.steps && p.step ? `${p.step} / ${p.steps.length || p.steps}: ` : '') + (p.label || p.stage || '準備しています…');
    const pct = p.total ? Math.min(100, 100 * (p.done || 0) / p.total) : null;
    $('suBarIn').style.width = pct == null ? '100%' : pct.toFixed(1) + '%';
    $('suBarIn').classList.toggle('busy', pct == null);
    $('suRunMsg').textContent = [p.msg, p.total > 1e6 ? `${gb(p.done)} / ${gb(p.total)}` : '', pct != null ? `${Math.floor(pct)}%` : ''].filter(Boolean).join('・');
    topButton(p);
    if (j.state === 'running') { timer = setTimeout(tick, 700); return; }
    JOB = null;
    ST = await call('GET', '/api/setup/status');
    render();
    const done = j.state === 'done' ? 'インストールが終わりました'
      : j.cancelled ? '一時停止しました（「続きから」で再開できます）'
      : '失敗しました: ' + String(j.log || '').trim().split('\n').slice(-1)[0];
    $('suSepNote').textContent = done;
    const un = $('suUpdNote'); if (un) un.textContent = done;
    if (A && j.state === 'done') A.status('音を分ける部品: ' + done);
  };
  tick();
}

async function stop() {
  if (!JOB) return;
  try { await call('POST', '/api/job/cancel', {id: JOB.id}); } catch (e) { $('suRunMsg').textContent = e.message; }
}

async function finish() {
  try { ST = await call('POST', '/api/setup/done', {}); close(); if (A) A.status('準備ができました。「＋ 曲を取り込む」から始めてください'); }
  catch (e) { $('suFootMsg').textContent = e.message; }
}

// ---- 開く・閉じる・上の列のボタン ----
export async function open() {
  if (!$('suDlg')) build();
  $('suDlg').style.display = 'flex';
  if (!ST) ST = await call('GET', '/api/setup/status');
  render();
  if (ST.running && !JOB) watch(ST.running);
  if (!(ST.sep.ok && ST.sep.kind === 'dev')) loadPlan();
}

function close() { if ($('suDlg')) $('suDlg').style.display = 'none'; }

function topButton(p) {
  const b = $('setupBtn'); if (!b || !ST) return;
  const rec = ST.ready && !JOB && updMode(ST.sep) === 'recommended';   // 使えるが、おすすめの更新がある＝小さな印
  b.classList.toggle('suWarn', !ST.ready);
  b.classList.toggle('suRec', rec);
  b.textContent = JOB ? `インストール中 ${p && p.total ? Math.floor(100 * (p.done || 0) / p.total) + '%' : '…'}` : ST.ready ? '準備と設定' : '⚠ 準備が足りない';
  if (rec) { const d = document.createElement('span'); d.className = 'suDot'; d.setAttribute('aria-hidden', 'true'); b.appendChild(d); }
  b.title = !ST.ready ? '足りない物があります（押すと準備の窓が開きます）'
    : rec ? '音を分ける部品に、おすすめの更新があります（今のままでも使えます・押すと準備の窓が開きます）'
    : '準備と設定（作業フォルダ・音を分ける部品・★を測る部品・NLM の場所）';
}

// 起動のたびに揃っているかを確かめ、足りなければ（初回・部品が消えた・インストールが途中で止まった・使ってはいけない版・古すぎる版）
// 窓を出す。おすすめの更新だけの時は窓を出さず、上の列の印と下の列の一言（起動して 1 回だけ）
export async function check() {
  try { ST = await call('GET', '/api/setup/status'); } catch (e) { return null; }
  topButton();
  if (ST.need_setup || ST.running) await open();
  else if ($('suDlg') && $('suDlg').style.display === 'flex') render();
  if (!ST.need_setup && updMode(ST.sep) === 'recommended' && !TOLD_REC && A) {
    TOLD_REC = true;
    A.status('音を分ける部品: おすすめの状態ではありません（今のままでも使えます・上の「準備と設定」から更新できます）');
  }
  return ST;
}

// 「NLM で開く」を使えるか（準備の様子をまだ読んでいない時は止めない）
export function nlmOk() { return !ST || !ST.nlm || !!ST.nlm.ok; }

export function init(app) {
  A = app;
  const b = $('setupBtn'); if (b) b.onclick = () => open();
  // アプリの更新の確かめで、使ってはいけない版（音を分ける部品）の控えが変わった＝準備を確かめ直す（必須になれば窓を出す）
  update.onChecked(j => { if (j && j.ng_changed && !FAKE) check(); });
}

// ---- 確かめ（#sutest=first|resume|running|ok|dev） ----
export async function selfTest(kind) {
  const work = {ok: true, dir: 'D:\\AutoNotePlotter', free: 412e9};
  const lib = {ok: true, dist: true, maps: 1600, made_at: '2026-11-09T08:00:00+00:00'};
  const rating = {ok: true, path: 'C:\\Program Files\\AutoNotePlotter\\parts\\nlm-rating\\nlm-rating.exe', version: '4.1.0', bundled: true};
  const base = {ready: false, setup_done: false, need_setup: true, distributed: true, default_work: 'C:\\Users\\me\\Documents\\AutoNotePlotter',
    default_sep: 'D:\\AutoNotePlotter\\parts\\separate', work, library: lib, rating, nlm: {path: null, ok: false}, running: null,
    sep: {ok: false, kind: null, missing: ['音を分ける部品がまだ入っていない'], pending: null}};
  const states = {
    first: {...base, work: {ok: false, dir: null, why: '作業フォルダがまだ決まっていません'}, default_sep: 'C:\\Users\\me\\Documents\\AutoNotePlotter\\parts\\separate'},
    resume: {...base, setup_done: true, sep: {ok: false, kind: null, dir: 'D:\\AutoNotePlotter\\parts\\separate', missing: ['PyTorch がまだ'],
      pending: {dir: 'D:\\AutoNotePlotter\\parts\\separate', variant: 'cu128'}, resume: {stage: 'download', label: '部品をダウンロードする（PyTorch・Demucs ほか）', downloaded_bytes: 1.2e9, download_bytes: 3.14e9}}},
    running: {...base, running: 'fake'},
    ok: {...base, ready: true, setup_done: true, need_setup: false, nlm: {path: 'C:\\NLM\\NonLinearMapper.exe', ok: true},
      sep: {ok: true, kind: 'pack', variant: 'cu128', dir: 'D:\\AutoNotePlotter\\parts\\separate', installed_at: '2026-11-03', missing: []}},
    dev: {...base, ready: true, setup_done: true, need_setup: false, work: {ok: true, dir: 'D:\\repo', dev: true, free: 900e9},
      rating: {ok: true, path: 'D:\\nlm-rating\\nlm-rating.exe', version: '4.1.0', bundled: false},
      sep: {ok: true, kind: 'dev', variant: 'dev', dir: 'D:\\repo\\.venv-sep', missing: []}, library: {ok: true, dist: false, path: 'D:\\lib\\library.sqlite'}},
  };
  // 版の 2 段: おすすめ（違う版・最低の版以上）・必須（NG・古すぎる）・確かめた組そのものが NG（アプリの更新）・初めてのインストールの組が NG
  const pack = {kind: 'pack', variant: 'cu128', dir: 'D:\\AutoNotePlotter\\parts\\separate', installed_at: '2026-11-03', partial: true, rebuild: false, ng_set: [],
    app_update: false, ng_why: null};
  const ch = (name, label, have, want, why, size, min = null, fixable = true) => ({key: name, name, label, have, want, min, why, required: why !== 'diff', fixable, size});
  const NGWHY = 'ファイルを書く途中で止まると壊れる不具合';
  states.rec = {...states.ok, sep: {...states.ok.sep, ...pack, ok: true, stage: 'recommended', missing: [], update_bytes: 2.84e9,
    changes: [ch('torch', 'PyTorch', '2.11.0+cu128', '2.12.1+cu128', 'diff', 2.81e9, '2.11.0'), ch('numpy', 'numpy', '2.5.4', '2.6.1', 'diff', 12.9e6, '2.5.4'),
      ch('einops', 'einops', '0.8.2', '0.8.3', 'diff', 66e3)]}};
  states.must = {...states.ok, ready: false, need_setup: true, ng: {why: NGWHY, at: '2026-11-03T09:12:00'}, sep: {...pack, ok: false, stage: 'required', ng_why: NGWHY,
    missing: [`使ってはいけない版の部品が入っている: filelock 4.2.7（${NGWHY}）`, 'このアプリには古すぎる版の部品がある: Demucs 4.0.1（4.1.0 以上が要る）'],
    update_bytes: 2.1e6, changes: [ch('filelock', 'filelock', '4.2.7', '4.2.9', 'ng', 165e3, '4.2.7'), ch('demucs', 'Demucs', '4.0.1', '4.1.0', 'older', 101e3, '4.1.0'),
      ch('einops', 'einops', '0.8.2', '0.8.3', 'diff', 66e3)]}};
  states.appng = {...states.ok, ready: false, need_setup: true, ng: {why: 'GPU 版で分けた音が無音になる不具合', at: '2026-11-03T09:12:00'},
    sep: {...pack, ok: false, stage: 'required', app_update: true, ng_why: 'GPU 版で分けた音が無音になる不具合', ng_set: [{key: 'torch-cu128', name: 'torch', version: '2.11.0+cu128'}],
      missing: ['使ってはいけない版の部品が入っている: PyTorch 2.11.0+cu128', 'このアプリの版がインストールする部品が使ってはいけない版＝アプリを更新してください'],
      update_bytes: 2.77e9, changes: [ch('torch-cu128', 'PyTorch', '2.11.0+cu128', '2.11.0+cu128', 'ng', 2.77e9, '2.11.0', false)]}};
  states.planng = {...states.first, work, ng: {why: 'GPU 版で分けた音が無音になる不具合', at: '2026-11-03T09:12:00'}};
  const gpu = {nvidia: true, name: 'NVIDIA GeForce RTX 4070 SUPER', driver: '581.57', variant: 'cu128', why: 'CUDA 12.8 に足りるドライバー'};
  const plans = {
    cu128: {download_bytes: 3.14e9, install_bytes: 4.99e9, items: [['python', '', 0, 27e6], ['torch', 'https://download.pytorch.org/whl/cu128', 2.77e9, 4.43e9],
      ['libs', 'https://pypi.org/', 33e6, 199e6], ['pip', 'https://pypi.org/', 2e6, 0], ['weights', 'https://huggingface.co/adefossez/HTDemucs-ft', 336e6, 336e6]]},
    cpu: {download_bytes: 0.49e9, install_bytes: 1.04e9, items: [['python', '', 0, 27e6], ['torch', 'https://download.pytorch.org/whl/cpu', 116e6, 479e6],
      ['libs', 'https://pypi.org/', 33e6, 199e6], ['pip', 'https://pypi.org/', 2e6, 0], ['weights', 'https://huggingface.co/adefossez/HTDemucs-ft', 336e6, 336e6]]},
  };
  let st = states[kind === 'move' ? 'ok' : kind] || states.first;
  FAKE = {api: async (m, url, body) => {
    if (url.startsWith('/api/setup/status')) return st;
    if (url.startsWith('/api/setup/plan')) {
      const v = (url.match(/variant=(\w+)/) || [])[1] || gpu.variant, p = plans[v] || plans.cpu;
      const dir = decodeURIComponent((url.match(/dir=([^&]+)/) || [])[1] || '');
      return {dir, variant: v, gpu, estimated: false, free_bytes: 412e9, enough: true, download_bytes: p.download_bytes, install_bytes: p.install_bytes,
              items: p.items.map(([key, source, download, install]) => ({key, name: key, what: '', source, download, install})),
              ng_set: kind === 'planng' && v === 'cu128' ? [{key: 'torch-cu128', name: 'torch', version: '2.11.0+cu128'}] : []};
    }
    if (url.startsWith('/api/job')) return {state: 'running', progress: {stage: 'download', label: '部品をダウンロードする（PyTorch・Demucs ほか）', done: 1.31e9, total: 3.14e9, msg: 'torch-2.11.0+cu128-cp314-cp314-win_amd64.whl', step: 2, steps: 6}};
    if (url === '/api/setup/settings') { st = {...st, work: {ok: true, dir: body.work_dir, free: 412e9}}; return st; }
    if (url.startsWith('/api/setup/move-plan')) return {old: 'D:\\AutoNotePlotter', new: 'E:\\AutoNotePlotter', bytes: 5.3e9, files: 2841, free: 2.4e12,
      same_drive: false, problems: [], warnings: ['NLM でこのアプリの曲を開いている時は、先に NLM を閉じてください（NLM が古い場所に保存してしまうため）']};
    return {};
  }};
  ST = null;
  await open();
  if (kind === 'move') { $('suMoveOpen').click(); $('suMovePath').value = 'E:\\AutoNotePlotter'; await movePlan(); }
  await new Promise(r => setTimeout(r, 300));
  const out = document.createElement('pre'); out.id = 'sutestOut'; out.style.display = 'none';
  out.textContent = [`kind=${kind}`, `head=${$('suHeadSub').textContent}`, `alert=${$('suAlert').hidden ? '' : $('suAlert').textContent}`,
    `install=${$('suInstall').textContent} disabled=${$('suInstall').disabled}`, `foot=${$('suFootMsg').textContent}`,
    `notice=${$('suNotice').textContent.replace(/\s+/g, ' ').trim()}`, `top=${($('setupBtn') || {}).textContent} class=${($('setupBtn') || {}).className}`,
    `upd=${$('suUpd').hidden ? '' : $('suUpd').textContent.replace(/\s+/g, ' ').trim()}`, `setupHidden=${$('suSepSetup').hidden}`].join('\n');
  document.body.appendChild(out);
  return out.textContent;
}
