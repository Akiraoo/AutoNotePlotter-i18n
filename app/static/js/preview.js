// 右下の 3D: NLM の 3D（preview-v4 の移植・app/static/preview3d/・NLM と同じ見え方）を使う。読めない時は canvas だけの簡単な見え方で代わりに描く。
// 譜面は結果のファイル（.nlmf）をそのまま nlmfToMap で読む＝NLM で入れた壁・ライトも出る。止まっている間も毎コマ時刻を渡す（ステージが後から読み込まれる）。
import {S, $, fmt, beatOf, timeOf, api, on, emit, commit, undo, redo, locked, saveWork, diffText, lsGet, lsSet, BEATS} from './store.js';
import {P, now as mediaNow} from './player.js';

const PV = {impl: null, kind: '', nlm: null, toMap: null, raf: 0};

export async function init() {
  const box = $('pv');
  // 上の欄は「再生と音」の 1 段（▶・時刻・パート・曲の音量＝上の列から移す・切る音・試す＝切る音のすぐ横・入らなければ細かい設定は
  // 「音の設定」に畳む）。3D の中の上の端に重ねる（#pvTop・2026-11-09 利用者「ノーツは上の方にあまり来ない・
  // 左右は隙間が開く」）: 左＝見え方の設定（視点・高さ・大きさ・距離・NJS・JD・反応・#pvOv・fitOv・たためる）、右＝★と結果のファイル名
  // （#pvInfo・上の列から移す）とその下に未反映の知らせ（#pend・pending.js が #pvSide に入れる）。横に並べる＝互いに重ならない
  box.innerHTML = `<div class="pvBar" id="pvBar"><span id="pvPlay"></span><span class="pvSep"></span>
    <label class="ck"><input type="checkbox" id="pvClk"> 切る音</label>
    <button id="pvTry" title="今の音を鳴らす（左・右・左・右・両手）">試す</button>
    <button id="pvMoreBtn" title="切る音の細かい設定（音の種類・何で鳴らすか・左右で変える・音量・ずれ）＝窓が狭くて 1 段に入らない時はここに畳む">音の設定 ▾</button>
    <span id="pvMore"><select id="pvSnd" title="音の種類">${Object.keys(SOUNDS).map(k => `<option>${k}</option>`).join('')}</select>
    <select id="pvWhat" title="何で鳴らすか（拍＝譜面と関係なく毎拍。音のずれが譜面か音の出方かを見分ける）"><option>ノーツ</option><option>拍</option></select>
    <label class="ck" title="左手＝低めで左から・右手＝高めで右から（両手は真ん中で強く）"><input type="checkbox" id="pvLR"> 左右で変える</label>
    <label class="ck">音量 <input type="range" id="pvVol" min="0" max="200" value="100"></label>
    <label class="ck" title="切る音の出る時刻を前後にずらす（耳で合わせる。＋で遅く）">ずれ <input type="range" id="pvOff" min="-150" max="150" step="5" value="0"><span id="pvOffV" class="sub"></span></label></span></div>
    <div id="pvWrap"><div id="pvView"></div><div id="pvTop">
    <div id="pvOv"><button id="pvOvBtn" title="3D の見え方の設定をたたむ・開く（たたんでも設定はそのまま）"><i>▾</i> <b>3D</b> の見え方<span class="sub" id="pvKind"></span><span class="pvNjsTag" id="pvNjsTag"></span></button>
    <div class="pvOvBody"><div class="pvOvGrp">
    <label class="pvOvRow"><span class="nm">視点</span><select id="pvCam">${Object.keys(CAMS).map(k => `<option>${k}</option>`).join('')}</select></label>
    <label class="pvOvRow" title="目の高さ（ゲームは 1.7m・上げると奥と手前のノーツの重なりが減る・下げると下の段が窓の下の縁から離れる・視点「標準」）"><span class="nm">高さ</span><input type="range" id="pvH" min="1.0" max="2.0" step="0.05"><span id="pvHV" class="sub"></span></label>
    <label class="pvOvRow" title="見える大きさ（ゲームの縦の視野 80° を 100% として・視野を狭める・視点「標準」）"><span class="nm">大きさ</span><input type="range" id="pvZoom" min="100" max="250" step="5"><span id="pvZoomV" class="sub"></span></label>
    <label class="pvOvRow" title="目の位置の、当たる面（音が鳴る所）からの距離（ゲームは 2m・近づけるほど、鳴る時にノーツが窓の外へ出ている・既定 1.4m＝下の段が 6 割ほど窓の外・視点「標準」）"><span class="nm">距離</span><input type="range" id="pvD" min="0.8" max="2.5" step="0.05"><span id="pvDV" class="sub"></span></label></div>
    <div class="pvOvGrp"><div class="pvOvRow"><label id="pvNjsLbl" title="ノーツの速さ（3D の見え方だけ・譜面は変わらない）"><span class="nm">NJS</span><input id="pvNjs" type="number" min="5" max="30" step="0.5" value="16"></label>
    <label title="ノーツが見え始める距離（m・3D の見え方だけ）&#10;アプリは NJS を書く時に、難易度ごとの狙いの JD（ランク譜面の中央値）になるオフセットも書く。NJS を変えると JD もその狙いに合わせる（NLM で決めたオフセットの時はゲームと同じに変わる）&#10;ここに打つと、それからは打った JD のまま">JD <input id="pvJd" type="number" min="5" max="40" step="0.5" value="15"></label></div>
    <div class="pvOvRow"><span class="nm"></span><label class="pvSw" id="pvNjsSw"><input type="checkbox" id="pvNjsUse"><i></i><span>譜面に使う</span></label></div>
    <div class="pvNjsNote" id="pvNjsNote"></div>
    <span class="sub pvOvRt" id="pvRt" title="ノーツが見え始めてから当たる面に来るまで"></span></div></div></div>
    <div id="pvSide"><div id="pvInfo" class="pvInfo"></div></div></div></div>`;
  // ★（rating.js が書く）と結果のファイル名（main.js の fileInfo が書く）は、上の列の物を DOM ごと移す（id と書く側はそのまま・
  // 上の列を 1 段に収めるため・2026-11-09 利用者）。ファイル名は長いので省略して出し、全文は title に
  for (const id of ['starInfo', 'fileInfo']) if ($(id)) $('pvInfo').append($(id));
  // 再生の操作（▶・時刻・鳴らすパート・曲の音量）も上の列から欄の頭へ移す（付いた処理＝main.js の topbar はそのまま・2026-11-09 利用者
  // 「基本的にこの 3D の画面を見て結果を確認することが多いので、この中にある程度の要素がまとまっているのが良い」）
  const musVol = $('musVol') && $('musVol').closest('label');
  for (const el of [$('play'), $('time'), $('stems'), musVol]) if (el) $('pvPlay').append(el);
  // 1 段に入らない時は切る音の細かい設定を「音の設定」の下に開く小さな窓へ畳む（fitBar・3D を低くしない）
  $('pvMoreBtn').onclick = () => $('pvMore').classList.toggle('open');
  document.addEventListener('pointerdown', e => {
    if ($('pvMore').classList.contains('open') && !e.target.closest('#pvMore, #pvMoreBtn')) $('pvMore').classList.remove('open');
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('pvMore').classList.remove('open'); });
  new ResizeObserver(() => fitBar()).observe($('pvBar'));
  const fi = $('fileInfo');
  if (fi) { const t = () => { fi.title = fi.textContent; }; t(); new MutationObserver(t).observe(fi, {childList: true, subtree: true, characterData: true}); }
  // 見え方の設定はたためる（覚える）。窓の大きさ・たたむ・中身が変わったら置き方を合わせ直す（fitOv）
  const fold = v => { $('pvOv').classList.toggle('fold', v); $('pvOvBtn').querySelector('i').textContent = v ? '▸' : '▾'; fitOv(); };
  fold(!!lsGet('automap-pvfold', false));
  $('pvOvBtn').onclick = () => { const v = !$('pvOv').classList.contains('fold'); lsSet('automap-pvfold', v); fold(v); };
  const ro = new ResizeObserver(() => fitOv());
  ['pvWrap', 'pvView', 'pvOv'].forEach(id => ro.observe($(id)));
  on('ui', () => { fitBar(); fitOv(); });   // 表示の大きさを小さくした時は欄の大きさが変わらない（畳んだままになる）ので測り直す
  try {
    const m = await import('/static/preview3d/preview3d.js');
    PV.toMap = (await import('/static/preview3d/nlmf-map.js')).nlmfToMap;
    PV.impl = await m.createPreview($('pvView'), {njs: 16});
    PV.nlm = true; PV.kind = '';
  } catch (e) {
    PV.impl = new Lite($('pvView')); PV.nlm = false;
    PV.kind = '（簡単な見え方）';
    console.warn('3D: NLM の 3D を読めなかったので簡単な見え方を使う', e);
  }
  $('pvKind').textContent = PV.kind;
  // 既定は「標準」（2026-11-03）。前の既定（少し引く）・すぐやめた「見下ろす」を覚えていたら1回だけ新しい既定に（選び直せば覚える）
  let cam = lsGet('automap-cam', CAM_DEFAULT);
  if (!lsGet('automap-cam3', false)) { if (cam === '少し引く' || !CAMS[cam]) cam = CAM_DEFAULT; lsSet('automap-cam3', true); lsSet('automap-cam', cam); }
  $('pvCam').value = CAMS[cam] ? cam : CAM_DEFAULT;
  // つまみの値（覚える名前は前の「標準」の物と分ける＝大きさの 100% が違う）
  for (const [id, key, def] of CAM_KNOBS) { $(id).value = lsGet(key, def); $(id).oninput = () => { lsSet(key, +$(id).value); setCam(); }; }
  setCam();
  $('pvCam').onchange = () => { lsSet('automap-cam', $('pvCam').value); setCam(); };
  $('pvSnd').value = lsGet('automap-snd', 'カッ'); if (!$('pvSnd').value) $('pvSnd').value = 'カッ';
  $('pvSnd').onchange = () => { lsSet('automap-snd', $('pvSnd').value); tryBeep(); };
  $('pvVol').value = Math.round(lsGet('automap-sndvol', 1) * 100);
  $('pvVol').oninput = () => { lsSet('automap-sndvol', +$('pvVol').value / 100); if (CLICK.master) CLICK.master.gain.value = +$('pvVol').value / 100; };
  $('pvTry').onclick = tryBeep;
  $('pvWhat').value = lsGet('automap-sndwhat', 'ノーツ'); $('pvWhat').onchange = () => { lsSet('automap-sndwhat', $('pvWhat').value); buildList(); };
  $('pvLR').checked = lsGet('automap-sndlr', false); $('pvLR').onchange = () => lsSet('automap-sndlr', $('pvLR').checked);
  $('pvOff').value = lsGet('automap-sndoff', 0);
  const offV = () => { $('pvOffV').textContent = (+$('pvOff').value > 0 ? '+' : '') + $('pvOff').value + 'ms'; }; offV();
  $('pvOff').oninput = () => { lsSet('automap-sndoff', +$('pvOff').value); offV(); CLICK.est = null; };
  $('pvNjs').oninput = e => { const v = +e.target.value; if (v > 0) { PV.impl.setNJS(v); jdFollow(v); showJump(); njTyped(v); } };
  njInit();
  $('pvJd').oninput = e => { const v = +e.target.value; if (v > 0) { JD.typed = true; PV.impl.setJD(v); showJump(true); } };
  // 切る音の入り切りも覚える（2026-11-08 利用者「起動するたびにチェックが外れていて毎回入れている」）。起動の時は音の部品を作らず、
  // 再生が始まった時に作る（clickTick・操作の前に作ると、ブラウザの決まりで音が出ないことがある）
  $('pvClk').checked = CLICK.on = !!lsGet('automap-sndon', false);
  $('pvClk').onchange = e => { CLICK.on = e.target.checked; lsSet('automap-sndon', CLICK.on); if (CLICK.on) { audio(); buildList(); } };   // 入れた時も今の曲の表を作り直す
  new ResizeObserver(() => PV.impl && PV.impl.resize()).observe($('pvView'));
  on('chart', proj => setMap(proj)); on('chart', () => buildList());   // emit('chart', .nlmf の中身) で別の案を 3D に（無ければ結果のファイル）
  const loop = () => { if (PV.impl && S.D) { PV.impl.setTime(beatOf(S.t), P.playing); clickTick(); } PV.raf = requestAnimationFrame(loop); };
  loop();
}
// 見え方の設定（3D の中の左上・#pvOv）の置き方: 窓が低くて縦 1 列に入らない時は 2 列に（wide・それでも入らなければ中を送る）。
// 16:9 の 3D の外（左右の黒い余白）に収まらずに 3D に重なる時は薄く（over・マウスを乗せると濃く＝ノーツを隠しすぎない）
function fitOv() {
  const ov = $('pvOv'), body = ov && ov.querySelector('.pvOvBody'), view = $('pvView');
  if (!body || !$('pvWrap').clientHeight) return;
  ov.classList.remove('wide');
  if (!ov.classList.contains('fold') && body.scrollHeight > body.clientHeight + 1) ov.classList.add('wide');
  const r = ov.getBoundingClientRect(), v = view.getBoundingClientRect();
  ov.classList.toggle('over', r.right > v.left + 2 && r.left < v.right);
}
// 再生と音の欄（#pvBar）: 1 段に入らない（切る音の細かい設定が次の行へ折り返す）時は、細かい設定を「音の設定」のボタンの下に開く窓へ畳む（tight）
function fitBar() {
  const bar = $('pvBar'), more = $('pvMore');
  if (!bar || !bar.clientWidth) return;
  bar.classList.remove('tight');
  if (more.getBoundingClientRect().top >= $('pvPlay').getBoundingClientRect().bottom - 1) bar.classList.add('tight');
  else more.classList.remove('open');
}
// 視点: ゲームと同じ（当たる面の 2m 手前・高さ 1.7m・縦の視野 80°・真っすぐ前を見る）。ノーツの段の中心は高さ 0.85・1.40・1.95m（大きさ 0.46m）。
// 「標準」（既定・2026-11-03 利用者「上からの見下ろしを止めて、ゲームの視点と同じに・視点の位置を少し下げて下側がよく見えるように・
// 画角を調整してノーツを大きく」）: ゲームと同じ位置（当たる面の 2m 手前）から真っすぐ前を見て（下を向けない＝レーンの線が集まる所は
// 窓の高さの真ん中）、目の「高さ」m（既定 1.6＝ゲームより 0.1m 低い）、縦の視野を「大きさ」%（ゲームの 80° を 100%・既定 170＝52.5°）で
// 狭める。既定の値で、当たる面のノーツは窓の高さの 23%（ゲームの 1.7 倍）・下の段の下の縁がほぼ窓の下の縁・上の段の上の縁が窓の下から 79%
// （camTest の数え方）。最初は高さ 1.4m（真ん中の段の高さ・下の段の下の縁が窓の下から 10%）にしたが、真ん中の段の奥と手前のノーツが
// 窓の同じ高さに並んで重なり、見にくかった（利用者「低すぎて重なりが見にくい」・同じ日）。目を段より上げるほど奥のノーツが上にずれて
// 重なりが減る（ずれは段と目の高さの差に比例）。1.6m は当たる面の直前の下の段が窓の下から約 3% で、まだ切れない。
// 距離のつまみも試したが、3D の上の列が2行に折り返して窓が低くなったのでやめた（距離はゲームと同じ 2m）。
// 2026-11-08 利用者「切る音が鳴るのが早く見える。鳴る時にノーツが窓の端に触る直前＝もう少し奥（前）へ、鳴る時に半分以上窓から出ている位置に」
// → 「距離」（当たる面からの目の距離・既定 1.4m）を足した（その時は 1 行目が折り返すので 2 行目の切る音の並びに置いた）。2m では鳴る瞬間に下の段の下の縁が窓の
// 下の縁、1.4m で下の段の 63% が窓の外（1.6m 41%・1.5m 52%・1.3m 74%・camTest の out）。真ん中・上の段は目の高さに近いので鳴る時も窓の中。
// 2026-11-09 利用者「距離は視点の設定なので上の段に・試すは切る音の横に・上の段は 3D の中に重ねてよい（ノーツは上の方にあまり来ない・
// 左右は隙間が開く）」→ 見え方の設定（視点・高さ・大きさ・距離・NJS・JD・反応）は 3D の中の左上に重ね（#pvOv・fitOv）、上の欄は切る音の
// 1 段だけ（2 段だった分だけ 3D が高くなった）。
// 前の「標準」（同じ日の午前・高さ 2.1m・当たる面の 3.8m 後ろから約 10° 下を向けて、レーンの線が集まる所を窓の下から 7 割に）は、上から
// 見下ろす見え方で、当たる面のノーツも小さかった（窓の高さの約 13%）＝やめた。その前の「見下ろす」（高さ 3.4m）も見下ろしすぎて捨てた。
const CAM_DEFAULT = '標準';
const CAM_KNOBS = [['pvH', 'automap-pvh2', 1.6], ['pvZoom', 'automap-pvzoom2', 170], ['pvD', 'automap-pvd', 1.4]];   // [つまみ, 覚える名前, 既定]（高さは 1.4m の時の物と分ける）
const CAMS = {'標準': {baseFov: 80, adjust: true},
  'ゲームと同じ': {fov: 80, y: 1.7, back: 2}, '少し引く': {fov: 64, y: 2.1, back: 3.8, lookY: 1.0, lookZ: -10},
  '引く': {fov: 56, y: 2.7, back: 6.0, lookY: 0.9, lookZ: -8}};   // 引く時は少し下（当たる面）を向く
function setCam() {
  const c = CAMS[$('pvCam').value];
  const [h, zoom, d] = CAM_KNOBS.map(([id, , def]) => +$(id).value || def);
  $('pvHV').textContent = h.toFixed(2) + 'm'; $('pvZoomV').textContent = zoom + '%'; $('pvDV').textContent = d.toFixed(2) + 'm';
  CAM_KNOBS.forEach(([id]) => { $(id).disabled = !(c && c.adjust); });
  if (!PV.impl || !PV.impl.setCameraView || !c) return;
  if (!c.adjust) { PV.impl.setCameraView(c); return; }
  const half = Math.atan(Math.tan(c.baseFov / 2 * Math.PI / 180) / (zoom / 100));   // 縦の視野の半分（大きさで狭める）
  PV.impl.setCameraView({fov: half * 2 * 180 / Math.PI, y: h, back: d, lookY: h, lookZ: -100});   // 真っすぐ前（ゲームと同じ向き）
}
// 確かめ用（main.js の #pvcam=秒&h=1.5&z=150&d=1.4&cam=標準）: つまみを変えて視点を作り直す（覚えない）。当たる面（音が鳴る時）のノーツが
// 窓のどこに来るかも返す（下の段の下の縁・上の段の上の縁を窓の下から何%か・ノーツ 1 つの高さが窓の何%か・窓の外は 0 未満・100 超・
// out＝鳴る時に下の段のノーツの何割が窓の下の外か）
export function camTest(o = {}) {
  if (o.cam && CAMS[o.cam]) $('pvCam').value = o.cam;
  [['pvH', o.h], ['pvZoom', o.z], ['pvD', o.d]].forEach(([id, v]) => { if (v != null && v !== '') $(id).value = v; });
  setCam();
  const c = CAMS[$('pvCam').value];
  if (!c.adjust) return {cam: $('pvCam').value};
  const [h, zoom, d] = CAM_KNOBS.map(([id, , def]) => +$(id).value || def);
  const t = Math.tan(c.baseFov / 2 * Math.PI / 180) / (zoom / 100), pct = y => Math.round((50 + 50 * (y - h) / d / t) * 10) / 10;
  const lo = h - d * t;   // 当たる面での窓の下の縁の高さ（m）
  return {cam: $('pvCam').value, h, zoom, d, fov: Math.round(2 * Math.atan(t) * 1800 / Math.PI) / 10,
    bottom: pct(0.85 - 0.23), top: pct(1.95 + 0.23), note: Math.round(0.46 / d / (2 * t) * 1000) / 10,
    out: Math.round(Math.min(1, Math.max(0, (lo - 0.62) / 0.46)) * 100)};
}
function showJump(keepJd) {
  if (!PV.impl.jump) return;
  const j = PV.impl.jump();
  if (!keepJd) $('pvJd').value = +j.jd.toFixed(1);
  $('pvRt').textContent = `反応 ${Math.round(j.rt * 1000)}ms`;
}
// ---- 見え始める距離（JD）（2026-11-10 利用者「ストロボで NJS 15.1 はゆっくりなのに 15.2 にした瞬間すごく速くなる」・automap/njs.py の fix_jd）----
// Beat Saber は見え始める所を 4 拍前から数え、18m を超える間は半分にする＝BPM の低い曲では NJS の小さな違いで JD が倍・半分に跳ぶ。アプリは
// NJS を書く時にその NJS で狙いの JD（難易度ごと・ランク譜面の中央値）になるオフセットも書く。3D で NJS を変えた時も、見ている難易度の
// オフセットがアプリの物なら狙いの JD に保つ（＝その NJS で作り直した時と同じ見え方）。NLM で決めたオフセットなら今のまま（ゲームと同じに跳ぶ）。
// JD の欄に打ったら、それからは打った JD を保つ（前からの動き・ページを読み直すまで）
const JD = {typed: false, auto: false, diff: 'ExpertPlus', fixed: ''};
const DIFF_OF = {easy: 'Easy', normal: 'Normal', hard: 'Hard', expert: 'Expert', expertplus: 'ExpertPlus'};
function jdAutoOf(e) {   // njsCfg の項目 → オフセットをアプリが決める（njs.fix_all と同じ: アプリが NJS を書いた・オフセットが NLM で決めた値でない）
  if (!e || e.njs == null || e.auto == null) return false;
  const o = +(e.offset || 0);
  return e.auto_offset != null ? o === +e.auto_offset : o === 0;
}
function jdTarget(name, njs) {   // njs.target_jd と同じ（難易度ごとの狙いを NLM の警告が出ない範囲に）
  const info = NJ.st && NJ.st.jd; if (!info || !(name in info.target)) return null;
  const lo = Math.max(info.min + info.margin, 2 * njs * (info.rt_min + info.margin / 10));
  const hi = 18 * (1 / 1.07) ** njs + 18 - info.margin;
  return Math.max(lo, Math.min(info.target[name], hi));
}
function jdFollow(njs) {   // 3D の NJS を変えた: アプリが決めるオフセットなら狙いの JD に
  if (JD.typed || !JD.auto || !PV.impl.setJD) return;
  const t = jdTarget(JD.diff, njs);
  if (t) PV.impl.setJD(t);
}
async function jdFix(file) {   // 曲を開いた: アプリが NJS を書いた難易度のオフセットを狙いの JD に（前の版の譜面はオフセット 0 のまま）
  if (S.readonly || !file) return;
  try {
    const r = await api('POST', '/api/njs/jd', {file});
    JD.fixed = r.line || '書くことは無かった';
    if (file !== S.file || !r.wrote) return;
    emit('status', r.line);
    emit('chart');   // 3D・★を読み直す
  } catch (e) { JD.fixed = '失敗: ' + e.message; console.warn('JD を整えられなかった', e); }
}
// 確かめ用（見えない Edge・写しの場所のサーバーで）: #jdtest=15.1,15.2&song=曲名 → 曲を開いて JD を整えた後、NJS の欄を順に変えた時の
// JD・反応を document.title と #jdtestOut に（結果のファイルは開いた時の整えだけ書く）
function jdTest() {
  const h = decodeURIComponent(location.hash), sm = h.match(/&song=([^&]+)/);
  if (sm && S.song !== sm[1]) {
    if (S.songs && S.songs.some(q => q.song === sm[1]) && $('song')) { $('song').value = sm[1]; $('song').dispatchEvent(new Event('change')); }
    return setTimeout(jdTest, 500);
  }
  if (!S.D || !PV.impl || !NJ.st || !JD.fixed) return setTimeout(jdTest, 300);
  setTimeout(() => {
    const out = [`${S.song}・${diffText(S.view || S.D.base)}・整え: ${JD.fixed}・開いた時 NJS ${$('pvNjs').value} JD ${$('pvJd').value} ${$('pvRt').textContent}・アプリの物 ${JD.auto}`];
    for (const v of (h.split('=')[1] || '').split('&')[0].split(',').filter(Boolean)) {
      $('pvNjs').value = v; $('pvNjs').dispatchEvent(new Event('input'));
      out.push(`NJS ${v} → JD ${$('pvJd').value} ${$('pvRt').textContent}`);
    }
    document.title = 'jdtest ' + out.join(' ／ ');
    const el = document.createElement('pre'); el.id = 'jdtestOut'; el.textContent = out.join('\n'); document.body.appendChild(el);
  }, 2500);   // 整えて読み直した 3D を待つ
}
// given＝見せる .nlmf の中身（別の案・履歴の版を見比べる時。無ければ結果のファイル）。難易度は帯と同じ物（S.D.key＝サーバーの chart() の
// key＝見ている難易度・版や案は基準の難易度）
export async function setMap(given) {
  if (!S.D) return;
  // 切る音の表も今の曲で作り直す（曲を開いた時は openSong がここだけを呼び、emit('chart') は出ない＝前は表が前に開いた曲のまま残り、
  // 曲の取り込み・曲の切り替えの後に切る音が合わなかった・2026-11-03 利用者）
  buildList();
  PV.given = !!given;   // 別の案・履歴の版を見ている（基準の NJS の切り替えは止める）
  if (!PV.impl) return;
  if (PV.nlm) {
    try {
      const proj = given || await api('GET', '/api/nlmf?file=' + encodeURIComponent(S.file));
      const key = S.D.key || 'expertplusstandard.dat';
      const m = PV.toMap(proj, {diff: key});
      PV.impl.setMap(m);
      // ファイルのオフセットで見せる（前に NJS を変えて狙いの JD にしていたのを外す・JD の欄に打った時はその JD のまま）
      if (!JD.typed && PV.impl.setNjsOffset) PV.impl.setNjsOffset(m.njsOffset || 0);
      JD.diff = DIFF_OF[key.replace(/standard\.dat$/i, '').toLowerCase()] || 'ExpertPlus';
      JD.auto = jdAutoOf((proj.njsCfg || {})[key]);
      $('pvNjs').value = m.njs;
      showJump();
      njRender();
      return;
    } catch (e) { console.warn('3D: .nlmf を読めなかった', e); }
  }
  PV.impl.setMap({bpm: S.D.bpm, notes: S.D.notes.map(([, x, y, c, d, b]) => ({b, x, y, c, d}))});
  njRender();
}

// ---- 3D で決めた NJS を曲の基準の NJS に（2026-11-09 利用者・app/njsbase.py・docs/アプリ仕様.md 20 節） ----
// 利用者「Brotherhood の Normal を NJS 13（式の値）で開いたら遅すぎて見にくい。3D で 17 にしたらちょうどよかった」「3D の画面で指定した場合に、
// それが基準になって新しく設定されていることが分かるように」。NJS の欄の下の「譜面に使う」（切り替え）を ON にすると、今の欄の値がこの曲の
// 基準の NJS（作業ファイルの njs＝{base}）になり、すぐ結果のファイルの基準の難易度に書く（作り直しを待たない・作り直しても動かさない・
// これから作る派生は 決めた値＋式の差・作ってある派生はそのまま）。ON の間は欄を緑（--accent）で囲み「基準の NJS（3D で決めた）」と出す
// （たたんだ時は見出しに札）。ON の間に欄を変えると 0.7 秒待って決めた値も変える。OFF で式の値に戻す。
// 作業ファイルを変えるのは commit（元に戻せる・派生を見ている間は止まる）。作業ファイルの njs が変わったら（切り替え・欄・元に戻す・やり直す）
// 保存してから POST /api/njs で結果のファイルに合わせる（1 つずつ・最後の値が勝つ）。書いたら emit('chart')＝3D と★を読み直す（★の控えは
// NJS も指紋に入る＝測り直し）。派生を見ている間・別の案や履歴の版を見ている間・作り直しの間は押せない。最後に決めた方が勝つ（2026-11-09
// 利用者）: 基準が NLM で直されている（njs が auto と違う）時は ON でも OFF でも橙で「NLM で 18 に直した値を基準に使っている（派生もこの値
// から）」。作業ファイルの njs.base は 3D で決めた値のまま（NLM の値に書き換えない）。3D で決め直す（欄を変える・ON にし直す）と 3D の値で
// 上書き。確かめは #njtest（=on・=lock）→ document.title と #njtestOut
const NJ = {file: null, synced: 'null', st: null, gen: false, busy: false, typeT: null, fetchT: null, tries: 0};
const njKey = v => JSON.stringify(v && typeof v.base === 'number' ? {base: v.base} : null);
const njOn = () => !!(S.W && S.W.njs && typeof S.W.njs.base === 'number');
const njNum = v => Math.round(v * 100) / 100;
const njSign = v => (v > 0 ? '＋' : v < 0 ? '−' : '±') + Math.abs(njNum(v));
function njBlocked() {   // 押せない訳（無ければ ''）
  if (!S.file || !S.D) return '曲を開いていない';
  if (locked()) return `${diffText(S.view)}（派生）を見ている間は変えられない（基準の NJS の切り替えは基準の ${diffText(S.D.base)} に戻ってから）`;
  if (PV.given) return '別の案・履歴の版を見ている間は変えられない（結果のファイルに戻ってから）';
  if (NJ.gen) return '作り直し・展開の間は変えられない';
  if (S.readonly) return '確かめ用の画面（作業ファイルに書かない）';
  if (NJ.st && NJ.st.exists && !NJ.st.has_base) return `結果のファイルに基準の ${diffText(NJ.st.base)} が無い`;
  return '';
}
function njRender() {
  const sw = $('pvNjsUse'); if (!sw) return;
  const on_ = njOn(), st = NJ.st, why = njBlocked(), base = (st && st.base) || (S.D && S.D.base) || '';
  const dec = on_ ? S.W.njs.base : null, view = !!S.view, here = !view && !PV.given;
  const f = st && st.formula && st.formula.value != null ? st.formula : null, user = st && st.user != null ? st.user : null;
  // 最後に決めた方が勝つ（2026-11-09 利用者「NLM でさらに調整がかかっている場合は、それを採用してほしい」）: 基準が NLM で直されて
  // いれば（ON でも OFF でも）その値が基準の NJS で、これから作る派生もその値から（橙）。3D で決め直すと 3D の値で上書き
  const nlm = here && user != null, showBase = on_ && here && user == null;
  sw.checked = on_; sw.disabled = !!why;
  $('pvNjsSw').classList.toggle('on', on_); $('pvNjsSw').classList.toggle('dis', !!why);
  $('pvNjs').classList.toggle('njsBase', showBase);
  $('pvNjs').classList.toggle('njsUser', nlm);
  let txt = '', cls = '';
  if (view) { txt = `${diffText(S.view)}（派生）の NJS` + (on_ ? `・基準は 3D で決めた ${dec}` : ''); cls = 'mute'; }
  else if (PV.given) { txt = on_ ? `基準の NJS は 3D で決めた ${dec}` : ''; cls = 'mute'; }
  else if (nlm) { txt = `NLM で ${user} に直した値を基準に使っている（派生もこの値から）`; cls = 'warn'; }
  else if (on_) { txt = `✓ 基準（${diffText(base)}）の NJS（3D で決めた）`; cls = 'on'; }
  $('pvNjsNote').textContent = txt; $('pvNjsNote').className = 'pvNjsNote ' + cls;
  const fx = f && on_ ? `式なら ${f.value} → 決めた値 ${dec}（${njSign(dec - f.value)}）` : '';
  const ftxt = f ? `式なら ${f.value}（${f.how}）` : st && st.formula && st.formula.state === 'running' ? '式の値は★を測っている' : '';
  const nlmTxt = nlm ? `\n基準（${diffText(base)}）は NLM で ${user} に直した値を使っている（これから作る派生もこの値＋式の差・作り直しでも触らない` +
    (on_ ? `・3D で決めた ${dec} より後に直した＝NLM の値が勝つ` : '') + '）。ここで値を変える・ON にし直すと 3D の値で上書きする' : '';
  $('pvNjsSw').title = (why ? why + '\n' : '') + (on_
    ? `ON: この曲の基準（${diffText(base)}）の NJS＝3D で決めた ${dec}` + (fx ? `（${fx}）` : '') +
      '。結果のファイルに書いてある・作り直しても動かさない。これから作る派生（難易度を展開）は 決めた値＋（派生の式 − 基準の式）。作ってある派生はそのまま' +
      nlmTxt + (ftxt && !fx ? `\n${ftxt}` : '') + '\nOFF にすると式の値に戻す（NLM で直した値は触らない）'
    : `ON にすると、今の NJS（${$('pvNjs').value}）をこの曲の基準（${diffText(base)}）の NJS にする（結果のファイルにすぐ書く・作り直しても動かさない・` +
      'ON の間に欄を変えると付いてくる）。これから作る派生も、この値から式の上下の間隔でずらす（作ってある派生はそのまま）' + nlmTxt + (ftxt ? `\n今は ${ftxt}` : ''));
  $('pvNjsLbl').title = nlm ? `基準（${diffText(base)}）の NJS＝NLM で直した ${user}（譜面に使う値・これから作る派生もこの値から）` +
      (on_ ? `\n3D で決めた ${dec} より後に NLM で直した＝NLM の値が勝つ\n変えると 0.7 秒待って 3D の値で上書きする` : '\n「譜面に使う」を ON にすると、この欄の値で上書きする')
    : showBase ? `基準（${diffText(base)}）の NJS＝3D で決めた ${dec}（譜面に使う値）` + (fx ? `\n${fx}` : '') + '\n変えると 0.7 秒待って決めた値も変える'
    : 'ノーツの速さ（3D の見え方だけ・譜面は変わらない）' + (view ? '' : '\n「譜面に使う」を ON にすると、この値が基準の NJS になる');
  $('pvNjsTag').textContent = nlm ? `NJS ${user}（NLM）` : showBase ? `NJS ${dec}（基準）` : '';
  $('pvNjsTag').classList.toggle('warn', nlm);
  $('pvOv').classList.toggle('njsOn', showBase || nlm);
  fitOv();
}
async function njFetch(wait = 8) {   // 今の様子（決めた値・結果のファイルの値・NLM で直したか・式の値）
  const file = S.file; if (!file) return null;
  clearTimeout(NJ.fetchT);
  try {
    const r = await api('GET', `/api/njs?file=${encodeURIComponent(file)}&wait=${wait}`);
    if (file !== S.file) return null;
    NJ.st = r; njRender();
    if (r.formula && r.formula.state === 'running' && NJ.tries++ < 20) NJ.fetchT = setTimeout(() => njFetch(8), 500);
    return r;
  } catch (e) { if (file === S.file) { NJ.st = null; njRender(); } return null; }
}
async function njApply(mode = 'set') {   // 作業ファイルの njs を結果のファイルへ（保存してから・1 つずつ）
  const file = S.file; if (!file || S.readonly) return;
  if (NJ.busy) return;   // 終わった所で今の値と比べ直す（finally）
  NJ.busy = true;
  const want = njKey(S.W.njs), base = JSON.parse(want);
  const si = $('starInfo');
  try {
    await saveWork();   // 作業ファイルを先に（PUT /api/work は丸ごと置き換え＝自動の保存と取り合わない）
    if (file !== S.file) return;
    if (si) si.classList.add('stale');
    const r = await api('POST', '/api/njs', {file, mode, base: base ? base.base : null});
    if (file !== S.file) return;
    NJ.synced = want; NJ.st = r; NJ.tries = 0;
    if (mode === 'set' || r.wrote) emit('status', r.line);
    if (r.wrote) emit('chart');   // 3D・★を読み直す（★は NJS も指紋に入る＝測り直す）
    else if (si) si.classList.remove('stale');
  } catch (e) {
    emit('status', '基準の NJS を変えられなかった: ' + e.message, true);
    if (si) si.classList.remove('stale');
    if (file === S.file) { S.W.njs = JSON.parse(NJ.synced); saveWork(); emit('work'); }   // 作業ファイルを前の値に戻す（元に戻すの列は増やさない）
  } finally {
    NJ.busy = false; njRender();
    if (file === S.file && S.W && njKey(S.W.njs) !== NJ.synced) njApply('set');
  }
}
function njTyped() {   // ON の間に欄を変えた → 少し待ってまとめて決めた値も変える
  if (!njOn() || njBlocked()) return;
  clearTimeout(NJ.typeT);
  NJ.typeT = setTimeout(() => {
    const x = njNum(+$('pvNjs').value);
    if (!(x >= 5 && x <= 30) || !njOn() || njBlocked()) return;
    if (x === S.W.njs.base) {   // 決めた値と同じ: NLM で直された後なら、3D で決め直した（明示した操作が後＝3D の値で上書き）
      if (NJ.st && NJ.st.user != null && NJ.st.user !== x) njApply('set');
      return;
    }
    commit(W => { W.njs = {base: x}; });
  }, 700);
}
function njInit() {
  $('pvNjsUse').onchange = e => {
    const why = njBlocked();
    if (why) { e.target.checked = njOn(); emit('status', why, true); if (locked()) emit('locked'); return; }
    clearTimeout(NJ.typeT);
    if (e.target.checked) {
      const v = njNum(+$('pvNjs').value);
      if (!(v >= 5 && v <= 30)) { e.target.checked = false; emit('status', 'NJS は 5〜30 の数で', true); return; }
      commit(W => { W.njs = {base: v}; });
    } else commit(W => { W.njs = null; });
    njRender();
  };
  on('work', () => {
    if (S.file !== NJ.file) {   // 曲を開いた: 作業ファイルの値をそのまま（書かない）。結果のファイルがアプリの書いた違う値なら合わせる（sync）
      NJ.file = S.file; NJ.synced = njKey(S.W && S.W.njs); NJ.st = null; NJ.tries = 0; njRender();
      const file = S.file;
      if (file) njFetch(8).then(async r => {
        if (r && file === S.file && njOn() && r.exists && r.has_base && r.user == null && r.njs !== S.W.njs.base) await njApply('sync');
        if (r && file === S.file && r.exists && !r.busy) jdFix(file);   // sync の後（同じ結果のファイルを続けて書く＝取り合わない）
      });
      return;
    }
    if (S.W && njKey(S.W.njs) !== NJ.synced) njApply('set'); else njRender();
  });
  on('chart', () => { clearTimeout(NJ.fetchT); NJ.tries = 0; NJ.fetchT = setTimeout(() => njFetch(8), 150); });   // 作り直した・展開した・見る難易度を変えた
  on('generating', v => { NJ.gen = !!v; njRender(); });
  if (location.hash.startsWith('#jdtest')) setTimeout(jdTest, 1500);
  if (location.hash.startsWith('#njtest')) {
    const arg = decodeURIComponent(location.hash.split('=')[1] || '');
    const go = () => { if (S.D && S.file && NJ.st && PV.impl) njTest(arg); else setTimeout(go, 300); };
    setTimeout(go, 1500);
  }
}
// 確かめ用（見えない Edge・写しの場所のサーバーで）: #njtest＝欄を 17 に → ON（結果のファイルと作業ファイル・★の NJS）→ 欄を 17.5 に（付いてくる）→
// 元に戻す・やり直す → 派生を見ている時は押せない → OFF（式に戻る）・派生の NJS は変わらない。=on は ON で止める・=lock は派生を見た所で止める
async function njTest(arg) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const until = async (fn, ms = 20000) => { const t0 = Date.now(); while (!fn()) { if (Date.now() - t0 > ms) return false; await sleep(100); } return true; };
  const idle = async () => { await sleep(200); return until(() => !NJ.busy && S.W && njKey(S.W.njs) === NJ.synced); };
  const q = '?file=' + encodeURIComponent(S.file);
  const get = () => api('GET', `/api/njs${q}&wait=10`), work = () => api('GET', '/api/work' + q);
  const der = async () => (await api('GET', '/api/expand' + q)).diffs.filter(r => r.exists && !r.base).map(r => `${r.diff}:${r.njs}`).join(',');
  const star = async v => { const re = new RegExp(`NJS ${v}(?![\\d.])`); await until(() => re.test($('starInfo').title || ''), 15000);
    return ($('starInfo').title || '').match(/NJS [\d.]+/)?.[0]; };
  const field = v => { $('pvNjs').value = v; $('pvNjs').dispatchEvent(new Event('input')); };
  const flip = on_ => { $('pvNjsUse').checked = on_; $('pvNjsUse').dispatchEvent(new Event('change')); };
  const out = [];
  const done = () => {
    document.title = 'njtest ' + out.join(' ／ ');
    let pre = $('njtestOut'); if (!pre) { pre = document.createElement('pre'); pre.id = 'njtestOut'; pre.style.display = 'none'; document.body.appendChild(pre); }
    pre.textContent = out.join('\n');
  };
  try {
    const s0 = await get(), d0 = await der();
    out.push(`はじめ: 基準=${s0.base} 結果のファイル=${s0.njs}（auto ${s0.auto}） 決めた=${s0.decided} 式=${s0.formula && s0.formula.value} 派生=${d0} 切り替え=${$('pvNjsUse').checked}`);
    field(17); flip(true); await idle();
    let s = await get(), w = await work();
    out.push(`ON: 結果のファイル=${s.njs}（auto ${s.auto}） 決めた=${s.decided} 作業ファイル=${JSON.stringify(w.njs)} 欄=${$('pvNjs').value}` +
      ` 緑=${$('pvNjs').classList.contains('njsBase')} 字=${$('pvNjsNote').textContent} 札=${$('pvNjsTag').textContent} ★の${await star(17)} 説明=${$('pvNjsSw').title.split('\n')[0]}`);
    if (arg === 'on') return done();
    field(17.5); await sleep(1200); await idle();
    s = await get(); w = await work();
    out.push(`欄を 17.5 に: 結果のファイル=${s.njs} 決めた=${s.decided} 作業ファイル=${JSON.stringify(w.njs)}`);
    undo(); await idle(); s = await get();
    const u = `元に戻す→${s.njs}`;
    redo(); await idle(); s = await get();
    out.push(`${u}・やり直す→${s.njs}`);
    const dv = ((S.D && S.D.diffs) || []).find(r => r.diff !== S.D.base && r.notes > 0);
    if (dv) {
      const before = njKey(S.W.njs);
      $('viewDiff').value = dv.diff; $('viewDiff').dispatchEvent(new Event('change'));
      await until(() => S.view === dv.diff); await sleep(1500);
      $('pvNjsUse').click();
      out.push(`派生 ${dv.diff} を見ている: 押せない=${$('pvNjsUse').disabled} 切り替え=${$('pvNjsUse').checked} 欄=${$('pvNjs').value} 字=${$('pvNjsNote').textContent} 変わらない=${njKey(S.W.njs) === before}`);
      if (arg === 'lock') return done();
      $('viewDiff').value = S.D.base; $('viewDiff').dispatchEvent(new Event('change'));
      await until(() => !S.view); await sleep(1500);
    }
    flip(false); await idle();
    s = await get(); w = await work();
    out.push(`OFF: 結果のファイル=${s.njs}（auto ${s.auto}） 決めた=${s.decided} 作業ファイル=${JSON.stringify(w.njs ?? null)} 式=${s.formula && s.formula.value} 欄=${$('pvNjs').value} 緑=${$('pvNjs').classList.contains('njsBase')}`);
    const d1 = await der();
    out.push(`派生の NJS: はじめ ${d0} → 終わり ${d1}（${d0 === d1 ? '同じ' : '違う'}）`);
  } catch (e) { out.push('失敗: ' + e.message); }
  done();
}

// ---- 簡単な見え方（canvas だけ・NLM の 3D が読めない時の代わり） ----
const PV_DIR = {0: 180, 1: 0, 2: 90, 3: -90, 4: 135, 5: -135, 6: 45, 7: -45};
class Lite {
  constructor(el) { this.cv = document.createElement('canvas'); el.appendChild(this.cv); this.notes = []; this.bpm = 120; this.njs = 16; this.jd = 15; this.b = 0; }
  setMap(m) { this.bpm = m.bpm; this.notes = (m.notes || []).map(n => ({b: n.b ?? n.beat, x: n.x, y: n.y, c: n.c, d: n.d})).sort((a, b) => a.b - b.b); }
  setNJS(n) { this.njs = n; } setJD(d) { this.jd = d; } resize() {}
  setTime(b) { if (b === this.b && this.drawn) return; this.b = b; this.drawn = true; this.draw(); }
  draw() {
    const cv = this.cv, dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W || !H) return;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const camH = 1.2, camZ = 2.2, f = H * 0.85, cx = W / 2, cy = H * 0.48, P_ = (x, y, z) => { const d = z + camZ; return [cx + x * f / d, cy - (y - camH) * f / d, f / d]; };
    const spawn = this.jd / 2, spb = 60 / this.bpm, now = this.b * spb;
    g.fillStyle = '#0c0c10'; g.fillRect(0, 0, W, H);
    g.strokeStyle = 'rgba(255,255,255,0.10)';
    for (let c = 0; c <= 4; c++) { const x = (c - 2) * 0.6, [a, b] = P_(x, 0, 0), [e, h] = P_(x, 0, spawn); g.beginPath(); g.moveTo(a, b); g.lineTo(e, h); g.stroke(); }
    const rt = spawn / this.njs, vis = this.notes.filter(n => n.b * spb >= now - 0.12 && n.b * spb <= now + rt).sort((a, b) => b.b - a.b);
    for (const n of vis) {
      const z = (n.b * spb - now) * this.njs, [sx, sy, s] = P_((n.x - 1.5) * 0.6, 0.55 + n.y * 0.55, Math.max(z, -0.9)), w = 0.45 * s;
      g.globalAlpha = z < 0 ? Math.max(0, 1 + z / 1.5) : 1;
      g.save(); g.translate(sx, sy); if (n.d >= 0 && n.d < 8) g.rotate(PV_DIR[n.d] * Math.PI / 180);
      g.fillStyle = n.c === 0 ? '#ff274d' : '#3092ff'; g.beginPath(); g.roundRect(-w / 2, -w / 2, w, w, w * 0.12); g.fill();
      g.fillStyle = '#fff';
      if (n.d >= 0 && n.d < 8) { g.beginPath(); g.moveTo(-w * 0.33, -w * 0.33); g.lineTo(w * 0.33, -w * 0.33); g.lineTo(0, -w * 0.10); g.closePath(); g.fill(); }
      else { g.beginPath(); g.arc(0, 0, w * 0.14, 0, 7); g.fill(); }
      g.restore();
    }
    g.globalAlpha = 1; g.fillStyle = 'rgba(255,255,255,0.6)'; g.font = '11px sans-serif'; g.fillText(`${fmt(now - S.D.lead)}・拍 ${this.b.toFixed(1)}`, 8, H - 8);
  }
}

// ---- 切るタイミングの音（ノーツが当たる面に来た時の短い音・両手は強めの音1つ） ----
// 前の「ピッ」（細い正弦波）は曲に埋もれて聞こえなかった（利用者）。雑音を混ぜた打楽器の音にし、まとめて圧縮して大きくする。
// どれもブラウザの中で作る音（ゲームの音は使わない）。音量は 0〜200%（圧縮で割れないようにする）。
const CLICK = {on: false, ctx: null, until: 0, master: null, noise: null};
function audio() {
  if (!CLICK.ctx) {
    const ctx = CLICK.ctx = new AudioContext();
    const comp = ctx.createDynamicsCompressor(); comp.threshold.value = -14; comp.ratio.value = 8; comp.attack.value = 0.001; comp.release.value = 0.08;
    CLICK.master = ctx.createGain(); CLICK.master.gain.value = lsGet('automap-sndvol', 1);
    CLICK.master.connect(comp).connect(ctx.destination);
    CLICK.bus = ctx.createGain(); CLICK.bus.connect(CLICK.master);   // 予約した音の出口（clickCancel で付け替える）
    const n = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate), d = n.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    CLICK.noise = n;
  }
  CLICK.ctx.resume();
  return CLICK.ctx;
}
// 予約した音を取り消す（止めた・位置を変えた・時計の差を作り直した時）: 予約は 1.5 秒先まで入るので、出口ごと付け替える
function clickCancel() {
  if (!CLICK.ctx || !CLICK.bus) return;
  try { CLICK.bus.disconnect(); } catch (e) {}
  CLICK.bus = CLICK.ctx.createGain(); CLICK.bus.connect(CLICK.master);
}
function env(ctx, at, peak, dec, att, out) { const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, at); g.gain.exponentialRampToValueAtTime(peak, at + att);
  g.gain.exponentialRampToValueAtTime(0.0001, at + att + dec); g.connect(out); return g; }
function noise(ctx, at, dur, ...filters) { const s = ctx.createBufferSource(); s.buffer = CLICK.noise; let node = s;
  filters.forEach(f => { node.connect(f); node = f; }); s.start(at, Math.random() * 0.5); s.stop(at + dur); return node; }
function filt(ctx, type, f, q = 1) { const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = f; b.Q.value = q; return b; }
function tone(ctx, at, f0, f1, dur, type = 'sine') { const o = ctx.createOscillator(); o.type = type; o.frequency.setValueAtTime(f0, at);
  o.frequency.exponentialRampToValueAtTime(f1, at + dur); o.start(at); o.stop(at + dur + 0.01); return o; }
const SOUNDS = {   // (ctx, 時刻, 高さの倍率 k, 強さ v, 出す先)
  'カッ': (ctx, at, k, v, out) => {   // 木の板を叩いたような短い音（よく通る）
    tone(ctx, at, 2100 * k, 1300 * k, 0.05, 'triangle').connect(env(ctx, at, 0.9 * v, 0.05, 0.001, out));
    noise(ctx, at, 0.02, filt(ctx, 'bandpass', 3500 * k, 1.2)).connect(env(ctx, at, 0.7 * v, 0.015, 0.001, out));
  },
  'シュッ': (ctx, at, k, v, out) => {   // 切るような音（高い雑音を絞る）
    const bp = filt(ctx, 'bandpass', 7000 * k, 0.9); bp.frequency.setValueAtTime(7000 * k, at); bp.frequency.exponentialRampToValueAtTime(2600 * k, at + 0.07);
    noise(ctx, at, 0.09, filt(ctx, 'highpass', 1800), bp).connect(env(ctx, at, 1.0 * v, 0.08, 0.003, out));
  },
  'パン': (ctx, at, k, v, out) => {   // 手拍子・スネアのような音
    [0, 0.008, 0.016].forEach((d, i) => noise(ctx, at + d, 0.03, filt(ctx, 'bandpass', 1500 * k, 0.8)).connect(env(ctx, at + d, (i === 2 ? 1.0 : 0.6) * v, i === 2 ? 0.11 : 0.01, 0.001, out)));
    tone(ctx, at, 260 * k, 180 * k, 0.06).connect(env(ctx, at, 0.5 * v, 0.06, 0.001, out));
  },
  'ピッ': (ctx, at, k, v, out) => { tone(ctx, at, 1500 * k, 1500 * k, 0.05, 'square').connect(env(ctx, at, 0.35 * v, 0.05, 0.001, out)); },
};
// 鳴らす: hand＝0 左手・1 右手・2 両手（拍の時は小節の頭）・-1 拍。左右で変える時は左手＝低め・左から、右手＝高め・右から、両手＝真ん中で強く
function beep(at, hand) {
  const ctx = CLICK.ctx, lr = $('pvLR').checked;
  let k = 1, v = 0.9, pan = 0;
  if (hand === 2) { k = 1.25; v = 1; }
  else if (hand === -1) { v = 0.8; }
  else if (lr) { k = hand === 0 ? 0.82 : 1.18; pan = hand === 0 ? -0.7 : 0.7; }
  let out = CLICK.bus;
  if (pan) { const p = ctx.createStereoPanner(); p.pan.value = pan; p.connect(CLICK.bus); out = p; }
  SOUNDS[$('pvSnd').value || 'カッ'](ctx, at, k, v, out);
}
function tryBeep() { const ctx = audio(), t = ctx.currentTime + 0.03; [0, 1, 0, 1, 2].forEach((h, i) => beep(t + i * 0.25, h)); }

// 鳴らす時刻の表 [[元の音源の秒, hand]]（ノーツ＝同じ時刻の物をまとめる・拍＝毎拍、小節の頭は強く）
function buildList() {
  if (!S.D) return;
  const out = [];
  if ($('pvWhat') && $('pvWhat').value === '拍') {
    const bars = new Set(BEATS());
    for (let b = Math.max(0, Math.ceil(beatOf(0))); timeOf(b) < S.D.dur; b++) out.push([timeOf(b), bars.has(b) ? 2 : -1]);
  } else {
    const ns = S.D.notes.slice().sort((a, b) => a[0] - b[0]);
    for (let i = 0; i < ns.length;) {
      const t = ns[i][0], cs = new Set();
      while (i < ns.length && Math.abs(ns[i][0] - t) < 0.005) { cs.add(ns[i][3]); i++; }
      out.push([t, cs.size >= 2 ? 2 : [...cs][0]]);
    }
  }
  CLICK.list = out; CLICK.est = null; CLICK.song = S.file;
}
// 確かめ用: 切る音の表の曲・数・最初の時刻（main.js の #cktest）
export function clickInfo() { return {song: CLICK.song, n: (CLICK.list || []).length, first: CLICK.list && CLICK.list[0] ? CLICK.list[0][0] : null, stat: CLICK.stat || null,
  done: CLICK.done, list: (CLICK.list || []).map(x => x[0])}; }
// 予約: 曲（<audio>）の再生位置と、音を作る時計（Web Audio）の差を毎コマ測ってならし（再生位置は 10ms ほどの段で進むので、
// そのまま使うと1つずつ前後にぶれた）、音を作る時計の出口の遅れ（outputLatency＋baseLatency・Windows で 10〜40ms、Bluetooth なら
// もっと）を先に引いて予約する（引かないと、その分だけ遅れて聞こえた・利用者「ずれて聞こえる」）。利用者のずれ直し（ms）を足す。
// 1.5 秒先まで予約する（AHEAD）。前は 0.4 秒先までで、画面の描き直しが 0.4 秒以上止まると、その間に来る音の時刻が過ぎて鳴らなかった
// （2026-11-08 利用者「1 曲で間隔を空けて 4 回ほど鳴らない」・見えない Edge で再生中に 0.8 秒止めると 7 回のうち 6 回で鳴らなかった）。
// 先まで予約するので、止めた・位置を変えた・時計の差を作り直した時は予約を取り消す（clickCancel）
const AHEAD = 1.5;
function clickTick() {
  if (CLICK.on && P.playing && (!CLICK.ctx || CLICK.ctx.state === 'suspended')) audio();   // 覚えていた「切る音」: 再生の操作の後に音の部品を作る・起こす
  if (!CLICK.on || !CLICK.ctx || !P.playing || !S.D) { if (CLICK.est != null) clickCancel(); CLICK.est = null; CLICK.lastPn = null; return; }
  if (!CLICK.list) buildList();
  // 数える（確かめ用・clickInfo）: 予約した音・時刻が過ぎて鳴らせなかった音・時計の差の作り直し・描き直しの一番長い間
  const stt = CLICK.stat || (CLICK.stat = {sched: 0, late: 0, resets: 0, maxGap: 0, gaps: 0, lateAt: [], resetAt: [], gapAt: []});
  const pn = performance.now();
  if (CLICK.lastPn != null) { const g = pn - CLICK.lastPn; if (g > stt.maxGap) stt.maxGap = Math.round(g); if (g > 250) { stt.gaps++; stt.gapAt.push([+mediaNow().toFixed(2), Math.round(g)]); } }
  CLICK.lastPn = pn;
  const ctx = CLICK.ctx, m = mediaNow(), sample = m - ctx.currentTime;
  if (CLICK.est == null || Math.abs(sample - CLICK.est) > 0.1) {   // 始め・再生位置が飛んだ（予約を取り消して今から予約し直す）
    if (CLICK.est != null) { stt.resets++; stt.resetAt.push([+m.toFixed(2), +(sample - CLICK.est).toFixed(3)]); }
    clickCancel(); CLICK.est = sample; CLICK.done = m;
  } else CLICK.est += (sample - CLICK.est) * 0.03;
  const lat = (ctx.outputLatency || 0) + (ctx.baseLatency || 0), adj = (+$('pvOff').value || 0) / 1000;
  const tMax = ctx.currentTime + AHEAD + CLICK.est + lat - adj, list = CLICK.list;
  // 予約した所（done）より後の音から。前は done＋0.1ms より後からで、前のコマの予約の端のすぐ後（0.1ms 以内）に来た音が、どのコマでも予約されずに
  // 飛ばされた（1 曲で 1〜10 回・コマが速い画面ほど多い・見えない Edge の The Cup of Life 230 秒で 695 のうち 4・2026-11-08 利用者「時々鳴らない」）
  let lo = 0, hi = list.length; while (lo < hi) { const md = (lo + hi) >> 1; if (list[md][0] <= CLICK.done) lo = md + 1; else hi = md; }
  for (let i = lo; i < list.length && list[i][0] <= tMax; i++) {
    const at = list[i][0] - CLICK.est - lat + adj;
    if (at >= ctx.currentTime - 0.005) { beep(Math.max(at, ctx.currentTime), list[i][1]); stt.sched++; }
    else { stt.late++; stt.lateAt.push([+list[i][0].toFixed(2), Math.round((ctx.currentTime - at) * 1000)]); }
  }
  CLICK.done = Math.max(CLICK.done, tMax);
  $('pvOffV').title = `自動で引いている音の出口の遅れ ${Math.round(lat * 1000)}ms`;
}
