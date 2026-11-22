// Product cards in the CHEE chat: a row of products under a reply (and the order they belong to).
// The picture and name open the product page; the Add to cart button adds one without leaving the chat.
// The agent sends them as a UI component next to its reply:
//   {type: "product_cards", version: 1, data: {
//      order: {order_id, status} or null,
//      products: [{id, name, price, image_url, rating, rating_count, in_stock, quantity}]}}
// The chat script (base.html) looks up card types here. Everything is built with textContent, and links are
// made from the ids, so nothing the model writes ends up as HTML or as a link.
(() => {
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const STATUS = { pending: "Pending", processing: "Processing", shipped: "Shipped", delivered: "Delivered", cancelled: "Cancelled" };

  // "Add to cart" right on the card, so the customer stays in the chat
  function addButton(p) {
    const btn = node("button", "pc-add", p.in_stock ? "Add to cart" : "Out of stock");
    btn.type = "button";
    btn.disabled = !p.in_stock;
    btn.setAttribute("aria-label", p.in_stock ? `Add ${p.name || "this product"} to cart` : "Out of stock");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";
        const r = await fetch(`/cart/add-json/${p.id}/`, { method: "POST", headers: { "X-CSRFToken": csrf } });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "Couldn't add it.");
        btn.textContent = `✓ In cart · ${d.quantity}`;
        btn.classList.add("added");
        btn.setAttribute("aria-label", `${d.quantity} in cart. Add one more`);
        const nav = document.querySelector('nav a[href="/cart/"]');
        if (nav) nav.textContent = `Cart · ${d.count}`;
        showCartLink(btn);
      } catch (e) {
        btn.textContent = e.message || "Couldn't add it.";
      }
      btn.disabled = false;
    });
    return btn;
  }

  function showCartLink(btn) {   // one "View cart" link under the row, after the first add
    const wrap = btn.closest(".pc-wrap");
    if (!wrap || wrap.querySelector(".pc-cart")) return;
    const a = node("a", "pc-cart", "View cart and place the order →");
    a.href = "/cart/";
    wrap.append(a);
  }

  function productCards(card) {
    const { order, products = [] } = card.data || {};
    const wrap = node("div", "pc-wrap");
    if (order && Number.isInteger(order.order_id)) {
      const head = node("a", "pc-head");
      head.href = `/orders/${order.order_id}/`;
      head.append(node("b", null, `Order #${order.order_id}`),
                  node("span", "pc-status " + (STATUS[order.status] ? order.status : ""), STATUS[order.status] || ""),
                  node("span", "pc-go", "View order →"));
      wrap.append(head);
    }
    const row = node("div", "pc-row");
    products.slice(0, 6).forEach((p) => {
      if (!Number.isInteger(p.id)) return;
      const box = node("div", "pc");
      const a = node("a", "pc-link");                    // picture and name: open the product page
      a.href = `/products/${p.id}/`;
      a.title = p.name || "";
      const img = node("img"); img.alt = ""; img.loading = "lazy";
      if (/^https:\/\//.test(p.image_url || "")) img.src = p.image_url;
      const pic = node("span", "pc-pic"); pic.append(img);
      if (p.quantity > 1) pic.append(node("span", "pc-qty", `×${p.quantity}`));
      const meta = node("span", "pc-meta");
      meta.append(node("b", null, `$${Number(p.price).toFixed(2)}`));
      if (p.rating) meta.append(node("span", "pc-rate", `★ ${Number(p.rating).toFixed(1)}`));
      a.append(pic, node("span", "pc-name", p.name || "Product"), meta);
      box.append(a, addButton(p));
      row.append(box);
    });
    wrap.append(row);
    return wrap;
  }

  window.cheebagCards = Object.assign(window.cheebagCards || {}, { product_cards: productCards });
})();
