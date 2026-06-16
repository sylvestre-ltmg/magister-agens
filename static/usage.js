// Pastille de consommation Claude (nav, en haut à droite)
(function () {
  function fmt(n) {
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
    return String(n);
  }
  function maj() {
    var el = document.getElementById('llm-counter');
    if (!el) return;
    fetch('/api/usage')
      .then(function (r) { return r.json(); })
      .then(function (u) {
        var toks = (u.input_tokens || 0) + (u.output_tokens || 0);
        el.textContent = '⚱ ' + fmt(toks) + ' tokens · $' + (u.cost_usd || 0).toFixed(3);
        el.title = (u.calls || 0) + ' appels Claude — '
          + (u.input_tokens || 0) + ' in / ' + (u.output_tokens || 0) + ' out';
      })
      .catch(function () { el.textContent = '⚱ —'; });
  }
  document.addEventListener('DOMContentLoaded', maj);
})();
