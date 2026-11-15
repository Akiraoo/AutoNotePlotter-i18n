// Beat Saber へ直接書き出す（app/bsexport.py・docs/アプリ仕様.md 22 節）。main.js が init(app) を呼ぶ。
// 2026-11-03 利用者: 直通の経路も用意する・足りない情報（マッパー名など）を入れられるように・プレイリストにまとめて入れたい・
// NLM の形式（.nlmf）を作るのは今まで通り既定。画面の言葉は使う人に分かる物で（「書き出す」「フォルダ」「プレイリスト」）。
// 2026-11-09 利用者: カバー画像を見せる・ここから変えられるように（取り込みの窓と同じ選び方＝importer.js の coverPicker）・
// 記録は上から下へ流し、終わりの表示も一番下に・終わったことがはっきり分かるように（目立つ表示・「閉じる」を強調し「書き出す」の強調を外す
// ＝何度も書き出さない・設定を変えた・開き直した時は元どおり「書き出す」を強調）。
// カバーは選ぶとすぐ結果のファイル（.nlmf）に入れる（POST /api/bsexport/cover・窓を閉じても残る・NLM で開いても同じ）。
// 確かめ: #bxtest（=ok・=missing・=unsupported・=run・=done・=edit・=fail・=cover・=paste）＝作り物の中身で窓を出す（サーバーに書かない）
// → #bxtestOut（--dump-dom）
import {$, api, S} from './store.js';
import {coverPicker, onPasteImage, testImage} from './importer.js';

let A = null, P = null, JOB = null, timer = 0, FAKE = null, CP = null;
let MODE = 'ready';   // ready（書き出すを強調）・done（書き出した＝閉じるを強調）
let CV = 0;           // 今のカバーの画像の版（変えたら上げる＝画像を読み直す）
const EMB = '(.nlmf)';   // .nlmf に入っているだけのカバー（ファイルが無い）の札
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const DTEXT = {Easy: 'Easy', Normal: 'Normal', Hard: 'Hard', Expert: 'Expert', ExpertPlus: 'Expert+'};
const INFO = [['songName', '曲名', true], ['songSubName', 'サブタイトル', false], ['songAuthorName', 'アーティスト', true],
  ['levelAuthorName', 'マッパー（譜面の作者）', true]];
const NEW = '__new__';

async function call(method, url, body) { return FAKE ? FAKE(method, url, body) : api(method, url, body); }
const shown = () => !!$('bxDlg') && $('bxDlg').style.display === 'flex';
const body = () => $('bxDlg').querySelector('.dlgBody');

function build() {
  const d = document.createElement('div');
  d.id = 'bxDlg'; d.className = 'modal bx';
  d.innerHTML = `<div class="dlg">
  <div class="dlgHead"><b>Beat Saber に書き出す</b><span class="sub" id="bxHeadSub"></span><button id="bxClose">閉じる</button></div>
  <div class="dlgBody">
    <p class="sub">この曲を Beat Saber で遊べる形（Info.dat・譜面・song.egg・カバー）にして、Beat Saber の曲のフォルダに書き出します。
      NLM の形式（.nlmf）はそのまま残るので、あとから NLM で開いて直すこともできます。</p>
    <div id="bxProblem" class="bxProblem" hidden></div>
    <section><h3>曲の情報</h3>
      <div class="bxGrid" id="bxInfo"></div>
      <div class="bxGrid"><label for="bxPrevS">試聴</label><div class="bxNums"><input id="bxPrevS" inputmode="decimal"> 秒から
        <input id="bxPrevD" inputmode="decimal"> 秒間<span class="sub">（曲を選ぶ画面で流れる所）</span></div>
        <label class="bxTop">カバー画像</label><div><div id="bxCover" class="impCovers bxCovers"></div>
          <div class="sub" id="bxCoverNote"></div><div class="sub" id="bxCoverMsg"></div></div></div>
      <p class="sub">入れた情報は .nlmf にも書くので、NLM で開いても同じになります。マッパーは次の曲でも初めから入ります。</p>
    </section>
    <section><h3>書き出す難易度</h3><div id="bxDiffs" class="bxDiffs"></div></section>
    <section><h3>曲の音量</h3>
      <label class="bxCheck"><input type="checkbox" id="bxLoud"> 曲の音量を自動でそろえる</label>
      <div class="sub" id="bxLoudNote">音の小さい曲を、平均の音量（−9 LUFS＝カスタム曲によくある大きさ）まで上げます。音が割れない所で止め、大きい曲は下げません。
        NLM の「自動調整」と同じ値で、.nlmf の音量補正にも書きます。</div>
      <div class="bxSub"><label class="bxCheck"><input type="checkbox" id="bxLim"> 大きい瞬間を少し抑えて、もっと上げる（リミッター）</label>
        <div class="sub">一番大きい瞬間に余裕が無くて上がらない曲も、大きい瞬間だけ少し抑えて −9 LUFS まで上げます（抑えるのは最大 8 dB まで・
          −11 LUFS より小さい曲だけ）。音の形が少し変わります。この書き出しの song.egg だけに入り、NLM で書き出す時は入りません。10〜20 秒かかります。</div></div>
    </section>
    <section><h3>書き出し先</h3>
      <div class="bxGrid"><label for="bxLevels">Beat Saber の曲のフォルダ</label>
        <div class="bxRow"><select id="bxLevels"></select><button id="bxLevelsPick">別のフォルダを選ぶ…</button></div>
        <label for="bxFolder">フォルダ名</label><div><input id="bxFolder" spellcheck="false">
          <div class="sub" id="bxPath"></div></div></div>
    </section>
    <section><h3>プレイリスト</h3>
      <label class="bxCheck"><input type="checkbox" id="bxPlOn" checked> プレイリストに入れる</label>
      <div class="bxRow" id="bxPlRow"><select id="bxPl"></select><input id="bxPlNew" placeholder="新しいプレイリストの名前" hidden></div>
      <div class="sub" id="bxPlNote"></div>
    </section>
    <div id="bxRun" class="bxRun" hidden><div class="bxRunHead">書き出しの記録</div><pre id="bxLog" class="bxLog"></pre><div id="bxRunLabel" class="bxRunNow"></div></div>
    <div id="bxDone" class="bxDone" hidden></div>
    <div class="bxFoot"><span id="bxFootMsg" class="sub"></span><button id="bxFootClose">閉じる</button><button id="bxGo" class="main">書き出す</button></div>
  </div></div>`;
  document.body.appendChild(d);
  // 窓の中のキーは後ろ（タイムラインの操作）へ渡さない・Esc で閉じる。Enter はその時のボタン（書き出した後は「閉じる」に移す）
  d.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Escape') close(); });
  // 設定を変えたら（書き出した後でも）元どおり「書き出す」を強調
  d.querySelector('.dlgBody').addEventListener('input', touched);
  d.querySelector('.dlgBody').addEventListener('change', touched);
  $('bxClose').onclick = close;
  $('bxFootClose').onclick = close;
  $('bxGo').onclick = go;
  $('bxFolder').oninput = showPath;
  $('bxLevels').onchange = showPath;
  $('bxLevelsPick').onclick = pickLevels;
  $('bxPlOn').onchange = () => { $('bxPlRow').hidden = !$('bxPlOn').checked; };
  $('bxPl').onchange = () => { $('bxPlNew').hidden = $('bxPl').value !== NEW; };
  CP = coverPicker($('bxCover'), {prefix: 'bxCov', api: call, url: coverUrl, name: c => c === nowKey() ? '今のカバー' : String(c).split(/[\\/]/).pop(),
    none: () => !P || !P.covers || P.covers.now == null, pick: pickCover, say: coverMsg, locked: () => !!JOB || !P || !P.covers});
  onPasteImage(() => shown() && !JOB && !!(P && P.covers), blob => CP.paste(blob));
}

// ---- カバー画像 ----
// 札: 今のカバー（ファイルの場所か EMB）・ほかの候補（結果のファイルの隣の前のカバー・音源のフォルダの Cover.jpg 等）・別の画像…・貼り付け。
// 今のカバーは /api/bsexport/cover（書き出しに使う物そのもの）、候補は /api/import/cover（取り込みと同じ）で見せる
const nowKey = () => !P || !P.covers || P.covers.now == null ? null : (P.covers.now || EMB);
function coverUrl(c) {
  if (FAKE) return fakeImg(c === nowKey() ? `now${CV}` : c);
  return c === nowKey() ? `/api/bsexport/cover?file=${encodeURIComponent(S.file)}&v=${CV}` : `/api/import/cover?path=${encodeURIComponent(c)}`;
}
const coverList = () => ({covers: [nowKey(), ...((P.covers && P.covers.cands) || [])].filter(c => c != null), sel: nowKey()});
function coverMsg(text, bad) { const m = $('bxCoverMsg'); m.textContent = text || ''; m.classList.toggle('bad', !!bad); }
function renderCover() {
  const cv = P && P.covers;
  if (!cv) {   // 様子が分からない（前の版のサーバー・読めない .nlmf）＝前のとおり文字だけ
    const p = P && P.plan;
    $('bxCover').innerHTML = p && p.info.cover ? `✓ ${esc(p.info.cover.split(/[\\/]/).pop())}` : p && p.info.cover_embedded ? '✓ .nlmf に入っている画像'
      : '<span class="sub">なし（NLM で入れられます。無くても書き出せます）</span>';
    $('bxCoverNote').textContent = '';
    return;
  }
  const l = coverList();
  CP.set(l.covers, l.sel);
  const sz = cv.size ? `・${cv.size[0]}×${cv.size[1]}` : '';
  $('bxCoverNote').textContent = (cv.now == null ? 'カバー画像はまだありません（無くても書き出せます）。画像'
    : `今のカバー: ${cv.now ? cv.name : `.nlmf に入っている画像（${cv.name || '名前なし'}）`}${sz}。ほかの画像`)
    + 'を選ぶ・貼り付けると、すぐ結果のファイル（.nlmf）に入ります（書き出しに使い、NLM で開いても同じ）。';
}
async function pickCover(c) {
  if (!c || c === nowKey()) return false;   // 「なし」は今がなしの時だけ出る（外す操作は無い）
  coverMsg('カバーを入れています…');
  try {
    const r = await call('POST', '/api/bsexport/cover', {file: S.file, path: c});
    const np = r.plan || {};
    P.covers = np.covers || P.covers;
    if (P.plan && np.plan) ['unsupported', 'warnings', 'missing'].forEach(k => { P.plan[k] = np.plan[k]; });
    if (P.plan && np.plan) { P.plan.info.cover = np.plan.info.cover; P.plan.info.cover_embedded = np.plan.info.cover_embedded; }
    CV++;
    renderCover(); renderProblem(); touched(); check();
    coverMsg(`カバーを変えました（${String(r.cover || c).split(/[\\/]/).pop()}・結果のファイルに入れました）`);
    if (A) A.status('カバー画像を変えた: ' + String(r.cover || c).split(/[\\/]/).pop());
    return coverList();
  } catch (e) { coverMsg('カバーを変えられませんでした: ' + e.message, true); return false; }
}

// フォルダ名の決まり（NLM の sanitizeFolderName＝automap/bs_export.sanitize_folder と同じ・英数字と一部の記号だけ）
const safe = s => String(s || '').replace(/[^A-Za-z0-9 \-_.()\[\]&'!+,]/g, '').trim().slice(0, 80);
const BLOCK = {audio: '曲の音源が見つかりません（音源のファイルを動かした・消した？ NLM で開いて音源を選び直してください）',
  ffmpeg: 'この音源の形式（m4a など）は ffmpeg が要ります（ffmpeg を入れるか、flac・wav・mp3・ogg の音源で取り込み直してください）',
  diffs: '書き出せる難易度がありません（ノーツのある難易度が無い）'};

function renderProblem() {
  const p = P.plan;
  const unsup = p ? [...(p.unsupported || []), ...(p.blocking || []).filter(k => BLOCK[k]).map(k => BLOCK[k])] : [];
  const prob = $('bxProblem');
  prob.hidden = !(P.error || unsup.length || (p && (p.warnings || []).length));
  prob.className = 'bxProblem' + (P.error || unsup.length ? ' bad' : '');
  prob.innerHTML = P.error ? esc(P.error)
    : (p.unsupported || []).length ? `<b>この譜面は NLM で書き出してください</b>（直接の書き出しにまだ対応していない物が入っています）<ul>${unsup.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`
    : unsup.length ? `<b>このままでは書き出せません</b><ul>${unsup.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`
    : (p.warnings || []).map(x => `<div>注意: ${esc(x)}</div>`).join('');
}

function render() {
  const p = P.plan;
  $('bxHeadSub').textContent = P.file;
  const ld = P.loudness || {};   // 曲の音量（覚えている入り切り・今の補正）
  $('bxLoud').checked = !!ld.on;
  $('bxLim').checked = !!ld.limiter;
  $('bxLim').disabled = !ld.on;
  $('bxLoud').onchange = () => { $('bxLim').disabled = !$('bxLoud').checked; };
  $('bxLoud').title = ld.gain_db ? `今の音量補正 ${ld.gain_db > 0 ? '+' : ''}${ld.gain_db} dB` : '今の音量補正 0 dB';
  renderProblem();
  if (!p) { $('bxGo').disabled = true; return; }
  $('bxInfo').innerHTML = INFO.map(([k, t, req]) => `<label for="bx_${k}">${t}</label>
    <div><input id="bx_${k}" value="${esc(p.info[k] || '')}" class="${req && !p.info[k] ? 'need' : ''}">${
      k === 'levelAuthorName' && P.plan.mapper_from_settings ? '<span class="sub">（前に入れた名前）</span>' : ''}${
      req && !p.info[k] ? '<span class="needNote">入れてください</span>' : ''}</div>`).join('');
  INFO.forEach(([k, , req]) => { const el = $('bx_' + k); el.oninput = () => { el.classList.toggle('need', req && !el.value.trim()); check(); }; });
  $('bxPrevS').value = p.info.previewStart ?? ''; $('bxPrevD').value = p.info.previewDuration ?? '';
  coverMsg('');
  renderCover();
  $('bxDiffs').innerHTML = (p.diffs || []).filter(d => d.notes > 0).map(d => `<label class="bxCheck"><input type="checkbox" data-diff="${d.diff}"${d.export ? ' checked' : ''}>
    ${esc(DTEXT[d.diff] || d.diff)}${d.label && d.label !== (DTEXT[d.diff] || d.diff) ? `（${esc(d.label)}）` : ''} <span class="sub">ノーツ ${d.notes}</span></label>`).join('') || '<span class="bad">ノーツのある難易度がありません</span>';
  $('bxDiffs').querySelectorAll('input').forEach(i => { i.onchange = check; });
  const lv = $('bxLevels');
  const cands = P.candidates || [];
  if (P.dest.levels && !cands.some(c => c.levels === P.dest.levels)) cands.unshift({levels: P.dest.levels, playlists: P.dest.playlists, kind: '設定'});
  lv.innerHTML = cands.map(c => `<option value="${esc(c.levels)}"${c.levels === P.dest.levels ? ' selected' : ''}>${esc(c.levels)}（${esc(c.kind)}）</option>`).join('')
    || '<option value="">（見つかりません。「別のフォルダを選ぶ」で選んでください）</option>';
  $('bxFolder').value = p.folder || (P.last && P.last.folder) || safe(`${p.info.songAuthorName ? p.info.songAuthorName + '-' : ''}${p.info.songName || ''}`).replace(/^-+|-+$/g, '');
  const pls = P.playlists || [];
  const def = P.playlist_last || P.default_playlist.file;
  const hasDef = pls.some(x => x.file === P.default_playlist.file);
  $('bxPl').innerHTML = (hasDef ? '' : `<option value="${esc(P.default_playlist.file)}" data-new="1">${esc(P.default_playlist.title)}（新しく作る）</option>`) +
    pls.map(x => `<option value="${esc(x.file)}">${esc(x.title)}（${x.songs} 曲${x.anp ? `・このアプリで書き出した曲 ${x.anp}` : ''}）</option>`).join('') +
    `<option value="${NEW}">新しいプレイリスト…</option>`;
  $('bxPl').value = [...$('bxPl').options].some(o => o.value === def) ? def : $('bxPl').options[0].value;
  $('bxPlNew').hidden = $('bxPl').value !== NEW;
  $('bxPlNote').textContent = P.dest.playlists ? `プレイリストのフォルダ: ${P.dest.playlists}（同じ曲を書き出し直した時は、プレイリストの中の前の行を置き換えます）` : '';
  showPath(); check();
}

function showPath() {
  const lv = $('bxLevels').value, raw = $('bxFolder').value.trim(), f = safe(raw);
  const last = P && P.last;
  $('bxPath').textContent = (lv && f ? `→ ${lv}\\${f}` + (last && last.folder === f ? `（前回 ${String(last.at || '').replace('T', ' ').slice(0, 16)} に書き出したフォルダ＝上書きします）` : '') : '') +
    (raw && f !== raw ? `　※フォルダ名に使えるのは英数字と - _ . ( ) [ ] & ' ! + , だけです（NLM と同じ決まり）。使えない字は落とします` : '');
  check();
}

function values() {
  const ch = {};
  INFO.forEach(([k]) => { ch[k] = $('bx_' + k).value.trim(); });
  const num = v => (v === '' || isNaN(+v)) ? null : +v;
  ch.previewStart = num($('bxPrevS').value); ch.previewDuration = num($('bxPrevD').value);
  const diffs = [...$('bxDiffs').querySelectorAll('input:checked')].map(i => i.dataset.diff);
  let playlist = null;
  if ($('bxPlOn').checked) {
    const v = $('bxPl').value, opt = $('bxPl').selectedOptions[0];
    playlist = v === NEW ? {title: $('bxPlNew').value.trim() || P.default_playlist.title}
      : opt && opt.dataset.new ? {title: P.default_playlist.title} : {file: v};
  }
  return {changes: ch, diffs, playlist, folder: safe($('bxFolder').value), levels: $('bxLevels').value};
}

function check() {
  if (!P || !P.plan) return;
  const v = values(), miss = INFO.filter(([k, , req]) => req && !v.changes[k]).map(([, t]) => t);
  const why = (P.plan.unsupported || []).length ? 'この譜面は NLM で書き出してください'
    : (P.plan.blocking || []).some(k => BLOCK[k]) ? 'このままでは書き出せません（上の理由）'
    : !v.levels ? 'Beat Saber の曲のフォルダを選んでください' : !v.folder ? 'フォルダ名を入れてください（英数字と - _ . など）'
    : !v.diffs.length ? '書き出す難易度を選んでください' : miss.length ? `入れてください: ${miss.join('・')}` : '';
  $('bxGo').disabled = !!why || !!JOB;
  $('bxFootMsg').textContent = JOB ? '書き出しています…' : why;
  $('bxFootMsg').classList.toggle('bad', !!why && !JOB);
  if (P.covers) $('bxCover').querySelectorAll('button').forEach(b => { b.disabled = !!JOB; });   // 書き出している間はカバーを変えられない
}

// 強調するボタン: ready＝「書き出す」・done＝「閉じる」（書き出すは強調を外し「もう一度書き出す」に・押せるまま）
function setMode(m) {
  MODE = m;
  const done = m === 'done';
  $('bxGo').classList.toggle('main', !done);
  $('bxFootClose').classList.toggle('main', done);
  $('bxGo').textContent = done ? 'もう一度書き出す' : '書き出す';
  $('bxGo').title = done ? '同じ設定でもう一度書き出す（前に書き出したフォルダは上書き）' : '';
  if (done) $('bxFootClose').focus();   // Enter で押されるのも「閉じる」に（「書き出す」に当たったままだと Enter でまた書き出した）
}
function touched() { if (MODE === 'done' && !JOB) setMode('ready'); }

async function pickLevels() {
  try {
    const r = await call('POST', '/api/setup/pick', {kind: 'folder', initial: $('bxLevels').value});
    if (!r.path) return;
    const s = await call('POST', '/api/bsexport/settings', {levels_dir: r.path});
    P.dest = s.dest; render(); touched();
  } catch (e) { $('bxFootMsg').textContent = e.message; }
}

async function go() {
  const v = values();
  try {
    if (v.levels !== P.dest.levels) { const s = await call('POST', '/api/bsexport/settings', {levels_dir: v.levels}); P.dest = s.dest; }
    const r = await call('POST', '/api/bsexport/run', {file: S.file, changes: v.changes, folder: v.folder, diffs: v.diffs, playlist: v.playlist,
                                                       levels: v.levels, save_info: true, loudness: $('bxLoud').checked,
                                                       limiter: $('bxLim').checked});
    watch(r.id);
  } catch (e) { $('bxFootMsg').textContent = e.message; $('bxFootMsg').classList.add('bad'); }
}

// 記録（上から下へ流す・「== 段」は段の見出し・終わりの行も一番下に足す）。読んでいる人が上へ戻していなければ一番下を見せ続ける
function showLog(j) {
  const el = $('bxLog'), atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  const b = body(), bEnd = b.scrollHeight - b.scrollTop - b.clientHeight < 48;   // 窓の中身も（記録が伸びても下の「書き出しています…」が見えるように）
  const lines = String(j.log || '').replace(/\s+$/, '').split('\n').filter((l, i, a) => l.trim() || (i && a[i - 1].trim()));
  let html = lines.map(l => l.startsWith('== ') ? `<span class="bxStep">▶ ${esc(l.slice(3))}</span>` : esc(l)).join('\n');
  const took = j.took != null ? `（${j.took} 秒）` : '';
  if (j.state === 'done') html += `\n<b class="ok">✓ 書き出しました${took}</b>`;
  else if (j.state !== 'running') html += `\n<b class="bad">✗ ${j.cancelled ? '止めました' : '書き出せませんでした'}${took}</b>`;
  el.innerHTML = html;
  if (atEnd) el.scrollTop = el.scrollHeight;
  $('bxRunLabel').textContent = j.state === 'running' ? `${(j.steps || [])[j.step] || ''}…` : '';
  $('bxRunLabel').hidden = j.state !== 'running';
  if (bEnd) b.scrollTop = b.scrollHeight;
}

// 終わりの目立つ表示（記録の下）: 書き出した所・プレイリスト・注意。失敗は理由（記録の最後の行）
function showDone(j) {
  const box = $('bxDone');
  if (j.state === 'done') {
    const r = j.result || {}, pl = j.playlist;
    box.className = 'bxDone ok';
    box.innerHTML = `<div class="bxDoneHead"><span class="mk">✓</span><b>Beat Saber に書き出しました</b></div>
      <div class="bxDoneGrid"><span>書き出したフォルダ</span><span class="bxDonePath">${esc(r.dir || '')}</span>
      ${pl ? `<span>プレイリスト</span><span>「${esc(pl.title)}」に${pl.replaced ? '入れ直しました（前の行を置き換え）' : '入れました'}（${pl.songs} 曲）</span>` : ''}</div>
      <div class="sub">Beat Saber を開いている時は、曲の一覧を読み直す（SongCore の Refresh・開き直す）と出てきます。</div>` +
      ((r.warnings || []).length ? r.warnings.map(w => `<div class="bad">注意: ${esc(w)}</div>`).join('') : '');
  } else {
    const ls = String(j.log || '').trim().split('\n').map(s => s.trim()).filter(Boolean), why = j.cancelled ? '' : (ls[ls.length - 1] || '');
    box.className = 'bxDone bad';
    box.innerHTML = `<div class="bxDoneHead"><span class="mk">✗</span><b>${j.cancelled ? '書き出しを止めました' : '書き出せませんでした'}</b></div>` +
      (why ? `<div class="bxDoneWhy">${esc(why)}</div>` : '') + '<div class="sub">理由は上の記録の最後にあります。直してから、もう一度「書き出す」を押してください。</div>';
  }
  box.hidden = false;
}

function watch(id) {
  JOB = {id}; $('bxRun').hidden = false; $('bxDone').hidden = true; $('bxLog').innerHTML = ''; check();
  body().scrollTop = body().scrollHeight;
  clearTimeout(timer);
  const tick = async () => {
    let j;
    try { j = await call('GET', `/api/job?id=${id}`); } catch (e) { timer = setTimeout(tick, 1000); return; }
    showLog(j);
    if (j.state === 'running') { timer = setTimeout(tick, 500); return; }
    JOB = null;
    showDone(j);
    if (j.state === 'done') {
      if (A) A.status('Beat Saber に書き出した: ' + ((j.result || {}).dir || ''));
      const t = new Date();   // この PC の時刻で（サーバーの記録＝<out>/.export と同じ・toISOString は世界時で 9 時間ずれた）
      P.last = {folder: values().folder, at: new Date(t - t.getTimezoneOffset() * 60000).toISOString().slice(0, 19)};
      showPath();
      setMode('done');
    } else setMode('ready');
    check();
    body().scrollTop = body().scrollHeight;   // 終わりの表示と「閉じる」が見えるように
  };
  tick();
}

export async function open() {
  if (!S.file) return;
  if (!$('bxDlg')) build();
  $('bxDlg').style.display = 'flex';
  if (!JOB) {   // 書き出している途中で開き直した時は、記録をそのまま見せる
    $('bxRun').hidden = true; $('bxLog').innerHTML = ''; $('bxDone').hidden = true;
    setMode('ready');
  }
  $('bxGo').disabled = true; $('bxFootMsg').textContent = '読んでいます…';
  try { P = await call('GET', `/api/bsexport/plan?file=${encodeURIComponent(S.file)}`); render(); }
  catch (e) { $('bxFootMsg').textContent = e.message; }
}

function close() { if ($('bxDlg')) $('bxDlg').style.display = 'none'; }

export function init(app) {
  A = app;
  const b = $('bsExportBtn'); if (b) b.onclick = () => open();
}

// ---- 確かめ（#bxtest=ok|missing|unsupported|run|done|edit|fail|cover|paste） ----
// run＝書き出している途中・done＝書き出した（終わりの表示・閉じるを強調）・edit＝書き出した後に設定を変えた（書き出すの強調に戻る）・
// fail＝失敗した・cover＝候補の画像を選んでカバーを変えた・paste＝作り物の画像を貼り付けてカバーを変えた
const IMGS = {};
function fakeImg(key) {   // 作り物の画像（名前ごとに色を変えた正方形）
  if (!IMGS[key]) {
    const cv = document.createElement('canvas'); cv.width = cv.height = 96;
    const g = cv.getContext('2d'), h = [...String(key)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
    g.fillStyle = `hsl(${h},55%,45%)`; g.fillRect(0, 0, 96, 96); g.fillStyle = '#fff'; g.font = 'bold 22px sans-serif'; g.textAlign = 'center';
    g.fillText(String(key).split(/[\\/]/).pop().slice(0, 7), 48, 56);
    IMGS[key] = cv.toDataURL();
  }
  return IMGS[key];
}
export async function selfTest(kind) {
  kind = String(kind || 'ok').split('&')[0];
  const nocover = kind === 'missing';
  const info = {songName: '桃源郷', songSubName: '', songAuthorName: 'yama', levelAuthorName: nocover ? '' : 'Oz', bpm: 129,
    previewStart: 40.6, previewDuration: 10, environment: 'DefaultEnvironment', cover: nocover ? null : 'C:\\x\\桃源郷.jpg'};
  const plan = {info, folder: nocover ? '' : 'yama-togenkyo', dest: '', missing: nocover ? ['levelAuthorName', 'folder', 'cover'] : [],
    unsupported: kind === 'unsupported' ? ['Music の配置を切り貼りしている（NLM の曲の流れの画面）'] : [], warnings: [],
    diffs: [{diff: 'ExpertPlus', label: '', notes: 812, export: true}, {diff: 'Expert', label: '', notes: 640, export: true},
            {diff: 'Hard', label: '', notes: 455, export: false}, {diff: 'Normal', label: '', notes: 0, export: false}]};
  const covers = nocover ? {now: null, name: '', size: null, cands: ['F:\\CD\\yama\\Cover.jpg']}
    : {now: 'C:\\x\\桃源郷.jpg', name: '桃源郷.jpg', size: [1200, 1200], cands: ['F:\\CD\\yama\\Cover.jpg']};
  const data = {file: '桃源郷.intent-s1.nlmf', plan, error: null, dest: {levels: 'D:\\BSManager\\SharedContent\\SharedMaps\\CustomLevels',
    playlists: 'D:\\BSManager\\SharedContent\\Playlists', ok: true},
    candidates: [{levels: 'D:\\BSManager\\SharedContent\\SharedMaps\\CustomLevels', playlists: 'D:\\BSManager\\SharedContent\\Playlists', kind: 'BSManager'}],
    playlists: [{file: '100989.bplist', title: 'PracticeSong1', author: 'BeatLeader', songs: 4, anp: 0}], playlist_last: null,
    mapper_name: 'Oz', last: ['done', 'edit'].includes(kind) ? {folder: 'yama-togenkyo', at: '2026-11-03T18:00:00'} : null,
    default_playlist: {file: 'AutoNotePlotter.bplist', title: 'Auto Note Plotter'}, covers};
  const steps = ['曲の情報を書く', '音量をそろえる', 'Beat Saber に書き出す', 'プレイリストに入れる'];
  const log = ['== 曲の情報を書く', '曲の情報を .nlmf にも書いた（NLM で開いても同じ）', '== 音量をそろえる',
    '音量: 平均 -10.2 LUFS・一番大きい瞬間 -0.3 dB → 補正 +0.0 dB（一番大きい瞬間が上限）。.nlmf の音量補正にも書いた（NLM の「自動調整」と同じ値）',
    '== Beat Saber に書き出す', 'カバー画像: cover.jpg', 'song.egg: 作った（3 分 49 秒）', 'Info.dat・ExpertPlusStandard.dat・ExpertStandard.dat'];
  const posted = [];
  FAKE = async (m, url, b) => {
    if (url.startsWith('/api/bsexport/plan')) return data;
    if (url.startsWith('/api/bsexport/run')) return {id: 'fake'};
    if (url.startsWith('/api/import/paste')) return {path: 'C:\\Temp\\automap-paste\\貼り付け-20261109-120000-abcd.jpg'};
    if (url.startsWith('/api/bsexport/cover')) {
      posted.push(b.path);
      const name = b.path.includes('貼り付け-') ? '桃源郷.cover2.jpg' : '桃源郷.cover.jpg';
      const nd = JSON.parse(JSON.stringify(data));
      nd.covers = {now: 'C:\\x\\' + name, name, size: [900, 900], cands: ['C:\\x\\桃源郷.jpg', 'F:\\CD\\yama\\Cover.jpg'].filter(c => c !== b.path)};
      nd.plan.info.cover = 'C:\\x\\' + name;
      return {ok: true, cover: 'C:\\x\\' + name, plan: nd};
    }
    if (url.startsWith('/api/job')) {
      if (kind === 'run') return {state: 'running', steps, step: 2, log: log.slice(0, 6).join('\n') + '\n'};
      if (kind === 'fail') return {state: 'error', steps, step: 2, took: 2.1,
        log: log.slice(0, 5).join('\n') + '\n\n書き出し先のフォルダが無い: D:\\BSManager\\SharedContent\\SharedMaps\\CustomLevels'};
      return {state: 'done', steps, step: 3, took: 4.2,
        log: log.join('\n') + '\n== プレイリストに入れる\nプレイリスト「Auto Note Plotter」に入れた（1 曲）\n',
        result: {dir: 'D:\\BSManager\\SharedContent\\SharedMaps\\CustomLevels\\yama-togenkyo', hash: 'abc', files: [], warnings: []},
        playlist: {title: 'Auto Note Plotter', songs: 1, replaced: false}};
    }
    return {};
  };
  S.file = S.file || '桃源郷.intent-s1.nlmf';
  await open();
  const wait = ms => new Promise(r => setTimeout(r, ms));
  if (['run', 'done', 'edit', 'fail'].includes(kind)) { await go(); await wait(300); }
  if (kind === 'edit') { const f = $('bxFolder'); f.value = 'yama-togenkyo-2'; f.dispatchEvent(new Event('input', {bubbles: true})); await wait(50); }
  if (kind === 'cover') { const t = [...$('bxCover').querySelectorAll('.impCov[data-c]')].find(b => b.dataset.c.endsWith('Cover.jpg')); if (t) t.click(); await wait(300); }
  if (kind === 'paste') { await CP.paste(await testImage()); await wait(300); }
  const lg = $('bxLog'), dn = $('bxDone');
  const out = document.createElement('pre'); out.id = 'bxtestOut'; out.style.display = 'none';
  out.textContent = [`kind=${kind}`, `go=${$('bxGo').disabled ? 'disabled' : 'enabled'}`, `goText=${$('bxGo').textContent}`,
    `main=${[...$('bxDlg').querySelectorAll('button.main')].map(b => b.id).join(',')}`, `focus=${document.activeElement && document.activeElement.id}`,
    `mode=${MODE}`, `foot=${$('bxFootMsg').textContent}`,
    `path=${$('bxPath').textContent}`, `pl=${$('bxPl').selectedOptions[0] && $('bxPl').selectedOptions[0].textContent}`,
    `problem=${$('bxProblem').hidden ? '' : $('bxProblem').textContent.replace(/\s+/g, ' ')}`,
    `cover=${CP.list().map(c => (c === CP.get() ? '*' : '') + String(c).split(/[\\/]/).pop()).join(' | ')}`,
    `coverNote=${$('bxCoverNote').textContent}`, `coverMsg=${$('bxCoverMsg').textContent}`, `posted=${posted.join(' | ')}`,
    `run=${$('bxRun').hidden ? '' : $('bxRunLabel').textContent}`, `logLast=${lg.textContent.trim().split('\n').pop()}`,
    `logAtEnd=${lg.scrollHeight - lg.scrollTop - lg.clientHeight < 24}`,
    `done=${dn.hidden ? '' : dn.className + ': ' + dn.textContent.replace(/\s+/g, ' ').trim()}`,
    `order=${!dn.hidden && lg.compareDocumentPosition(dn) & Node.DOCUMENT_POSITION_FOLLOWING ? 'log→done' : ''}`].join('\n');
  document.body.appendChild(out);
}
