// 作った譜面の★（app/rating.py・nlm-rating の近似）を上の列の #starInfo に出す。main.js が init(app) を呼ぶ。
// 曲を開いた時（作業ファイルを読んだ＝'work' で開いている結果のファイルが変わった時）・作り直した後（'generated'）・
// 譜面を読み直した後（'chart'＝履歴から戻した・別の案を選んだ）に測り直す。サーバーは中身が同じなら前の答えを返す。
// 作業ファイルにライブラリの設定（library.stars＝★の帯）があれば「★ 5.8（ライブラリ ★〜8.5）」のように並べる。
// 測るのは見ている難易度（S.view＝派生を見ている時は &diff=・基準の時は渡さない＝サーバーが基準の難易度）。派生の時は難易度の名前を並べ、
// ライブラリの帯は出さない（帯は基準の設定）。
import {S, $, api, on, diffText} from './store.js';

let seq = 0, shownFile = null, last = null, timer = null;

const f2 = v => (v == null ? '—' : (+v).toFixed(2));
const band = s => (!s || s.length !== 2 ? '' : s[0] <= 0 ? `★〜${+s[1]}` : s[1] >= 99 ? `★${+s[0]}〜` : `★${+s[0]}〜${+s[1]}`);   // library.js の書き方と同じ
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
// 版の上 2 つが本家の PP の版（4.1.0＝PPv4.1）。本家との差はスコアから譜面ごとに決まる Acc の倍率の分で、上下どちらにもずれる
const note = v => {
  const m = /^(\d+\.\d+)\./.exec(v || '');
  return `作った譜面の★（BeatLeader の★の近似${m ? `・PPv${m[1]}（nlm-rating ${v}）` : ''}。本家とは数 % ずれることがある）`;
};

function libStars() {   // 画面で変えた設定（別の担当が S.W.library に持つ）があればそれ、無ければサーバーが作業ファイルから読んだ物
  const s = S.W && S.W.library && S.W.library.stars;
  if (Array.isArray(s) && s.length === 2) return s;
  return last && last.library_stars || null;
}

function show(html, title, cls = '') {
  const el = $('starInfo'); if (!el) return;
  el.innerHTML = html; el.title = title; el.className = 'sub rating ' + cls;
}

function render() {
  const r = last;
  if (!r) return;
  if (r.state === 'unavailable') { show('★ —', '★を測れない: ' + r.error, 'na'); return; }
  if (!r.ok) { show('★ ?', '★を測れなかった: ' + (r.error || ''), 'bad'); return; }
  if (r.skipped || r.stars == null) { show('★ —', `★を測れない（${r.skipped || '答えが無い'}・ノーツ ${r.notes}。20 個より少ないと測れない）`, 'na'); return; }
  const der = r.view_diff && S.D && r.view_diff !== S.D.base ? r.view_diff : null;   // 派生の★
  const lib = der ? null : libStars();
  let cls = '', where = '';
  if (lib) {
    if (r.stars > lib[1]) { cls = 'over'; where = '\n選んだライブラリの帯より上'; }
    else if (r.stars < lib[0]) { cls = 'under'; where = '\n選んだライブラリの帯より下'; }
  }
  const title = `${note(r.version)}\n★ ${f2(r.stars)}・Pass ${f2(r.pass)}・Tech ${f2(r.tech)}・Acc ${f2(r.acc)}` +
    (r.predicted_acc != null ? `・予測精度 ${(r.predicted_acc * 100).toFixed(1)}%` : '') +
    `\nノーツ ${r.notes}` + (r.nps ? `・1秒 ${r.nps.toFixed(1)} ノーツ` : '') + `・NJS ${r.njs}` +
    (r.bombs ? `・ボム ${r.bombs}` : '') + (r.walls ? `・壁 ${r.walls}` : '') +
    (lib ? `\nライブラリ ${band(lib)}` + where : '') + `\n${r.diff}・${r.file}`;
  show(`<b>★ ${f2(r.stars)}</b>` + (der ? `<span class="lib">（${esc(diffText(der))}）</span>` : '') + (lib ? `<span class="lib">（ライブラリ ${esc(band(lib))}）</span>` : ''), title, cls);
}

async function refresh() {
  const file = S.file;
  if (!file) return;
  const my = ++seq, diff = S.view || '', req = file + '|' + diff;
  shownFile = file;
  const el = $('starInfo');
  if (el) { el.classList.add('busy'); if (!last || last.file_req !== req) show('★ 測っている…', '作った譜面の★を nlm-rating で測っている', 'busy'); }
  for (let i = 0; i < 40; i++) {
    let r;
    try { r = await api('GET', '/api/rating?wait=8&file=' + encodeURIComponent(file) + (diff ? '&diff=' + encodeURIComponent(diff) : '')); }
    catch (e) { if (my === seq) { last = null; show('★ ?', '★を測れなかった: ' + e.message, 'bad'); } return; }
    if (my !== seq) return;
    if (r.state === 'running') continue;
    last = {...r, file_req: req};
    render();
    return;
  }
  if (my === seq) show('★ ?', '★を測るのに時間がかかりすぎた', 'bad');
}

function later() { clearTimeout(timer); timer = setTimeout(refresh, 80); }   // 'chart' と 'generated' が続けて来ても 1 回だけ

export function init(app) {
  on('work', () => { if (S.file && S.file !== shownFile) { last = null; later(); } else render(); });
  on('chart', later);
  on('generated', later);
  on('library', later);   // ライブラリの設定を変えた（別の担当が出す時）→ 帯を読み直す（★は前の答えのまま）
  on('generating', v => { const el = $('starInfo'); if (el) el.classList.toggle('stale', !!v); });
}
