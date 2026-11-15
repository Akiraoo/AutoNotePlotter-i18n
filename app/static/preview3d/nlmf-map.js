// .nlmf（NLM の保存形式 version 2）→ preview3d の譜面（絶対拍）。NLM の editor-app.js の _ENC・decArr・flatFromSections と同じ読み方:
// 物はタプル（項目の並びは _ENC）、正はクリップの中身（拍はクリップの頭から・見えるのは 0 以上 len 未満）。テンポは一定だけ扱う。
const ENC = {
  notes: ['beat', 'x', 'y', 'c', 'd'],
  bombs: ['beat', 'x', 'y'],
  walls: ['beat', 'x', 'y', 'dur', 'w', 'h'],
  arcs: ['b', 'c', 'x', 'y', 'd', 'mu', 'tb', 'tx', 'ty', 'tc', 'tmu', 'm'],
  chains: ['b', 'c', 'x', 'y', 'd', 'tb', 'tx', 'ty', 'sc', 's'],
  lights: ['beat', 'et', 'i', 'f'],
};
const DEF_NJS = {Easy: 10, Normal: 10, Hard: 10, Expert: 12, ExpertPlus: 16};

function dec(arr, key) {
  const f = ENC[key];
  return (arr || []).map(o => {
    if (!Array.isArray(o)) return {...o};   // v1（オブジェクト形式）
    const it = {};
    f.forEach((k, i) => { if (o[i] != null) it[k] = o[i]; });
    if (o[f.length] != null) it._tr = o[f.length];
    it.raw = o[f.length + 1] || null;   // 標準外の項目（v3 の角度 a 等）
    if (key === 'notes' && it.raw && it.raw.a != null) it.a = it.raw.a;
    return it;
  });
}

// 難易度のキー（'expertplusstandard.dat' 等）。無ければ今開いている難易度 → ノーツのある Expert+ → 最初の物
export function diffKeys(proj) { return Object.keys(proj.difficulties || {}); }
function pickDiff(proj, want) {
  const ds = proj.difficulties || {};
  const lc = k => (k || '').toLowerCase();
  if (want && ds[lc(want)]) return lc(want);
  if (ds[lc(proj.current)]) return lc(proj.current);
  return Object.keys(ds).find(k => k.startsWith('expertplus') && (ds[k].sections || []).length) || Object.keys(ds)[0];
}

// opts: {diff: 難易度キーか名前, muted: 'hide'|'show'（ミュートしたレーンを隠すか・既定 hide＝NLM の 3D と同じ）}
export function nlmfToMap(proj, opts = {}) {
  if ((proj.tempoParts || []).length) console.warn('nlmf-map: テンポパートは扱わない（最初の BPM で通す）');
  const key = pickDiff(proj, opts.diff);
  const st = (proj.difficulties || {})[key] || {};
  const mute = new Set(opts.muted === 'show' ? [] : ((proj.laneStates || {}).mute || []));
  const out = {notes: [], bombs: [], walls: [], arcs: [], chains: [], lights: []};
  for (const s of st.sections || []) {
    if (s.kind === 'null') continue;
    if (mute.has((s.lk || 'n') + (s.track || 0))) continue;
    const c = s.content || {}, L = s.len || 4, off = s.beat || 0;
    for (const k of Object.keys(ENC)) {
      for (const it of dec(c[k], k)) {
        const b = it.beat ?? it.b ?? 0;
        if (!(b >= 0 && b < L)) continue;   // 負の拍・はみ出し＝トリムで隠れた分
        if (k === 'arcs' || k === 'chains') { it.b += off; it.tb = (it.tb ?? 0) + off; } else it.beat += off;
        out[k].push(it);
      }
    }
  }
  if (!(st.sections || []).length) {   // クリップが無い古い形: フラットの配列を使う
    for (const [k, fk] of [['notes', 'notes'], ['bombs', 'bombs'], ['walls', 'walls'], ['arcs', 'arcs'], ['chains', 'chains'], ['lights', 'lightEvents']])
      out[k] = dec(st[fk], k);
  }
  out.lights.sort((a, b) => a.beat - b.beat);
  const name = (st.name || key || '').replace(/Standard\.dat$/i, '').replace(/\.dat$/i, '');
  const nc = (proj.njsCfg || {})[key] || {};
  const info = proj.info || {};
  return {
    ...out, diff: key, bpm: proj.bpm || 120,
    njs: nc.njs != null ? nc.njs : (DEF_NJS[name] || 16), njsOffset: nc.offset != null ? nc.offset : 0,
    colors: {noteRed: proj.noteRed, noteBlue: proj.noteBlue, laserRed: proj.laserRed, laserBlue: proj.laserBlue},
    env: info._environmentName || 'DefaultEnvironment',
    lead: -(((proj.graph || {}).song || {}).offset || 0),   // 無音追加（秒）。元の音源の秒＝拍の時刻−無音追加
  };
}
