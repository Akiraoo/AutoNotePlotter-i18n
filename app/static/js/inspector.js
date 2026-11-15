// 右の欄: 選んだ区間に付ける指示（意思入れ・docs/意思入れ.md 7節）と、付けた指示の一覧・自動の休み。
// 同じ振りの形をつないで直す（docs/アプリ仕様.md 15 節）: 同じ振りの回（A1 等）を帯・一覧で押すと、その形の全部の回を選び（S.sel）、欄はその形の
//   設定（＝各回の同じ振りの指示の motif 以外の項目・回ごとに違えば印）。「この形の指示を直す」で形の全部の回に同じ物を書く（1回の commit）。
//   同じ振りの欄（グループの名前・そのまま／アレンジ・アレンジの量）はグループ全部にそろえる。形で直しているかは S.edit から決める（formOf）。
//   確かめ用の入口: #ftest（&song=曲名）→ 結果を document.title に（下の ftest）。
import {S, $, fmt, SIGN, timeOf, beatOf, BEATS, barIdx, rangeText, on, emit, commit, newId, rangeKey, motifForms, formColor, formLabel,
        formRuns, formDiff, withoutMotif, formDeleteItems, undo, workBody, saveWork, stable, UI, lsGet, lsSet, locked, api} from './store.js';
import {P, play, pause, playRange, seek, busyPlaying} from './player.js';
import {draw, selectRange, showRange, menu, V as TV} from './timeline.js';
import * as hooks from './hooks.js';

// ★の帯（境目は★の物差しの一部＝サーバーから。bandStars は automap/library_use.py の band_stars と同じ決まり）
const {steps: BAND_STEPS, choices: BAND_CHOICES, default: BAND_DEFAULT} = await api('GET', '/api/library/bands');
export function starsText(st) { if (!st || (st[0] <= 0 && st[1] >= 99)) return '★全部'; const [lo, hi] = st; return lo <= 0 ? `★〜${hi}` : hi >= 99 ? `★${lo}〜` : `★${lo}〜${hi}`; }
export function bandText(v) { return Array.isArray(v) ? starsText(v) : `★${Math.abs(v)}段${v > 0 ? '難しく' : 'やさしく'}`; }
function bandStars(v, base) {   // 指示の値 → [下, 上]（段の数なら曲の帯の両端を段の境目でずらす・下が開いた帯を難しくする時は上の2段の帯として数える）
  if (Array.isArray(v)) return v;
  const [lo, hi] = base && !(base[0] <= 0 && base[1] >= 99) ? base : BAND_DEFAULT;
  const step = x => BAND_STEPS.reduce((b, s, i) => Math.abs(s - x) < Math.abs(BAND_STEPS[b] - x) ? i : b, 0), n = BAND_STEPS.length - 1;
  let i = step(lo), j = Math.max(step(hi), i + 1);
  if (v > 0 && i === 0) i = Math.max(0, j - 2);
  const i2 = Math.min(Math.max(0, i + v), n - 1), j2 = Math.min(Math.max(i2 + 1, j + v), n);
  return [BAND_STEPS[i2], BAND_STEPS[j2]];
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);   // 押した値と欄の値（★の帯は [下, 上] の並びもある）
export function bandOptions(sel) {   // 別の案の「★の帯を変えて作る」の選び（versions.js も使う）。値は JSON（空＝曲のまま）
  const vs = [[null, '★の帯は曲のまま'], [-1, '★1段やさしく'], [1, '★1段難しく'], ...BAND_CHOICES.map(b => [b, starsText(b)])];
  return vs.map(([v, t]) => `<option value='${v == null ? '' : JSON.stringify(v)}'${same(v ?? null, sel ?? null) ? ' selected' : ''}>${t}</option>`).join('');
}
export const CTRL = [   // 区間の指示（g: 0 どこに打つか・1 どう置くか）。o＝押せる値（[値, 表示]）。押さない＝おまかせ
  {g: 0, k: 'source', n: '元にする音', o: [['vocal', '歌'], ['drums', 'ドラム'], ['bass', 'ベース'], ['inst', 'その他の楽器'], ['vocal+drums', '歌＋ドラム']],
   tip: '打点をどの音から拾うか（押さない＝おまかせ＝歌のある所は歌・無い所はドラムと楽器）。その他の楽器＝ギター・鍵盤など（ベースは入らない）'},
  {g: 0, k: 'amount', n: '量', o: [-2, -1, 1, 2], tip: '−2 1拍に1つまで・−1 強い打点を半拍まで・+1 弱い打点も＋空きをドラムで・+2 1/4拍まで'},
  {g: 0, k: 'snare', n: 'スネアに打つ', o: [[1, '1 強い所'], [2, '2 全部・両手']], tip: 'スネア（「タン」の太鼓）の打点を必ずノーツに（2＝強いスネアは両手）'},
  {g: 0, k: 'kick', n: 'キックで決める', o: [[1, '1 頭・強い所'], [2, '2 強いキック全部']], tip: 'キック（「ドン」の太鼓）の強い打点を両手の振り下ろしに'},
  {g: 0, k: 'fill', n: '空きを埋める', o: [[true, '入']], tip: '1拍以上ノーツの無い所に、ドラム・楽器の打点を足す'},
  {g: 0, k: 'vsnap', n: '歌を拍に寄せる', o: [[true, '寄せる'], [false, '寄せない']],
   tip: '歌のタイミングが拍とずれて感じる所に。迷った歌の打点を、隣の目盛り（1/4 拍）でキック・スネアが鳴っていればそちらへ置き直す（ノーツは増やさない・細かさは 1/4 拍まで）。押さない＝おまかせ＝歌が目盛りからばらつく所だけ弱く寄せる・寄せない＝おまかせでも寄せない'},
  {g: 0, k: 'rest', n: '休み', o: [[true, '入']], tip: 'この区間はノーツを置かない'},
  {g: 0, k: 'keep', n: 'そのまま残す', o: [[true, '入']],
   tip: 'この区間は前の譜面（今の結果のファイル）のノーツをそのまま残す（NLM の「固定」と同じ強さ・ほかの指示は効かない）。一覧から消せば次の作り直しで作り直す'},
  {g: 1, k: 'hands', n: '両手', o: [-1, 1, 2], tip: '−1 自動の両手も無し・+1 小節の頭と真ん中・+2 強い打点は全部'},
  {g: 1, k: 'speed', n: '振りの速さの上限', o: [-1, 1], tip: '−1 同じ手は0.20秒以上空ける・+1 0.12秒まで（今は0.15秒）'},
  {g: 1, k: 'move', n: '動きの大きさ', o: [-1, 1, 2], tip: '1振りごとの腕の移動'},
  {g: 1, k: 'width', n: '横の広がり', o: [-1, 1], tip: '−1 内側の2列に・+1 4列を使い切る（両手を同時に外へも。指示が無ければランク譜面のふつう＝3列くらいに寄せる）'},
  {g: 1, k: 'height', n: '腕の高さ', o: [-1, 1], tip: '上の段を減らす・増やす'},
  {g: 1, k: 'diag', n: '斜め', o: [-1, 1], tip: '斜めの振りを減らす・増やす'},
  {g: 1, k: 'turn', n: '向きの変わり方', o: [-1, 1], tip: '−1 真上・真下の往復・+1 45°曲げる振りを増やす'},
  {g: 1, k: 'variety', n: '型の変わり方', o: [-1, 1], tip: '−1 同じ型を長く・+1 もっと細かく変える'},
  {g: 1, k: 'bigmove', n: '大技', o: [[true, '入']], tip: '腕の交差・大きな跳びなどを少し許す'},
  {g: 1, k: 'rare', n: '型の幅', o: [[1, '珍しいまで']],
   tip: '押さない＝既定（曲のライブラリのしきい値・何曲以上に出た型か）。珍しいまで＝この区間の小節のテーマを、少ない曲にしか出ない型（2 曲以上）まで広げた束から選び直す（曲全体のテーマの束は変えない・「案 k」と一緒なら広げた束の中で案 k）。型のデータベースの曲は決めも入れる側'},
  {g: 1, k: 'band', n: '★の帯', o: [[-1, '1段やさしく'], [1, '1段難しく'], ...BAND_CHOICES.map(b => [b, starsText(b)])],
   tip: `この区間の小節のテーマを、型のライブラリの★の帯だけ変えて選び直す（曲全体のテーマの束・量は変えない）。1段＝帯の両端を★の段（〜${BAND_STEPS.slice(1, -1).join('・')}・それより上）で1つずらす（${starsText(BAND_DEFAULT)} の1段難しく＝${starsText(bandStars(1))}・1段やさしく＝${starsText(bandStars(-1))}）。帯を直接選ぶこともできる。「珍しいまで」「案 k」と一緒なら、その帯の束の中で`},
  {g: 1, k: 'kime', n: '決め', o: [[-1, '入れない'], [1, '入れる']],
   tip: '珍しい型の「決め」（1回だけの珍しい並び）を、この区間に入れる（曲の数の上限の外）・入れない。押さない＝既定（途切れの前・区間の変わり目などに自動）。型のデータベースの曲（上の「ライブラリ」で選んだ曲）だけ効く'},
];
const PRESETS = [
  ['華やか −1', {hands: -1, move: -1, width: -1}], ['華やか +1', {hands: 1, move: 1, width: 1}], ['華やか +2', {hands: 2, move: 2, width: 1, height: 1, diag: 1}],
  ['難しさ −2', {amount: -2, speed: -1, turn: -1, move: -1, variety: -1}], ['難しさ −1', {amount: -1, speed: -1, turn: -1}],
  ['難しさ +1', {amount: 1, turn: 1, variety: 1}], ['難しさ +2', {amount: 2, speed: 1, turn: 1, move: 1, variety: 1, bigmove: true}],
];
const AB = {source: v => '元:' + ({vocal: '歌', drums: 'ドラム', bass: 'ベース', inst: '楽器', 'vocal+drums': '歌＋ドラム'}[v] || v), amount: v => '量' + SIGN(v),
  snare: v => 'スネア' + v, kick: v => 'キック' + v, fill: () => '空き埋め', vsnap: v => v ? '歌を拍に' : '歌を寄せない', rest: () => '休み', keep: () => 'そのまま残す', hands: v => '両手' + SIGN(v), speed: v => '速さ' + SIGN(v),
  move: v => '動き' + SIGN(v), width: v => '横' + SIGN(v), height: v => '高さ' + SIGN(v), diag: v => '斜め' + SIGN(v), turn: v => '向き' + SIGN(v),
  variety: v => '型' + SIGN(v), bigmove: () => '大技', rare: () => '珍しい型まで', band: v => bandText(v), kime: v => v > 0 ? '決め入れる' : '決め入れない'};
export function summary(set) {
  const out = CTRL.filter(c => set[c.k] !== undefined).map(c => AB[c.k](set[c.k]));
  if (set.variant != null) out.push('案 ' + set.variant);   // 別の案で選んだ案（versions.js の「これにする」が付ける）
  if (set.motif) out.push(`同じ振り「${set.motif.group}」${set.motif.mode === 'arrange' ? '（アレンジ' + (set.motif.extra != null ? '・量' + SIGN(set.motif.extra) : '') + '）' : ''}`);
  if (set.comment) out.push('※' + set.comment);
  return out;
}
const clean = p => { const o = JSON.parse(JSON.stringify(p)); if (o.motif && !o.motif.group) delete o.motif; return o; };
function warnings(p) {
  const w = [], others = ks => Object.keys(p).some(k => !ks.includes(k));
  if (p.rest && others(['rest', 'comment'])) w.push('休みの区間にはほかの指示は効かない');
  if (p.keep && others(['keep', 'comment'])) w.push('そのまま残す区間は前の譜面のまま（ほかの指示は効かない）');
  if ((p.amount || 0) >= 1 && p.speed === -1) w.push('量を増やすと速い振りが要る（振りの速さの上限 −1 とぶつかる）');
  if (p.hands === -1 && (p.kick || p.snare === 2)) w.push('両手 −1 と、両手を足すキック・スネア2 がぶつかる');
  if (p.vsnap != null && p.source && !String(p.source).includes('vocal')) w.push('歌を拍に寄せるのは歌の打点だけ（元にする音に歌が無いと効かない）');
  if (p.motif && !p.motif.group) w.push('同じ振りのグループ名を入れる');
  return w;
}

function row(c) {
  const btns = c.o.map(o => { const [v, label] = Array.isArray(o) ? o : [o, SIGN(o)];
    return `<button data-k="${c.k}" data-v='${JSON.stringify(v)}'>${label}</button>`; }).join('');
  const note = c.k === 'band' ? '<span class="sub" id="iBandNote"></span>' : '';   // ★の帯: 選んだ帯
  return `<div class="row${c.later ? ' later' : ''}" data-row="${c.k}" title="${c.tip}"><div class="nm">${c.n}</div><div class="bs">${btns}${note}</div></div>`;
}
export function build() {
  $('selBox').innerHTML = `
<section class="card">
 <div class="cardHead">選んだ区間</div>
 <div id="iSel" class="selText"></div>
 <div class="bar wrap"><button id="iPlay">▶ 選んだ所を再生</button><button id="iShow">ここを広げて見る</button><button id="iClear">選ぶのをやめる</button>
  <button id="iRegen" title="選んだ区間だけ作り直す（外は今の譜面のまま・区間をまたぐクリップは境目で分ける）">この区間だけ作り直す</button>
  <button id="iCands" title="選んだ区間で別の案を作って見比べる">別の案を作る</button>
  <label class="ck" title="別の案を、少ない曲にしか出ない型（珍しい型）まで広げた束から作る（これにすると区間に「珍しい型まで」も付く）"><input type="checkbox" id="iCandsRare"> 珍しい型まで広げて</label>
  <select id="iCandsBand" title="別の案を、型のライブラリの★の帯を変えた束から作る（これにすると区間に「★の帯」も付く・曲のまま＝変えない）"></select></div>
 <div class="hint">帯をドラッグ（小節の頭にそろう・Alt で拍の頭・Shift で足す）／流れの表のまとまりをクリック（ダブルクリックで同じ記号を全部）</div>
</section>`;
  const box = $('insp');
  box.innerHTML = `
<section class="card">
 <div class="cardHead">指示 <span class="sub" id="iMode"></span></div>
 <div class="formBox" id="iForm"></div>
 <div class="bar wrap" id="iPresets"></div>
 <div class="row" id="iVarRow" title="別の案で選んだ案。作り直しても、この区間の小節のテーマは案のまま（置き方は前後とのつながりで少し変わり得る）。外す＝既定の作り方に戻す">
  <div class="nm">別の案</div><div class="bs"><span id="iVarText"></span><button id="iVarDel">外す</button></div></div>
 <details open><summary>どこに打つか</summary>${CTRL.filter(c => c.g === 0).map(row).join('')}</details>
 <details open><summary>どう置くか</summary>${CTRL.filter(c => c.g === 1).map(row).join('')}</details>
 <details><summary>同じ振り・コメント</summary>
  <div class="row"><div class="nm">同じ振り</div><div class="bs"><input type="text" id="iMotif" placeholder="グループ名（例 掛け声）" list="iMotifList"><datalist id="iMotifList"></datalist>
   <button data-mm="same">そのまま</button><button data-mm="arrange">アレンジ</button></div></div>
  <div class="row" id="iExtraRow"><div class="nm">アレンジの量</div><div class="bs"><button data-mx="-1">−1 減らす</button><button data-mx="0">0 同じ</button>
   <button data-mx="1">+1 少し増やす</button><button data-mx="2">+2 多く</button></div></div>
  <div class="hint">同じグループの区間には毎回同じ打点の並びと置き方。アレンジ＝1回目・3回目…が手本の形、2回目・4回目…がアレンジの形（その形どうしは同じ）。
   アレンジの量は2つ目の形のノーツの数（手本と比べて・押さない＝+1）。形の回（A1 等）を押すと形の全部の回を選び、ここで変えて「この形の指示を直す」で全部の回にそろう
   （グループの名前・そのまま／アレンジ・アレンジの量はグループ全部に）。形の区間の中に別に付けた指示も、その形の全部に効く</div>
  <div class="row"><div class="nm"></div><div class="bs"><button id="iFind">似た所を探す</button></div></div>
  <div id="iCand" class="cand"></div>
  <div class="row"><div class="nm">コメント</div><div class="bs"><input type="text" id="iComment" placeholder="作る側への伝言（譜面には効かない）"></div></div>
 </details>
 <div class="warn" id="iWarn"></div>
 <div class="bar act"><button class="main" id="iAdd">選んだ区間に付ける</button><button id="iUpd">この指示を直す</button><button id="iDel">消す</button><button id="iCancel">やめる</button></div>
</section>
<section class="card">
 <div class="cardHead">曲全体</div>
 <div class="row"><div class="nm">自動の休み</div><div class="bs" id="iRest"></div></div>
 <div class="hint">量のライン: 帯の上でダブルクリック＝その小節から値を変える点（10% きざみ）・ドラッグで動かす・右クリックでなめらかにつなぐ／消す・Delete で消す・全部消すのは帯の見出しの「全部消す」</div>
</section>`;
  PRESETS.forEach(([n, v]) => { const b = document.createElement('button'); b.textContent = n; b.onclick = () => { Object.assign(S.panel, JSON.parse(JSON.stringify(v))); refresh(); }; $('iPresets').appendChild(b); });
  const rb = document.createElement('button'); rb.textContent = '全部おまかせ';   // 別の案の「案 k」（と一緒の「珍しい型まで」）は残す（外すのは「外す」）
  rb.onclick = () => { const v = S.panel.variant, r = S.panel.rare;
    S.panel = v != null ? Object.assign({variant: v}, r ? {rare: r} : {}) : {}; refresh(); }; $('iPresets').appendChild(rb);
  box.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.k) { const k = b.dataset.k, v = JSON.parse(b.dataset.v); if (same(S.panel[k], v)) delete S.panel[k]; else S.panel[k] = v; refresh(); }
    if (b.dataset.mm) { const g = $('iMotif').value.trim(), m = b.dataset.mm;
      if (S.panel.motif && S.panel.motif.mode === m) delete S.panel.motif; else S.panel.motif = Object.assign(S.panel.motif || {}, {group: g, mode: m}); refresh(); }
    if (b.dataset.mx != null) { const v = +b.dataset.mx;   // アレンジの量（アレンジの時だけ）
      if (!S.panel.motif) S.panel.motif = {group: $('iMotif').value.trim(), mode: 'arrange'};
      S.panel.motif.mode = 'arrange';
      if (S.panel.motif.extra === v) delete S.panel.motif.extra; else S.panel.motif.extra = v; refresh(); }
  });
  $('iMotif').oninput = () => { const g = $('iMotif').value.trim(); if (S.panel.motif) S.panel.motif.group = g; else if (g) S.panel.motif = {group: g, mode: 'same'}; refreshWarn(); };
  $('iComment').oninput = () => { const c = $('iComment').value.trim(); if (c) S.panel.comment = c; else delete S.panel.comment; refreshWarn(); };
  $('iVarDel').onclick = dropVariant;
  $('iAdd').onclick = addFromPanel;
  $('iUpd').onclick = () => { const r = S.W.ranges.find(r => r.id === S.edit); if (!r) return;
    const MF = motifForms(), f = formOf(MF, r.id); if (f) { updateForm(r, f, MF); return; }   // 同じ振りの回＝形の全部の回にそろえる
    const set = clean(S.panel), sel = S.sel.length === 1 ? S.sel[0] : null;
    commit(() => { r.set = set; if (sel) [r.b0, r.b1] = sel; }); done(`指示を直した（${rangeText([r.b0, r.b1])}）`); };
  $('iDel').onclick = () => { const r = S.W.ranges.find(q => q.id === S.edit); if (!r) return;
    if (formOf(motifForms(), r.id)) { askDelete(r, $('iDel')); return; }   // 同じ振りの回＝回だけ／形の全部／グループの全部を選ぶ
    const id = S.edit; S.edit = null; S.panel = {}; commit(W => { W.ranges = W.ranges.filter(r => r.id !== id); }); };
  $('iCancel').onclick = () => { S.edit = null; S.panel = {}; refresh(); draw(); };
  $('iPlay').onclick = () => { if (!S.sel.length) return;
    if (S.sel.length > 1 && curForm()) playSeq(S.sel); else playRange(timeOf(S.sel[0][0]), timeOf(S.sel[0][1])); };   // 形を選んでいる時は全部の回を続けて
  $('iShow').onclick = () => { if (S.sel.length) showRange(timeOf(S.sel[0][0]), timeOf(S.sel[S.sel.length - 1][1])); };
  $('iClear').onclick = () => { S.sel = []; S.cand = []; refresh(); draw(); };
  $('iRegen').onclick = () => { if (S.sel.length === 1) emit('generateOnly', S.sel[0].slice()); };
  $('iCandsRare').checked = !!lsGet('automap-vs-rare', false);
  $('iCandsRare').onchange = () => lsSet('automap-vs-rare', $('iCandsRare').checked);
  $('iCandsBand').innerHTML = bandOptions((() => { try { const v = lsGet('automap-vs-band', ''); return v ? JSON.parse(v) : null; } catch (e) { return null; } })());
  $('iCandsBand').onchange = () => lsSet('automap-vs-band', $('iCandsBand').value);
  $('iCands').onclick = () => { const rare = $('iCandsRare').checked, band = $('iCandsBand').value ? JSON.parse($('iCandsBand').value) : null, MF = motifForms(), f = curForm(MF);
    if (f && !selMoved(MF)) { const r0 = S.W.ranges.find(q => q.id === formRuns(MF, f.key)[0]);   // 形の別の案: 区間＝形の1回目・form＝{group, form}
      emit('candidates', [r0.b0, r0.b1, rare, band, {group: f.group, form: f.form}]); return; }
    if (S.sel.length === 1) emit('candidates', [...S.sel[0].slice(0, 2), rare, band]); };   // 受け持ちは versions.js（3つ目＝珍しい型まで広げる・4つ目＝★の帯・5つ目＝形）
  on('generating', v => { S.generating = v; refresh(); });
  $('iFind').onclick = findSimilar;
  on('work', refresh); on('select', refresh);
  on('editDirective', openDirective);
  on('deleteDirective', deleteDirective);
  on('frame', seqFrame); on('player', () => { if (!busyPlaying()) SEQ = null; });
  on('work', () => { if (location.hash.startsWith('#ftest') && S.D && !FT.started) { FT.started = true; setTimeout(ftest, 1200); } });
  hooks.build(box, {playSeq});   // 盛り上がりの繰り返しの候補（hooks.js・指示のカードの下）
}

// ---- 同じ振りの形 ----
const formOf = (MF, id) => { const f = id != null ? MF.byId.get(id) : null; return f && !f.link ? f : null; };   // 回（形に付いた指示ではない）の形
export const curForm = (MF = motifForms()) => formOf(MF, S.edit);   // 形で直しているか（直している指示が同じ振りの回）
const eqB = (a, b) => Math.abs(a - b) < 1e-6;
const runName = (MF, id) => { const f = MF.byId.get(id); return f.form + f.n; };
const runsOf = (MF, key) => formRuns(MF, key).map(id => S.W.ranges.find(q => q.id === id)).filter(Boolean);
function selMoved(MF) {   // 形を直している時に区間が1つだけ選び直された（「直す」で押した回をそこへ動かす）。帯で選ぶと直すのをやめるので、今は帯からは起きない
  const r = S.W.ranges.find(q => q.id === S.edit);
  return S.sel.length === 1 && !!r && !(eqB(S.sel[0][0], r.b0) && eqB(S.sel[0][1], r.b1));
}
const selIsForm = (MF, f) => { const rs = runsOf(MF, f.key);   // 選んでいるのが形の全部の回そのもの（開いた時のまま）
  return S.sel.length === rs.length && rs.every((r, i) => eqB(S.sel[i][0], r.b0) && eqB(S.sel[i][1], r.b1)); };
function valText(k, v) { return v === undefined ? 'なし' : AB[k] ? AB[k](v) : k === 'variant' ? '案 ' + v : k === 'comment' ? '※' + v : k + ' ' + JSON.stringify(v); }
export function mixedText(MF, key) {   // 回ごとに違う項目 → ['量+1 は B1・B2 だけ', …]
  return formDiff(MF, key).map(({k, vals}) => {
    const lab = ids => ids.map(id => runName(MF, id)).join('・'), def = vals.filter(x => x.v !== undefined);
    if (vals.length === 2 && def.length === 1) return `${valText(k, def[0].v)} は ${lab(def[0].ids)} だけ`;
    return vals.map(x => `${valText(k, x.v)}＝${lab(x.ids)}`).join('、');
  });
}
function openDirective(r) {   // 帯・一覧・右クリックで指示を押した: 同じ振りの回なら形の全部の回を選ぶ・ほかは今まで通りその区間
  if (locked()) { emit('locked'); return; }   // 派生を見ている間は指示を開かない（store.locked）
  const MF = motifForms(), f = formOf(MF, r.id);
  S.edit = r.id; S.panel = f ? formPanel(MF, f, r) : clean(r.set); S.cand = [];
  S.sel = f ? runsOf(MF, f.key).map(q => [q.b0, q.b1]) : [[r.b0, r.b1]];
  refresh(); draw();
}
// 形の欄の初めの値＝作る側（intent.form_set）と同じ合わせ方: どれかの回に付いている物は形の全部に効く・同じ種類なら後の回。
// 押した回の設定だけを出すと、何も付いていない回を押して直した時に、ほかの回に付いていて効いていた物（速さ等）が消えた
function formPanel(MF, f, r) {
  const p = {};
  runsOf(MF, f.key).sort((a, b) => a.b0 - b.b0).forEach(q => Object.assign(p, withoutMotif(clean(q.set))));
  const own = clean(r.set);
  return own.motif ? Object.assign(p, {motif: own.motif}) : p;
}
// 形の全部の回の同じ振りの指示を欄のとおりにそろえる（motif 以外の項目は形の回に・motif の名前・そのまま／アレンジ・アレンジの量はグループ全部に）。1回の commit
function updateForm(r, f, MF) {
  if (S.panel.motif && !(S.panel.motif.group || '').trim()) { $('iWarn').textContent = '同じ振りのグループ名を入れる'; return; }
  const p = clean(S.panel), base = withoutMotif(p), m = p.motif || null, ids = new Set(formRuns(MF, f.key));
  const gids = new Set([...formRuns(MF, f.group + '|A'), ...formRuns(MF, f.group + '|B')]), mv = selMoved(MF) ? S.sel[0].slice() : null;
  commit(W => {
    W.ranges.forEach(q => { if (ids.has(q.id)) q.set = Object.assign(JSON.parse(JSON.stringify(base)), q.set.motif ? {motif: q.set.motif} : {}); });
    W.ranges.forEach(q => { if (!gids.has(q.id)) return;
      if (!m) { delete q.set.motif; return; }   // 同じ振りを外した＝グループ全部が同じ振りでなくなる（ほかの指示は残す）
      q.set.motif = Object.assign({}, q.set.motif, {group: m.group, mode: m.mode});
      if (m.extra != null) q.set.motif.extra = m.extra; else delete q.set.motif.extra; });
    if (!m) W.ranges = W.ranges.filter(q => Object.keys(q.set).length);
    if (mv) [r.b0, r.b1] = mv;
  });
  done(m ? `形 ${f.group} ${f.form} の ${ids.size} 回の指示をそろえた${mv ? `（${f.form}${f.n} を ${rangeText(mv)} へ動かした）` : ''}`
         : `グループ「${f.group}」の同じ振りをやめた（${gids.size} 回・ほかの指示は残した）`);
}
function askDelete(r, at) {   // 同じ振りの回を消す: 回だけ／形の全部／グループの全部（at＝出来事かボタン）
  const items = formDeleteItems(r); if (!items) return;
  const b = at && at.getBoundingClientRect ? at.getBoundingClientRect() : null;
  menu(b ? {clientX: b.left, clientY: b.bottom + 4} : at && at.clientX != null ? at : {clientX: innerWidth / 2, clientY: innerHeight / 2}, items);
}
function deleteDirective(r, mode, at) {   // mode: 無し＝回なら選びを出す・'one'・'form'・'group'
  if (locked()) { emit('locked'); return; }
  const MF = motifForms(), f = formOf(MF, r.id);
  if (f && !mode) { askDelete(r, at || $('iDel')); return; }
  const ids = new Set(!f || mode === 'one' ? [r.id] : mode === 'form' ? MF.members.get(f.key)
                      : [...(MF.members.get(f.group + '|A') || []), ...(MF.members.get(f.group + '|B') || [])]);
  const ef = curForm(MF);   // 直している指示が消える・直している形の回の番号が変わる時は、欄と選んだ区間を空にする
  if (ids.has(S.edit) || (f && ef && ef.group === f.group)) { S.edit = null; S.panel = {}; S.sel = []; }
  commit(W => { W.ranges = W.ranges.filter(q => !ids.has(q.id)); });
  if (f) emit('status', mode === 'one' ? `${f.group} の ${f.form}${f.n} を消した${f.arr && !f.last ? '（後ろの回の A・B が入れ替わった）' : ''}`
                                        : `${mode === 'form' ? '形 ' + f.group + ' ' + f.form : 'グループ「' + f.group + '」'} の指示 ${ids.size} 個を消した（Ctrl+Z で戻る）`);
}
// 形の全部の回を続けて鳴らす（回ごとに少し前から）。止める・ほかを再生すると終わる
let SEQ = null;
const SEQ_LEAD = 1.0, SEQ_TAIL = 0.4;
export function playSeq(list) {
  if (!list.length) return;
  const s = {list: list.map(r => r.slice()), i: 0};
  seek(timeOf(s.list[0][0]) - SEQ_LEAD); P.stopAt = null; SEQ = s;
  if (!busyPlaying()) play();
}
function seqFrame() {
  if (!SEQ || !busyPlaying()) return;
  const [b0, b1] = SEQ.list[SEQ.i];
  if (S.t < timeOf(b0) - SEQ_LEAD - 0.3 || S.t > timeOf(b1) + SEQ_TAIL + 0.6) { SEQ = null; return; }   // ほかの所を再生した・動かした
  if (S.t < timeOf(b1) + SEQ_TAIL) return;
  if (++SEQ.i >= SEQ.list.length) { SEQ = null; pause(); return; }
  seek(timeOf(SEQ.list[SEQ.i][0]) - SEQ_LEAD);
}
function addFromPanel() {
  if (!S.sel.length) return;
  const set = clean(S.panel);
  if (!Object.keys(set).length) { $('iWarn').textContent = '指示が何も入っていない'; return; }
  const have = new Set(S.W.ranges.map(rangeKey));   // 同じ所に同じ指示を2回付けない（押し直しで重なっていた）
  const add = S.sel.filter(([b0, b1]) => !have.has(rangeKey({b0, b1, set})));
  if (!add.length) { $('iWarn').textContent = 'その区間にはもう同じ指示が付いている'; return; }
  commit(W => add.forEach(([b0, b1]) => W.ranges.push({id: newId(), b0, b1, set: clean(set)})));
  done(`${add.length} か所に指示を付けた`);
}
// 「案 k」だけ外す（既定の作り方に戻す）。直している指示なら、すぐ作業ファイルからも外す（「案」だけの指示で欄にほかに何も無ければ指示ごと消す）
function dropVariant() {
  const k = S.panel.variant; delete S.panel.variant;
  const r = S.edit != null && S.W.ranges.find(q => q.id === S.edit), MF = motifForms(), f = curForm(MF);
  if (r && f) {   // 形を直している: 形の全部の回から外す
    const ids = new Set(formRuns(MF, f.key));
    if (S.W.ranges.some(q => ids.has(q.id) && q.set.variant != null)) {
      commit(W => W.ranges.forEach(q => { if (ids.has(q.id)) delete q.set.variant; }));
      emit('status', `形 ${f.group} ${f.form} の全部の回から案 ${k} を外した（作り直すと、この形は既定の作り方に戻る）`);
    }
    refresh(); draw(); return;
  }
  if (r && r.set.variant != null) {
    const gone = Object.keys(r.set).length === 1 && !Object.keys(S.panel).length;
    commit(W => { delete r.set.variant; if (gone) W.ranges = W.ranges.filter(q => q !== r); });
    if (gone) { S.edit = null; S.sel = []; }
    emit('status', `案 ${k} を外した（作り直すと、この区間は既定の作り方に戻る${r.set.rare ? '。「珍しい型まで」は残している＝外すのは型の幅の「珍しいまで」を押し直す' : ''}）`);
  }
  refresh(); draw();
}
// 付けた・直した後は欄と選んだ区間を空にする（そのままだと次の区間の前に毎回手で空にする必要があった・利用者）
function done(msg) { S.panel = {}; S.edit = null; S.sel = []; S.cand = []; refresh(); draw(); emit('status', msg); }
function refreshWarn() { $('iWarn').textContent = warnings(S.panel).join('／'); }
export function refresh() {
  if (!S.D) return;
  document.querySelectorAll('#insp button[data-k]').forEach(b => b.classList.toggle('on', same(S.panel[b.dataset.k], JSON.parse(b.dataset.v))));
  document.querySelectorAll('#insp button[data-mm]').forEach(b => b.classList.toggle('on', !!S.panel.motif && S.panel.motif.mode === b.dataset.mm));
  document.querySelectorAll('#insp button[data-mx]').forEach(b => b.classList.toggle('on', !!S.panel.motif && S.panel.motif.extra === +b.dataset.mx));
  $('iExtraRow').style.opacity = S.panel.motif && S.panel.motif.mode === 'arrange' ? 1 : 0.5;
  $('iVarRow').style.display = S.panel.variant != null ? '' : 'none';
  $('iVarText').textContent = S.panel.variant != null ? `案 ${S.panel.variant}（別の案で選んだ）` : '';
  if ($('iBandNote')) { const v = S.panel.band, base = S.W.library ? S.W.library.stars : null;   // 選んだ帯（曲の設定からずらした結果）
    $('iBandNote').textContent = v == null ? '' : (!Array.isArray(v) ? `（${S.W.library ? '曲の設定' : '既定'} ${starsText(base || BAND_DEFAULT)} → ${starsText(bandStars(v, base))}）` : ''); }
  if (document.activeElement !== $('iMotif')) $('iMotif').value = S.panel.motif ? S.panel.motif.group : '';
  if (document.activeElement !== $('iComment')) $('iComment').value = S.panel.comment || '';
  $('iMotifList').innerHTML = [...new Set(S.W.ranges.filter(r => r.set.motif).map(r => r.set.motif.group))].map(g => `<option value="${g}">`).join('');
  const MF = motifForms(), ef = curForm(MF), efSel = ef && selIsForm(MF, ef), efN = ef ? formRuns(MF, ef.key).length : 0;
  $('iSel').innerHTML = (efSel ? `<span class="chip form" style="background:${formColor(ef)}">形 ${ef.group} ${ef.form}・${efN} 回</span><br>` : '')
    + (S.sel.length ? S.sel.slice(0, 3).map(r => '<b>' + rangeText(r) + '</b>').join('<br>') + (S.sel.length > 3 ? `<br>ほか ${S.sel.length - 3} か所` : '') : '（まだ選んでいない）');
  $('iMode').textContent = ef ? `（形を直している（${ef.group} ${ef.form}・${efN} 回））` : S.edit ? '（付けた指示を直している）' : '';
  renderForm(MF, ef);
  const song = S.songs.find(q => q.song === S.song);   // 選んだ区間だけ作り直すのは、結果のファイルがあって区間が1つの時
  $('iRegen').disabled = S.generating || S.sel.length !== 1 || !(song && song.app_exists);
  $('iCands').disabled = S.generating || !(song && song.app_exists) || !(S.sel.length === 1 || efSel);   // 形を選んでいる時は形の別の案（区間＝1回目）
  $('iCands').title = $('iCands').disabled ? (!(song && song.app_exists) ? '先に上の「作り直す」で結果のファイルを作る' : '区間を1つだけ選ぶ（か同じ振りの回を押して形を選ぶ）')
    : efSel ? `形 ${ef.group} ${ef.form}（${efN} 回）の別の案を作って見比べる（1回目の区間で作り、形の全部の回に写る）` : '選んだ区間で別の案を作って見比べる';
  $('iRegen').title = !(song && song.app_exists) ? '先に上の「作り直す」で結果のファイルを作る' : S.sel.length !== 1 ? '区間を1つだけ選ぶ' : '選んだ区間だけ作り直す（外は今の譜面のまま・区間をまたぐクリップは境目で分ける）';
  $('iAdd').disabled = !S.sel.length || !!efSel;   // 形を開いたまま付けると回が増える＝「この形の指示を直す」で（区間を選び直せば付けられる）
  $('iAdd').title = efSel ? '形を直している間は「この形の指示を直す」で（帯で区間を選ぶと、形を直すのをやめて新しい区間の空の指示になる）' : '';
  $('iUpd').disabled = !S.edit; $('iDel').disabled = !S.edit; $('iCancel').disabled = !S.edit && !Object.keys(S.panel).length;
  // 強調の色は今押すボタンに: 付けた指示・形を直している間は「直す」（形なら全部の回に反映）、ほかは「付ける」（2026-11-02 利用者:
  // 形の 3 回を選んで直した時、強調の「付ける」が押せない色のままで、反映するボタンが目立たず押し間違えた）
  $('iUpd').classList.toggle('main', !!S.edit); $('iAdd').classList.toggle('main', !S.edit);
  $('iUpd').textContent = ef ? `この形の指示を直す（${efN} 回をそろえる）` : 'この指示を直す';
  $('iDel').textContent = ef ? '消す…' : '消す';
  const ar = S.W.auto_rest;
  $('iRest').innerHTML = `<button data-ar="on" class="${ar.on ? 'on' : ''}">入</button><button data-ar="off" class="${ar.on ? '' : 'on'}">切</button>
    <button data-ar="auto" class="${ar.b == null ? 'on' : ''}">曲の7割あたり</button><button data-ar="here" class="${ar.b != null ? 'on' : ''}">今の再生位置${ar.b != null ? '（' + fmt(timeOf(ar.b)) + '）' : ''}</button><span class="sub">（1小節休む）</span>`;
  $('iRest').querySelectorAll('button').forEach(b => b.onclick = () => { const v = b.dataset.ar;
    commit(W => { if (v === 'on' || v === 'off') W.auto_rest.on = v === 'on'; else if (v === 'auto') W.auto_rest.b = null; else W.auto_rest.b = BEATS()[barIdx(beatOf(S.t))]; }); });
  refreshWarn(); renderCand(); renderList();
}
// 形を直している時の欄の上の箱: 形の名前・回・回ごとに違う項目（直すと全部の回が欄のとおりになる）。回ごとに違う項目の行に印
function renderForm(MF, ef) {
  const box = $('iForm'), diff = ef ? formDiff(MF, ef.key) : [], mixedKeys = new Set(diff.map(d => d.k));
  document.querySelectorAll('#insp .row[data-row]').forEach(el => el.classList.toggle('mixed', mixedKeys.has(el.dataset.row)));
  if (!ef) { box.style.display = 'none'; box.innerHTML = ''; return; }
  const ids = formRuns(MF, ef.key), other = formRuns(MF, ef.group + '|' + (ef.form === 'A' ? 'B' : 'A')), mt = mixedText(MF, ef.key);
  const links = (MF.members.get(ef.key) || []).length - ids.length;
  box.style.display = 'block'; box.style.borderColor = formColor(ef);
  box.innerHTML = `<div><span class="chip form" style="background:${formColor(ef)}">${ef.group} ${ef.form}</span>${ef.form === 'A' ? '手本の形' : 'アレンジの形'}・${ids.length} 回
     <span class="runs">${ids.map(id => `<button data-run="${id}" class="${id === S.edit ? 'on' : ''}" title="ここへ飛んで鳴らす">${runName(MF, id)}</button>`).join('')}</span>
     ${ids.length > 1 ? '<button data-runall="1" title="形の全部の回を続けて鳴らす（回ごとに少し前から）">▶ 全部の回</button>' : ''}</div>
    <div class="sub">ここで変えて「この形の指示を直す」で、形の全部の回に同じ指示を書く${other.length ? `（もう1つの形 ${ef.form === 'A' ? 'B' : 'A'}・${other.length} 回は別）` : ''}。
     ${links ? `形に付いた指示 ${links} 個（→ の札）も形の全部に効く。` : ''}帯で別の区間を選ぶと、形を直すのをやめて新しい区間の空の指示になる</div>`
    + (mt.length ? `<div class="mixedNote">≠ 回ごとに違う: ${mt.join('／')}（欄は、どれかの回に付いている物を合わせた設定＝今の作り直しで形の全部に効いている物。直すと全部の回が欄のとおりになる）</div>` : '')
    + (ef.form === 'B' ? '<div class="sub">アレンジの形には「量」「元にする音」は効かない（アレンジの量で決める）</div>' : '');
  box.querySelectorAll('button[data-run]').forEach(b => b.onclick = () => { const r = S.W.ranges.find(q => q.id === +b.dataset.run); if (!r) return;
    showRange(timeOf(r.b0) - 4, timeOf(r.b1) + 4); playRange(timeOf(r.b0) - 1, timeOf(r.b1)); });
  const all = box.querySelector('button[data-runall]'); if (all) all.onclick = () => playSeq(runsOf(MF, ef.key).map(q => [q.b0, q.b1]));
}
function renderList() {
  const rs = S.W.ranges.slice().sort((a, b) => a.b0 - b.b0 || a.id - b.id), MF = motifForms(), ef = curForm(MF);
  const mixed = new Map([...MF.members.keys()].map(k => [k, mixedText(MF, k)]).filter(([, t]) => t.length));   // 回ごとに設定が違う形 → 違う所
  const fchip = f => f ? `<span class="chip form" style="background:${formColor(f)}" title="${f.form === 'A' ? '手本の形' : 'アレンジの形'}${f.link ? '（この形に付いた指示＝形の全部に効く）' : ''}">${f.link ? '→ ' : ''}${formLabel(f)}</span>` : '';
  const mchip = f => f && !f.link && mixed.has(f.key) ? `<span class="chip mixed" title="回ごとに違う: ${mixed.get(f.key).join('／').replace(/"/g, '&quot;')}（押して直すと形の全部の回がそろう）">≠ 回ごとに違う</span>` : '';
  $('iCount').textContent = rs.length ? rs.length + ' 個' : '';
  $('iList').innerHTML = rs.length ? rs.map(r => { const f = MF.byId.get(r.id), inForm = ef && f && f.key === ef.key && r.id !== S.edit;
    return `<div class="item${r.id === S.edit ? ' cur' : ''}${inForm ? ' inForm' : ''}" data-id="${r.id}"${f ? ` style="border-left:4px solid ${formColor(f)}"` : ''}>
     <div class="when">${fmt(timeOf(r.b0))}〜${fmt(timeOf(r.b1))}<span class="sub">（拍 ${+r.b0.toFixed(2)}〜${+r.b1.toFixed(2)}）</span></div>
     <div class="chips">${fchip(f)}${summary(r.set).filter(s => !(f && !f.link && s.startsWith('同じ振り'))).map(s => `<span class="chip">${s}</span>`).join('')}${mchip(f)}</div>
     <div class="ops"><button data-pl="${r.id}" title="ここだけ再生">▶</button><button data-ed="${r.id}">直す</button><button data-rm="${r.id}">消す</button></div></div>`; }).join('')
    : '<div class="hint">まだ指示は無い。帯で区間を選んで、上の欄から付ける。</div>';
  const find = id => S.W.ranges.find(r => r.id === +id);
  $('iList').querySelectorAll('.item').forEach(el => { el.onmouseenter = () => { S.hoverId = +el.dataset.id; draw(); };
    el.onmouseleave = () => { S.hoverId = null; draw(); }; });
  $('iList').querySelectorAll('button[data-ed]').forEach(b => b.onclick = () => { const r = find(b.dataset.ed); emit('editDirective', r); seek(timeOf(r.b0)); });
  $('iList').querySelectorAll('button[data-pl]').forEach(b => b.onclick = () => { const r = find(b.dataset.pl); playRange(timeOf(r.b0), timeOf(r.b1)); });
  $('iList').querySelectorAll('button[data-rm]').forEach(b => b.onclick = () => emit('deleteDirective', find(b.dataset.rm), undefined, b));   // 同じ振りの回は選びを出す
}

// ---- 似た所を探す（拍ごと・歌の音名と伴奏の和音・転調した所は半音ずらして比べる） ----
const keyShiftAt = b => S.D.mus.shift[barIdx(b)] || 0;
function dotRolled(a, b, k) { let s = 0; for (let i = 0; i < 12; i++) s += a[(i - k + 12) % 12] * b[i]; return s; }
function findSimilar() {
  if (S.sel.length !== 1) { $('iWarn').textContent = '1か所だけ選んでから押す'; return; }
  const [b0, b1] = S.sel[0], s0 = Math.round(b0), L = Math.max(1, Math.round(b1 - b0));
  const M_ = S.D.mus.bf.mel, A_ = S.D.mus.bf.acc, N = M_.length, nz = v => v.some(x => x !== 0);
  const voc = S.D.blocks.some(k => k[7] && k[5] < b1 && k[6] > b0) && M_.slice(s0, s0 + L).some(nz), wm = voc ? 0.7 : 0;
  const ks0 = keyShiftAt(s0), sc = [];
  for (let j = 0; j + L <= N; j++) {
    if (j < s0 + L && j + L > s0) continue;
    const kexp = ((keyShiftAt(j) - ks0) % 12 + 12) % 12;
    let best = -1, bk = 0;
    for (const k of [0, 1, 2, 10, 11]) {
      let m = 0, mc = 0, a = 0;
      for (let i = 0; i < L; i++) { if (nz(M_[s0 + i]) && nz(M_[j + i])) { m += dotRolled(M_[s0 + i], M_[j + i], k); mc++; } a += dotRolled(A_[s0 + i], A_[j + i], k); }
      let v = wm * (mc ? m / mc : 0) + (1 - wm) * a / L; if (k !== kexp) v -= 0.1;
      if (v > best) { best = v; bk = k; }
    }
    sc.push([best, j, bk]);
  }
  sc.sort((a, b) => b[0] - a[0]);
  const got = [];
  for (const [s, j, k] of sc) { if (s < 0.7 || got.length >= 20) break; if (got.some(o => j < o.j + L && j + L > o.j)) continue; got.push({j, s, k}); }
  S.cand = got.sort((a, b) => a.j - b.j).map(o => ({b0: o.j, b1: o.j + L, s: o.s, k: o.k > 6 ? o.k - 12 : o.k, on: true}));
  $('iWarn').textContent = S.cand.length ? '' : `似た所は見つからなかった（${voc ? '歌と伴奏' : '伴奏'}で比べた）`;
  refresh(); draw();
}
function renderCand() {   // 似た所の一覧（hooks.js が帯に出す繰り返しの候補＝hook の印は入れない）
  const box = $('iCand');
  if (!S.cand.length || S.cand.some(c => c.hook)) { box.innerHTML = ''; return; }
  const kname = k => k ? `・半音${k > 0 ? '上' : '下'}${Math.abs(k) > 1 ? Math.abs(k) : ''}` : '';
  box.innerHTML = '<div class="sub">似た所（チェックした所を選ぶ）</div>' + S.cand.map((c, i) =>
    `<div class="ci"><label><input type="checkbox" data-c="${i}" ${c.on ? 'checked' : ''}> ${fmt(timeOf(c.b0))}〜（${c.s.toFixed(2)}${kname(c.k)}）</label><button data-p="${i}" title="ここだけ再生">▶</button></div>`).join('')
    + '<div class="bar"><button id="iCandAdd">チェックした所も選ぶ</button><button id="iCandClr">候補を消す</button></div>';
  box.querySelectorAll('input[data-c]').forEach(x => x.onchange = () => { S.cand[+x.dataset.c].on = x.checked; draw(); });
  box.querySelectorAll('button[data-p]').forEach(b => b.onclick = () => { const c = S.cand[+b.dataset.p]; playRange(timeOf(c.b0), timeOf(c.b1)); });
  $('iCandAdd').onclick = () => { const cs = S.cand.filter(c => c.on); cs.forEach(c => selectRange(c.b0, c.b1, true)); S.cand = []; refresh(); draw(); };
  $('iCandClr').onclick = () => { S.cand = []; refresh(); draw(); };
}

// ---- 確かめ用（見えない Edge で開いて画像に写す・結果は document.title に） ----
// #ftest（&song=曲名）: 帯の意思入れで最初の同じ振りのグループの A1 を押す（canvas に押した出来事を送る）→ 形の全部の回が選ばれるか・欄の印 →
//   B1 を押す → B の欄で「両手 +1」を足して「この形の指示を直す」→ B の全部の回が同じか → Ctrl+Z 1回で戻るか → ふつうの区間を押す → 形の別の案の本文。
//   作業ファイルには保存しない。#ftest=a・=b・=upd はそこで止めて写す（=resel は A1 の後に帯で別の区間を選ぶ）。#ftest=save は B を直して作業ファイルに保存する（写しの場所でだけ使う）
const FT = {started: false};
function clickIntent(r) {   // 意思入れの帯の r の真ん中を押す（timeline.js の mousedown・mouseup と同じ道）
  const cv = $('lanes'), rc = cv.getBoundingClientRect(), u = UI.s, gut = Math.round(132 * u), W = cv.clientWidth;
  const t = (timeOf(r.b0) + timeOf(r.b1)) / 2, x = gut + (t - TV.t0) / TV.span * (W - gut - 8);
  const y = Math.round(20 * u) + Math.round(22 * u) + 3 + Math.round(22 * u) + 3 + Math.round(26 * u) / 2;
  const o = {clientX: rc.left + x, clientY: rc.top + y, button: 0, bubbles: true};
  cv.dispatchEvent(new MouseEvent('mousedown', o)); window.dispatchEvent(new MouseEvent('mouseup', o));
}
async function ftest() {
  const h = decodeURIComponent(location.hash), sm = h.match(/&song=([^&]+)/);
  if (sm && S.song !== sm[1] && S.songs.some(q => q.song === sm[1])) { FT.started = false; $('song').value = sm[1]; $('song').dispatchEvent(new Event('change')); return; }
  const step = (h.match(/^#ftest(?:=([a-z]+))?/) || [])[1] || 'all';
  if (step !== 'save') S.readonly = true;
  const MF = motifForms(), g = [...MF.byId.values()].find(f => !f.link)?.group;
  if (!g) { document.title = 'ftest 同じ振りなし'; return; }
  const find = id => S.W.ranges.find(q => q.id === id), A = formRuns(MF, g + '|A').map(find), B = formRuns(MF, g + '|B').map(find), out = {group: g, A: A.length, B: B.length};
  const look = () => ({sel: S.sel.length, edit: S.edit, mode: $('iMode').textContent, mixed: (($('iForm').querySelector('.mixedNote') || {}).textContent || ''),
                       upd: $('iUpd').textContent, add: $('iAdd').disabled, cands: $('iCands').disabled});
  const wide = () => showRange(timeOf(A[0].b0) - 3, timeOf(Math.max(A[A.length - 1].b1, B.length ? B[B.length - 1].b1 : 0)) + 3);
  const fin = () => { document.title = 'ftest ' + JSON.stringify(out); };
  wide(); await new Promise(r => setTimeout(r, 100));
  clickIntent(A[0]); out.a = look();
  if (step === 'a') { fin(); return; }
  if (step === 'menu') { $('iDel').click(); out.menu = [...$('ctx').querySelectorAll('button')].map(b => b.textContent); fin(); return; }   // 消す…の選び
  if (step === 'resel') { const B = BEATS(); selectRange(B[2], B[4]); refresh(); out.resel = look(); out.panel = S.panel; fin(); return; }   // A1 を押した後に帯で別の区間を選ぶ＝直すのをやめて空の指示
  if (B.length) { clickIntent(B[0]); out.b = look(); }
  if (step === 'b') { fin(); return; }
  if (!B.length) { fin(); return; }
  const before = stable(workBody());
  if (step !== 'save') document.querySelector('#insp button[data-k="hands"][data-v="1"]').click();
  $('iUpd').click();
  const MF2 = motifForms(), sets = formRuns(MF2, g + '|B').map(id => stable(withoutMotif(find(id).set)));
  const asets = formRuns(MF2, g + '|A').map(id => stable(find(id).set));
  out.upd = {same: sets.every(s => s === sets[0]), set: JSON.parse(sets[0]), n: sets.length, Aunchanged: asets.join() === A.map(r => stable(r.set)).join(),
             motifs: [...new Set(formRuns(MF2, g + '|A').concat(formRuns(MF2, g + '|B')).map(id => stable(find(id).set.motif)))].length};
  if (step === 'save') { await saveWork(); fin(); return; }
  if (step === 'upd') { clickIntent(find(formRuns(MF2, g + '|B')[0])); fin(); return; }
  undo(); out.undo = stable(workBody()) === before;
  const plain = S.W.ranges.find(q => !motifForms().byId.has(q.id));
  if (plain) { emit('editDirective', plain); out.plain = look(); }
  // 形の別の案: /api/cands/start に送る本文を見る（fetch を差し替えて、本当には作らない）
  clickIntent(find(formRuns(motifForms(), g + '|A')[0]));
  const of = window.fetch; let body = null;
  window.fetch = (url, o) => { if (String(url).includes('/api/cands/start')) { body = JSON.parse(o.body); return Promise.resolve(new Response('{"error":"ftest"}', {status: 400})); } return of(url, o); };
  $('iCands').disabled = false; $('iCands').click();
  await new Promise(r => setTimeout(r, 800)); window.fetch = of;
  out.cands = body;
  // 消す（形の全部）→ Ctrl+Z
  const n0 = S.W.ranges.length; emit('deleteDirective', A[0], 'form'); out.delForm = n0 - S.W.ranges.length; undo(); out.delUndo = S.W.ranges.length === n0;
  clickIntent(find(formRuns(motifForms(), g + '|A')[0])); wide();
  fin();
}
