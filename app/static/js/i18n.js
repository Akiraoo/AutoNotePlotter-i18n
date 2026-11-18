// UI language (日本語 / 简体中文 / 繁體中文 / English).
// A plain <script> loaded right after key.js (before any module), so it is in place before the UI is built.
// The app's own code keeps its Japanese strings; this file translates what reaches the screen:
//   - text nodes and the title / placeholder / aria-label / alt attributes (MutationObserver)
//   - text drawn on <canvas> (fillText / strokeText / measureText)
//   - alert / confirm / prompt
// Dictionaries are app/static/i18n/<lang>.json, built by tools/i18n/build.py from tools/i18n/messages.json.
// Lookup: exact match → template with {0}… placeholders → line by line → known fragments inside the text.
// Elements with translate="no" (and their children), inputs/textareas and scripts are left alone.
// The language is kept in the app settings (ui_prefs 'automap-lang', like store.js lsSet) and in localStorage.
(function () {
  var KEY = 'automap-lang';
  var LANGS = [['ja', '日本語'], ['zh-Hans', '简体中文'], ['zh-Hant', '繁體中文'], ['en', 'English']];
  var known = function (l) { return LANGS.some(function (x) { return x[0] === l; }); };

  function prefLang() {
    try {
      var x = new XMLHttpRequest();
      x.open('GET', '/api/prefs', false);
      x.setRequestHeader('X-Automap', '1');
      x.send();
      if (x.status === 200) { var v = JSON.parse(x.responseText)[KEY]; if (known(v)) return v; }
    } catch (_) {}
    return null;
  }
  function localLang() { try { var v = JSON.parse(localStorage.getItem(KEY)); return known(v) ? v : null; } catch (_) { return null; } }
  function browserLang() {
    var ls = navigator.languages || [navigator.language || ''];
    for (var i = 0; i < ls.length; i++) {
      var l = String(ls[i]).toLowerCase();
      if (/^zh-(tw|hk|mo)|^zh-hant/.test(l)) return 'zh-Hant';
      if (/^zh/.test(l)) return 'zh-Hans';
      if (/^ja/.test(l)) return 'ja';
      if (/^en/.test(l)) return 'en';
    }
    return 'zh-Hans';
  }

  var lang = prefLang() || localLang() || browserLang();
  var I = window.anpI18n = {
    lang: lang, langs: LANGS,
    t: function (s) { return s; },
    set: function (l) {
      if (!known(l)) return;
      try { localStorage.setItem(KEY, JSON.stringify(l)); } catch (_) {}
      var b = {}; b[KEY] = l;
      fetch('/api/prefs', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Automap': '1'}, body: JSON.stringify(b)})
        .catch(function () {}).then(function () { location.reload(); });
    },
  };
  document.documentElement.lang = lang === 'ja' ? 'ja' : lang === 'en' ? 'en' : lang === 'zh-Hant' ? 'zh-Hant' : 'zh-Hans';

  // Language picker in the footer (next to the UI size)
  function picker() {
    var foot = document.getElementById('foot');
    if (!foot || document.getElementById('langSel')) return;
    var lab = document.createElement('label');
    lab.className = 'sub'; lab.setAttribute('translate', 'no'); lab.title = 'Language / 语言 / 語言 / 言語';
    lab.appendChild(document.createTextNode('🌐 '));
    var sel = document.createElement('select');
    sel.id = 'langSel';
    LANGS.forEach(function (x) { var o = document.createElement('option'); o.value = x[0]; o.textContent = x[1]; sel.appendChild(o); });
    sel.value = lang;
    sel.onchange = function () { I.set(sel.value); };
    lab.appendChild(sel);
    var size = document.getElementById('uiSize');
    var at = size && size.closest('label');
    foot.insertBefore(lab, at && at.parentNode === foot ? at : foot.firstChild ? foot.firstChild.nextSibling : null);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', picker); else picker();

  if (lang === 'ja') return;

  var M = {};
  try {
    var x = new XMLHttpRequest();
    x.open('GET', '/static/i18n/' + lang + '.json', false);
    x.send();
    if (x.status === 200) M = JSON.parse(x.responseText).m || {};
  } catch (_) {}

  var JP = /[、-。぀-ヿ㐀-鿿！-～]/;
  var KANA = /[぀-ヿ]/;
  var esc = function (s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); };
  var exact = Object.create(null), squash = Object.create(null), tpls = [], frags = [], WS = /\s+/g;
  var NONWORD = /[^぀-ゟァ-ヺー-ヿ㐀-鿿]/g;   // keep kana and kanji only
  Object.keys(M).forEach(function (k) {
    var v = M[k];
    if (/\{\d+\}/.test(k)) {
      var parts = k.split(/(\{\d+\})/), src = '^', order = [], lit = '';
      parts.forEach(function (p) {
        var m = /^\{(\d+)\}$/.exec(p);
        if (m) { src += '([\\s\\S]*?)'; order.push(+m[1]); } else { src += esc(p); if (p.length > lit.length) lit = p; }
      });
      // a template must have real words of its own (not just "{0}・{1}"), or it would swallow any text
      var words = parts.filter(function (p) { return !/^\{\d+\}$/.test(p); }).join('').replace(NONWORD, '');
      if (words.length) tpls.push({re: new RegExp(src + '$'), v: v, order: order, lit: lit.trim(), n: k.length});
    } else {
      exact[k] = v;
      squash[k.replace(WS, '')] = v;
      var t = k.trim();
      if (t !== k && !(t in exact)) exact[t] = v.trim();
      if (t.length >= 2 && (KANA.test(t) || t.length >= 3)) frags.push(t);
    }
  });
  tpls.sort(function (a, b) { return b.n - a.n; });
  frags.sort(function (a, b) { return b.length - a.length; });
  var FRAG = frags.length ? new RegExp(frags.map(esc).join('|'), 'g') : null;
  var fragVal = function (m) { var v = exact[m]; return v == null ? m : v.trim(); };

  var cache = new Map();
  function strict(s, depth) {   // exact or template only (used for template captures, so names in them stay as they are)
    if (s in exact) return exact[s];
    var q = squash[s.replace(WS, '')];   // the same text with other spaces / line breaks (text folded in HTML)
    if (q != null) return q;
    if (depth > 3) return null;
    for (var i = 0; i < tpls.length; i++) {
      var t = tpls[i];
      if (t.lit && s.indexOf(t.lit) < 0) continue;
      var m = t.re.exec(s);
      if (!m) continue;
      var caps = {};
      t.order.forEach(function (n, j) { var c = m[j + 1]; caps[n] = JP.test(c) ? (depth < 3 ? capture(c, depth + 1) : c) : c; });
      return t.v.replace(/\{(\d+)\}/g, function (_, n) { return caps[n] != null ? caps[n] : ''; });
    }
    return null;
  }
  function capture(c, depth) {   // a value put into a template: a known string, or known fragments inside it
    var r = strict(c, depth);
    return r != null ? r : FRAG ? c.replace(FRAG, fragVal) : c;
  }
  function core(s) {
    var r = strict(s, 0);
    if (r != null) return r;
    if (s.indexOf('\n') >= 0) return s.split('\n').map(tr).join('\n');
    return FRAG ? s.replace(FRAG, fragVal) : s;
  }
  // English: Japanese punctuation left around translated parts (lists joined with ・, （…） around values) → ASCII.
  // Only where no Japanese remains next to it, so untranslated text keeps its own punctuation.
  var EN = lang === 'en', PUN = {'（': ' (', '）': ')', '・': ' · ', '：': ': ', '「': '"', '」': '"', '＝': ' = ', '、': ', ', '／': ' / '};
  var LETTER = /[぀-ヺー-ヿ㐀-鿿]/;
  function enPunct(r) {
    return r.replace(/[（）・：「」＝、／]/g, function (c, i) {
      return LETTER.test(r.charAt(i - 1) || '') || LETTER.test(r.charAt(i + 1) || '') ? c : PUN[c];
    }).replace(/ {2,}/g, ' ').replace(/\( /g, '(').replace(/ \)/g, ')').replace(/^ /, '');
  }
  function tr(s) {
    if (typeof s !== 'string' || !JP.test(s)) return s;
    var c = cache.get(s);
    if (c !== undefined) return c;
    var m = /^(\s*)([\s\S]*?)(\s*)$/.exec(s);
    var r = s;
    if (m[2]) { var c2 = core(m[2]); r = m[1] + (EN && c2 !== m[2] ? enPunct(c2) : c2) + m[3]; }
    if (cache.size > 20000) cache.clear();
    cache.set(s, r);
    return r;
  }
  I.t = tr;

  // DOM
  var SKIP = {SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1, NOSCRIPT: 1, CODE: 1, PRE: 0};
  var ATTRS = ['title', 'placeholder', 'aria-label', 'alt'];
  var doneText = new WeakMap(), doneAttr = new WeakMap();
  function blocked(el, self) {   // self: the element's own tag may be INPUT/TEXTAREA (its attributes are still translated)
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (SKIP[e.tagName] && !(self && e === el)) return true;
      if (e.getAttribute('translate') === 'no' || e.isContentEditable) return true;
    }
    return false;
  }
  function textNode(n) {
    var d = n.data;
    if (!JP.test(d) || doneText.get(n) === d) return;
    if (blocked(n.parentElement)) return;
    var r = tr(d);
    if (EN) r = enSpace(n, d, r);
    doneText.set(n, r);
    if (r !== d) n.data = r;
  }
  // English: Japanese needs no spaces between a word and the <b>…</b> next to it; English does
  var ALONE = {'。': '.', '、': ',', '・': ' · ', '：': ':'};
  function enSpace(n, d, r) {
    if (ALONE[d.trim()]) return d.replace(d.trim(), ALONE[d.trim()]);
    if (r === d) return r;
    var prev = n.previousSibling, next = n.nextSibling;
    if (prev && /^[A-Za-z0-9"(★]/.test(r) && !/[\s(（"]$/.test(prev.textContent || '')) r = ' ' + r;
    if (next && /[A-Za-z0-9".,;:)]$/.test(r) && !/^[\s.,;:)）。、]/.test(next.textContent || '')) r = r + ' ';
    return r;
  }
  function attrs(el) {
    var mem = doneAttr.get(el);
    for (var i = 0; i < ATTRS.length; i++) {
      var a = ATTRS[i], v = el.getAttribute(a);
      if (!v || !JP.test(v) || (mem && mem[a] === v)) continue;
      if (blocked(el, true)) return;
      var r = tr(v);
      if (!mem) { mem = {}; doneAttr.set(el, mem); }
      mem[a] = r;
      if (r !== v) el.setAttribute(a, r);
    }
  }
  function walk(root) {
    if (root.nodeType === 3) { textNode(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 11) return;
    if (root.nodeType === 1) { attrs(root); if (blocked(root)) return; }
    var w = document.createTreeWalker(root, 5, {   // elements + text
      acceptNode: function (n) {
        if (n.nodeType === 1 && n.getAttribute('translate') === 'no') return 2;   // reject the subtree
        return 1;
      },
    });
    for (var n = w.nextNode(); n; n = w.nextNode()) { if (n.nodeType === 3) textNode(n); else attrs(n); }
  }
  var obs = new MutationObserver(function (list) {
    for (var i = 0; i < list.length; i++) {
      var m = list[i];
      if (m.type === 'childList') { for (var j = 0; j < m.addedNodes.length; j++) walk(m.addedNodes[j]); }
      else if (m.type === 'characterData') textNode(m.target);
      else if (m.type === 'attributes' && m.target.nodeType === 1) attrs(m.target);
    }
  });
  obs.observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS});
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { walk(document.documentElement); });
  else walk(document.documentElement);

  // canvas text (timeline lanes, ruler, 3D labels)
  var C = window.CanvasRenderingContext2D && CanvasRenderingContext2D.prototype;
  if (C) ['fillText', 'strokeText', 'measureText'].forEach(function (f) {
    var o = C[f];
    C[f] = function (t) { var a = Array.prototype.slice.call(arguments); a[0] = tr(String(t)); return o.apply(this, a); };
  });

  // dialogs
  ['alert', 'confirm'].forEach(function (f) { var o = window[f]; window[f] = function (m) { return o.call(window, tr(String(m == null ? '' : m))); }; });
  var _prompt = window.prompt;
  window.prompt = function (m, d) { return _prompt.call(window, tr(String(m == null ? '' : m)), d); };
})();
