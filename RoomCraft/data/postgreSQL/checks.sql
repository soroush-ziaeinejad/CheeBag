-- Business-consistency checks. Every row should show problems = 0.

SELECT 'order total = sum of items' AS check_name, count(*) AS problems
FROM orders o
JOIN (SELECT order_id, sum(quantity * unit_price) AS items_total FROM order_items GROUP BY order_id) i
  USING (order_id)
WHERE o.total_amount <> i.items_total

UNION ALL
SELECT 'every order has items', count(*)
FROM orders o
WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)

UNION ALL
SELECT 'every order has one payment with the right amount', count(*)
FROM orders o
LEFT JOIN payments p USING (order_id)
WHERE p.payment_id IS NULL OR p.amount <> o.total_amount

UNION ALL
SELECT 'payment status matches order', count(*)
FROM orders o
JOIN payments p USING (order_id)
WHERE (o.status = 'pending')   <> (p.status = 'pending')
   OR (o.status = 'cancelled') <> (p.status = 'refunded')

UNION ALL
SELECT 'no shipment for pending/cancelled orders', count(*)
FROM orders o
JOIN shipments s USING (order_id)
WHERE o.status IN ('pending', 'cancelled')

UNION ALL
SELECT 'processing/shipped/delivered orders have a shipment', count(*)
FROM orders o
LEFT JOIN shipments s USING (order_id)
WHERE o.status IN ('processing', 'shipped', 'delivered') AND s.shipment_id IS NULL

UNION ALL
SELECT 'shipment status matches order', count(*)
FROM orders o
JOIN shipments s USING (order_id)
WHERE (o.status, s.status) NOT IN (('processing', 'pending'), ('shipped', 'in_transit'), ('delivered', 'delivered'))

UNION ALL
SELECT 'timestamps in order (signup < order < ship < deliver)', count(*)
FROM orders o
JOIN customers c USING (customer_id)
LEFT JOIN shipments s USING (order_id)
WHERE o.order_date < c.created_at
   OR s.shipped_at < o.order_date
   OR s.delivered_at < s.shipped_at;
