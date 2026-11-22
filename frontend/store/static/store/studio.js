// Room studio: the second tab of the CHEE panel.
// Upload a room photo -> CHEE describes it -> choose up to 6 products (or let CHEE pick a set for a budget)
// -> see them in the room -> drag them / recolour them and update the preview -> ask about the room.
// Everything shown here is built with textContent (never HTML from the model or the server).
(() => {
  const panel = document.getElementById("assistant");
  const studio = document.getElementById("studio");
  if (!panel || !studio) return;

  const $ = (sel) => studio.querySelector(sel);
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";
  const roomUrl = (what) => studio.dataset.uploadUrl.replace(/upload\/$/, `rooms/${state.room}/${what}/`);
  const MAX_BYTES = 8 * 1024 * 1024;
  const MAX_ITEMS = 6;          // the same limit as the service: more objects make previews less faithful
  // the same colour names the service accepts (room_studio/app/images.py COLOURS)
  const COLOURS = ["black", "white", "grey", "beige", "brown", "red", "pink", "orange", "yellow", "sage green",
                   "green", "teal", "blue", "navy", "purple", "gold", "silver", "copper"];

  // the studio survives page changes (e.g. going to a product page and back) and is shared with the bigger window
  // (localStorage, kept in sync by the "storage" event at the end of this file), but it belongs to one demo
  // customer: switching customers or pressing "New chat" starts it again
  const KEY = "cheebag-studio";
  const owner = panel.dataset.customer || "guest";
  const fresh = () => ({ room: null, analysis: null, items: [], plan: null, renders: [], showing: null, chat: [], left: null,
                         source: state?.source || "store",      // "store": CheeBag's products, "shops": online shops
                         owner });
  let state;
  state = fresh();
  try { state = { ...fresh(), ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch (e) {}
  if (state.owner !== owner) { state = undefined; state = fresh(); }    // another customer's studio: start clean
  state.night = false;
  if (!Array.isArray(state.items)) state.items = [];
  if (state.product) { if (!state.items.length) state.items = [state.product]; delete state.product; }   // older single-product state
  const newRoom = () => ({ ...fresh(), items: state.items });   // a new photo keeps the chosen products
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} };
  let busy = false;
  let selected = null;          // the item picked on the picture (its id), for the quick-edit box

  const status = (text) => { $("[data-st-status]").textContent = text || ""; };    // progress notes ("Uploading…")

  // ---------- the banner at the top of the studio: errors, limits and notices ----------
  // kinds: "error" (red: something failed), "limit" (amber: a daily or monthly limit), "warn" (amber: check what you
  // entered), "info" (neutral). It stays until it is dismissed or the next action starts.
  function banner(kind, message, title = "") {
    const b = $("[data-st-banner]");
    b.className = "st-banner " + kind;
    $("[data-st-banner-title]").textContent = title;
    $("[data-st-banner-msg]").textContent = message;
    b.hidden = false;
  }
  const clearBanner = () => { $("[data-st-banner]").hidden = true; };
  function showError(e) {
    if (e.status === 429) return banner("limit", e.message, "Limit reached");
    if (e.status === 503) return banner("warn", e.message, "Not available yet");
    banner("error", e.message, e.status === 0 ? "Connection problem" : "Something went wrong");
  }

  // ---------- the loading screen over the photo while a preview is made ----------
  let loadingTimer;
  // steps: [[seconds, text], …] to change the title as the work goes on (the server does it all in one request)
  function loading(on, title, steps = []) {
    clearInterval(loadingTimer);
    $("[data-st-loading]").hidden = !on;
    $(".st-photo").classList.toggle("is-busy", on);
    $(".st-frame").setAttribute("aria-busy", String(on));
    $("[data-st-reset]").disabled = on;
    if (!on) return;
    $("[data-st-loading-title]").textContent = title;
    const start = Date.now(), clock = $("[data-st-loading-time]");
    clock.textContent = "0";
    loadingTimer = setInterval(() => {
      const secs = Math.round((Date.now() - start) / 1000);
      clock.textContent = String(secs);
      const step = steps.filter(([at]) => secs >= at).pop();
      if (step) $("[data-st-loading-title]").textContent = step[1];
    }, 1000);
    $(".st-photo").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  // wait until the new picture has loaded, so the loading screen doesn't lift on the old one
  const pictureLoaded = () => new Promise((resolve) => {
    const img = $("[data-st-img]");
    if (img.complete) return resolve();
    img.addEventListener("load", resolve, { once: true });
    img.addEventListener("error", resolve, { once: true });
  });

  async function api(url, options = {}) {
    const headers = { "X-CSRFToken": csrf(), ...(options.json ? { "Content-Type": "application/json" } : {}) };
    let res;
    try {
      res = await fetch(url, { method: options.method || "POST", headers, body: options.json ? JSON.stringify(options.json) : options.body });
    } catch (e) {
      throw Object.assign(new Error("Couldn't reach the store. Check your connection and try again."), { status: 0 });
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(data.error || "Something went wrong. Please try again."), { status: res.status });
    return data;
  }

  // ---------- tabs: Chat | Room studio ----------
  function showTab(name) {
    panel.classList.toggle("studio-on", name === "studio");
    panel.querySelectorAll("[data-as-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.asTab === name)));
    try { sessionStorage.setItem(KEY + "-tab", name); } catch (e) {}
  }
  panel.querySelectorAll("[data-as-tab]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.asTab)));
  try { if (sessionStorage.getItem(KEY + "-tab") === "studio") showTab("studio"); } catch (e) {}

  // ---------- 1. the photo ----------
  async function upload(file) {
    if (busy) return;
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return banner("warn", "Please choose a JPG, PNG or WebP photo.");
    if (file.size > MAX_BYTES) return banner("warn", "That photo is too big. Please use one under 8 MB.");
    busy = true; clearBanner(); status("Uploading your photo…");
    $("[data-st-start]").classList.add("is-busy");
    const form = new FormData(); form.append("photo", file);
    try {
      const data = await api(studio.dataset.uploadUrl, { body: form });
      state = { ...newRoom(), room: data.room_id };
      save(); draw(); status("");
      await analyze();
    } catch (e) { status(""); showError(e); }
    $("[data-st-start]").classList.remove("is-busy");
    busy = false;
  }

  async function analyze() {
    const box = $("[data-st-analysis]");
    box.replaceChildren(node("p", "st-small", "CHEE is looking at your room…"));
    try { state.analysis = await api(roomUrl("analyze")); save(); }
    catch (e) { box.replaceChildren(node("p", "st-small err", e.message)); return; }
    drawAnalysis();
  }

  function drawAnalysis() {
    const a = state.analysis, box = $("[data-st-analysis]");
    if (!a) return;
    const head = node("div", "st-tags");
    [a.room_type, a.style].filter(Boolean).forEach((t) => head.append(node("span", "st-tag", t)));
    const swatches = node("div", "st-swatches");
    (a.colours || []).forEach((c) => {
      const s = node("span", "st-swatch"); s.title = c.name;
      if (/^#[0-9a-f]{6}$/i.test(c.hex)) s.style.background = c.hex;
      swatches.append(s);
    });
    const parts = [node("b", "st-h", "What CHEE sees"), head, swatches, node("p", null, a.summary)];
    if ((a.free_spots || []).length) {
      const ul = node("ul", "st-spots"); a.free_spots.forEach((s) => ul.append(node("li", null, s))); parts.push(ul);
    }
    box.replaceChildren(...parts);
  }

  function drawPhoto() {
    const img = $("[data-st-img]"), sw = $("[data-st-switch]"), cap = $("[data-st-caption]");
    const shown = state.renders.find((r) => r.id === state.showing);
    const night = !!(shown && state.night && shown.nightId);
    img.src = roomUrl("image") + (shown ? `?render=${night ? shown.nightId : shown.id}` : "");
    $("[data-st-light]").hidden = !shown;
    studio.querySelectorAll("[data-st-light-btn]").forEach((b) => b.setAttribute("aria-pressed", String((b.dataset.stLightBtn === "night") === night)));
    sw.replaceChildren();
    if (state.renders.length) {
      const [prev, last] = state.renders.slice(-2).length === 2 ? state.renders.slice(-2) : [null, state.renders[0]];
      const choices = [["Your room", null]];
      if (prev) choices.push(["Previous", prev.id]);
      choices.push([last.updated ? "Updated" : `With ${short(last.label)}`, last.id]);
      choices.forEach(([label, id]) => {
        const b = node("button", state.showing === id ? "on" : "", label); b.type = "button";
        b.addEventListener("click", () => { state.showing = id; selected = null; save(); drawPhoto(); });
        sw.append(b);
      });
    }
    drawPins(); drawAdjust(); drawLayout();
    cap.textContent = !shown ? "" : shown.demo ? "Demo preview: no image model is set up yet."
      : night ? "Night view (AI preview). Switch to Day to make changes." : "AI preview: the real products and their sizes may differ.";
  }
  const short = (name) => (name.length > 28 ? name.slice(0, 26) + "…" : name);

  // ---------- where products come from: CheeBag or online shops ----------
  const shopsMode = () => state.source === "shops";
  // the customer picks a source: it's saved and the old budget plan goes (it was for the other source)
  function setSource(source) {
    state.source = source; state.plan = null; save();
    showSource();
  }
  // drawing only, never saving: draw() calls this, and draw() runs when the other window changes the studio
  // (saving here would make the two windows redraw each other forever)
  function showSource() {
    const source = state.source;
    studio.querySelectorAll("[data-st-source]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.stSource === source)));
    $("[data-st-shops-note]").hidden = !shopsMode();
    const box = $("[data-st-search]"); box.value = "";
    box.placeholder = shopsMode() ? "Search the shops, e.g. floor lamp, then Enter" : "Search products, e.g. kettle";
    $("[data-st-results]").replaceChildren(shopsMode() ? node("p", "st-small", "Type what you're looking for and press Enter.") : "");
    if (!shopsMode()) search("");
    drawPlan();
  }
  const storeLabel = (p) => (p.store && p.store !== "CheeBag" ? p.store : "");

  // ---------- 2. choose products and preview them ----------
  let searchTimer;
  async function search(q) {
    const list = $("[data-st-results]");
    if (shopsMode() && q.length < 2) return;     // shop searches cost money: only on Enter, never while typing
    if (shopsMode()) list.replaceChildren(node("p", "st-small", "Searching the shops…"));
    try {
      const url = shopsMode() ? studio.dataset.shopsUrl : studio.dataset.productsUrl;
      const data = await api(`${url}?q=${encodeURIComponent(q)}`, { method: "GET" });
      list.replaceChildren(...data.products.map((p) => {
        const b = node("button", "st-item"); b.type = "button"; b.dataset.id = p.id;
        const img = node("img"); img.src = p.image_url || ""; img.alt = ""; img.loading = "lazy";
        const name = node("span", "st-name", p.name);
        if (storeLabel(p)) name.prepend(node("em", "st-store", storeLabel(p)));
        b.append(img, name, node("span", "st-price", `$${p.price}`), node("span", "st-add", "+"));
        b.addEventListener("click", () => (has(p.id) ? remove(p.id) : add(p)));
        return b;
      }));
      if (!data.products.length) list.replaceChildren(node("p", "st-small", shopsMode()
        ? "None of our 14 shops came up for that. Try other words." : "No products match that search."));
      drawSelected();
    } catch (e) {
      list.replaceChildren(node("p", "st-small err", e.message));
      if (e.status === 429) showError(e);      // e.g. today's shop searches are used up
    }
  }

  // ids are text: "123" for CheeBag products, "s…" for shop listings
  const has = (id) => state.items.some((i) => String(i.id) === String(id));
  const slim = (p) => ({ id: String(p.id), name: p.name, price: p.price, image_url: p.image_url,
                         store: p.store || "CheeBag", link: p.link || `/products/${p.id}/` });
  const money = (n) => `$${n.toFixed(2)}`;
  const total = (items) => items.reduce((sum, i) => sum + Number(i.price), 0);

  function add(p) {
    if (has(p.id)) return;
    if (state.items.length >= MAX_ITEMS) return banner("warn", `You can place up to ${MAX_ITEMS} products in one preview. Remove one to add another.`);
    state.items.push(slim(p)); save(); drawSelected();
  }
  function remove(id) {
    state.items = state.items.filter((i) => String(i.id) !== String(id)); save(); drawSelected();
  }

  function drawSelected() {
    const box = $("[data-st-selected]"), go = $("[data-st-render]"), n = state.items.length;
    box.replaceChildren(...state.items.map((i) => {
      const row = node("div", "st-pick");
      const img = node("img"); img.src = i.image_url || ""; img.alt = "";
      const x = node("button", "st-x", "×"); x.type = "button"; x.setAttribute("aria-label", `Remove ${i.name}`);
      x.addEventListener("click", () => remove(i.id));
      const name = node("span", "st-name", i.name);
      if (storeLabel(i)) name.prepend(node("em", "st-store", storeLabel(i)));
      row.append(img, name, node("span", "st-price", `$${i.price}`), x);
      return row;
    }));
    if (n) box.append(node("div", "st-total", `${n} of ${MAX_ITEMS} · total ${money(total(state.items))} CAD`));
    box.hidden = !n;
    studio.querySelectorAll(".st-item").forEach((b) => b.classList.toggle("on", has(b.dataset.id)));
    if (!busy) go.textContent = n > 1 ? `Show these ${n} in my room` : "Show it in my room";
    go.disabled = busy || !n || !state.room;
    $("[data-st-left]").textContent = state.left == null ? "" : `${state.left} preview${state.left === 1 ? "" : "s"} left today`;
  }

  async function preview() {
    if (busy || !state.items.length || !state.room) return;
    busy = true; clearBanner();
    const items = [...state.items];
    const go = $("[data-st-render]"); go.disabled = true; go.textContent = "Making your preview…"; go.classList.add("is-loading");
    loading(true, items.length > 1 ? `CHEE is planning the layout for your ${items.length} products…`
                                   : `CHEE is planning where ${short(items[0].name)} goes…`, PREVIEW_STEPS);
    try {
      const data = await api(roomUrl("render"), { json: { product_ids: items.map((i) => String(i.id)) } });
      // CHEE's layout: items start where it put them (not "moved" until the customer drags them)
      const edits = {}, warnings = [];
      (data.layout || []).forEach((l) => {
        edits[l.product_id] = { x: l.x, y: l.y };
        const item = items.find((i) => String(i.id) === String(l.product_id));
        if (l.warning && item) warnings.push({ name: item.name, text: l.warning });
      });
      state.renders.push({ id: data.render_id, label: items.length > 1 ? `${items.length} products` : items[0].name,
                           demo: data.demo, items, edits, notes: data.layout_notes || "", warnings,
                           info: infoFrom(data, {}), checked: data.checked, fixed: data.fixed || [] });
      state.showing = data.render_id; state.left = data.renders_left;
      save(); drawPhoto();
      await pictureLoaded();
    } catch (e) { showError(e); }
    loading(false); go.classList.remove("is-loading");
    busy = false; drawSelected();
  }

  // ---------- adjusting a preview: click an item on the picture, recolour / remove / drag it, update ----------
  const current = () => state.renders.find((r) => r.id === state.showing);
  const nightOn = () => !!(state.night && current()?.nightId);
  const cap = (c) => c[0].toUpperCase() + c.slice(1);
  const PREVIEW_STEPS = [[8, "Drawing your products into the room…"], [35, "Checking each product against its photo…"],
                         [55, "Fixing what didn't match…"]];

  // per product, from the server: its real colour, colours CHEE suggests for this room, and the check's result
  // (where it is in the picture, and whether it matches the real product). Earlier suggestions are kept.
  function infoFrom(data, before) {
    const info = {};
    (data.items || []).forEach((it) => {
      const old = before[it.product_id] || {};
      info[it.product_id] = { sold: it.colour_sold || old.sold || "", colours: it.colours?.length ? it.colours : old.colours || [],
                              box: it.box || null, point: it.point || null, ok: it.ok, note: it.note || "" };
    });
    return info;
  }

  // CHEE's layout notes and its check of each product, for the preview on screen
  function drawLayout() {
    const card = $("[data-st-layout]"), render = current();
    const checks = render ? render.items.filter((i) => render.info?.[i.id]?.note) : [];
    card.hidden = !render || (!render.notes && !(render.warnings || []).length && !checks.length);
    if (card.hidden) return;
    const parts = [];
    if (render.notes || (render.warnings || []).length) parts.push(node("b", "st-h", "CHEE's layout"));
    if (render.notes) parts.push(node("p", null, render.notes));
    (render.warnings || []).forEach((w) => {
      const p = node("p", "st-warn"); p.append(node("b", null, w.name + ": "), w.text); parts.push(p);
    });
    if (checks.length) {
      parts.push(node("b", "st-h st-h2", "CHEE's check against the real products"));
      const ul = node("ul", "st-checks");
      checks.forEach((item) => {
        const info = render.info[item.id], li = node("li", info.ok === false ? "bad" : "good");
        li.append(node("span", "st-tick", info.ok === false ? "!" : "✓"), node("b", null, short(item.name)), " " + info.note);
        ul.append(li);
      });
      parts.push(ul);
      if ((render.fixed || []).length) parts.push(node("p", "st-small", `CHEE redrew ${render.fixed.map(short).join(", ")} because ${render.fixed.length > 1 ? "they" : "it"} didn't match the first time.`));
    }
    card.replaceChildren(...parts);
  }

  // where an item is on the picture, in % (left, top, right, bottom): the check's box, moved along if the item was
  // dragged; without a box, a small area around CHEE's planned spot (or spread along the bottom)
  function boxOf(render, item, i) {
    const e = render.edits[item.id] || {}, b = render.info?.[item.id]?.box, p = render.info?.[item.id]?.point;
    if (b) {
      // centred on the spot where the marker goes: where it was dragged, else the check's point on the product
      const w = b[2] - b[0], h = b[3] - b[1], [x, y] = e.moved ? [e.x, e.y] : p || [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
      return [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
    }
    let x = e.x, y = e.y;
    if (x == null) { const n = render.items.length, slot = 100 / Math.max(n, 3); x = (100 - slot * n) / 2 + slot * (i + 0.5); y = 78; }
    return [x - 7, y - 9, x + 7, y + 9];
  }
  const changeCount = (render) => render.items.filter((item) => {
    const e = render.edits[item.id] || {};
    return e.moved || e.remove || (e.colour || null) !== (e.shown || null);
  }).length;

  function setEdit(render, item, patch) {
    render.edits[item.id] = { ...(render.edits[item.id] || {}), ...patch };
    save(); drawPins(); drawAdjust();
  }

  // the colour list: the colour it is sold in, then AI-preview colours (CHEE's picks for this room first)
  function colourSelect(render, item) {
    const info = render.info?.[item.id] || {}, edit = render.edits[item.id] || {};
    const select = node("select"); select.setAttribute("aria-label", `Colour for ${item.name}`);
    const group = (label, options) => {
      const g = node("optgroup"); g.label = label;
      options.forEach(([value, text]) => { const o = node("option", null, text); o.value = value; o.selected = (edit.colour || "") === value; g.append(o); });
      select.append(g);
    };
    const sold = (info.sold || "").slice(0, 30);
    group("Available", [["", sold ? `${sold} (as sold)` : "Original colour (as sold)"]]);
    const picks = (info.colours || []).filter((c) => COLOURS.includes(c));
    if (picks.length) group("AI preview · suits your room", picks.map((c) => [c, `${cap(c)} ✦`]));
    group("AI preview · other colours", COLOURS.filter((c) => !picks.includes(c)).map((c) => [c, cap(c)]));
    select.addEventListener("change", () => setEdit(render, item, { colour: select.value || null }));
    return select;
  }
  function removeButton(render, item) {
    const removing = !!render.edits[item.id]?.remove;
    const b = node("button", removing ? "st-undo" : "st-remove", removing ? "Undo remove" : "Remove"); b.type = "button";
    b.addEventListener("click", () => setEdit(render, item, { remove: !removing }));
    return b;
  }

  // the items on the picture: a box around each one with its photo as a handle. Click to edit, drag to move.
  let showPins = true;   // the "Hide pointers" button: the picture on its own, without dots
  function drawPins() {
    const layer = $("[data-st-pins]"), quick = $("[data-st-quick]"), toggle = $("[data-st-pins-toggle]"), render = current();
    layer.replaceChildren(); quick.replaceChildren(); quick.hidden = true;
    const ready = render && render.items && !nightOn();
    toggle.hidden = !ready;
    toggle.textContent = showPins ? "Hide pointers" : "Show pointers";
    toggle.setAttribute("aria-pressed", String(!showPins));
    layer.hidden = !showPins;
    if (!ready || !showPins) return;
    render.items.forEach((item, i) => {
      const e = render.edits[item.id] || {}, info = render.info?.[item.id] || {};
      const box = boxOf(render, item, i);
      const mark = node("div", "st-mark" + (selected === item.id ? " on" : "") + (e.moved ? " moved" : "")
                               + (e.remove ? " removing" : "") + (info.ok === false ? " bad" : ""));
      // a dot on the item's centre; its photo shows above it (below it near the top, inwards near the sides)
      const put = (b) => {
        const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
        mark.style.left = cx + "%"; mark.style.top = cy + "%";
        mark.classList.toggle("below", cy < 35); mark.classList.toggle("at-left", cx < 15); mark.classList.toggle("at-right", cx > 85);
      };
      put(box);
      const chip = node("button", "st-chip"); chip.type = "button";
      chip.setAttribute("aria-label", `${i + 1}: ${item.name}. Press to change its colour or remove it; arrow keys move it`);
      chip.append(node("span", "st-dot-n", String(i + 1)));
      const tip = node("span", "st-tip");
      const img = node("img"); img.src = item.image_url || ""; img.alt = "";
      tip.append(img, node("b", null, item.name), node("small", null, e.remove ? "Will be removed" : "Click to edit · drag to move"));
      mark.append(chip, tip);

      // drag the dot to move the item; a click without moving opens the quick-edit bar
      mark.addEventListener("pointerdown", (ev) => {
        if (ev.button > 0) return;
        ev.preventDefault(); mark.setPointerCapture(ev.pointerId);
        const area = layer.getBoundingClientRect(), x0 = ev.clientX, y0 = ev.clientY;
        let moved = false, now = box;
        const move = (m) => {
          const dx = (m.clientX - x0) / area.width * 100, dy = (m.clientY - y0) / area.height * 100;
          if (!moved && Math.hypot(m.clientX - x0, m.clientY - y0) < 4) return;
          moved = true; mark.classList.add("drag");
          const cx = Math.max(0, Math.min(100, (box[0] + box[2]) / 2 + dx)), cy = Math.max(0, Math.min(100, (box[1] + box[3]) / 2 + dy));
          const w = box[2] - box[0], h = box[3] - box[1];
          now = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]; put(now);
        };
        const up = () => {
          mark.removeEventListener("pointermove", move);
          if (!moved) { selected = selected === item.id ? null : item.id; drawPins(); return; }
          selected = item.id;
          setEdit(render, item, { x: Math.round((now[0] + now[2]) / 2), y: Math.round((now[1] + now[3]) / 2), moved: true });
        };
        mark.addEventListener("pointermove", move);
        mark.addEventListener("pointerup", up, { once: true });
      });
      chip.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selected = selected === item.id ? null : item.id; drawPins(); return focusChip(item.id); }
        if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); setEdit(render, item, { remove: !e.remove }); return focusChip(item.id); }
        const step = { ArrowLeft: [-2, 0], ArrowRight: [2, 0], ArrowUp: [0, -2], ArrowDown: [0, 2] }[ev.key];
        if (!step) return;
        ev.preventDefault();
        const cx = (box[0] + box[2]) / 2 + step[0], cy = (box[1] + box[3]) / 2 + step[1];
        setEdit(render, item, { x: Math.round(Math.max(0, Math.min(100, cx))), y: Math.round(Math.max(0, Math.min(100, cy))), moved: true });
        focusChip(item.id);
      });
      layer.append(mark);

      if (selected === item.id) { quick.append(...quickEdit(render, item, i)); quick.hidden = false; }
    });
  }
  $("[data-st-pins-toggle]").addEventListener("click", () => { showPins = !showPins; selected = null; drawPins(); drawAdjust(); });
  const focusChip = (id) => {
    const render = current(), i = render.items.findIndex((it) => it.id === id);
    $("[data-st-pins]").querySelectorAll(".st-chip")[i]?.focus();
  };

  // the bar under the picture for the selected item: its colour, remove it, close (under the picture, so it never
  // covers other items)
  function quickEdit(render, item, i) {
    const name = node("span", "st-quick-name");
    const img = node("img"); img.src = item.image_url || ""; img.alt = "";
    name.append(img, node("span", "st-chip-n", String(i + 1)), node("b", null, item.name));
    const close = node("button", "st-pop-x", "×"); close.type = "button"; close.setAttribute("aria-label", "Close");
    close.addEventListener("click", () => { selected = null; drawPins(); drawAdjust(); });
    const info = render.info?.[item.id] || {};
    const help = node("small", info.ok === false ? "st-pop-bad" : null,
                      info.ok === false ? `${info.note}. Drag its dot on the picture to move it.` : "Drag its dot on the picture to move it.");
    return [name, close, colourSelect(render, item), removeButton(render, item), help];
  }

  // the same controls in a list under the picture (easier on phones and with a keyboard)
  function drawAdjust() {
    const card = $("[data-st-adjust]"), render = current();
    card.hidden = !render || !render.items;
    if (card.hidden) return;
    const night = nightOn();
    $("[data-st-adjust-help]").textContent = night ? "This is the night view. Switch to Day to make changes."
      : "Click a dot on the picture to change that item's colour or remove it, or drag the dot to move it. Then update the preview.";
    $("[data-st-adjust-items]").replaceChildren(...(night ? [] : render.items.map((item, i) => {
      const e = render.edits[item.id] || {}, info = render.info?.[item.id] || {};
      const row = node("div", "st-adj" + (selected === item.id ? " on" : "") + (e.remove ? " removing" : ""));
      const img = node("img"); img.src = item.image_url || ""; img.alt = "";
      const name = node("button", "st-adj-name"); name.type = "button";
      name.append(node("span", "st-chip-n", String(i + 1)), node("span", "st-name", item.name));
      name.addEventListener("click", () => { selected = selected === item.id ? null : item.id; drawPins(); drawAdjust(); });
      const tags = [e.moved && "moved", (e.colour || null) !== (e.shown || null) && "new colour", e.remove && "will be removed",
                    info.ok === false && "doesn't match"].filter(Boolean);
      const controls = node("div", "st-adj-controls");
      controls.append(colourSelect(render, item), removeButton(render, item));
      row.append(img, name, controls, node("span", "st-moved", tags.join(" · ")));
      return row;
    })));
    $("[data-st-note]").hidden = night;
    const btn = $("[data-st-update]"), n = changeCount(render);
    btn.hidden = night;
    if (!busy) btn.textContent = n ? `Update preview · ${n} change${n > 1 ? "s" : ""}` : "Update preview";
    btn.classList.toggle("has-changes", n > 0);
  }

  async function updatePreview() {
    const render = current();
    if (busy || !render) return;
    const note = $("[data-st-note]").value.trim().slice(0, 300);
    const edits = render.items.map((item) => {
      const e = render.edits[item.id] || {};
      const colour = (e.colour || null) !== (e.shown || null) ? { colour: e.colour || "original" } : {};
      return { product_id: String(item.id), ...(e.moved ? { x: e.x, y: e.y } : {}), ...colour, ...(e.remove ? { remove: true } : {}) };
    }).filter((e) => e.x != null || e.colour || e.remove);
    if (!edits.length && !note) return banner("warn", "Move, recolour or remove an item, or describe a change first.", "Nothing to update yet");
    busy = true; clearBanner(); selected = null;
    const btn = $("[data-st-update]"); btn.disabled = true; btn.textContent = "Updating your preview…"; btn.classList.add("is-loading");
    loading(true, "Updating your preview…", [[30, "Checking each product against its photo…"], [50, "Fixing what didn't match…"]]);
    try {
      const data = await api(roomUrl("render"), { json: { product_ids: render.items.map((i) => String(i.id)), edits, note, based_on: render.id } });
      const kept = render.items.filter((i) => data.product_ids.includes(String(i.id)));
      // the new preview shows the chosen colours; items stay where they were; nothing is "changed" until edited again
      const newEdits = {}, info = infoFrom(data, render.info || {});
      kept.forEach((item) => {
        const i = render.items.indexOf(item), e = render.edits[item.id] || {}, b = boxOf(render, item, i);
        newEdits[item.id] = { x: Math.round((b[0] + b[2]) / 2), y: Math.round((b[1] + b[3]) / 2), colour: e.colour || null, shown: e.colour || null };
        if (!data.checked && info[item.id]) info[item.id].box = b.slice();      // no check this time: keep the old spot
        if (!info[item.id]) info[item.id] = { ...(render.info?.[item.id] || {}), box: render.info?.[item.id]?.box ? b : null };
      });
      state.renders.push({ ...render, id: data.render_id, demo: data.demo, items: kept, edits: newEdits, info, nightId: null,
                           checked: data.checked, fixed: data.fixed || [], warnings: (render.warnings || []).filter((w) => kept.some((k) => k.name === w.name)),
                           updated: true });
      state.showing = data.render_id; state.left = data.renders_left; state.night = false;
      $("[data-st-note]").value = ""; save(); drawPhoto();
      await pictureLoaded();
    } catch (e) { showError(e); }
    loading(false); btn.classList.remove("is-loading");
    btn.disabled = false; busy = false; drawAdjust(); drawSelected();
  }

  // the same preview at night (made once, then it's a switch); "Day" is the preview as it was made
  async function setLight(light) {
    const render = current();
    if (busy || !render) return;
    selected = null;
    if (light === "day" || render.nightId) { state.night = light === "night"; save(); return drawPhoto(); }
    busy = true; clearBanner();
    loading(true, "CHEE is turning the lights on…");
    try {
      const data = await api(roomUrl("render"), { json: { product_ids: render.items.map((i) => String(i.id)), based_on: render.id, light: "night" } });
      render.nightId = data.render_id; state.night = true; state.left = data.renders_left;
      save(); drawPhoto();
      await pictureLoaded();
    } catch (e) { showError(e); }
    loading(false); busy = false; drawSelected();
  }

  // ---------- 3. let CHEE pick a set for a budget ----------
  async function planRoom(budget, wishes) {
    if (busy || !state.room) return;
    if (!(budget >= 10 && budget <= 10000)) return banner("warn", "Enter a budget between $10 and $10,000.");
    busy = true; clearBanner();
    const box = $("[data-st-plan-result]"), btn = $("[data-st-plan] button");
    btn.disabled = true; btn.classList.add("is-loading");
    box.replaceChildren(node("p", "st-small", "CHEE is putting a set together…"));
    try {
      state.plan = await api(roomUrl("plan"), { json: { budget, wishes, source: state.source } }); save();
    } catch (e) { state.plan = null; showError(e); }
    btn.disabled = false; btn.classList.remove("is-loading"); busy = false; drawPlan(); drawSelected();
  }

  function drawPlan() {
    const box = $("[data-st-plan-result]"), plan = state.plan;
    if (!plan) return box.replaceChildren();
    const parts = [node("p", "st-reply", plan.reply)];
    plan.items.forEach((p) => parts.push(productCard(p, false)));
    if (plan.items.length) {
      parts.push(node("div", "st-total", `${plan.items.length} products · total $${plan.total} of your $${Number(plan.budget).toFixed(2)} CAD budget`));
      const act = node("div", "st-pact");
      const use = node("button", null, "Show this set in my room"); use.type = "button";
      use.addEventListener("click", () => { state.items = plan.items.slice(0, MAX_ITEMS).map(slim); save(); drawSelected(); preview(); });
      const pick = node("button", "ghost", "Use as my selection"); pick.type = "button";
      pick.addEventListener("click", () => {
        state.items = plan.items.slice(0, MAX_ITEMS).map(slim); save(); drawSelected();
        $("[data-st-render]").scrollIntoView({ behavior: "smooth", block: "center" });
      });
      act.append(use, pick); parts.push(act);
    }
    box.replaceChildren(...parts);
  }

  // a product suggested by CHEE, with its reason; withActions adds "Add to my room" and "View"
  function productCard(p, withActions = true) {
    const card = node("div", "st-pcard");
    const img = node("img"); img.src = p.image_url || ""; img.alt = "";
    const text = node("div");
    const name = node("b", null, p.name);
    if (storeLabel(p)) name.prepend(node("em", "st-store", storeLabel(p)));
    text.append(name, node("span", "st-price", `$${p.price}`), node("small", null, p.reason));
    card.append(img, text);
    if (withActions) {
      const actions = node("div", "st-pact");
      const addIt = node("button", null, "Add to my room"); addIt.type = "button";
      addIt.addEventListener("click", () => { add(p); $("[data-st-render]").scrollIntoView({ behavior: "smooth", block: "center" }); });
      const view = node("a", null, storeLabel(p) ? `View at ${storeLabel(p)} ↗` : "View");
      view.href = slim(p).link;
      if (storeLabel(p)) { view.target = "_blank"; view.rel = "noopener noreferrer"; }   // another site: new tab
      actions.append(addIt, view);
      card.append(actions);
    }
    return card;
  }

  // ---------- 4. questions about the room ----------
  function drawMessage(m) {
    const log = $("[data-st-log]");
    const el = node("div", "st-msg " + (m.role === "user" ? "st-user" : "st-bot"));   // not "assistant": that is the panel's class
    el.append(node("div", "st-b", m.content));
    (m.products || []).forEach((p) => el.append(productCard(p)));
    log.append(el); log.scrollTop = log.scrollHeight;
  }

  async function ask(text) {
    text = (text || "").trim();
    if (!text || busy || !state.room) return;
    busy = true; clearBanner();
    const input = $("[data-st-form] textarea"); input.value = "";
    state.chat.push({ role: "user", content: text }); drawMessage(state.chat[state.chat.length - 1]);
    const typing = node("div", "st-msg st-bot"); typing.append(node("div", "st-b", "CHEE is thinking…")); $("[data-st-log]").append(typing);
    // the service accepts up to 20 messages and the first one must be the customer's
    let history = state.chat.slice(-19).map(({ role, content }) => ({ role, content }));
    while (history.length && history[0].role !== "user") history.shift();
    try {
      const data = await api(roomUrl("ask"), { json: { messages: history, product_ids: state.items.map((i) => String(i.id)), source: state.source } });
      typing.remove();
      const m = { role: "assistant", content: data.reply, products: data.products || [] };
      state.chat.push(m); save(); drawMessage(m);
    } catch (e) {
      typing.remove(); state.chat.pop(); $("[data-st-log]").lastChild?.remove();
      input.value = text; showError(e);
    }
    busy = false;
  }

  // ---------- drawing the whole tab ----------
  function draw() {
    const hasRoom = !!state.room;
    $("[data-st-start]").hidden = hasRoom;
    $("[data-st-room]").hidden = !hasRoom;
    const n = state.items.length;
    $("[data-st-intro]").textContent = n && !hasRoom
      ? `Upload a photo of your room to see ${n > 1 ? `your ${n} products` : state.items[0].name} in it. CHEE will also suggest what else would suit it.`
      : "Upload a photo of your room. CHEE looks at its style and colours, shows products in it, and can pick a set for your budget.";
    if (hasRoom) {
      drawPhoto(); drawAnalysis(); drawPlan();
      $("[data-st-log]").replaceChildren(); state.chat.forEach(drawMessage);
      showSource();
    }
    drawSelected();
  }

  // a room photo can expire on the server (after 6 hours): start again cleanly
  $("[data-st-img]").addEventListener("error", () => {
    if (!state.room) return;
    state = newRoom(); save(); draw();
    banner("info", "Room photos are deleted after 6 hours. Please upload it again.", "Your photo expired");
  });

  // ---------- events ----------
  const file = $("[data-st-file]");
  file.addEventListener("change", () => { if (file.files[0]) upload(file.files[0]); file.value = ""; });
  const drop = $("[data-st-drop]");
  ["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
  studio.querySelectorAll("[data-st-sample]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const res = await fetch(b.dataset.stSample);
      const blob = await res.blob();
      if (!res.ok || !blob.type.startsWith("image/")) throw new Error("no sample photo");   // e.g. a 404 page
      upload(new File([blob], "sample-room.jpg", { type: "image/jpeg" }));
    } catch (e) { banner("error", "The sample room photo is missing from the site. Please upload your own photo.", "Couldn't load the sample room"); }
  }));
  $("[data-st-reset]").addEventListener("click", () => { state = newRoom(); save(); clearBanner(); draw(); });
  $("[data-st-banner-close]").addEventListener("click", clearBanner);
  $("[data-st-search]").addEventListener("input", (e) => {
    if (shopsMode()) return;          // shop searches cost money, so they wait for Enter
    clearTimeout(searchTimer); searchTimer = setTimeout(() => search(e.target.value.trim()), 250);
  });
  $("[data-st-search]").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); clearTimeout(searchTimer); search(e.target.value.trim()); }
  });
  studio.querySelectorAll("[data-st-source]").forEach((b) => b.addEventListener("click", () => setSource(b.dataset.stSource)));
  $("[data-st-render]").addEventListener("click", preview);
  $("[data-st-update]").addEventListener("click", updatePreview);
  studio.querySelectorAll("[data-st-light-btn]").forEach((b) => b.addEventListener("click", () => setLight(b.dataset.stLightBtn)));
  // a click on the picture outside the items closes the quick-edit box
  $(".st-frame").addEventListener("pointerdown", (e) => { if (selected && !e.target.closest(".st-mark")) { selected = null; drawPins(); drawAdjust(); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && selected) { selected = null; drawPins(); drawAdjust(); } });
  $("[data-st-plan]").addEventListener("submit", (e) => {
    e.preventDefault();
    planRoom(Number(e.target.budget.value), e.target.wishes.value.trim().slice(0, 200) || null);
  });
  studio.querySelectorAll("[data-st-ask]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.stAsk)));
  const form = $("[data-st-form]"), input = form.querySelector("textarea");
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); } });

  // "Try Room studio" on the landing page: open CHEE on the Room studio tab
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-open-studio]")) return;
    window.cheebagAsk?.();
    showTab("studio");
  });

  // "See it in your room" buttons on product pages
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-studio-product]");
    if (!b) return;
    add({ id: b.dataset.studioProduct, name: b.dataset.name, price: b.dataset.price, image_url: b.dataset.image });
    window.cheebagAsk?.();      // opens the CHEE panel (or focuses it when it's docked)
    showTab("studio"); draw();
    if (state.room) $("[data-st-render]").scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // ---------- the bigger window: the same studio on its own page, the size of the screen ----------
  const full = document.body.classList.contains("studio-full");
  $("[data-st-popout]").addEventListener("click", () => {
    const url = studio.dataset.fullUrl;
    const win = window.open(url, "cheebag-studio", `popup,left=0,top=0,width=${screen.availWidth},height=${screen.availHeight}`);
    if (win) win.focus(); else location.href = url;           // pop-ups blocked: open it here instead
  });
  if (full) {
    showTab("studio");
    // the panel's ✕ closes this window (or goes back to the store if it wasn't opened as a window)
    panel.querySelector(".x-close")?.addEventListener("click", () => { if (window.opener) window.close(); else location.href = "/"; });
  }
  // the panel and the bigger window share the studio: when one changes it, the other redraws
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY || busy || e.newValue === JSON.stringify(state)) return;
    let next;
    try { next = JSON.parse(e.newValue || "{}"); } catch (err) { return; }
    if (next.owner && next.owner !== owner) return location.reload();    // another demo customer now: load them
    state = { ...fresh(), ...next, night: state.night }; selected = null; draw();
  });

  // "New chat" clears the studio too: a fresh start for the demo
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-new-chat]") || busy) return;
    state = undefined; state = fresh(); selected = null; save();
    $("[data-st-search]").value = ""; $("[data-st-note]").value = ""; $("[data-st-form] textarea").value = "";
    status(""); clearBanner(); draw();
  });

  draw();
})();
