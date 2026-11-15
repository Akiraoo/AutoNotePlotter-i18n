// 別の案と履歴（app/versions.py）の画面。main.js が init(app) を呼ぶ。
// 履歴: 上の「履歴」で一覧の窓（作り直すたびに控えた結果のファイルの版）。「見る」＝帯と 3D をその版に（右の欄の上に「見ている」の欄・
//   タイムラインの縁が橙）。「戻す」＝今の結果のファイルを控えてから、その版を結果のファイルに（意思入れも戻すかは選べる・既定は譜面だけ）。
// 別の案: 選んだ区間の「別の案を作る」（inspector.js の #iCands → emit('candidates', [拍の始まり, 終わり])）。区間だけ作り直した案を 3 つ
//   （テーマをずらす compose --variant）作り、右の欄の上の表で「今の譜面」と切り替えて帯と 3D で見比べ、「これにする」で結果のファイルに。
//   選んだ案は区間の意思入れの指示「案 k」として作業ファイルに足す（ここで commit＝Ctrl+Z で外せる・作り直しても区間のテーマは案 k のまま）。
//   案の名前は案の通し番号 v（ほかの案を作るたびに 4・5・6…）＝指示の「案 k」と同じ番号。
//   珍しい型まで広げて作る（選んだ区間の欄のチェック・表の下のチェック）: compose に --rare も渡し、表に「広げた」。これにすると区間に
//   「珍しい型まで」も付ける（作り直しても区間のテーマは広げた束の案 k のまま）。
//   ★の帯を変えて作る（選んだ区間の欄・表の下の選び）: compose に --band も渡し、表に帯の名前。これにすると区間に「★の帯」も付ける。
// 確かめ用の入口（main.js は触らない＝location.hash を自分で見る）: #vtest=hist（履歴の窓）・#vtest=view（1つ前の版を見る）・
//   #vtest=cand2（今ある案の 2 番目を見る）・#vtest=choose2（今ある案の 2 番目を、聞かずに「これにする」）・
//   #vtest=edit（「案」の付いた指示を「直す」で開き、両手 +1 を足して「この指示を直す」→ 案が残るかを document.title に）・
//   #vtest=unvar（「案」の付いた最初の指示を開いて「外す」→ 残った指示を document.title に）・
//   #vtest=addvar（「これにする」で足す「案」と「珍しい型まで」の決まり → document.title に）・
//   #vtest=rare（指示の欄の「型の幅: 珍しいまで」「決め: 入れる」を押して区間に付ける → 付けた指示を document.title に・作業ファイルに保存する）。
//   後ろに &song=曲名 でその曲を開いてから。
// ★（app/rating.py・nlm-rating の近似）: 別の案の表と履歴の窓の表に★の列（小数 2 桁＝区間しか変わらない案どうしの差が見える）。
//   測るのは 1 つずつ順番に（同時に頼むと nlm-rating が並んで重い）・測っている間は「…」・測れない PC（unavailable）では列ごと隠す。
//   答えは案の組（V.cand）・履歴の版（V.hstars）ごとに覚える（サーバーも中身の指紋で覚えている＝2回目からはすぐ）。
// viewing(): 帯と 3D に出している版（check.js の決めの場所が、その版の報告を読む・main.js の見る難易度は版を見ている間は基準だけ）。
// 難易度（docs/アプリ仕様.md 17 節）: 版・案は基準の難易度の譜面（サーバーの chart() が版の基準の難易度を読む）。版・案を見る時は
//   見る難易度を基準に戻す（S.view＝null）。戻す・案を選ぶのは基準の難易度だけ（ほかの難易度・ライト・書き出す印は今のまま・
//   app/versions.py の _put_base）。一覧の版の基準が今と違えば（基準を置き直す前の版）「基準 Expert+」の札。
// 形の別の案（docs/アプリ仕様.md 15 節）: 同じ振りの形を選んでいる時の「別の案を作る」は、本文に form＝{group, form}・only＝その形の1回目の区間。
//   表の上に形の回のボタン（押すとそこへ飛んで鳴らす）と「全部の回を続けて」。「これにする」は形の全部の回の同じ振りの指示に「案 k」
//   （と「珍しい型まで」「★の帯」）を書く（1回の commit）。サーバーの答え（/api/cands・/api/cands/choose）に form があればそれを使う。
import {S, $, fmt, timeOf, api, on, emit, commit, newId, rangeKey, rangeText, lsGet, lsSet, workBody, motifForms, formRuns, formColor, diffText} from './store.js';
import {draw, showRange} from './timeline.js';
import {playRange, seek} from './player.js';
import {bandText, bandOptions, playSeq} from './inspector.js';

let A = null;   // main.js から渡された口（loadSongs, openSong, reloadChart, status, showReport, reportHTML, esc, saveWork）
const V = {
  D: null,        // 今の曲のデータ（曲を開き直したら作り直す）
  view: null,     // 帯と 3D に出している物: {kind: 'hist', e} | {kind: 'cand', n} | null（結果のファイル）
  cand: null,     // 別の案: {only, meta（/api/cands の答え）, prog, secs, sel（0＝今の譜面）}
  making: false,  // 案を作っている
  cache: {},      // 'cur'・'c<n>' → {chart, proj}（切り替えをすぐに）
  hist: null,     // 履歴の一覧（/api/versions の答え）
  hstars: {},     // 履歴の版の★: 版 → {state: 'wait'|'run'|'done', r}（曲を開き直したら空に）
};
const ST = {na: false, busy: false, q: []};   // ★を測る順番待ち（na＝測れない PC＝列を隠す）
const enc = encodeURIComponent;
const esc = s => A.esc(String(s ?? ''));
const attr = s => esc(s).replace(/"/g, '&quot;');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const span = o => `${fmt(timeOf(o[0]))}〜${fmt(timeOf(o[1]))}`;
const pct = v => v == null ? '' : Math.round(v * 100) + '%';
const when = e => e.at.slice(5, 16);
export const viewing = () => (!V.view ? null : V.view.kind === 'hist' ? {ver: V.view.e.id} : {cand: V.view.n});   // 見ている版（無ければ結果のファイル）
const candV = n => { const c = V.cand && V.cand.meta && V.cand.meta.cands.find(q => q.n === n); return c ? (c.v ?? c.n) : n; };   // 表の n → 案の番号

export function init(app) {
  A = app;
  const card = document.createElement('section');
  card.id = 'vsCard'; card.className = 'card vsCard'; card.style.display = 'none';
  $('side').prepend(card);
  card.addEventListener('click', onCardClick);
  const keepCheck = e => {   // チェックはすぐ覚える（欄は描き直すたびに覚えた値から作る）
    const k = {vsFix: 'automap-vs-fix', vsWork: 'automap-vs-work', vsHWork: 'automap-vs-work', vsRare: 'automap-vs-rare'}[e.target.id];
    if (k) lsSet(k, e.target.checked);
    if (e.target.id === 'vsBand') lsSet('automap-vs-band', e.target.value);
  };
  card.addEventListener('change', keepCheck);
  const tag = document.createElement('div'); tag.id = 'vsTag'; tag.className = 'vsTag'; $('tl').appendChild(tag);
  const dlg = document.createElement('div');
  dlg.id = 'vsHist'; dlg.className = 'modal vsModal';
  dlg.innerHTML = `<div class="dlg vsDlg"><div class="dlgHead"><b>履歴（作り直した版）</b><span class="sub" id="vsHistSub"></span>
    <button id="vsHistClose">閉じる</button></div><div class="dlgBody" id="vsHistBody"></div></div>`;
  document.body.appendChild(dlg);
  $('vsHistClose').onclick = closeHistory;
  dlg.addEventListener('mousedown', e => { if (e.target === dlg) closeHistory(); });
  $('vsHistBody').addEventListener('click', onHistClick);
  $('vsHistBody').addEventListener('change', keepCheck);
  $('histBtn').onclick = openHistory;
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && histOpen()) closeHistory(); });
  on('candidates', r => startCands(r, 1, !!r[2], r[3] ?? null, r[4] || null));   // r＝[拍の始まり, 終わり, 珍しい型まで広げるか, ★の帯（無ければ null）, 形 {group, form}（無ければ null）]
  on('generating', v => {   // 作り直しが始まった: 見ている版・案はやめる（結果のファイルが変わる＝案は使えなくなる）
    if (!v || V.making) return;
    const was = V.view; V.view = null; V.cand = null; V.cache = {}; render();
    if (was) A.reloadChart().catch(() => {});
  });
  on('generated', () => { V.cand = null; V.cache = {}; render(); if (histOpen()) openHistory(); });
  on('work', () => { if (S.D && S.D !== V.D) songChanged(); });
}

// ---- 曲を開いた ----
async function songChanged() {
  V.D = S.D; V.view = null; V.cand = null; V.cache = {}; V.hist = null; V.hstars = {}; ST.q.length = 0; render();
  if (histOpen()) closeHistory();
  const D = S.D, file = S.file;
  try {   // 前に作った案が残っていれば表を出す（作っている途中なら続きを見る）
    const m = await api('GET', '/api/cands?file=' + enc(file));
    if (S.D !== D) return;
    if (m.cands && m.done) { V.cand = {only: m.only, meta: m, prog: [], sel: 0, rare: !!m.rare, band: m.band ?? null, form: m.form || null}; render(); }
    else if (m.cands && m.making) {
      const j = (await api('GET', '/api/jobs')).find(q => q.kind === 'cands' && q.file === file);
      if (j && S.D === D) { V.cand = {only: m.only, meta: null, prog: [], sel: 0, rare: !!m.rare, band: m.band ?? null, form: m.form || null}; follow(j.id); }
    }
  } catch (e) { /* 案が無い・読めない時は何もしない */ }
  if (location.hash.startsWith('#vtest') && !V.tested) { V.tested = true; setTimeout(selfTest, 1500); }
}

// ---- 帯と 3D に出す ----
function showChart(it) {   // it＝{chart: server の chart() の答え, proj: .nlmf の中身}。版・案は基準の難易度＝見る難易度も基準に
  S.view = null;
  S.D.notes = it.chart.notes; S.D.clips = it.chart.clips; S.D.holes = it.chart.holes; S.D.key = it.chart.key; S.D.diff = S.D.base;
  emit('chart', it.proj); draw();
}
async function fetchPair(chartUrl, nlmfUrl) {
  const [chart, proj] = await Promise.all([api('GET', chartUrl), api('GET', nlmfUrl)]);
  return {chart, proj};
}
async function backToResult() { V.view = null; render(); await A.reloadChart(); }

// ---- 右の欄の上の欄（見ている版・別の案） ----
function render() {
  const c = $('vsCard'); if (!c) return;
  const parts = [];
  if (V.view && V.view.kind === 'hist') parts.push(histViewHTML(V.view.e));
  if (V.cand) parts.push(candHTML());
  c.style.display = parts.length ? '' : 'none';
  c.innerHTML = parts.join('<div class="vsSep"></div>');
  const tag = $('vsTag');
  if (tag) tag.textContent = !V.view ? '' : V.view.kind === 'hist' ? `履歴の版（${when(V.view.e)}）を見ている` : `案${candV(V.view.n)} を見ている`;
  document.body.classList.toggle('vsViewing', !!V.view);
}
function histViewHTML(e) {
  const busy = V.making || S.generating;
  return `<div class="cardHead">履歴の版を見ている <span class="sub">（帯と 3D。結果のファイルはまだ変えていない）</span></div>
   <div class="vsWhat"><b>${esc(e.at)}</b>　${esc(e.title)}${e.only ? '・区間 ' + span(e.only) : ''}・ノーツ ${e.notes}${e.current ? '　<span class="chip">今の版</span>' : ''}</div>
   <div class="bar wrap"><button class="main" data-act="restore" ${busy || e.current ? 'disabled' : ''}>この版に戻す</button>
    <label class="ck" title="作業ファイル（意思入れ・量のライン・自動の休み）もこの版の時の物に戻す（Ctrl+Z で今の意思入れに戻せる）">
     <input type="checkbox" id="vsWork" ${lsGet('automap-vs-work', false) ? 'checked' : ''} ${e.work ? '' : 'disabled'}> 意思入れも戻す</label>
    <button data-act="stop">見るのをやめる</button><button data-act="list">履歴の一覧</button></div>`;
}
function candHTML() {
  const C = V.cand, m = C.meta;
  const wide = m ? !!m.rare : !!C.rare, band = m ? m.band ?? null : C.band ?? null, fr = formRanges(C.form);
  let h = `<div class="cardHead">別の案 <span class="sub">${C.form ? `形 ${esc(C.form.group)} ${esc(C.form.form)}（${fr.length} 回・1回目の区間 ${esc(rangeText(C.only))}）` : '区間 ' + esc(rangeText(C.only))}${wide ? '・珍しい型まで広げた' : ''}${band != null ? '・' + bandText(band) : ''}</span></div>`;
  if (C.form && fr.length) h += `<div class="bar wrap vsRuns"><span class="sub">回:</span>${fr.map((r, i) => `<button data-act="run" data-i="${i}" title="ここへ飛んで鳴らす（表の行を押すと、鳴らしたまま譜面だけ切り替わる）">${esc(C.form.form)}${i + 1}</button>`).join('')}
     ${fr.length > 1 ? '<button data-act="runs" title="形の全部の回を続けて鳴らす（回ごとに少し前から）">▶ 全部の回を続けて</button>' : ''}</div>`;
  if (V.making || !m) {
    const st = s => s === 'done' ? '<span class="ok">✓</span>' : s === 'error' ? '<span class="bad">✕</span>' : '…';
    h += `<div class="vsProg">作っている…（区間だけ作り直す・数秒〜十数秒）${C.secs != null ? C.secs + ' 秒' : ''}<br>`
      + (C.prog.length ? C.prog.map(p => `案${p.n} ${st(p.state)}${p.took ? ' ' + Math.round(p.took) + '秒' : ''}`).join('　') : '始めている')
      + `</div><div class="bar wrap"><button data-act="cancel" ${V.followId && !C.stopping ? '' : 'disabled'} title="案を作るのを止める（作りかけの案は残さない・結果のファイルは今のまま）">${C.stopping ? 'やめています…' : '作るのをやめる'}</button></div>`
      + '<div class="hint">できたら、表の行を押して帯と 3D で見比べる。外は今の譜面のまま。</div>';
    return h;
  }
  const row = (n, name, r, extra = '') => {
    if (!r || r.state === 'error') return `<tr class="vsRow bad" data-n="${n}"><td>${name}</td><td colspan="9">作れなかった</td></tr>`;
    return `<tr class="vsRow${C.sel === n ? ' sel' : ''}" data-n="${n}" title="${attr((r.head || []).join('\n'))}"><td>${C.sel === n ? '▶ ' : ''}${name}</td>
      <td>${r.notes}</td><td>${r.double}</td><td>${n === 0 ? '—' : `${r.same}/${r.notes}`}</td><td>${pct(r.diag)}</td><td>${pct(r.top)}</td>
      <td>${(r.move ?? 0).toFixed(2)}</td><td>${pct(r.reset)}</td><td class="${r.warn ? 'bad' : ''}">${r.warn}</td>${starTd('c:' + n)}${extra}</tr>`;
  };
  wantStar(C.stars = C.stars || {}, 'c:0', '');   // 今の譜面（結果のファイル）と、できた案を測る
  m.cands.forEach(c => { if (c.state === 'done') wantStar(C.stars, 'c:' + c.n, '&cand=' + c.n); });
  const outBad = m.cands.filter(c => c.state === 'done' && c.outside_diff);
  h += `<table class="vsTbl"><tr><th></th><th title="区間の中のノーツ">ノーツ</th><th title="両手同時の打点">両手</th><th title="今の譜面と全く同じ置き方のノーツ">今と同じ</th>
      <th>斜め</th><th>上の段</th><th title="同じ手の1振りの移動（マス）">動き</th><th title="振りの交互の崩れ（区間の前後1小節も）">崩れ</th>
      <th title="NLM の振りの続きの警告と同じ決まり（区間の前後1小節も）">警告</th><th class="vsStar" title="作った譜面の★（nlm-rating＝BeatLeader の★の近似・曲全体）。案は区間しか変わらないので小数 2 桁で見比べる">★</th></tr>
      ${row(0, '今の譜面', m.current)}${m.cands.map(c => row(c.n, `案${c.v ?? c.n}${c.rare ? ' <span class="vsRare" title="珍しい型まで広げた束から作った案">広げた</span>' : ''}${c.band != null ? ` <span class="vsRare" title="★の帯を変えた型の束から作った案">${bandText(c.band)}</span>` : ''}`, c)).join('')}</table>`;
  if (outBad.length) h += C.form ? `<div class="sub">形の回の外で今と違うノーツ（前の譜面に寄せた所・つなぎ目）: ${outBad.map(c => '案' + (c.v ?? c.n) + ' ' + c.outside_diff).join('・')}</div>`
                                 : `<div class="warn">区間の外が今と違う案がある（${outBad.map(c => '案' + (c.v ?? c.n) + ' ' + c.outside_diff).join('・')}）</div>`;
  const othBad = C.form ? m.cands.filter(c => c.state === 'done' && c.others_diff) : [];   // 同じグループのもう1つの形の回も変わる（A を変えると B も）
  if (othBad.length) h += `<div class="sub">もう1つの形（${C.form.form === 'A' ? 'B' : 'A'}）の回も変わる: ${othBad.map(c => '案' + (c.v ?? c.n) + ' ' + c.others_diff).join('・')} ノーツ</div>`;
  h += `<div class="bar wrap"><button data-act="play" title="区間を鳴らす（表の行を押すと、鳴らしたまま譜面だけ切り替わる）">▶ 区間を鳴らす</button>
     <button class="main" data-act="choose" ${C.sel > 0 ? '' : 'disabled'} title="案を結果のファイルにして、区間に指示「案 k」を付ける（全部を作り直しても区間のテーマは案のまま・指示を消せば既定の作り方）">${C.sel > 0 ? `案${candV(C.sel)} にする` : '案を選ぶ'}</button>
     <label class="ck" title="選んだ区間のクリップの名前に「固定」を足す＝1つも変えたくない時（全部を作り直しても区間のノーツをそのまま残す。しなくても区間の指示「案 k」でテーマは案のまま＝前後とのつながりで置き方が少し変わり得る）。外すのは NLM でクリップの名前から「固定」を消す">
      <input type="checkbox" id="vsFix" ${lsGet('automap-vs-fix', false) ? 'checked' : ''}> 区間を固定</label></div>
    <div class="bar wrap"><button data-act="more" title="テーマのずらし方を変えて、また 3 つ作る">ほかの案を作る</button>
     <label class="ck" title="ほかの案を、少ない曲にしか出ない型（珍しい型）まで広げた束から作る"><input type="checkbox" id="vsRare" ${wide ? 'checked' : ''}> 珍しい型まで広げて</label>
     <select id="vsBand" title="ほかの案を、型のライブラリの★の帯を変えた束から作る（曲のまま＝変えない）">${bandOptions(band)}</select>
     <button data-act="discard">やめる（今の譜面のまま）</button></div>
    <div class="hint">行を押すと帯と 3D がその案になる。${C.form ? `案は形の全部の回に「案 k」を付けて作り直した物（ほかは今の譜面に寄せる・同じグループのもう1つの形も少し変わり得る）。選ぶと形の全部の回の同じ振りの指示に「案 k」が付く。`
      : '案はテーマを曲のテーマの並びの中でずらして、区間だけ作り直した物（外は今の譜面のまま）。'}
     「広げた」案は、テーマを少ない曲にしか出ない型まで広げた束から選んだ物（型のデータベースの曲は決めも区間に入れる）。
     選ぶと区間に指示「案 k」（広げた案は「珍しい型まで」も・★の帯を変えた案は「★の帯」も）が付く（付けた指示の一覧と意思入れの帯に出る・Ctrl+Z か指示を消すと、次に作り直した時に既定の作り方に戻る）。</div>`;
  return h;
}
async function onCardClick(ev) {
  const b = ev.target.closest('button, tr.vsRow'); if (!b || b.disabled) return;
  const act = b.dataset.act;
  if (b.matches('tr.vsRow')) return selectCand(+b.dataset.n);
  if (act === 'stop') return backToResult();
  if (act === 'list') return openHistory();
  if (act === 'restore') { const w = $('vsWork') && $('vsWork').checked; lsSet('automap-vs-work', w); return restoreVersion(V.view.e, w); }
  if (act === 'play' && V.cand) return playRange(timeOf(V.cand.only[0]), timeOf(V.cand.only[1]));
  if ((act === 'run' || act === 'runs') && V.cand) {   // 形の回へ飛ぶ・全部の回を続けて鳴らす
    const fr = formRanges(V.cand.form); if (!fr.length) return;
    if (act === 'runs') { showRange(timeOf(fr[0][0]) - 2, timeOf(fr[fr.length - 1][1]) + 2); return playSeq(fr); }
    const r = fr[+b.dataset.i]; if (!r) return;
    showRange(timeOf(r[0]) - 4, timeOf(r[1]) + 4); return playRange(timeOf(r[0]) - 1, timeOf(r[1]));
  }
  if (act === 'choose') { lsSet('automap-vs-fix', $('vsFix').checked); return chooseCand($('vsFix').checked); }
  if (act === 'more' && V.cand) return startCands(V.cand.only, (V.cand.meta ? V.cand.meta.start + V.cand.meta.cands.length : 1), !!($('vsRare') && $('vsRare').checked),
                                                  $('vsBand') && $('vsBand').value ? JSON.parse($('vsBand').value) : null, V.cand.form || null);
  if (act === 'discard') return discardCands();
  if (act === 'cancel' && V.cand && V.followId) {   // 案を作るのを止める（server.cancel_job・作りかけの案は残さない）
    V.cand.stopping = true; render();
    try { await api('POST', '/api/job/cancel', {id: V.followId}); }
    catch (e) { V.cand.stopping = false; render(); A.status('やめられなかった: ' + e.message, true); }
  }
}

// ---- 別の案 ----
// 形の回の区間（[[b0, b1]]・回の順）。form＝{group, form}
function formRanges(form) {
  if (!form) return [];
  const MF = motifForms();
  return formRuns(MF, form.group + '|' + form.form).map(id => S.W.ranges.find(q => q.id === id)).filter(Boolean).map(q => [q.b0, q.b1]);
}
// 形の全部の回の同じ振りの指示に「案 k」（と rare・band）を書く（W を変える）
function addVariantForm(W, form, k, rare = false, band = null) {
  const MF = motifForms(W), ids = new Set(formRuns(MF, form.group + '|' + form.form));
  W.ranges.forEach(r => { if (!ids.has(r.id)) return; r.set.variant = k; if (rare) r.set.rare = 1; if (band != null) r.set.band = band; });
  return ids.size;
}
async function startCands(r, start = 1, rare = false, band = null, form = null) {
  if (!S.file || V.making || S.generating) return;
  const song = S.songs.find(q => q.song === S.song);
  if (!song || !song.app_exists) { A.status('別の案は、結果のファイルがある時だけ（先に上の「作り直す」で作る）', true); return; }
  await A.saveWork();
  if (V.view) await backToResult();
  V.cache = {};
  V.cand = {only: [Math.min(r[0], r[1]), Math.max(r[0], r[1])], meta: null, prog: [], sel: 0, secs: 0, rare: !!rare, band, form: form ? {group: form.group, form: form.form} : null};
  render();
  try {
    const {id} = await api('POST', '/api/cands/start', {file: S.file, only: V.cand.only, start, rare: !!rare, band, ...(V.cand.form ? {form: V.cand.form} : {})});
    await follow(id);
  } catch (e) { V.cand = null; render(); A.status('別の案を作れなかった: ' + e.message, true); }
}
function setBusy(v) {   // 作っている間は作り直し・区間だけ作り直す・別の案のボタンを止める（同じ曲の作業は1つずつ）
  emit('generating', v);
  $('gen').disabled = v;
  $('genState').textContent = v ? '別の案を作っている…' : '';
}
async function follow(id) {   // 作業の進み具合を見続ける（曲を開き直したら見るのをやめる・作業はサーバーで続く）
  const D = S.D, t0 = Date.now();
  V.followId = id; V.making = true; setBusy(true); render();
  try {
    let j;
    for (;;) {
      await sleep(1000);
      j = await api('GET', '/api/job?id=' + id);
      if (S.D !== D || V.followId !== id) return;
      if (V.cand) { V.cand.prog = j.cands || []; V.cand.secs = Math.round((Date.now() - t0) / 1000); render(); }
      if (j.state !== 'running') break;
    }
    if (j.cancelled) { V.cand = null; render(); A.status('別の案を作るのをやめた（結果のファイルは今のまま）'); return; }
    if (j.state !== 'done') { V.cand = null; render(); A.showReport('別の案を作れなかった', '<pre>' + esc(j.log || '') + '</pre>'); return; }
    const m = await api('GET', '/api/cands?file=' + enc(S.file));
    if (!m.cands || !V.cand) { V.cand = null; render(); A.status('結果のファイルが変わったので、案は使えなくなった', true); return; }
    V.cand.meta = m; if (m.form) V.cand.form = m.form;
    const [b0, b1] = m.only;
    showRange(timeOf(b0) - 2, timeOf(b1) + 2); seek(Math.max(0, timeOf(b0) - 0.5));
    A.status(`別の案を ${m.cands.filter(c => c.state === 'done').length} 個作った（${j.took} 秒）。右の表の行を押して見比べる`
             + (V.cand.form ? `（形 ${V.cand.form.group} ${V.cand.form.form}: 表の上の回のボタンでほかの回へ飛ぶ）` : ''));
    V.making = false;
    const first = m.cands.find(c => c.state === 'done');
    if (first) await selectCand(first.n);
  } catch (e) { A.status('別の案の様子が分からない: ' + e.message, true); }
  finally { if (V.followId === id) { V.followId = null; V.making = false; setBusy(false); render(); } }
}
async function selectCand(n) {
  if (!V.cand || !V.cand.meta) return;
  const c = n ? V.cand.meta.cands.find(q => q.n === n) : null;
  if (n && (!c || c.state !== 'done')) return;
  const key = n ? 'c' + n : 'cur', f = enc(S.file);
  const end = V.cache[key] ? () => {} : A.busy(n ? `案${candV(n)} を読み込んでいます…` : '今の譜面を読み込んでいます…');   // 読み込み中の札（main.js）
  try {
    let it = V.cache[key];
    if (!it) it = V.cache[key] = n ? await fetchPair(`/api/cands/chart?file=${f}&n=${n}`, `/api/cands/nlmf?file=${f}&n=${n}`)
                                   : await fetchPair(`/api/chart?file=${f}`, `/api/nlmf?file=${f}`);
    end();
    if (!V.cand) return;
    V.view = n ? {kind: 'cand', n} : null;   // 先に（'chart' を受ける側が見ている版を読む）
    showChart(it);
    V.cand.sel = n; render();
  } catch (e) { end('案を読めなかった: ' + e.message); A.status('案を読めなかった: ' + e.message, true); }
}
// 区間 [b0, b1] に指示「案 k」を足す（W を変える）。全く同じ区間の指示があれば、その set に入れる（ほかの指示は残す）。
// 重なる区間のほかの「案」は外す（区間に収まる物は外し、はみ出す物ははみ出した所だけ「案」を残す）＝後で選んだ案がこの区間で必ず勝つ
// （作業ファイルは区間の始まりの順に並べ直すので、付けた順だけでは勝ち負けが決まらない）。rare＝珍しい型まで広げた案（「珍しい型まで」も
// 足す。重なる区間の「珍しい型まで」はそのまま＝小節ごとに足し合わせなので、案と違ってぶつからない）。band＝★の帯を変えた案（「★の帯」も足す・
// 重なる区間の★の帯はそのまま＝小節ごとに後の区間が勝つ）
function addVariant(W, b0, b1, k, rare = false, band = null) {
  const eq = (a, b) => Math.abs(a - b) < 1e-6;
  const same = W.ranges.filter(r => eq(r.b0, b0) && eq(r.b1, b1) && !r.set.rest), target = same[same.length - 1] || null;
  const keep = [], add = [];
  W.ranges.forEach(r => {
    if (r === target || r.set.variant == null || r.b0 >= b1 - 1e-6 || r.b1 <= b0 + 1e-6) { keep.push(r); return; }
    const old = r.set.variant;
    delete r.set.variant;
    if (Object.keys(r.set).length) keep.push(r);
    if (r.b0 < b0 - 1e-6) add.push({id: newId(), b0: r.b0, b1: b0, set: {variant: old}});
    if (r.b1 > b1 + 1e-6) add.push({id: newId(), b0: b1, b1: r.b1, set: {variant: old}});
  });
  if (target) { target.set.variant = k; if (rare) target.set.rare = 1; if (band != null) target.set.band = band; }
  else add.push({id: newId(), b0, b1, set: Object.assign({variant: k}, rare ? {rare: 1} : {}, band != null ? {band} : {})});
  W.ranges = keep.concat(add);
}
async function chooseCand(fix, ask = true) {
  const n = V.cand && V.cand.sel; if (!n) return;
  const k = candV(n), [b0, b1] = V.cand.only, c = V.cand.meta && V.cand.meta.cands.find(q => q.n === n), rare = !!(c && c.rare);
  const band = c && c.band != null ? c.band : null, form = V.cand.form || null, nf = form ? formRanges(form).length : 0;
  const what = `「案 ${k}」` + (rare ? '「珍しい型まで」' : '') + (band != null ? `「${bandText(band)}」` : '');
  const where = form ? `形 ${form.group} ${form.form} の全部の回（${nf} 回）の同じ振りの指示に` : '区間に指示';
  if (ask && !confirm(`案${k} を結果のファイルにします（今の結果のファイルは履歴に控えます）。\n${where}${what}を付けます（全部を作り直しても${form ? 'この形' : '区間'}のテーマは案 ${k} のまま・指示を消せば既定の作り方）。`
                      + `${fix ? '\n区間のクリップは「固定」にします。' : ''}\nよいですか？`)) return;
  let end = () => {};
  try {
    const W2 = JSON.parse(JSON.stringify(S.W));   // 履歴の版に控える作業ファイル（足した後）
    if (form) addVariantForm(W2, form, k, rare, band); else addVariant(W2, b0, b1, k, rare, band);
    end = A.busy(`案${k} を結果のファイルにしています…`);   // 読み込み中の札（main.js）
    const r = await api('POST', '/api/cands/choose', {file: S.file, n, fix, work: workBody(W2)});
    V.cand = null; V.view = null; V.cache = {}; render();
    const kk = r.variant ?? k, rr = r.rare ?? rare, bb = r.band !== undefined ? r.band : band, ff = r.form || form;
    let nn = 0;
    commit(W => { if (ff) nn = addVariantForm(W, ff, kk, rr, bb); else addVariant(W, b0, b1, kk, rr, bb); });   // 作業ファイルの正は画面（Ctrl+Z で外せる）
    const er = S.edit != null && S.W.ranges.find(q => q.id === S.edit);   // 直している指示の欄も合わせる（「この指示を直す」で消えないように）
    if (S.edit != null && !er) { S.edit = null; S.panel = {}; }
    else if (er) { if (er.set.variant != null) S.panel.variant = er.set.variant; else delete S.panel.variant; if (er.set.rare) S.panel.rare = er.set.rare; if (er.set.band != null) S.panel.band = er.set.band; }
    await A.saveWork();
    await A.reloadChart();
    end();
    A.status(`案${kk} を結果のファイルにした（履歴に控えた）。${ff ? `形 ${ff.group} ${ff.form} の ${nn} 回` : '区間'}に指示「案 ${kk}」${rr ? '「珍しい型まで」' : ''}${bb != null ? `「${bandText(bb)}」` : ''}を付けた（全部を作り直しても${ff ? '形' : '区間'}のテーマは案のまま）`
             + (r.fixed ? `。区間のクリップ ${r.fixed} 個を固定にした` : ''));
    A.showReport(`別の案 ${kk} を選んだ（${span(r.only)}）`, A.reportHTML(r.report || ''));
  } catch (e) { end('選べなかった: ' + e.message); A.status('選べなかった: ' + e.message, true); }
}
async function discardCands() {
  try { await api('POST', '/api/cands/discard', {file: S.file}); } catch (e) { /* 消せなくても表示は戻す */ }
  V.cand = null; V.cache = {};
  await backToResult();
  A.status('別の案をやめた（今の譜面のまま）');
}

// ---- 履歴 ----
const histOpen = () => $('vsHist') && $('vsHist').style.display === 'flex';
function closeHistory() { $('vsHist').style.display = 'none'; }
async function openHistory() {
  if (!S.file) return;
  try { V.hist = await api('GET', '/api/versions?file=' + enc(S.file)); } catch (e) { A.status('履歴を読めなかった: ' + e.message, true); return; }
  renderHistory();
  $('vsHist').style.display = 'flex';
}
function renderHistory() {
  const d = V.hist, busy = d.busy || V.making || S.generating, vid = V.view && V.view.kind === 'hist' ? V.view.e.id : null;
  $('vsHistSub').textContent = `${S.song}・${d.versions.length} 版（曲ごとに ${d.max} 版まで。☆ の版は消さない）`;
  let h = `<div class="bar wrap"><label class="ck" title="作業ファイル（意思入れ・量のライン・自動の休み）もその版の時の物に戻す">
      <input type="checkbox" id="vsHWork" ${lsGet('automap-vs-work', false) ? 'checked' : ''}> 戻す時に意思入れも戻す（既定は譜面だけ）</label>
      <span class="sub">戻す・案を選ぶ・作り直す前に、今の結果のファイルがどの版とも違えば（NLM で直した等）先に控える。</span></div>`;
  if (d.exists && !d.known) h += `<div class="bar wrap"><span class="warn">今の結果のファイルはどの版とも違う（NLM で直して保存した等）。</span><button data-h="snap">今の版を控える</button></div>`;
  if (busy) h += '<div class="warn">今この曲を作り直している（終わるまで戻せない）</div>';
  if (!d.versions.length) h += '<p class="sub">まだ控えは無い（作り直す・区間だけ作り直す・別の案を選ぶと控える）。</p>';
  else {
    h += `<table class="vsHTbl"><tr><th>時刻</th><th>したこと</th><th>区間</th><th>ノーツ</th><th class="vsStar" title="その版の譜面の★（nlm-rating＝BeatLeader の★の近似）">★</th><th>要点</th><th></th></tr>`
      + d.versions.map(e => `<tr class="${e.current ? 'cur' : ''}${e.id === vid ? ' viewing' : ''}">
        <td>${esc(when(e))}</td><td>${esc(e.title)}${e.current ? ' <span class="chip">今の版</span>' : ''}${e.id === vid ? ' <span class="chip vsOn">見ている</span>' : ''}${e.diff && S.D && S.D.base && e.diff !== S.D.base ? ` <span class="chip" title="この版の基準の難易度（基準を置き直す前の版）。戻すと今の基準の ${esc(diffText(S.D.base))} に入る">基準 ${esc(diffText(e.diff))}</span>` : ''}</td>
        <td>${e.only ? span(e.only) : '全部'}</td><td>${e.notes}</td>${starTd('h:' + e.id)}<td class="head">${esc((e.head || []).join('・'))}</td>
        <td class="ops"><button data-h="view" data-id="${e.id}">見る</button><button data-h="restore" data-id="${e.id}" ${busy || e.current ? 'disabled' : ''}>戻す</button>
         <button data-h="rep" data-id="${e.id}" ${e.report ? '' : 'disabled'}>報告</button>
         <button data-h="keep" data-id="${e.id}" class="${e.keep ? 'on' : ''}" title="${e.keep ? '残す印を外す' : '残す（古い版を消す時も消さない）'}">☆</button>
         <button data-h="del" data-id="${e.id}" ${e.current ? 'disabled' : ''} title="この版の控えを消す">消す</button></td></tr>`).join('')
      + '</table>';
  }
  $('vsHistBody').innerHTML = h;
  d.versions.forEach(e => wantStar(V.hstars, 'h:' + e.id, '&ver=' + enc(e.id)));
}

// ---- ★（app/rating.py） ----
const starBox = key => (key.startsWith('h:') ? V.hstars : (V.cand && V.cand.stars) || {});
function starText(key) {   // → [中身, 見出し（title）]
  const it = starBox(key)[key];
  if (!it || it.state !== 'done') return ['…', '★を測っている（nlm-rating）'];
  const r = it.r;
  if (!r.ok) return ['?', '★を測れなかった: ' + (r.error || '')];
  if (r.skipped || r.stars == null) return ['—', `★を測れない（${r.skipped || '答えが無い'}・ノーツ ${r.notes}）`];
  let t = `★ ${(+r.stars).toFixed(2)}・Pass ${(+r.pass).toFixed(2)}・Tech ${(+r.tech).toFixed(2)}・Acc ${(+r.acc).toFixed(2)}` +
    (r.predicted_acc != null ? `・予測精度 ${(r.predicted_acc * 100).toFixed(1)}%` : '') + `\nノーツ ${r.notes}` + (r.nps ? `・1秒 ${r.nps.toFixed(1)} ノーツ` : '');
  const cur = key.startsWith('c:') && key !== 'c:0' && starBox(key)['c:0'];
  if (cur && cur.state === 'done' && cur.r.ok && cur.r.stars != null) {
    const dv = r.stars - cur.r.stars;
    t += `\n今の譜面（★ ${(+cur.r.stars).toFixed(2)}）より ${dv >= 0 ? '+' : '−'}${Math.abs(dv).toFixed(2)}`;
  }
  return [(+r.stars).toFixed(2), t];
}
function starTd(key) { const [v, t] = starText(key); return `<td class="vsStar" data-star="${attr(key)}" title="${attr(t)}">${v}</td>`; }
function paintStars() {   // 欄を描き直さずに★の所だけ書き換える（チェックの状態などを崩さない）
  document.querySelectorAll('[data-star]').forEach(td => { const [v, t] = starText(td.dataset.star); td.textContent = v; td.title = t; });
}
function wantStar(box, key, qs) {
  if (ST.na || box[key]) return;
  box[key] = {state: 'wait'};
  ST.q.push({box, key, qs, file: S.file});
  pump();
}
async function pump() {   // 1 つずつ測る（running の間は聞き直す）
  if (ST.busy) return;
  ST.busy = true;
  try {
    while (ST.q.length) {
      const it = ST.q.shift();
      if (it.file !== S.file || ST.na) continue;   // 曲を開き直した・測れない PC
      it.box[it.key] = {state: 'run'};
      let r = null;
      for (let i = 0; i < 40 && !r; i++) {
        try { const a = await api('GET', `/api/rating?wait=8&file=${enc(it.file)}${it.qs}`); if (a.state !== 'running') r = a; }
        catch (e) { r = {state: 'done', ok: false, error: e.message}; }
      }
      if (r && r.state === 'unavailable') { ST.na = true; document.body.classList.add('vsNoStar'); }   // 測れない PC＝列ごと隠す
      it.box[it.key] = {state: 'done', r: r || {ok: false, error: '測るのに時間がかかりすぎた'}};
      paintStars();
    }
  } finally { ST.busy = false; }
}
async function onHistClick(ev) {
  const b = ev.target.closest('button[data-h]'); if (!b || b.disabled) return;
  const id = b.dataset.id, e = id && V.hist.versions.find(v => v.id === id), f = enc(S.file);
  try {
    if (b.dataset.h === 'view') return viewVersion(e);
    if (b.dataset.h === 'restore') { const w = $('vsHWork').checked; lsSet('automap-vs-work', w); return restoreVersion(e, w); }
    if (b.dataset.h === 'rep') { const {md} = await api('GET', `/api/versions/report?file=${f}&id=${id}`); closeHistory(); A.showReport(`${e.at}「${e.title}」の報告`, A.reportHTML(md)); return; }
    if (b.dataset.h === 'keep') await api('POST', '/api/versions/keep', {file: S.file, id, keep: !e.keep});
    if (b.dataset.h === 'del') { if (!confirm(`${e.at}「${e.title}」の控えを消します。よいですか？`)) return; await api('POST', '/api/versions/delete', {file: S.file, id}); }
    if (b.dataset.h === 'snap') await api('POST', '/api/versions/snapshot', {file: S.file});
    await openHistory();
  } catch (err) { A.status(err.message, true); }
}
async function viewVersion(e) {
  const q = `?file=${enc(S.file)}&id=${e.id}`;
  const end = A.busy(`${e.at} の版を読み込んでいます…`);   // 読み込み中の札（main.js）
  try {
    const it = await fetchPair('/api/versions/chart' + q, '/api/versions/nlmf' + q);
    end();
    if (V.cand) V.cand.sel = null;
    V.view = {kind: 'hist', e};   // 先に（'chart' を受ける側が見ている版を読む）
    showChart(it);
    closeHistory(); render();
    if (e.only) showRange(timeOf(e.only[0]) - 2, timeOf(e.only[1]) + 2);
    A.status(`${e.at} の版を見ている（帯と 3D。右の欄の上で「この版に戻す」「見るのをやめる」）`);
  } catch (err) { end('その版を読めなかった: ' + err.message); A.status('その版を読めなかった: ' + err.message, true); }
}
async function restoreVersion(e, work) {
  if (!confirm(`${e.at}「${e.title}」の版に戻します。${work ? '意思入れ（作業ファイル）も戻します。' : '意思入れはそのまま（譜面だけ戻す）。'}\n今の結果のファイルは履歴に控えます。よいですか？`)) return;
  const end = A.busy(`${e.at} の版に戻しています…`);   // 読み込み中の札（main.js）
  try {
    await A.saveWork();
    const r = await api('POST', '/api/versions/restore', {file: S.file, id: e.id, work: !!work});
    if (r.work) applyWork(r.work);
    V.view = null; V.cand = null; V.cache = {}; render(); closeHistory();
    await A.reloadChart();
    end();
    A.status(`${e.at} の版に戻した` + (r.work ? '（意思入れも。Ctrl+Z で前の意思入れに戻せる）' : '（譜面だけ）')
             + (r.merged ? `。戻したのは基準の ${diffText(S.D.base)} だけ（ほかの難易度・ライト・書き出す印は今のまま＝新しい版として控えた）` : '') + '。NLM で開いていたら開き直す');
  } catch (err) { end('戻せなかった: ' + err.message); A.status('戻せなかった: ' + err.message, true); }
}
function applyWork(w) {   // 戻した意思入れを画面へ（元に戻せる操作にする＝前の意思入れは Ctrl+Z で戻る）
  const seen = new Set(), rs = (w.ranges || []).filter(r => { const k = rangeKey(r); if (seen.has(k)) return false; seen.add(k); return true; });
  S.edit = null; S.panel = {}; S.lineSel = null;
  commit(W => {
    W.ranges = rs.map(r => ({id: newId(), b0: r.b0, b1: r.b1, set: r.set || {}}));
    W.line = (w.line || []).map(k => ({b: k.b, k: k.k, smooth: !!k.smooth}));
    W.auto_rest = w.auto_rest || {on: false, b: null};
  });
}

// ---- 確かめ用（見えない Edge で開いて画像に写す） ----
async function selfTest() {   // #vtest=…&song=曲名 で、その曲を開いてから
  const h = decodeURIComponent(location.hash), sm = h.match(/&song=([^&]+)/);
  if (sm && S.song !== sm[1] && S.songs.some(q => q.song === sm[1])) { V.tested = false; await A.openSong(sm[1]); return; }
  const m = h.match(/^#vtest(?:=([a-z]+)(\d*))?/), what = (m && m[1]) || 'hist', n = +(m && m[2]) || 2;
  if (what === 'hist') return openHistory();
  if (what === 'edit') {
    const r = S.W.ranges.find(q => q.set.variant != null); if (!r) { document.title = 'vtest-edit なし'; return; }
    emit('editDirective', r); S.panel.hands = 1; $('iUpd').click();
    const r2 = S.W.ranges.find(q => q.b0 === r.b0 && q.b1 === r.b1 && q.set.hands === 1);
    document.title = 'vtest-edit ' + JSON.stringify(r2 ? r2.set : null);
    if (r2) { emit('editDirective', r2); showRange(timeOf(r2.b0) - 8, timeOf(r2.b1) + 8); }
    return;
  }
  if (what === 'addvar') {   // 「これにする」で足す「案」の決まり（作業ファイルは変えない・結果を document.title に）
    const W = {ranges: [{id: 1, b0: 0, b1: 16, set: {variant: 2}}, {id: 2, b0: 8, b1: 12, set: {variant: 3, hands: 1}},
                        {id: 3, b0: 20, b1: 24, set: {amount: 1}}, {id: 4, b0: 20, b1: 24, set: {hands: 1}}]};
    addVariant(W, 4, 12, 5); addVariant(W, 20, 24, 6, true); addVariant(W, 30, 34, 7, true);
    document.title = 'vtest-addvar ' + JSON.stringify(W.ranges.map(r => [r.b0, r.b1, r.set]));
    return;
  }
  if (what === 'rare') {   // 指示の欄の「型の幅: 珍しいまで」「決め: 入れる」を押して付ける → 付けた指示を document.title に（一覧のチップ・帯の札も写る）
    const B = S.D.mus.beats, b0 = B[20], b1 = B[24];
    S.sel = [[b0, b1]]; S.panel = {}; S.edit = null;
    document.querySelector('#insp button[data-k="rare"]').click();
    document.querySelector('#insp button[data-k="kime"][data-v="1"]').click();
    $('iAdd').click();
    const r = S.W.ranges.find(q => q.b0 === b0 && q.b1 === b1 && q.set.rare);
    document.title = 'vtest-rare ' + JSON.stringify(r ? r.set : null) + ' 決めの欄=' + (($('iKimeNote') || {}).textContent || '');
    if (r) { emit('editDirective', r); showRange(timeOf(b0) - 8, timeOf(b1) + 8); }
    return;
  }
  if (what === 'unvar') {   // 「案」の付いた最初の指示を「直す」で開いて「外す」→ 残った指示を document.title に（「案」だけなら指示ごと消える＝null）
    const r = S.W.ranges.find(q => q.set.variant != null); if (!r) { document.title = 'vtest-unvar なし'; return; }
    const [b0, b1] = [r.b0, r.b1];
    emit('editDirective', r); $('iVarDel').click();
    const r2 = S.W.ranges.find(q => q.b0 === b0 && q.b1 === b1);
    document.title = `vtest-unvar ${b0}-${b1} ` + JSON.stringify(r2 ? r2.set : null) + ` 直している=${S.edit != null}`;
    return;
  }
  if (what === 'view') {
    const d = await api('GET', '/api/versions?file=' + enc(S.file));
    V.hist = d;
    const e = d.versions.find(v => !v.current) || d.versions[0];
    if (e) await viewVersion(e);
    return;
  }
  if ((what === 'cand' || what === 'choose') && V.cand && V.cand.meta) {
    const [b0, b1] = V.cand.only;
    showRange(timeOf(b0) - 2, timeOf(b1) + 2); seek(timeOf(b0) + 1);
    const c = V.cand.meta.cands[n - 1];   // n 番目の案（案の番号は c.v）
    if (!c) return;
    await selectCand(c.n);
    if (what === 'choose') { await chooseCand(false, false); $('rep').style.display = 'none'; showRange(timeOf(b0) - 8, timeOf(b1) + 8); }
  }
}
