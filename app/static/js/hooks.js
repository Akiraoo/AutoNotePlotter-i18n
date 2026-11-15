// 盛り上がりの繰り返しの候補（automap/hooks.py・docs/アプリ仕様.md 18 節）: 右の欄のカード。inspector.js の build() が置く。
// 曲のデータの hooks（サーバーが曲を開く時に探した組）を並べ、組ごとに回を選び（チェック）・範囲を直し（全部の回の頭 ±1 拍・長さ ±1 拍）・
// 名前とそのまま／アレンジを決めて「同じ振りにする」でまとめて付ける（1回の commit＝Ctrl+Z で戻る）。間違っていてよい・多めに拾う
// （利用者 2026-11-02「多めに拾って人間が後で消していく」）。初めの譜面づくりには入れない（押した時だけ）。
// 組に乗る・「帯で見る」で回を帯に枠で出す（S.cand に hook の印を付けて入れる＝inspector の「似た所」の一覧には出さない）。
// 確かめ用の入口: #hktest（&song=曲名）→ 候補を出して1つ目の組の様子を document.title に（作業ファイルには保存しない）。
import {S, $, fmt, timeOf, commit, newId, emit, on} from './store.js';
import {playRange} from './player.js';
import {draw, showRange} from './timeline.js';

let H = {D: null, groups: null};   // groups＝画面の候補（null＝まだ出していない）
let A = {};                         // inspector.js から渡す口（playSeq）
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

function css() {
  if (document.getElementById('hooksCss')) return;
  const l = document.createElement('link'); l.id = 'hooksCss'; l.rel = 'stylesheet'; l.href = '/static/hooks.css'; document.head.appendChild(l);
}
export function build(box, app) {
  A = app || {}; css();
  const sec = document.createElement('section');
  sec.className = 'card hooks'; sec.id = 'hkCard';
  sec.innerHTML = `<div class="cardHead">盛り上がりの繰り返し <span class="sub">自動で探した「同じ振り」の候補</span></div>
 <div class="bar"><button id="hkFind" title="歌のくり返しのうち、曲の中で何回も出る盛り上がる所を探して組にする（曲を開いた時に探してある）">候補を出す</button>
  <button id="hkClose">閉じる</button><span class="sub" id="hkNote"></span></div>
 <div class="hint">多めに拾う（間違っていてよい）。組ごとに要らない回のチェックを外し、範囲を直して（頭・長さは全部の回まとめて）「同じ振りにする」。付けた後も一覧から回ごとに消せる。</div>
 <div id="hkList"></div>`;
  const first = box.querySelector('section.card');
  if (first) first.after(sec); else box.appendChild(sec);
  $('hkFind').onclick = open;
  $('hkClose').onclick = () => { H.groups = null; unmark(); render(); };
  on('work', () => { if (H.D !== S.D) { H.D = S.D; H.groups = null; render(); } });
  on('work', () => { if (location.hash.startsWith('#hktest') && S.D && !HT.started) { HT.started = true; setTimeout(hktest, 1200); } });
}

// ---- 候補 ----
const motifRanges = () => S.W.ranges.filter(r => r.set.motif && !r.set.rest);
const overlaps = (a0, a1, b0, b1) => Math.min(a1, b1) - Math.max(a0, b0) > 1e-6;
function sectionAt(b) {   // 区間の名前（マーカー。書き込みだけのマーカーは飛ばす）
  const ms = (S.D.marks || []).filter(m => m.name && m.beat <= b + 1e-6);
  return ms.length ? ms[ms.length - 1].name : '';
}
function freeName(i, used) { let k = i + 1, n; do { n = '繰り返し' + k++; } while (used.has(n)); used.add(n); return n; }
function open() {
  const hs = S.D && S.D.hooks;
  if (!hs) { $('hkNote').textContent = '曲のデータに候補が無い（アプリを起動し直すと出る）'; return; }
  const used = new Set(motifRanges().map(r => r.set.motif.group)), taken = motifRanges();
  H.groups = hs.map((g, i) => {
    const occ = g.occ.map(o => { const t = taken.some(r => overlaps(o.b0, o.b1, r.b0, r.b1));
      return {b0: o.b0, b1: o.b1, s: o.s, k: o.k, weak: o.weak, taken: t, on: !t}; });
    return {i, L: g.L, score: g.score, why: g.why, name: '', mode: occ.filter(o => o.on).length >= 4 ? 'arrange' : 'same', d0: 0, dl: 0, occ};
  }).filter(g => g.occ.filter(o => !o.taken).length >= 2);   // もう同じ振りが付いている所だけの組は出さない
  H.groups.forEach((g, i) => { g.name = freeName(i, used); });
  $('hkNote').textContent = H.groups.length ? `${H.groups.length} 組` : (hs.length ? '候補はもう同じ振りが付いている所だけ' : '候補が見つからなかった');
  render();
}
const spanOf = (g, o) => [o.b0 + g.d0, Math.max(o.b0 + g.d0 + 1, o.b1 + g.d0 + g.dl)];   // 範囲を直した後の回
const picked = g => g.occ.filter(o => o.on).map(o => spanOf(g, o));
function clash(g) {   // 直した範囲で回どうしが重なる（長くしすぎ）
  const xs = g.occ.map(o => spanOf(g, o)).sort((a, b) => a[0] - b[0]);
  return xs.some((x, i) => i && x[0] < xs[i - 1][1] - 1e-6);
}
function mark(g) { S.cand = g ? g.occ.map(o => { const [b0, b1] = spanOf(g, o); return {b0, b1, on: o.on, hook: true}; }) : []; draw(); emit('select'); }
function unmark() { if (S.cand.some(c => c.hook)) { S.cand = []; draw(); } }
const kText = k => k ? `・半音${k > 0 ? '上' : '下'}${Math.abs(k) > 1 ? Math.abs(k) : ''}` : '';

function render() {
  const box = $('hkList'); if (!box) return;
  if (!H.groups) { box.innerHTML = ''; return; }
  box.innerHTML = H.groups.map((g, gi) => {
    const n = g.occ.filter(o => o.on).length, len = spanOf(g, g.occ[0])[1] - spanOf(g, g.occ[0])[0], bad = clash(g);
    return `<div class="hkG" data-g="${gi}">
  <div class="hkHead"><b>候補 ${gi + 1}</b>・${len} 拍 × ${g.occ.length} 回<span class="sub" title="${esc(g.why)}">点 ${g.score.toFixed(2)}</span></div>
  <div class="hkRow"><input class="hkName" data-name="${gi}" value="${esc(g.name)}" spellcheck="false" title="同じ振りのグループの名前">
   <button data-mode="same" class="${g.mode === 'same' ? 'on' : ''}" title="全部の回を同じ並び・置き方に">そのまま</button><button data-mode="arrange" class="${g.mode === 'arrange' ? 'on' : ''}" title="1回目・3回目…が手本の形、2回目・4回目…がアレンジの形">アレンジ</button></div>
  <div class="hkRow"><span class="sub">範囲（全部の回）</span><button data-mv="-1" title="全部の回の頭を1拍前へ">頭 ←</button><button data-mv="1" title="全部の回の頭を1拍後ろへ">頭 →</button>
   <button data-ln="-1" title="全部の回を1拍短く">短く</button><button data-ln="1" title="全部の回を1拍長く">長く</button>
   <span class="sub">${g.d0 || g.dl ? `頭 ${g.d0 > 0 ? '+' : ''}${g.d0}・長さ ${len} 拍` : ''}</span>${bad ? '<span class="bad">回どうしが重なる</span>' : ''}</div>
  <div class="hkOcc">${g.occ.map((o, oi) => { const [b0, b1] = spanOf(g, o);
      return `<div class="hkO${o.weak ? ' weak' : ''}${o.taken ? ' taken' : ''}"><label><input type="checkbox" data-o="${oi}" ${o.on ? 'checked' : ''} ${o.taken ? 'disabled' : ''}>
       ${fmt(timeOf(b0))}<span class="sub">（拍 ${+b0.toFixed(2)}・${esc(sectionAt(b0))}）</span></label>
       <span class="sub" title="${o.k ? `比べた元の回から${kText(o.k).slice(1)}にずらして比べた（転調した所）` : ''}">${o.taken ? 'もう同じ振りがある' : o.s >= 0.999 ? '比べた元' : `近さ ${o.s.toFixed(2)}${o.weak ? '・弱い' : ''}`}</span><button data-p="${oi}" title="ここだけ再生">▶</button></div>`; }).join('')}</div>
  <div class="bar"><button data-all title="チェックした回を続けて鳴らす（回ごとに少し前から）">▶ 続けて</button><button data-show title="帯に回を枠で出して、全部の回が見える所まで広げる">帯で見る</button>
   <button data-adopt class="main" ${!n || bad ? 'disabled' : ''}>同じ振りにする（${n} 回）</button><button data-drop title="この組を候補から外す">外す</button></div></div>`;
  }).join('') || '';
  box.querySelectorAll('.hkG').forEach(el => {
    const g = H.groups[+el.dataset.g];
    el.onmouseenter = () => mark(g);
    el.onmouseleave = () => { if (!el.dataset.pin) unmark(); };
    el.querySelector('.hkName').oninput = e => { g.name = e.target.value; };
    el.querySelectorAll('button[data-mode]').forEach(b => b.onclick = () => { g.mode = b.dataset.mode; render(); });
    el.querySelectorAll('button[data-mv]').forEach(b => b.onclick = () => { g.d0 += +b.dataset.mv; render(); mark(g); });
    el.querySelectorAll('button[data-ln]').forEach(b => b.onclick = () => { const L = spanOf(g, g.occ[0])[1] - spanOf(g, g.occ[0])[0];
      if (+b.dataset.ln < 0 && L <= 1) return; g.dl += +b.dataset.ln; render(); mark(g); });
    el.querySelectorAll('input[data-o]').forEach(x => x.onchange = () => { g.occ[+x.dataset.o].on = x.checked; render(); mark(g); });
    el.querySelectorAll('button[data-p]').forEach(b => b.onclick = () => { const [b0, b1] = spanOf(g, g.occ[+b.dataset.p]); playRange(timeOf(b0) - 0.5, timeOf(b1)); });
    el.querySelector('button[data-all]').onclick = () => { const xs = picked(g); if (xs.length && A.playSeq) A.playSeq(xs); };
    el.querySelector('button[data-show]').onclick = () => { const xs = g.occ.map(o => spanOf(g, o));
      el.dataset.pin = '1'; mark(g); showRange(timeOf(xs[0][0]) - 3, timeOf(xs[xs.length - 1][1]) + 3); };
    el.querySelector('button[data-adopt]').onclick = () => adopt(g);
    el.querySelector('button[data-drop]').onclick = () => { H.groups = H.groups.filter(q => q !== g); unmark(); render(); };
  });
}

function adopt(g) {
  const name = (g.name || '').trim(), xs = picked(g);
  if (!name) { $('hkNote').textContent = 'グループの名前を入れる'; return; }
  if (motifRanges().some(r => r.set.motif.group === name)) { $('hkNote').textContent = `「${name}」はもうある（別の名前にする）`; return; }
  if (!xs.length || clash(g)) return;
  const motif = {group: name, mode: g.mode};
  commit(W => xs.forEach(([b0, b1]) => W.ranges.push({id: newId(), b0, b1, set: {motif: Object.assign({}, motif)}})));
  H.groups = H.groups.filter(q => q !== g); unmark(); render();
  $('hkNote').textContent = '';
  emit('status', `同じ振り「${name}」（${g.mode === 'arrange' ? 'アレンジ' : 'そのまま'}）を ${xs.length} か所に付けた（Ctrl+Z で戻る・次の作り直しで効く）`);
}

// ---- 確かめ用（見えない Edge）: #hktest（&song=曲名）・=adopt で1つ目の組を付ける（S.readonly＝作業ファイルには保存しない） ----
const HT = {started: false};
function hktest() {
  const h = decodeURIComponent(location.hash), sm = h.match(/&song=([^&]+)/);
  if (sm && S.song !== sm[1] && S.songs.some(q => q.song === sm[1])) { HT.started = false; $('song').value = sm[1]; $('song').dispatchEvent(new Event('change')); return; }
  S.readonly = true;
  open();
  const g = H.groups && H.groups[0], out = {song: S.song, groups: H.groups ? H.groups.length : null,
    first: g ? {L: g.L, n: g.occ.length, at: g.occ.map(o => o.b0), mode: g.mode, name: g.name} : null};
  if (g) {
    const el = document.querySelector('.hkG');
    el.querySelector('button[data-show]').click();
    if (/=adopt/.test(h)) { const n0 = S.W.ranges.length; adopt(g); out.added = S.W.ranges.length - n0; }
  }
  document.title = 'hktest ' + JSON.stringify(out);
  const card = $('hkCard'); if (card) card.scrollIntoView();
}
