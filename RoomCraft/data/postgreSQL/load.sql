-- Load the generated CSVs (mounted at /data inside the container). Safe to re-run.
BEGIN;

-- empty all tables first so re-running doesn't duplicate rows
TRUNCATE reviews, shipments, payments, order_items, orders, customers, products;

-- parents before children, because of the foreign keys
COPY products    FROM '/data/products_clean.csv' WITH (FORMAT csv, HEADER match);
COPY customers   FROM '/data/customers.csv'      WITH (FORMAT csv, HEADER match);
COPY orders      FROM '/data/orders.csv'         WITH (FORMAT csv, HEADER match);
COPY order_items FROM '/data/order_items.csv'    WITH (FORMAT csv, HEADER match);
COPY payments    FROM '/data/payments.csv'       WITH (FORMAT csv, HEADER match);
COPY shipments   FROM '/data/shipments.csv'      WITH (FORMAT csv, HEADER match);
COPY reviews     FROM '/data/reviews_clean.csv'  WITH (FORMAT csv, HEADER match);

-- move each ID counter past the loaded IDs, so new rows get fresh IDs
SELECT setval(pg_get_serial_sequence('products', 'id'),             (SELECT max(id) FROM products));
SELECT setval(pg_get_serial_sequence('customers', 'customer_id'),   (SELECT max(customer_id) FROM customers));
SELECT setval(pg_get_serial_sequence('orders', 'order_id'),         (SELECT max(order_id) FROM orders));
SELECT setval(pg_get_serial_sequence('order_items', 'order_item_id'), (SELECT max(order_item_id) FROM order_items));
SELECT setval(pg_get_serial_sequence('payments', 'payment_id'),     (SELECT max(payment_id) FROM payments));
SELECT setval(pg_get_serial_sequence('shipments', 'shipment_id'),   (SELECT max(shipment_id) FROM shipments));
SELECT setval(pg_get_serial_sequence('reviews', 'review_id'),       (SELECT max(review_id) FROM reviews));

COMMIT;
