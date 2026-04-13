#!/usr/bin/env bash
# seed_data.sh — Insert sample data for development and testing
set -euo pipefail

AUTH_HOST="${AUTH_DB_HOST:-localhost}"
AUTH_PORT="${AUTH_DB_PORT:-5433}"
PRODUCT_HOST="${PRODUCT_DB_HOST:-localhost}"
PRODUCT_PORT="${PRODUCT_DB_PORT:-5434}"
PRODUCT_ITEMS_PER_CATEGORY="${PRODUCT_ITEMS_PER_CATEGORY:-1000}"
PRODUCT_DESCRIPTION_REPEAT="${PRODUCT_DESCRIPTION_REPEAT:-8}"

if ! [[ "${PRODUCT_ITEMS_PER_CATEGORY}" =~ ^[1-9][0-9]*$ ]]; then
    echo "❌ PRODUCT_ITEMS_PER_CATEGORY must be a positive integer, got: ${PRODUCT_ITEMS_PER_CATEGORY}" >&2
    exit 1
fi

if ! [[ "${PRODUCT_DESCRIPTION_REPEAT}" =~ ^[1-9][0-9]*$ ]]; then
    echo "❌ PRODUCT_DESCRIPTION_REPEAT must be a positive integer, got: ${PRODUCT_DESCRIPTION_REPEAT}" >&2
    exit 1
fi

TOTAL_TARGET_PRODUCTS=$((PRODUCT_ITEMS_PER_CATEGORY * 10 + 20))

echo "🌱 Seeding sample data..."
echo "  Target items per category: ${PRODUCT_ITEMS_PER_CATEGORY}"
echo "  Description repeat factor: ${PRODUCT_DESCRIPTION_REPEAT}"

if kubectl get pod product-db-0 -n ecommerce >/dev/null 2>&1; then
    echo "  Running in Kubernetes cluster, using kubectl exec..."
    CMD="kubectl exec -i product-db-0 -n ecommerce -- psql -U product_user -d product_db"
else
    CMD="docker compose exec -T product-db psql -U ${PRODUCT_DB_USER:-product_user} -d ${PRODUCT_DB_NAME:-product_db}"
fi

# Seed categories and a large search-heavy catalog into product DB
# The generated product names are deterministic, so increasing
# PRODUCT_ITEMS_PER_CATEGORY grows the catalog idempotently.
$CMD <<SQL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

INSERT INTO categories (name, description, created_at) VALUES
    ('Electronics', 'Gadgets, phones, laptops, and accessories', now()),
    ('Clothing', 'Men and apparel', now()),
    ('Books', 'Fiction, non-fiction, and textbooks', now()),
    ('Home & Kitchen', 'Furniture, cookware, and decor', now()),
    ('Sports', 'Equipment, clothing, and accessories', now()),
    ('Toys', 'Games, puzzles, and kids items', now()),
    ('Beauty', 'Skincare, makeup, and grooming', now()),
    ('Automotive', 'Car parts and accessories', now()),
    ('Garden', 'Plants, tools, and outdoor furniture', now()),
    ('Food', 'Snacks, beverages, and gourmet items', now())
ON CONFLICT DO NOTHING;

WITH starter_products(name, description, price, stock, category_name, image_url) AS (
    VALUES
        ('Wireless Headphones', 'Noise-cancelling Bluetooth headphones', 149.99, 100, 'Electronics', 'https://placehold.co/400x400?text=Headphones'),
        ('Laptop Stand', 'Adjustable aluminum laptop stand', 49.99, 200, 'Electronics', 'https://placehold.co/400x400?text=LaptopStand'),
        ('USB-C Hub', '7-in-1 USB-C hub with HDMI', 39.99, 150, 'Electronics', 'https://placehold.co/400x400?text=USBHub'),
        ('Mechanical Keyboard', 'Cherry MX Brown switches, RGB backlit', 129.99, 75, 'Electronics', 'https://placehold.co/400x400?text=Keyboard'),
        ('Wireless Mouse', 'Ergonomic wireless mouse, 2.4GHz', 29.99, 300, 'Electronics', 'https://placehold.co/400x400?text=Mouse'),
        ('Cotton T-Shirt', 'Premium cotton crew neck t-shirt', 24.99, 500, 'Clothing', 'https://placehold.co/400x400?text=TShirt'),
        ('Denim Jeans', 'Slim fit denim jeans', 59.99, 200, 'Clothing', 'https://placehold.co/400x400?text=Jeans'),
        ('Running Shoes', 'Lightweight running shoes', 89.99, 150, 'Sports', 'https://placehold.co/400x400?text=Shoes'),
        ('Yoga Mat', 'Non-slip exercise yoga mat', 34.99, 250, 'Sports', 'https://placehold.co/400x400?text=YogaMat'),
        ('Python Cookbook', 'Advanced Python recipes and patterns', 44.99, 100, 'Books', 'https://placehold.co/400x400?text=PythonBook'),
        ('Clean Code', 'Robert C. Martin - Clean Code', 39.99, 120, 'Books', 'https://placehold.co/400x400?text=CleanCode'),
        ('Coffee Maker', 'Drip coffee maker, 12-cup capacity', 79.99, 80, 'Home & Kitchen', 'https://placehold.co/400x400?text=CoffeeMaker'),
        ('Cast Iron Skillet', '12-inch pre-seasoned cast iron skillet', 34.99, 90, 'Home & Kitchen', 'https://placehold.co/400x400?text=Skillet'),
        ('Board Game Set', 'Classic board game collection', 49.99, 60, 'Toys', 'https://placehold.co/400x400?text=BoardGame'),
        ('Face Moisturizer', 'Daily hydrating face moisturizer', 19.99, 400, 'Beauty', 'https://placehold.co/400x400?text=Moisturizer'),
        ('Car Phone Mount', 'Magnetic dashboard phone mount', 14.99, 350, 'Automotive', 'https://placehold.co/400x400?text=PhoneMount'),
        ('Garden Tool Set', '5-piece stainless steel garden tools', 29.99, 180, 'Garden', 'https://placehold.co/400x400?text=GardenTools'),
        ('Organic Coffee Beans', '1kg premium organic coffee beans', 24.99, 200, 'Food', 'https://placehold.co/400x400?text=CoffeeBeans'),
        ('Smartwatch', 'Fitness tracker with heart rate monitor', 199.99, 100, 'Electronics', 'https://placehold.co/400x400?text=Smartwatch'),
        ('Backpack', 'Water-resistant laptop backpack', 64.99, 175, 'Clothing', 'https://placehold.co/400x400?text=Backpack')
)
INSERT INTO products (id, name, description, price, stock, category_id, image_url, is_deleted, created_at, updated_at)
SELECT
    uuid_generate_v4(),
    sp.name,
    sp.description,
    sp.price,
    sp.stock,
    c.id,
    sp.image_url,
    false,
    now(),
    now()
FROM starter_products sp
JOIN categories c ON c.name = sp.category_name
WHERE NOT EXISTS (
    SELECT 1
    FROM products p
    WHERE p.name = sp.name
);

WITH search_terms(keyword, term_index) AS (
    VALUES
        ('Laptop', 1),
        ('Phone', 2),
        ('Camera', 3),
        ('Headphones', 4),
        ('Keyboard', 5),
        ('Monitor', 6),
        ('Speaker', 7),
        ('Charger', 8)
),
category_pool AS (
    SELECT id, name, ROW_NUMBER() OVER (ORDER BY id) AS category_index
    FROM categories
),
generated_catalog AS (
    SELECT
        cp.id AS category_id,
        cp.name AS category_name,
        gs.seq,
        st.keyword,
        FORMAT('%s %s Recovery Catalog Item %s', st.keyword, cp.name, gs.seq) AS product_name,
        FORMAT(
            '%s %s recovery benchmark item %s. %s',
            st.keyword,
            cp.name,
            gs.seq,
            repeat(FORMAT('%s autoscaling search workload detail for %s category. ', st.keyword, cp.name), ${PRODUCT_DESCRIPTION_REPEAT})
        ) AS product_description,
        ROUND((19.99 + (((gs.seq - 1) % 250) * 3.15) + cp.category_index)::numeric, 2) AS product_price,
        25 + ((gs.seq * 13 + cp.category_index * 17) % 475) AS product_stock,
        FORMAT(
            'https://placehold.co/400x400?text=%s%s%s',
            regexp_replace(st.keyword, '[[:space:]]+', '', 'g'),
            regexp_replace(cp.name, '[[:space:]&]+', '', 'g'),
            gs.seq
        ) AS product_image
    FROM category_pool cp
    CROSS JOIN generate_series(1, ${PRODUCT_ITEMS_PER_CATEGORY}) AS gs(seq)
    JOIN search_terms st
      ON (((gs.seq + cp.category_index - 2) % 8) + 1) = st.term_index
)
INSERT INTO products (id, name, description, price, stock, category_id, image_url, is_deleted, created_at, updated_at)
SELECT
    uuid_generate_v4(),
    gc.product_name,
    gc.product_description,
    gc.product_price,
    gc.product_stock,
    gc.category_id,
    gc.product_image,
    false,
    now(),
    now()
FROM generated_catalog gc
WHERE NOT EXISTS (
    SELECT 1
    FROM products p
    WHERE p.name = gc.product_name
);
SQL
if [ -n "${PGPASSWORD:-}" ]; then unset PGPASSWORD; fi

echo "✅ Seeded 10 categories + starter catalog + recovery dataset (target ~${TOTAL_TARGET_PRODUCTS} products)."
echo ""
echo "To create test users, POST to http://localhost:8080/auth/register"
