-- Load the generated CSVs (mounted at /data inside the container). Safe to re-run.
BEGIN;

-- empty all tables first so re-running doesn't duplicate rows
TRUNCATE reviews, shipments, payments, order_items, orders, customers, products, sellers CASCADE;

-- parents before children, because of the foreign keys
COPY sellers     FROM '/data/sellers.csv'        WITH (FORMAT csv, HEADER match);

-- products_clean.csv has no seller column: load the products, then set seller_id from product_sellers.csv
ALTER TABLE products ALTER COLUMN seller_id DROP NOT NULL;
COPY products (id, source_asin, source_url, name, full_title, category, description, original_price, price,
               currency, image_url, brand, color, material, width_cm, depth_cm, height_cm, dimension_source,
               rating, rating_count, stock_quantity, active)
    FROM '/data/products_clean.csv' WITH (FORMAT csv, HEADER match);
CREATE TEMP TABLE product_sellers (product_id INTEGER PRIMARY KEY, seller_id INTEGER NOT NULL) ON COMMIT DROP;
COPY product_sellers FROM '/data/product_sellers.csv' WITH (FORMAT csv, HEADER match);
UPDATE products p SET seller_id = ps.seller_id FROM product_sellers ps WHERE ps.product_id = p.id;
ALTER TABLE products ALTER COLUMN seller_id SET NOT NULL;  -- the whole load fails if any product has no seller

COPY customers   FROM '/data/customers.csv'      WITH (FORMAT csv, HEADER match);
COPY orders      FROM '/data/orders.csv'         WITH (FORMAT csv, HEADER match);
COPY order_items FROM '/data/order_items.csv'    WITH (FORMAT csv, HEADER match);
COPY payments    FROM '/data/payments.csv'       WITH (FORMAT csv, HEADER match);
COPY shipments   FROM '/data/shipments.csv'      WITH (FORMAT csv, HEADER match);
COPY reviews     FROM '/data/reviews_clean.csv'  WITH (FORMAT csv, HEADER match);

-- move each ID counter past the loaded IDs, so new rows get fresh IDs
SELECT setval(pg_get_serial_sequence('sellers', 'seller_id'),     (SELECT max(seller_id) FROM sellers));
SELECT setval(pg_get_serial_sequence('products', 'id'),             (SELECT max(id) FROM products));
SELECT setval(pg_get_serial_sequence('customers', 'customer_id'),   (SELECT max(customer_id) FROM customers));
SELECT setval(pg_get_serial_sequence('orders', 'order_id'),         (SELECT max(order_id) FROM orders));
SELECT setval(pg_get_serial_sequence('order_items', 'order_item_id'), (SELECT max(order_item_id) FROM order_items));
SELECT setval(pg_get_serial_sequence('payments', 'payment_id'),     (SELECT max(payment_id) FROM payments));
SELECT setval(pg_get_serial_sequence('shipments', 'shipment_id'),   (SELECT max(shipment_id) FROM shipments));
SELECT setval(pg_get_serial_sequence('reviews', 'review_id'),       (SELECT max(review_id) FROM reviews));

COMMIT;
