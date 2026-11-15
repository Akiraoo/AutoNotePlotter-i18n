// 合言葉（2026-11-11・セキュリティのスキャン CLAUDE-SECURITY-20261111-045144 の F1・F2・F7・F13〜F15・NLM の js/settings-mirror.js と同じ考え）。
// ふつうの <script>（type="module" を付けない）で index.html の頭から読む＝どのモジュールより先に動く。
// - サーバー（app/server.py の「出入りの守り」）は、画面の部品の外は起動ごとの合言葉を頭 X-Automap-Key で求める。画面へは URL の #k=… で
//   渡る（app/server.py の main・窓のアプリが付ける）。サーバーで合っているか確かめてから、このタブの sessionStorage に控える（読み込み直しても
//   使える・ほかのタブとほかの番号のページからは見えない）。localStorage には置かない（ほかのサイトが開かせたタブからも読めてしまう）。
// - 同じサーバーへの fetch・XHR に頭を付ける＝個々の通信で付け忘れない。<audio>・<img> は頭を付けられないので anpUrl(u) で ?k= を足す
//   （サーバーは音とカバー画像だけ ?k= を受ける・KEY_QUERY）。
// - URL の # の確かめの入口（#vtest・#wtest・#xtest・#import= …）は、同じ URL に正しい合言葉がある時だけ残し、k= を外してから各部品へ渡す。
//   合言葉の無い #（ほかのサイトがアプリの URL へ飛ばして、画面自身に作業ファイルを書き換えさせる道）は、どの部品も読む前に消す。
//   読み込んだ後に # だけが変わった時も同じ（hashchange）。確かめの URL は #vtest=hist&song=曲名&k=<合言葉> の形（CLAUDE.md）。
(function () {
  var SS = 'anp-key', HEAD = 'X-Automap-Key';
  var tok = '';
  try { tok = sessionStorage.getItem(SS) || ''; } catch (_) {}
  var _fetch = window.fetch;

  function same(u) { try { return new URL(u, location.href).origin === location.origin; } catch (_) { return false; } }

  function check(k) {   // その合言葉でサーバーが答えるか（同期＝モジュールが動く前に決める・手元のサーバーなので一瞬）
    try {
      var x = new XMLHttpRequest();
      x.open('GET', '/api/ping', false);
      x.setRequestHeader(HEAD, k);
      x.send();
      return x.status === 200;
    } catch (_) { return false; }
  }

  function settle() {   // URL の # を整える（上の説明）
    var h = location.hash || '';
    if (!h || h === '#') return;
    var m = /(^#|&)k=([A-Za-z0-9_-]+)(?=&|$)/.exec(h);
    var ok = !!m && (m[2] === tok || check(m[2]));
    if (ok && m[2] !== tok) { tok = m[2]; try { sessionStorage.setItem(SS, tok); } catch (_) {} }
    var rest = ok ? h.slice(0, m.index) + (m[1] === '#' ? '#' : '') + h.slice(m.index + m[0].length) : '';
    rest = rest.replace(/^#&/, '#');
    if (rest === '#') rest = '';
    if (rest !== h) history.replaceState(history.state, '', location.pathname + location.search + rest);
  }
  settle();
  window.addEventListener('hashchange', settle);   // 先に登録＝ほかの部品の hashchange より先に動く

  window.fetch = function (input, init) {
    var req = typeof Request !== 'undefined' && input instanceof Request;
    if (tok && same(req ? input.url : String(input))) {
      init = Object.assign({}, init || {});
      var h = new Headers(init.headers || (req ? input.headers : undefined));   // init.headers は Request 側の頭を丸ごと置き換えるので合わせる
      h.set(HEAD, tok);
      init.headers = h;
    }
    return _fetch.call(window, input, init);
  };
  var _open = XMLHttpRequest.prototype.open, _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) { this._anpKey = same(url); return _open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function () { if (this._anpKey && tok) this.setRequestHeader(HEAD, tok); return _send.apply(this, arguments); };

  // <audio>・<img> の src（同じサーバーの /… だけ ?k= を足す・data: 等はそのまま）
  window.anpUrl = function (u) {
    u = String(u == null ? '' : u);
    if (!tok || u.charAt(0) !== '/' || u.charAt(1) === '/') return u;
    return u + (u.indexOf('?') < 0 ? '?' : '&') + 'k=' + encodeURIComponent(tok);
  };

  if (!tok) {   // 合言葉が無い＝ブックマーク・手で打った URL から開いた。開き直す道を出す
    document.addEventListener('DOMContentLoaded', function () {
      var d = document.createElement('div');
      d.id = 'anpNoKey';
      d.setAttribute('role', 'alert');
      d.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:99999;padding:10px 16px;background:#7f1d1d;color:#fff;font:14px/1.6 sans-serif';
      d.textContent = 'このページは使えません（起動ごとの合言葉がありません）。app/start.bat か窓のアプリから開き直してください。'
        + '起動しているサーバーで開き直すには、起動した時に出た URL（#k= の付いた物）を使います。';
      document.body.appendChild(d);
    });
  }
})();
