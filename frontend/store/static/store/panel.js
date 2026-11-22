// Resizing the docked CHEE panel (wide screens only; phones and narrow windows keep the slide-in drawer).
// Drag the panel's left edge, or focus the edge and use the arrow keys. Double-click resets the width.
// The width is remembered in this browser only (localStorage), as a small convenience.
(() => {
  const panel = document.getElementById("assistant");
  const handle = panel && panel.querySelector("[data-resize-panel]");
  if (!handle) return;

  const KEY = "cheebag-chat-width";
  const docked = window.matchMedia("(min-width: 1180px)");   // the same breakpoint as cheebag.css
  const root = document.documentElement;
  const MIN = 320, MIN_PAGE = 800;                           // keep the store at least 800px wide

  const maxWidth = () => Math.max(MIN, Math.min(760, window.innerWidth - MIN_PAGE));
  const clamp = (w) => Math.round(Math.max(MIN, Math.min(maxWidth(), w)));

  function apply(width) {
    if (!docked.matches || width == null) {
      root.style.removeProperty("--chat-w");                 // back to the default widths in cheebag.css
      document.body.classList.remove("main-narrow");
      handle.setAttribute("aria-valuenow", String(Math.round(panel.getBoundingClientRect().width)));
      return;
    }
    width = clamp(width);
    root.style.setProperty("--chat-w", width + "px");
    // with a wide panel the store gets narrow: the header then puts the search on its own row
    document.body.classList.toggle("main-narrow", window.innerWidth - width < 1000);
    handle.setAttribute("aria-valuenow", String(width));
  }

  const saved = () => { try { return Number(localStorage.getItem(KEY)) || null; } catch (e) { return null; } };
  const remember = (w) => { try { w == null ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, String(w)); } catch (e) {} };

  handle.setAttribute("aria-valuemin", String(MIN));
  const refresh = () => { handle.setAttribute("aria-valuemax", String(maxWidth())); apply(saved()); };
  refresh();
  docked.addEventListener("change", refresh);
  window.addEventListener("resize", refresh);

  handle.addEventListener("pointerdown", (e) => {
    if (!docked.matches) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add("panel-resizing");
    const move = (ev) => apply(window.innerWidth - ev.clientX);   // the panel's left edge follows the pointer
    const up = () => {
      document.body.classList.remove("panel-resizing");
      handle.removeEventListener("pointermove", move);
      remember(Math.round(panel.getBoundingClientRect().width));
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up, { once: true });
    handle.addEventListener("pointercancel", up, { once: true });
  });

  handle.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: 20, ArrowRight: -20 }[e.key];      // left makes the panel wider
    if (!step || !docked.matches) return;
    e.preventDefault();
    const width = clamp(panel.getBoundingClientRect().width + step);
    apply(width); remember(width);
  });

  handle.addEventListener("dblclick", () => { remember(null); apply(null); });
})();

// Hiding the docked CHEE panel to the right (wide screens only). It starts hidden: the store gets the full width,
// and the "Ask CHEE" button opens it. Remembered in this browser only (localStorage); a small script
// in base.html's <head> sets the class before the first paint, so a hidden panel doesn't flash open.
(() => {
  const KEY = "cheebag-chat-hidden";
  const launch = document.querySelector(".as-launch");

  function hide(hidden) {
    document.documentElement.classList.toggle("as-collapsed", hidden);
    try { localStorage.setItem(KEY, hidden ? "1" : "0"); } catch (e) {}   // nothing saved yet: hidden
  }
  window.cheebagPanel = { expand: () => hide(false) };   // base.html calls this when CHEE is opened

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-collapse-assistant]")) { hide(true); launch?.focus(); }
  });
})();
