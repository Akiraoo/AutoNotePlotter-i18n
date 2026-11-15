// 分けた音（歌・ドラム・ベース・その他）を4つ同時に鳴らす。<audio> を4つ並べ、1つ目を時刻の基準にしてずれを直し続ける。
// 埋め込みのリプレイとつないでいる間（P.link・js/replaypane.js・2026-11-15）は、時刻の元はリプレイ: 自分の音は鳴らさず、リプレイの時刻に
// 合わせて S.t を動かす（follow）。再生・停止・位置を変える（seek・帯・キー・区間の再生）はリプレイへ送る（P.link.play／pause／seek）。
import {S, emit} from './store.js';

export const STEM = [{k: 'vocals', n: '歌', c: '--voc'}, {k: 'drums', n: 'ドラム', c: '--drm'}, {k: 'bass', n: 'ベース', c: '--bas'}, {k: 'other', n: 'その他', c: '--oth'}];
// link＝つないだリプレイ（{play(), pause(), seek(t)}・t＝この画面の時刻）・remote＝リプレイが再生中か（上の ▶ の形）
export const P = {au: [], on: [true, true, true, true], playing: false, stopAt: null, vol: 1, link: null, remote: false};
let raf = 0;

export function load(D) {
  P.au.forEach(a => { a.pause(); a.src = ''; });
  P.au = STEM.map(s => { const a = new Audio(window.anpUrl(D.src[s.k])); a.preload = 'auto'; return a; });   // ?k=＝合言葉（js/key.js）
  P.au[0].addEventListener('ended', ended);
  P.au[0].addEventListener('loadedmetadata', () => emit('frame'));
  P.playing = false; P.link = null; P.remote = false; P.stopAt = null; applyOn();
  emit('song');   // 曲を開いた（つないだリプレイは前の曲の物＝js/replaypane.js が外す）
}
export function now() { return P.link ? S.t : P.au[0] ? P.au[0].currentTime : 0; }
export function applyOn() { P.au.forEach((a, i) => { a.muted = !P.on[i]; a.volume = P.vol; }); emit('player'); }
export function setVolume(v) { P.vol = Math.max(0, Math.min(1, v)); applyOn(); }
export const busyPlaying = () => P.playing || (!!P.link && P.remote);   // 鳴っているか（自分の音かつないだリプレイ）
export async function play() {
  if (P.link) { P.link.play(); return; }
  if (!P.au.length) return;
  const t = now(); P.au.forEach(a => { a.currentTime = t; });
  await Promise.all(P.au.map(a => a.play().catch(() => {})));
  P.playing = true; emit('player'); loop();
}
// 曲の終わりまで鳴らしたら頭に戻って続ける（停止するまでくり返す・2026-11-02 利用者）。区間の再生（playRange）は区間の終わりで止める
function ended() {
  if (!P.playing || P.stopAt != null) { pause(); return; }
  seek(0); play();
}
export function pause() {
  if (P.link) P.link.pause();
  P.au.forEach(a => a.pause()); P.playing = false; P.stopAt = null; emit('player'); emit('frame');
}
export function toggle() { busyPlaying() ? pause() : play(); }
export function seek(t) {
  if (!S.D) return;
  t = Math.max(0, Math.min(S.D.dur - 0.05, t));
  if (P.link) P.link.seek(t); else P.au.forEach(a => { a.currentTime = t; });
  S.t = t; emit('frame');
}
export function playRange(t0, t1) { seek(Math.max(0, t0 - 0.3)); P.stopAt = t1 + 0.2; if (!busyPlaying()) play(); }
// つなぐ・外す（js/replaypane.js）。つなぐ時は自分の音を止める。外す時は今の位置から自分の音で続けられるようにする（再生はしない）
export function setLink(L) {
  if (L) { P.au.forEach(a => a.pause()); P.playing = false; cancelAnimationFrame(raf); }
  P.link = L || null; P.remote = false;
  if (!L) { P.stopAt = null; P.au.forEach(a => { a.currentTime = S.t; }); }
  emit('player'); emit('frame');
}
// リプレイの時刻に合わせる（t＝この画面の時刻・playing＝リプレイが再生中か）。区間の再生の終わり（stopAt）でリプレイを止める
export function follow(t, playing) {
  if (!S.D || !P.link) return;
  S.t = Math.max(0, Math.min(S.D.dur - 0.05, t));
  if (P.stopAt != null && playing && S.t >= P.stopAt) { P.stopAt = null; P.link.pause(); }
  if (!playing && P.remote) P.stopAt = null;   // リプレイの側で止めた
  if (P.remote !== !!playing) { P.remote = !!playing; emit('player'); }
  emit('frame');
}
function loop() {
  cancelAnimationFrame(raf);
  const step = () => {
    S.t = now();
    if (P.stopAt != null && S.t >= P.stopAt) { pause(); return; }
    emit('frame');
    if (P.playing) raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
}
setInterval(() => {   // 4つの音のずれを直す
  if (!P.playing) return;
  const t = now();
  for (let i = 1; i < P.au.length; i++) if (Math.abs(P.au[i].currentTime - t) > 0.04) P.au[i].currentTime = t;
}, 300);
