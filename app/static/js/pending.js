// 未反映の意思入れの知らせ（docs/アプリ仕様.md 16 節・利用者 2026-10-26: 付けた指示が譜面に入ったと思い込んで確かめないのを防ぐ）。
// 3D の窓の右上に小さな窓「まだ譜面に入っていない意思入れがあります」（何が・どこ・作り直す・あとで）。3D の窓の中だけ＝ほかの操作は
// そのまま続けられる。「あとで」＝小さな札にたたむ（未反映の間は消えない・押すと開く。全部入ったら、次はまた開いて出す）。上の「作り直す」にも印。
// 比べるのはサーバー（/api/versions/pending＝今の結果のファイルを作った時の作業ファイルと、次の作り直しと同じ決まりで比べる＝前の譜面に
// 寄せる時の「変わった所」と同じ）。聞くのは作業ファイルを保存した時（'saved'）・結果のファイルを読み直した時（'chart'）・曲を開いた時。
// 作り直しの間は隠す（作り直しの間に付けた指示は、終わった後にまた知らせる）。確かめは #ptest（--dump-dom の #pend）。
import {S, $, fmt, timeOf, api, on, emit} from './store.js';
import * as player from './player.js';
import {showRange} from './timeline.js';

const PD = {d: null, folded: false, busy: false, file: null, seq: 0, timer: 0, test: false};
let A = null;   // main.js から渡された口（generate を使う）

export function init(app) {
  A = app;
  // 3D の中の右上の列（preview.js の #pvSide＝★と結果のファイル名の下・左の見え方の設定とは横に並ぶ＝重ならない・2026-11-09）
  const box = document.createElement('div'); box.id = 'pend'; ($('pvSide') || $('pvWrap')).appendChild(box);
  box.addEventListener('click', onClick);
  on('saved', () => ask(150));
  on('chart', proj => { if (!proj) ask(0); });   // proj あり＝別の案・履歴の版を見ているだけ（結果のファイルは同じ）
  on('work', () => { if (S.file !== PD.file) { PD.file = S.file; PD.d = null; PD.folded = false; render(); ask(0); } });
  on('generating', v => { PD.busy = v; render(); if (!v) ask(0); });
  on('freshNext', render);   // 指示の読み込み・全部外すの後は「全部作り直す」がおすすめ
}
function ask(ms) { clearTimeout(PD.timer); PD.timer = setTimeout(fetchNow, ms); }
async function fetchNow() {
  if (!S.file || PD.test) return;
  const n = ++PD.seq, file = S.file;
  let d = null;
  try { d = await api('GET', '/api/versions/pending?file=' + encodeURIComponent(file)); } catch (e) { d = null; }
  if (n !== PD.seq || file !== S.file) return;
  if (!d || !open(d)) PD.folded = false;
  PD.d = d; render();
  // 量のラインの帯の網掛け（作り直した時の量のラインと違う小節＝未反映）: 前の版が分かる時だけ
  S.pendLine = d && d.state !== 'nofile' && d.state !== 'unknown' ? (d.line_was || null) : null; emit('pending');
}
const open = d => d.state === 'some' || d.state === 'nofile';
const span = s => `${fmt(timeOf(s[0]))}〜${fmt(timeOf(s[1]))}`;

function render() {
  const box = $('pend'), d = PD.d, on_ = !!d && open(d);
  $('gen').classList.toggle('pending', on_);
  $('gen').title = $('gen').title.replace(/^（まだ譜面に入っていない意思入れがある）/, '');
  if (on_) $('gen').title = '（まだ譜面に入っていない意思入れがある）' + $('gen').title;
  if (!d || PD.busy || !S.D || (!on_ && d.state !== 'unknown')) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  if (d.state === 'unknown') {   // 前の作り直しが分からない（履歴が無い等）＝比べられない。小さく出すだけ
    box.innerHTML = `<span class="pendTag dim" title="${d.why || ''}（作り直すと分かるようになる）">反映の具合が分からない</span>`;
    return;
  }
  if (PD.folded) {
    box.innerHTML = `<button class="pendTag" data-act="open" title="押すと開く">⚠ まだ入っていない意思入れ</button>`;
    return;
  }
  const fresh = !!S.freshNext;
  let h = '<div class="pendBox">';
  if (d.state === 'nofile') {
    h += '<div class="pendHead">⚠ この曲はまだ作り直していない</div><div class="pendWhat">結果のファイルが無い（作り直すと作る）</div>';
  } else {
    const sp = d.spans || [], more = sp.length - 4;
    h += '<div class="pendHead">⚠ まだ譜面に入っていない意思入れがあります</div>'
      + [...(d.items || []), ...(d.settings || []).map(x => x + 'の設定')].map(x => `<div class="pendWhat">・${x}</div>`).join('')
      + (sp.length ? `<div class="pendWhere">場所 ${sp.slice(0, 4).map((s, i) => `<a data-i="${i}" title="帯をこの場所に">${span(s)}</a>`).join(' ')}`
                     + (more > 0 ? ` ほか ${more}` : '') + '</div>' : '')
      + ((d.settings || []).length ? `<div class="pendNote">曲の全体の設定を変えた＝作り直すと曲の全部が変わる（前の譜面に寄せない）</div>` : '');
  }
  if (fresh) h += '<div class="pendNote">指示を読み込んだ・全部外した後＝作り直す時は「全部作り直す」がおすすめ</div>';
  h += '<div class="pendBtns"><button class="main" data-act="gen" title="上の「作り直す」と同じ（「変えた所だけ」か「全部」かを聞く）">作り直す</button>'
     + '<button data-act="fold" title="小さな札にたたむ（まだ入っていない間は消えない）">あとで</button></div></div>';
  box.innerHTML = h;
}
function onClick(e) {
  const a = e.target.closest('[data-act], a[data-i]'); if (!a) return;
  if (a.dataset.i != null) { const s = PD.d.spans[+a.dataset.i]; showRange(timeOf(s[0]) - 2, timeOf(s[1]) + 2); player.seek(timeOf(s[0])); return; }
  const act = a.dataset.act;
  if (act === 'gen') { PD.folded = false; A.generate(); return; }
  PD.folded = act === 'fold'; render();
}
// 確かめ用（#ptest）: サーバーの答えを使わずに、決まった中身で出す（#ptest=fold でたたんだ札・=nofile）
export function selfTest(kind) {
  clearTimeout(PD.timer); PD.test = true;
  const B = S.D.mus.beats;
  PD.d = kind === 'nofile' ? {state: 'nofile'} : {state: 'some', spans: [[B[8], B[12]], [B[20], B[22]]], settings: kind === 'lib' ? ['ライブラリ'] : [],
    items: ['区間の指示（足した 1・変えた 2・消した 1）', '同じ振り「バーン」（全部の回が変わる）', '量のライン']};
  PD.folded = kind === 'fold'; PD.busy = false; render();
}
