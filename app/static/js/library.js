// 曲ごとのライブラリの設定（app/library.py・automap/library_use.py）の画面。main.js が init(app) を呼ぶ。
// 上の列の「ライブラリ」→ 窓で★の帯・年・難易度・型の頻度と難しさの上限を選ぶ（型は BeatLeader のランク譜面の型のデータベースから。
// 前の「今の型（cache/themes.json）」と出どころの手元の譜面の選びは除いた・2026-11-09・docs/除いた物.md）。選ぶたびに曲と型の数を出す。
// 「決める」で作業ファイルの library に入れる（commit＝Ctrl+Z で戻せる・すぐ保存）。次の作り直しから効く。設定の無い曲は新しい曲の既定
// （サーバーが作業ファイルを読む時に読み替える＝automap/library_setting.py）。
// 同じ窓の下に「量の目安」（作業ファイルの amount・自動／★の帯の中央値／1秒のノーツを直接）。今の譜面の1秒のノーツと帯の中央値を並べる。
// 絞り込みの欄（窓の上半分）は filterPanel で作る＝取り込みの基本設定の窓（importer.js）にも同じ物を置く。
import {$, api, S, on, commit, saveWork, undo} from './store.js';

let A = null;          // main.js から渡された口
let INFO = null;       // GET /api/library（データベースが使えるか・既定・年の範囲・★の帯）
let PANEL = null;      // 窓の絞り込みの欄（filterPanel）
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const pct = v => v == null ? '?' : Math.round(v * 100) + '%';
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

// 時期の自動（years＝'auto'・automap/library_use.AUTO）: 曲ごとに手本の時期を決める（2026-11-03 から新しい曲の既定）。auto_v＝決め方の版
// （2＝離れた年も入る新しい決め方・2026-11-15。印の無い自動は前の決め方＝つながった年＝それより前に作った曲）。選んだ年は年の一覧（year_set・
// 歯抜けあり）。前の範囲 [から, まで]（years）は年の一覧に読み替える（automap/library_use.normalize と同じ）
export const AUTO = 'auto', AUTO_V = 2;
// 年の一覧 → 字（続いた年はまとめる・library_use.years_text と同じ）: [2019, 2021, 2022, 2023] → 「2019・21〜23」（long＝「2019・2021〜2023」）
export function yearsText(ys, long = false) {
  const a = [...new Set((ys || []).map(Number))].sort((x, y) => x - y), runs = [];
  a.forEach(y => { if (runs.length && y === runs[runs.length - 1][1] + 1) runs[runs.length - 1][1] = y; else runs.push([y, y]); });
  return runs.map(([x, y], i) => { const sx = !long && i ? String(x).slice(2) : String(x);
    return x === y ? sx : `${sx}〜${long ? y : String(y).slice(2)}`; }).join('・');
}
const range = (a, b) => { const o = []; for (let y = +a; y <= +b; y++) o.push(y); return o; };
const yearsOf = f => f.year_set ? [...f.year_set] : Array.isArray(f.years) && f.years.length === 2 ? range(f.years[0], f.years[1]) : null;

// 絞り込み → 短い説明（ボタン用・automap/library_use.label の short と同じ）。autoYears＝時期が自動の時のこの曲の時期（無ければ書かない）
const starText = st => !st ? '★全部' : st[0] <= 0 ? `★〜${st[1]}` : st[1] >= 99 ? `★${st[0]}〜` : `★${st[0]}〜${st[1]}`;
export function labelShort(f, autoYears = null) {
  if (!f) return '新しい曲の既定';
  const src = (f.sources && f.sources.length === 1) ? ({ranked: 'ランク', local: '手元'})[f.sources[0]] : 'ランク＋手元';
  const parts = [src, starText(f.stars)], ay = autoYears || f.auto_years, ys = yearsOf(f);
  if (f.years === AUTO) parts.push('時期自動' + (ay ? `（${yearsText(ay)}）` : ''));
  else if (ys) parts.push(yearsText(ys));
  if (f.freq) parts.push(f.freq + 'まで');
  if (f.hard) parts.push(f.hard + 'まで');
  return parts.join(' ');
}

// 量の目安 → 短い説明（null＝自動）
export function amountShort(a) {
  if (!a) return '自動';
  if (a.mode === 'nps') return `1秒 ${(+a.nps).toFixed(1)}`;
  const s = a.stars || [];
  return s[0] <= 0 ? `★〜${s[1]}` : `★${s[0]}〜${s[1]}`;
}

// GET /api/library を読み直す（labelShort が既定の年を見る・取り込みの基本設定の窓も使う）→ INFO
export async function libraryInfo() {
  INFO = await api('GET', '/api/library');
  button();
  return INFO;
}

// 上の列のボタン: 字は★の帯と量だけ（上の列を 1 段に収める・2026-11-09 利用者）・出どころ・時期・頻度・難しさまでの全部はマウスを乗せた時（title の 1 行目）
function button() {
  const b = $('libBtn'); if (!b) return;
  const f = (S.W && S.W.library) || (INFO && INFO.default), am = S.W && S.W.amount;
  b.textContent = 'ライブラリ ' + (f ? starText(f.stars) : '') + (am ? `・量 ${amountShort(am)}` : '');
  const bad = INFO && !INFO.available;
  b.classList.toggle('libBad', !!bad);
  b.classList.toggle('libDb', !bad);
  b.title = `ライブラリ: ${labelShort(f)}` + (am ? `・量の目安 ${amountShort(am)}` : '') + '\n' +
    (bad ? `型のデータベースが使えない（${INFO.error}）＝作り直しは止まる（「準備と設定」で型のライブラリを確かめる）`
         : 'この曲は BeatLeader のランク譜面の型のデータベースから型を取る（押すと変えられる）');
}

// ---- 型のライブラリの絞り込みの欄（ライブラリの窓の上半分。取り込みの基本設定の窓＝importer.js でも使う） ----
// filterPanel(host, {prefix, onChange, who}) → {load(info, filters), get(), set(filters), last()}。host の中に欄を作る。
// who＝() => 数える曲（{file: 結果のファイル} か {song: 曲の名前}）＝時期が自動の時にその曲の時期で数える（無ければ年を絞らない数）。
// prefix＝欄の要素の id の頭（ライブラリの窓は 'lib'＝前からの id・取り込みの窓は 'impLib'＝同じページで重ならない）。
// load＝/api/library の答えと初めの絞り込み（null＝新しい曲の既定）で出し直す・get＝選んでいる絞り込み（形は library_use.normalize と同じ・
// 出どころはランク譜面に固定）・set＝選び直す（「新しい曲の既定に戻す」）・last＝最後に数えた答え。選ぶたびに /api/library/count で
// 曲と型の数を数え直す（onChange(絞り込み) も呼ぶ）。
export function filterPanel(host, {prefix = 'lib', onChange = null, who = null} = {}) {
  const p = prefix, q = k => host.querySelector('#' + p + k);
  let I = null, F = fromFilters(null), LAST = null, reqNo = 0, timer = 0;
  host.classList.add('libPick');
  host.innerHTML = `<div id="${p}Db" class="libNote"></div>
    <div id="${p}Form" class="libForm">
      <!-- 上から下へだんだん詳しく絞る（2026-11-15 利用者「アップロード年を一番上に置こう。そこを絞ると下の星の型が絞られていく」）:
           年の横の数＝★を外した曲の数・★の帯の横の数＝選んだ年の中の曲の数 -->
      <span class="libKey">アップロード年</span><div class="libYears"><div class="seg" id="${p}YMode"></div>
        <div class="libYChecks" id="${p}YList"></div>
        <span class="sub" id="${p}YNote"></span></div>
      <span class="libKey">★の帯</span><div class="seg" id="${p}Stars"></div>
      <span class="libKey">難易度</span><div class="seg" id="${p}Diffs"></div>
      <span class="libKey">型の頻度</span><div class="seg" id="${p}Freq"></div>
      <span class="libKey">置き方の難しさ</span><div class="seg" id="${p}Hard"></div>
      <span class="libKey">出どころ</span><div class="sub" id="${p}Src">BeatLeader のランク譜面（ランクの難易度だけ）</div>
    </div>
    <div id="${p}Count" class="libCount"></div>
    <div id="${p}Warn"></div>`;
  const changed = () => { render(); recount(); if (onChange) onChange(toFilters()); };
  const isAuto = () => F.years === AUTO;

  function toFilters() {      // 欄の状態 → 絞り込み。形は library_use.normalize と同じ（出どころはランク譜面に固定）
    const f = {sources: ['ranked']};
    if (F.years === AUTO) { f.years = AUTO; if (F.autoV === AUTO_V) f.auto_v = AUTO_V; }
    else if (F.ysel && F.ysel.length) f.year_set = [...F.ysel].sort((a, b) => a - b);
    if (F.stars) f.stars = [...F.stars];
    f.diffs = F.diffs && F.diffs.length ? [...F.diffs] : ['Expert', 'ExpertPlus'];
    if (F.freq) f.freq = F.freq;   // 無い＝既定（曲の数に合わせたしきい値）・「珍しい」＝少ない曲にしか出ない型もテーマの候補に
    if (F.hard && F.hard !== I.hard[I.hard.length - 1]) f.hard = F.hard;
    return f;
  }
  function seg(id, items, cur, pick) {   // 並んだボタン（1つ選ぶ）。items＝[{v, t, sub, title}]
    const el = q(id);
    el.innerHTML = items.map((it, i) => `<button data-i="${i}" class="${same(it.v, cur) ? 'on' : ''}" title="${esc(it.title || '')}">${esc(it.t)}${it.sub != null ? `<small>${esc(it.sub)}</small>` : ''}</button>`).join('');
    el.querySelectorAll('button').forEach(b => b.onclick = () => { pick(items[+b.dataset.i].v); changed(); });
  }
  function render() {
    const ok = I.available;
    q('Db').innerHTML = ok ? `型のデータベース: 使える（作った日 ${esc((I.built_at || '').slice(0, 10))}）`
      : `<span class="bad">型のデータベースが使えない</span>（${esc(I.error)}）。この PC では作り直せない（型は BeatLeader のランク譜面の
         型のデータベースから作る・「準備と設定」で型のライブラリを確かめる）`;
    const bandSongs = LAST && LAST.bands;
    const bands = I.bands.map((b, i) => ({v: b.stars, t: '★' + b.name, sub: bandSongs ? `${bandSongs[i]} 曲` : ''}));
    if (F.stars && !I.bands.some(b => same(b.stars, F.stars))) bands.push({v: F.stars, t: `★${F.stars[0]}〜${F.stars[1]}`, sub: ''});
    seg('Stars', bands, F.stars, v => { F.stars = v; });
    // アップロード年（2026-11-15 利用者「チェックボックス式にしてどの年とどの年を選べる…歯抜けの年を持たせたり」）: 年ごとのチェック
    // （横の数＝★を外した曲の数＝LAST.year_counts）。自動の時はこの曲に選ばれた年にチェック（触れない）。自動 → 年を選ぶは自動の年から始める
    const R = I.years || [2020, 2026], ys = range(R[0], R[1]);
    const auto = isAuto(), old = auto && F.autoV !== AUTO_V, ay = LAST && LAST.auto_years, yc = (LAST && LAST.year_counts) || {};
    seg('YMode', [{v: AUTO, t: '自動（曲ごと）', title: '曲ごとに手本の年を決める＝曲どうしのテーマが散る（新しい曲の既定）。中心の年は曲の名前で決まり、離れた年も入る（歯抜けあり）。人の譜面は時期で型の選ばれ方が大きく変わる'},
                  {v: 'pick', t: '年を選ぶ', title: '年を自分で選ぶ（チェックした年だけ・歯抜けも可・どれも選ばない＝全部の年）'}], auto ? AUTO : 'pick',
        v => { if (v === AUTO) { if (!isAuto()) { F.years = AUTO; F.autoV = AUTO_V; } }
               else if (isAuto()) { F.years = null; F.ysel = ay ? [...ay] : []; } });
    const on = new Set(auto ? (ay || []) : (F.ysel || []));
    q('YList').classList.toggle('auto', auto);
    q('YList').innerHTML = ys.map(y => `<label class="libY${on.has(y) ? ' on' : ''}" title="${auto ? '自動の時は選べない（「年を選ぶ」で選び直す）' : ''}"><input type="checkbox" data-y="${y}"${on.has(y) ? ' checked' : ''}${auto ? ' disabled' : ''}>${y}`
      + (yc[y] != null ? `<small>${yc[y]} 曲</small>` : '') + '</label>').join('');
    q('YList').querySelectorAll('input').forEach(c => c.onchange = () => {
      const y = +c.dataset.y, s = new Set(F.ysel || []);
      if (c.checked) s.add(y); else s.delete(y);
      F.ysel = [...s].sort((a, b) => a - b); changed();
    });
    q('YNote').innerHTML = auto
      ? (ay ? `この曲は <b>${esc(yearsText(ay, true))} 年</b>` + (old ? '（前の決め方＝つながった年・この曲を作った時のまま）<button class="libYNew" title="離れた年も入る新しい決め方の自動にする（次の作り直しから型が変わる）">新しい決め方にする</button>'
                                                    : '（曲の名前で決まる・離れた年も入る・曲の数が足りるまで足す）')
            : LAST && LAST.available !== false && who ? '年ごとの曲の数を数えられないので年は絞らない' : '曲ごとに決める（数えた後に出る）')
      : (F.ysel && F.ysel.length ? `<b>${esc(yearsText(F.ysel, true))} 年</b>・` : 'どれも選ばない＝全部の年・') + 'BeatSaver に上がった年（年の分からない譜面は年を選ぶと入らない）';
    const nb = q('YNote').querySelector('.libYNew');
    if (nb) nb.onclick = () => { F.autoV = AUTO_V; changed(); };
    const dd = F.diffs || ['Expert', 'ExpertPlus'];
    seg('Diffs', [{v: ['Expert', 'ExpertPlus'], t: 'Expert と Expert+'}, {v: ['ExpertPlus'], t: 'Expert+ だけ'}, {v: ['Expert'], t: 'Expert だけ'}], dd, v => { F.diffs = v; });
    const fq = I.freq, hd = I.hard;
    seg('Freq', [{v: fq[0], t: fq[0] + 'まで', title: '多くの曲に出る型だけ（曲の 5% 以上）'}, {v: fq[1], t: fq[1] + 'まで', title: '曲の 1% 以上に出る型まで'},
                 {v: null, t: '既定', title: '曲の数に合わせたしきい値（手元の 899 曲で 片手 8 曲・両手 3 曲以上と同じ割合）'},
                 {v: fq[2], t: fq[2] + 'まで', title: '少ない曲（2 曲以上）にしか出ない型もテーマの候補に入れる'}], F.freq || null, v => { F.freq = v; });
    seg('Hard', [{v: hd[0], t: hd[0] + 'まで', title: '置き方の難しさの点が下から 1/3 の型だけ'}, {v: hd[1], t: hd[1] + 'まで', title: '下から 2/3 まで'},
                 {v: hd[2], t: hd[2] + 'まで（全部）'}], F.hard || hd[2], v => { F.hard = v; });
  }
  function recount() {
    clearTimeout(timer);
    const no = ++reqNo, f = toFilters();
    q('Count').classList.add('busy');
    timer = setTimeout(async () => {
      try {
        const c = await api('POST', '/api/library/count', Object.assign({library: f}, f.years === AUTO && who ? who() : {}));
        if (no !== reqNo) return;
        LAST = c;
        q('Count').innerHTML = countHTML(c);
        q('Warn').innerHTML = c.warn ? `<div class="libWarnBox">${esc(c.warn)}</div>` : '';
        if (c.bands) render();
      } catch (e) { if (no === reqNo) q('Count').innerHTML = `<span class="bad">数えられない: ${esc(e.message)}</span>`; }
      finally { if (no === reqNo) q('Count').classList.remove('busy'); }
    }, 120);
  }
  return {
    load(info, filters) {
      I = info; F = fromFilters(filters || info.default); LAST = null;
      q('Count').innerHTML = ''; q('Warn').innerHTML = '';
      render(); recount();
    },
    get: () => toFilters(),
    set(filters) { F = fromFilters(filters); changed(); },
    last: () => LAST,
  };
}

function fromFilters(f) {   // 絞り込み → 欄の状態（出どころはランク譜面に固定＝欄に持たない）
  f = f || {};
  const auto = f.years === AUTO;
  return {stars: f.stars ? [...f.stars] : null, years: auto ? AUTO : null, autoV: auto && f.auto_v === AUTO_V ? AUTO_V : null,
          ysel: auto ? [] : (yearsOf(f) || []), diffs: f.diffs ? [...f.diffs] : ['Expert', 'ExpertPlus'], freq: f.freq || null, hard: f.hard || null};
}

function countHTML(c) {
  if (!c) return '';
  if (c.available === false) return `<span class="bad">数えられない</span>: ${esc(c.error)}`;
  const s = c.stats;
  return `<div class="libNums"><span><b>${c.songs}</b> 曲</span><span>片手の型 <b>${c.hands}</b></span><span>両手の組 <b>${c.pairs}</b></span>
    <span>1回だけの並び <b>${c.once}</b></span>
    <span class="libMain">テーマに使える型 <b>${c.themes}</b><small>（片手 ${c.min[0]} 曲以上・両手 ${c.min[1]} 曲以上）</small></span></div>`
    + (s ? `<div class="sub">選んだ譜面（${s.diffs} 難易度）: 斜め ${pct(s.diag)}・外側の列 ${pct(s.outer)}・上の段 ${pct(s.top)}`
         + (s.nps ? `・1秒のノーツ 中央値 ${s.nps}` : '') + '（斜め・外側の列・上の段は曲の個性の目標に効かせる）</div>' : '');
}

function build() {
  const d = document.createElement('div');
  d.id = 'libDlg'; d.className = 'modal lib';
  d.innerHTML = `<div class="dlg">
  <div class="dlgHead"><b>型のライブラリ・量の目安</b><span class="sub" id="libSong"></span><button id="libClose">閉じる</button></div>
  <div class="dlgBody">
    <div id="libPanel"></div>
    <div class="libAmt">
      <div class="libAmtHead"><b>量の目安</b><span class="sub">1秒のノーツの数（型のライブラリとは別。帯を変えても量は変わらない）</span></div>
      <div class="libAmtNow" id="libAmtNow"></div>
      <label class="libMode"><input type="radio" name="amtMode" value="auto"><span><b>自動</b>（今のまま＝曲から拾った打点の量）</span></label>
      <label class="libMode"><input type="radio" name="amtMode" value="band"><span><b>★の帯に合わせる</b>（その帯の人の譜面の中央値）</span></label>
      <div class="seg libAmtBands" id="libAmtBands"></div>
      <label class="libMode"><input type="radio" name="amtMode" value="nps"><span><b>1秒のノーツを直接</b></span>
        <input type="number" id="libAmtNps" min="1" max="16" step="0.1"><span class="sub">ノーツ</span></label>
      <div class="libAmtCmp" id="libAmtCmp"></div>
    </div>
    <div class="hint">決めると次の作り直しから効く（設定は作業ファイルに入る・Ctrl+Z で戻せる）。型のライブラリの★の帯を変えても量は変わらない（量は「量の目安」）。
      量を増やす時はまず拾う打点を増やす（半拍・1/4 拍の弱めの音・歌とドラムの両方）。両手は区間の「両手」の指示のまま。
      量のライン（50〜150%）と区間の量 ±は、目安で合わせた量に対する割合。設定の無い曲は新しい曲の既定・今の量のまま。</div>
    <div class="libFoot"><button id="libDefault" title="新しく取り込む曲の既定（ランク譜面・時期は曲ごとに自動・既定の★の帯・Expert／Expert+）">新しい曲の既定に戻す</button>
      <span class="libSpacer"></span><button id="libCancel">やめる</button><button id="libOk" class="main">決める</button></div>
  </div></div>`;
  document.body.appendChild(d);
  PANEL = filterPanel($('libPanel'), {prefix: 'lib', who: () => ({file: S.file})});
  d.addEventListener('keydown', e => { e.stopPropagation(); if (e.key === 'Escape') close(); });
  d.addEventListener('mousedown', e => { if (e.target === d) d.dataset.down = '1'; });
  d.addEventListener('click', e => { if (e.target === d && d.dataset.down === '1') close(); d.dataset.down = ''; });
  $('libClose').onclick = close; $('libCancel').onclick = close;
  $('libOk').onclick = decide;
  $('libDefault').onclick = () => PANEL.set(INFO.default);
  d.querySelectorAll('input[name=amtMode]').forEach(r => r.onchange = () => {
    AM.mode = r.value;
    if (AM.mode === 'band' && !AM.stars) AM.stars = nearBand();
    if (AM.mode === 'nps' && !AM.nps) AM.nps = +(NOW.nps || 4).toFixed(1);
    renderAmount();
  });
  $('libAmtNps').oninput = () => { const v = parseFloat($('libAmtNps').value); if (isFinite(v)) { AM.nps = v; AM.mode = 'nps'; } renderAmount(false); };
}

// ---- 量の目安（作業ファイルの amount・app/library.py の amount_extra → compose --nps-target・automap/amount.py） ----
let AM = {mode: 'auto'};      // 窓で選んでいる物 {mode: 'auto'|'band'|'nps', stars, nps}
let NOW = {};                  // 今の譜面の1秒のノーツ（S.D.notes から）と★（/api/rating）
const NPS_MIN = () => (INFO && INFO.nps_range ? INFO.nps_range[0] : 1), NPS_MAX = () => (INFO && INFO.nps_range ? INFO.nps_range[1] : 16);
function fromAmount(a) { return !a ? {mode: 'auto'} : a.mode === 'nps' ? {mode: 'nps', nps: +a.nps} : {mode: 'band', stars: [...a.stars]}; }
function toAmount() {         // 窓の状態 → 作業ファイルの amount（null＝自動＝今のまま）。形は library_use.amount_of と同じ
  if (AM.mode === 'band' && AM.stars) return {mode: 'band', stars: [...AM.stars]};
  if (AM.mode === 'nps' && isFinite(AM.nps) && AM.nps >= NPS_MIN() && AM.nps <= NPS_MAX()) return {mode: 'nps', nps: Math.round(AM.nps * 100) / 100};
  return null;
}
function bandsOf() { return (INFO && INFO.amount_bands) || []; }
function nearBand() {          // 今の量に一番近い帯（帯を初めて選ぶ時）
  const bs = bandsOf(); if (!bs.length) return [4, 6];
  const v = NOW.nps || 4; return [...bs.reduce((a, b) => Math.abs(b.nps - v) < Math.abs(a.nps - v) ? b : a).stars];
}
function amountTarget(a) {     // amount → [1秒のノーツ, 説明] か null
  if (!a) return null;
  if (a.mode === 'nps') return [a.nps, '直接'];
  const b = bandsOf().find(b => same(b.stars, a.stars));
  return b ? [b.nps, `★${b.name} の人の譜面${b.diffs ? ` ${b.diffs} 難易度` : ''}の中央値${b.diffs ? '' : '（参考の値）'}`] : null;
}
function measureNow() {        // 今の譜面（帯「作った譜面」と同じ）: ノーツ ÷ 最初から最後のノーツまでの秒
  const ns = (S.D && S.D.notes) || [];
  if (ns.length < 2) return {n: ns.length, nps: null};
  let t0 = Infinity, t1 = -Infinity; ns.forEach(n => { t0 = Math.min(t0, n[0]); t1 = Math.max(t1, n[0]); });
  return {n: ns.length, nps: t1 > t0 ? ns.length / (t1 - t0) : null};
}
function renderAmount(setInput = true) {
  document.querySelectorAll('input[name=amtMode]').forEach(r => { r.checked = r.value === AM.mode; });
  const n = NOW.nps;
  $('libAmtNow').innerHTML = n ? `今の譜面: <b>1秒 ${n.toFixed(2)}</b> ノーツ（${NOW.n} ノーツ${NOW.stars != null ? `・★ ${(+NOW.stars).toFixed(2)}` : ''}）`
    + (S.W.amount ? `・今の設定「${esc(amountShort(S.W.amount))}」で作った量` : '・今の設定「自動」') : '今の譜面: まだ無い';
  const bs = bandsOf();
  $('libAmtBands').innerHTML = bs.length ? bs.map((b, i) => `<button data-i="${i}" class="${AM.mode === 'band' && same(b.stars, AM.stars) ? 'on' : ''}"
      title="${esc(`★${b.name} の人の譜面${b.diffs ? `（${b.diffs} 難易度・ランク譜面・2020 年以降・Expert／Expert+）` : '（参考の値・型のデータベースが使えない）'}の1秒のノーツの中央値`)}">★${esc(b.name)}<small>${b.nps.toFixed(1)}${n ? `・${(b.nps / n).toFixed(2)} 倍` : ''}</small></button>`).join('')
    : '<span class="sub">帯の中央値を読めなかった</span>';
  $('libAmtBands').querySelectorAll('button').forEach(b => b.onclick = () => { AM.mode = 'band'; AM.stars = [...bs[+b.dataset.i].stars]; renderAmount(); });
  $('libAmtBands').classList.toggle('off', AM.mode !== 'band');
  if (setInput) $('libAmtNps').value = AM.nps != null && isFinite(AM.nps) ? (+AM.nps).toFixed(1) : '';
  const t = amountTarget(toAmount());
  const bad = AM.mode === 'nps' && !toAmount();
  $('libAmtCmp').innerHTML = bad ? `<span class="bad">1秒のノーツは ${NPS_MIN()}〜${NPS_MAX()} で入れる</span>`
    : !t ? '自動: 作り直しは今の作り方の量のまま（曲から拾った打点）。'
    : `目安 <b>1秒 ${(+t[0]).toFixed(2)}</b> ノーツ（${esc(t[1])}）` + (n ? `＝今の譜面の <b>${(t[0] / n).toFixed(2)}</b> 倍` : '')
      + '。自動の打点を小節ごとに同じ倍率で足す・減らして合わせ、量のラインと区間の量 ±はこの量に対する割合で効く。'
      + (n && t[0] / n > 1.6 ? '<br><span class="warnTxt">大きく増やす: 拾える打点が足りない所は目安に届かない（報告に「目安 x に対して y」）。</span>' : '');
}
async function openAmount() {
  AM = fromAmount(S.W.amount);
  NOW = measureNow();
  renderAmount();
  try {   // ★は測った答えがあればすぐ返る（無ければ少し待つ）
    const r = await api('GET', '/api/rating?wait=3&file=' + encodeURIComponent(S.file));
    if (r && r.state === 'done' && r.stars != null) { NOW.stars = r.stars; renderAmount(false); }
  } catch (e) {}
}

async function open() {
  if (!S.file) return;
  if (!$('libDlg')) build();
  try { await libraryInfo(); } catch (e) { A.status('ライブラリを読めなかった: ' + e.message, true); return; }
  $('libSong').textContent = `${S.song}・今は「${labelShort(S.W.library)}」`;
  PANEL.load(INFO, S.W.library);
  openAmount();
  $('libDlg').style.display = 'flex';
}
async function undoTest() {   // #libtest&undo: 違う★の帯に決める → Ctrl+Z で戻す（結果を題名に・--dump-dom で読む）
  const before = JSON.stringify(S.W.library);
  const cur = S.W.library || INFO.default, b = INFO.bands.find(x => x.stars && !same(x.stars, cur.stars));
  PANEL.set(Object.assign({}, cur, {stars: [...b.stars]})); await decide();
  const mid = JSON.stringify(S.W.library), btn1 = $('libBtn').textContent;
  undo();
  document.title = `libtest before=${before} mid=${mid} btn1=${btn1} after=${JSON.stringify(S.W.library)} btn2=${$('libBtn').textContent}`;
}
function close() { if ($('libDlg')) $('libDlg').style.display = 'none'; }

async function decide() {
  const f = PANEL.get(), am = toAmount();
  if (AM.mode === 'nps' && !am) { $('libAmtNps').focus(); return; }   // 範囲の外の数は決めない（窓を閉じない）
  close();
  const libSame = same(f, S.W.library || null), amSame = same(am, S.W.amount || null);
  if (libSame && amSame) { A.status('ライブラリと量の目安の設定は変わっていない'); return; }
  commit(W => { W.library = f; W.amount = am; });   // 1つの操作（Ctrl+Z で両方戻る）
  await saveWork();
  A.status([libSame ? '' : `ライブラリを「${labelShort(f)}」`, amSame ? '' : `量の目安を「${amountShort(am)}」`].filter(Boolean).join('・')
           + 'にした。次の作り直しから効く（Ctrl+Z で戻せる）');
}

export function init(app) {
  A = app;
  libraryInfo().catch(() => {});
  if ($('libBtn')) $('libBtn').onclick = open;
  on('work', button);   // 曲を開いた・元に戻した・決めた時
  if (location.hash.startsWith('#libtest')) {   // 確かめ用（見えない Edge で窓を写す）: #libtest&song=曲名 でその曲を開いてから
    const m = decodeURIComponent(location.hash).match(/&song=([^&]+)/);
    on('work', () => {
      if (!S.D || $('libDlg')) return;
      if (m && S.song !== m[1] && S.songs.some(q => q.song === m[1])) { A.openSong(m[1]); return; }
      open().then(() => {
        if (/&undo/.test(location.hash)) setTimeout(undoTest, 1500);
        const am = decodeURIComponent(location.hash).match(/&amt=([^&]+)/);   // &amt=6,8（★の帯）・&amt=5.5（直接）: 量の目安を選んだ所を写す
        if (am) setTimeout(() => {
          const v = am[1].split(',').map(Number);
          AM = v.length === 2 ? {mode: 'band', stars: v} : {mode: 'nps', nps: v[0]};
          renderAmount();
          document.title = `libtest amt=${JSON.stringify(toAmount())} now=${NOW.nps && NOW.nps.toFixed(2)}`;
        }, 800);
      });
    });
  }
}
