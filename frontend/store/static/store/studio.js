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

  // the studio survives page changes in this tab (e.g. going to a product page and back)
  const KEY = "cheebag-studio";
  const fresh = () => ({ room: null, analysis: null, items: [], plan: null, renders: [], showing: null, chat: [], left: null,
                         source: state?.source || "store" });   // "store": CheeBag's products, "shops": online shops
  let state;
  state = fresh();
  try { state = { ...fresh(), ...JSON.parse(sessionStorage.getItem(KEY) || "{}") }; } catch (e) {}
  if (!Array.isArray(state.items)) state.items = [];
  if (state.product) { if (!state.items.length) state.items = [state.product]; delete state.product; }   // older single-product state
  const newRoom = () => ({ ...fresh(), items: state.items });   // a new photo keeps the chosen products
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} };
  let busy = false;

  const status = (text, isError) => { const s = $("[data-st-status]"); s.textContent = text || ""; s.classList.toggle("err", !!isError); };

  async function api(url, options = {}) {
    const headers = { "X-CSRFToken": csrf(), ...(options.json ? { "Content-Type": "application/json" } : {}) };
    let res;
    try {
      res = await fetch(url, { method: options.method || "POST", headers, body: options.json ? JSON.stringify(options.json) : options.body });
    } catch (e) {
      throw new Error("Couldn't reach the store. Please try again.");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Something went wrong. Please try again.");
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
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return status("Please choose a JPG, PNG or WebP photo.", true);
    if (file.size > MAX_BYTES) return status("That photo is too big. Please use one under 8 MB.", true);
    busy = true; status("Uploading your photo…");
    const form = new FormData(); form.append("photo", file);
    try {
      const data = await api(studio.dataset.uploadUrl, { body: form });
      state = { ...newRoom(), room: data.room_id };
      save(); draw(); status("");
      await analyze();
    } catch (e) { status(e.message, true); }
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
    img.src = roomUrl("image") + (shown ? `?render=${shown.id}` : "");
    sw.replaceChildren();
    if (state.renders.length) {
      const [prev, last] = state.renders.slice(-2).length === 2 ? state.renders.slice(-2) : [null, state.renders[0]];
      const choices = [["Your room", null]];
      if (prev) choices.push(["Previous", prev.id]);
      choices.push([last.updated ? "Updated" : `With ${short(last.label)}`, last.id]);
      choices.forEach(([label, id]) => {
        const b = node("button", state.showing === id ? "on" : "", label); b.type = "button";
        b.addEventListener("click", () => { state.showing = id; save(); drawPhoto(); });
        sw.append(b);
      });
    }
    drawPins(); drawAdjust();
    cap.textContent = shown ? (shown.demo ? "Demo preview: no image model is set up yet." : "AI preview: the real products and their sizes may differ.") : "";
  }
  const short = (name) => (name.length > 28 ? name.slice(0, 26) + "…" : name);

  // ---------- where products come from: CheeBag or online shops ----------
  const shopsMode = () => state.source === "shops";
  function setSource(source) {
    state.source = source; state.plan = null; save();
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
    } catch (e) { list.replaceChildren(node("p", "st-small err", e.message)); }
  }

  // ids are text: "123" for CheeBag products, "s…" for shop listings
  const has = (id) => state.items.some((i) => String(i.id) === String(id));
  const slim = (p) => ({ id: String(p.id), name: p.name, price: p.price, image_url: p.image_url,
                         store: p.store || "CheeBag", link: p.link || `/products/${p.id}/` });
  const money = (n) => `$${n.toFixed(2)}`;
  const total = (items) => items.reduce((sum, i) => sum + Number(i.price), 0);

  function add(p) {
    if (has(p.id)) return;
    if (state.items.length >= MAX_ITEMS) return status(`You can place up to ${MAX_ITEMS} products in one preview.`, true);
    state.items.push(slim(p)); status(""); save(); drawSelected();
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
    busy = true;
    const go = $("[data-st-render]"); go.disabled = true; go.textContent = "Making your preview…";
    status("This can take up to a minute.");
    try {
      const items = [...state.items];
      const data = await api(roomUrl("render"), { json: { product_ids: items.map((i) => String(i.id)) } });
      state.renders.push({ id: data.render_id, label: items.length > 1 ? `${items.length} products` : items[0].name,
                           demo: data.demo, items, edits: {} });
      state.showing = data.render_id; state.left = data.renders_left;
      save(); drawPhoto(); status("");
      $("[data-st-img]").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { status(e.message, true); }
    busy = false; drawSelected();
  }

  // ---------- adjusting a preview: drag pins, pick colours, add a note, update ----------
  const current = () => state.renders.find((r) => r.id === state.showing);

  // where a pin starts: where the customer last put it, or spread along the bottom like the first preview
  function pinSpot(render, item, i) {
    const e = render.edits[item.id];
    if (e && e.x != null) return [e.x, e.y];
    const n = render.items.length, slot = 100 / Math.max(n, 3), left = (100 - slot * n) / 2;
    return [left + slot * (i + 0.5), 78];
  }

  function drawPins() {
    const layer = $("[data-st-pins]"), render = current();
    layer.replaceChildren();
    if (!render || !render.items) return;
    render.items.forEach((item, i) => {
      const [x, y] = pinSpot(render, item, i);
      const pin = node("button", "st-pin" + (render.edits[item.id]?.moved ? " moved" : ""), String(i + 1));
      pin.type = "button"; pin.title = `Drag to move: ${item.name}`;
      pin.setAttribute("aria-label", `Move ${item.name}. Use the arrow keys or drag.`);
      pin.style.left = x + "%"; pin.style.top = y + "%";
      const place = (nx, ny) => {
        nx = Math.max(0, Math.min(100, nx)); ny = Math.max(0, Math.min(100, ny));
        render.edits[item.id] = { ...(render.edits[item.id] || {}), x: Math.round(nx), y: Math.round(ny), moved: true };
        pin.style.left = nx + "%"; pin.style.top = ny + "%"; pin.classList.add("moved");
      };
      pin.addEventListener("pointerdown", (e) => {
        e.preventDefault(); pin.setPointerCapture(e.pointerId); pin.classList.add("drag");
        const box = layer.getBoundingClientRect();
        const move = (ev) => place((ev.clientX - box.left) / box.width * 100, (ev.clientY - box.top) / box.height * 100);
        const up = () => { pin.classList.remove("drag"); pin.removeEventListener("pointermove", move); save(); drawAdjust(); };
        pin.addEventListener("pointermove", move);
        pin.addEventListener("pointerup", up, { once: true });
      });
      pin.addEventListener("keydown", (e) => {           // keyboard: arrow keys move the pin
        const step = { ArrowLeft: [-3, 0], ArrowRight: [3, 0], ArrowUp: [0, -3], ArrowDown: [0, 3] }[e.key];
        if (!step) return;
        e.preventDefault();
        const [cx, cy] = pinSpot(render, item, i);
        place(cx + step[0], cy + step[1]); save(); drawAdjust();
      });
      layer.append(pin);
    });
  }

  function drawAdjust() {
    const card = $("[data-st-adjust]"), render = current();
    card.hidden = !render || !render.items;
    if (card.hidden) return;
    $("[data-st-adjust-items]").replaceChildren(...render.items.map((item, i) => {
      const row = node("div", "st-adj");
      const edit = render.edits[item.id] || {};
      const select = node("select"); select.setAttribute("aria-label", `Colour for ${item.name}`);
      [["", "Original"], ...COLOURS.map((c) => [c, c[0].toUpperCase() + c.slice(1)])].forEach(([value, label]) => {
        const o = node("option", null, label); o.value = value; o.selected = (edit.colour || "") === value; select.append(o);
      });
      select.addEventListener("change", () => {
        render.edits[item.id] = { ...(render.edits[item.id] || {}), colour: select.value || null }; save();
      });
      row.append(node("span", "st-num", String(i + 1)), node("span", "st-name", item.name),
                 node("span", "st-moved", edit.moved ? "moved" : ""), select);
      return row;
    }));
  }

  async function updatePreview() {
    const render = current();
    if (busy || !render) return;
    const note = $("[data-st-note]").value.trim().slice(0, 300);
    const edits = render.items.map((item) => {
      const e = render.edits[item.id] || {};
      return { product_id: String(item.id), ...(e.moved ? { x: e.x, y: e.y } : {}), ...(e.colour ? { colour: e.colour } : {}) };
    }).filter((e) => e.x != null || e.colour);
    if (!edits.length && !note) return status("Move a pin, pick a colour or describe a change first.", true);
    busy = true;
    const btn = $("[data-st-update]"); btn.disabled = true; btn.textContent = "Updating your preview…";
    status("This can take up to a minute.");
    try {
      const data = await api(roomUrl("render"), { json: { product_ids: render.items.map((i) => String(i.id)), edits, note, based_on: render.id } });
      // the new preview keeps the colours and the pins where they are; nothing is "moved" again until dragged
      const kept = Object.fromEntries(Object.entries(render.edits).map(([id, e]) => [id, { ...e, moved: false }]));
      state.renders.push({ ...render, id: data.render_id, demo: data.demo, edits: kept, updated: true });
      state.showing = data.render_id; state.left = data.renders_left;
      $("[data-st-note]").value = ""; save(); drawPhoto(); status("");
      $("[data-st-img]").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (e) { status(e.message, true); }
    btn.disabled = false; btn.textContent = "Update preview"; busy = false; drawSelected();
  }

  // ---------- 3. let CHEE pick a set for a budget ----------
  async function planRoom(budget, wishes) {
    if (busy || !state.room) return;
    if (!(budget >= 10 && budget <= 10000)) return status("Enter a budget between $10 and $10,000.", true);
    busy = true;
    const box = $("[data-st-plan-result]"), btn = $("[data-st-plan] button");
    btn.disabled = true; box.replaceChildren(node("p", "st-small", "CHEE is putting a set together…")); status("");
    try {
      state.plan = await api(roomUrl("plan"), { json: { budget, wishes, source: state.source } }); save();
    } catch (e) { state.plan = null; status(e.message, true); }
    btn.disabled = false; busy = false; drawPlan(); drawSelected();
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
    busy = true;
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
      input.value = text; status(e.message, true);
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
      setSource(state.source);
    }
    drawSelected();
  }

  // a room photo can expire on the server (after 6 hours): start again cleanly
  $("[data-st-img]").addEventListener("error", () => {
    if (!state.room) return;
    state = newRoom(); save(); draw();
    status("Your room photo expired, so please upload it again.");
  });

  // ---------- events ----------
  const file = $("[data-st-file]");
  file.addEventListener("change", () => { if (file.files[0]) upload(file.files[0]); file.value = ""; });
  const drop = $("[data-st-drop]");
  ["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
  $("[data-st-sample]").addEventListener("click", async () => {
    try {
      const blob = await (await fetch(studio.dataset.sampleUrl)).blob();
      upload(new File([blob], "sample-room.jpg", { type: "image/jpeg" }));
    } catch (e) { status("Couldn't load the sample room.", true); }
  });
  $("[data-st-reset]").addEventListener("click", () => { state = newRoom(); save(); draw(); });
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
  $("[data-st-plan]").addEventListener("submit", (e) => {
    e.preventDefault();
    planRoom(Number(e.target.budget.value), e.target.wishes.value.trim().slice(0, 200) || null);
  });
  studio.querySelectorAll("[data-st-ask]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.stAsk)));
  const form = $("[data-st-form]"), input = form.querySelector("textarea");
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); } });

  // "See it in your room" buttons on product pages
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-studio-product]");
    if (!b) return;
    add({ id: b.dataset.studioProduct, name: b.dataset.name, price: b.dataset.price, image_url: b.dataset.image });
    window.cheebagAsk?.();      // opens the CHEE panel (or focuses it when it's docked)
    showTab("studio"); draw();
    if (state.room) $("[data-st-render]").scrollIntoView({ behavior: "smooth", block: "center" });
  });

  draw();
})();
