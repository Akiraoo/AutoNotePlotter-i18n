// 埋め込みのリプレイの窓の伝言の受け手（BL のリプレイアプリの中で動く・2026-11-15 利用者「プレイ履歴をアプリ内で表示して、全部の
// 再生位置を同期させて見たい」・docs/アプリ仕様.md 26 節）。
// アプリのサーバーは BL のリプレイアプリを別の番号（別のオリジン）で出し、その時だけ index.html の終わりにこの <script> を足す
// （app/server.py の ViewerH・写した物には手を入れない）。data-parent＝埋め込んでよいアプリの画面のオリジン（空白で区切る）。
// アプリの画面（static/js/replaypane.js）とは窓どうしの伝言（postMessage）だけでやり取りする（相手のオリジンを確かめる・送る先も決める）:
//   アプリ → ここ: {anp:'blr', cmd:'hello'}（つながったか）・{cmd:'seek', t}（曲の秒＝song.egg の秒）・{cmd:'play'}・{cmd:'pause'}
//   ここ → アプリ: {anp:'blr', ev:'hi'}・{ev:'ready', dur}（曲を読めた）・{ev:'time', t, playing, speed, at}（時刻か再生中かが変わるたび＝毎コマ・
//   at＝時刻を読んだ時の壁の時計（performance.timeOrigin＋now・ミリ秒）＝アプリが届くまでの遅れの分を先読みする）
// BL のリプレイアプリの中の部品（a-scene の song-controls・song）を使う: 時刻＝song.getCurrentTime()・動かす＝song-controls の seek
// （アプリの帯の上の時刻の棒と同じ）・再生中＝再生のボタン（#controlsPause）に play の印が無い・再生と停止＝そのボタンを押す（終わった後は頭から）。
// 開く位置（URL の time）の動かし直しを止める（2026-11-15 利用者「スローを有効化して再生したら画面がずれた」）: BL のリプレイアプリは time を
// 受けると、最初に音が鳴り始めた（songstartaudio）0.1 秒後に一度だけ song-controls の seek(time, false) でその位置へ戻す。埋め込みでは
// 開いた後にアプリの位置へ動かすので、最初の ▶ で開いた時の位置へ引き戻された（46 秒から ▶ → 0.3 秒へ飛んだ）。その 1 回だけを飛ばす
// （ノーツを作り直さない seek＝第 2 引数 false を呼ぶのは BL のリプレイアプリの中でここだけ・2026-11-12 に写した版で確かめた）。
(function () {
  'use strict';
  if (window.parent === window) return;   // 別のタブで開いた時は何もしない
  const me = document.currentScript;
  const ALLOW = String((me && me.dataset.parent) || '').split(/\s+/).filter(Boolean);
  const PT = (() => { const v = new URLSearchParams(location.search).get('time'); return v && isFinite(v) ? parseFloat(v) / 1e3 : null; })();
  let PO = null;          // つながったアプリの画面のオリジン（最初の正しい伝言で決める）
  let ready = false, lastT = null, lastP = null, lastSp = null, want = null;   // want＝読めるまで待たせた seek
  let skipPT = PT != null;   // 開く位置への動かし直し（1 回だけ）をまだ飛ばしていない
  const send = m => { if (PO) window.parent.postMessage(Object.assign({anp: 'blr'}, m), PO); };
  const scene = () => document.querySelector('a-scene');
  const ctl = () => { const s = scene(); return s && s.components ? s.components['song-controls'] : null; };
  const loaded = c => !!(c && c.song && c.song.source && c.song.getDuration() > 0);
  const btn = () => document.getElementById('controlsPause');
  const playing = () => { const b = btn(); return !!b && !b.classList.contains('play'); };
  const wall = () => performance.timeOrigin + performance.now();

  function guard(c) {   // song-controls の seek を包む（開く位置への動かし直しだけ飛ばす・ほかはそのまま）
    if (!c || c.__anpGuard) return;
    c.__anpGuard = true;
    const orig = c.seek;
    c.seek = function (t, clearBeats) {
      if (skipPT && clearBeats === false && Math.abs(t - PT) < 1e-6) { skipPT = false; return; }
      return orig.apply(this, arguments);
    };
  }
  function seek(t) {
    const c = ctl();
    if (!loaded(c)) { want = t; return; }
    want = null;
    const d = c.song.getDuration();
    c.seek(Math.max(0, Math.min(d - 0.01, t)));
  }
  function setPlay(on) {
    const b = btn();
    if (b && loaded(ctl()) && on !== playing()) b.click();
  }

  window.addEventListener('message', e => {
    if (e.source !== window.parent || !ALLOW.includes(e.origin)) return;
    const d = e.data;
    if (!d || d.anp !== 'blr') return;
    PO = e.origin;
    if (d.cmd === 'hello') { send({ev: 'hi'}); if (ready) send({ev: 'ready', dur: ctl().song.getDuration()}); lastT = null; return; }
    if (d.cmd === 'seek' && isFinite(d.t)) seek(+d.t);
    else if (d.cmd === 'play') setPlay(true);
    else if (d.cmd === 'pause') setPlay(false);
  });

  function tick() {
    const c = ctl();
    guard(c);
    if (PO && loaded(c)) {
      if (!ready) { ready = true; send({ev: 'ready', dur: c.song.getDuration()}); }
      if (want != null) seek(want);
      const t = c.song.getCurrentTime(), p = playing(), sp = c.song.speed;
      if (lastT == null || Math.abs(t - lastT) > 1e-4 || p !== lastP || sp !== lastSp) {
        send({ev: 'time', t, playing: p, speed: sp, at: wall()});
        lastT = t; lastP = p; lastSp = sp;
      }
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
