// Product cards in the CHEE chat: a row of clickable products under a reply (and the order they belong to).
// The agent sends them as a UI component next to its reply:
//   {type: "product_cards", version: 1, data: {
//      order: {order_id, status} or null,
//      products: [{id, name, price, image_url, rating, rating_count, in_stock, quantity}]}}
// The chat script (base.html) looks up card types here. Everything is built with textContent, and links are
// made from the ids, so nothing the model writes ends up as HTML or as a link.
(() => {
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const STATUS = { pending: "Pending", processing: "Processing", shipped: "Shipped", delivered: "Delivered", cancelled: "Cancelled" };

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
      const a = node("a", "pc");
      a.href = `/products/${p.id}/`;
      a.title = p.name || "";
      const img = node("img"); img.alt = ""; img.loading = "lazy";
      if (/^https:\/\//.test(p.image_url || "")) img.src = p.image_url;
      const pic = node("span", "pc-pic"); pic.append(img);
      if (p.quantity > 1) pic.append(node("span", "pc-qty", `×${p.quantity}`));
      const meta = node("span", "pc-meta");
      meta.append(node("b", null, `$${Number(p.price).toFixed(2)}`));
      if (p.rating) meta.append(node("span", "pc-rate", `★ ${Number(p.rating).toFixed(1)}`));
      a.append(pic, node("span", "pc-name", p.name || "Product"), meta,
               node("span", "pc-stock" + (p.in_stock ? "" : " out"), p.in_stock ? "In stock" : "Out of stock"));
      row.append(a);
    });
    wrap.append(row);
    return wrap;
  }

  window.cheebagCards = Object.assign(window.cheebagCards || {}, { product_cards: productCards });
})();
