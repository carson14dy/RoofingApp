/* Radar echo tops in the Map's List and town sheets (behind --storm-layers; website/build.py).
   The words are Python's (website/storm.py): map.html keeps them in <template> elements, and
   data/map.json carries them per town. map.js builds its sheets without them, so this file puts a copy
   in each time a sheet opens. Browser-only: it needs the page's own sheet elements (AGENTS.md rule 4). */
(function () {
  "use strict";
  var body = document.getElementById("sheet-body");
  var title = document.getElementById("sheet-title");
  if (!body || !title || !document.getElementById("storm-list")) return;

  function heading(text) {
    var hs = body.querySelectorAll("h3");
    for (var i = 0; i < hs.length; i++) if (hs[i].textContent === text) return hs[i];
    return null;
  }

  function place() {
    if (body.querySelector("[data-storm]")) return;          // already placed in this sheet
    if (title.textContent === "List") {
      body.appendChild(document.getElementById("storm-list").content.cloneNode(true));
      return;
    }
    var go = body.querySelector("a.go");                      // a town sheet links to its page
    var m = go && /(?:^|\/)town\/([a-z-]+)\.html$/.exec(go.getAttribute("href") || "");
    var tpl = m && document.querySelector('template[data-storm-town="' + m[1] + '"]');
    if (tpl) body.insertBefore(tpl.content.cloneNode(true), heading("Official alerts"));
  }

  var queued = false;
  function later() {
    if (queued) return;
    queued = true;
    setTimeout(function () { queued = false; place(); }, 0);
  }
  new MutationObserver(later).observe(body, { childList: true });
  new MutationObserver(later).observe(title, { childList: true, characterData: true, subtree: true });
})();
