#!/usr/bin/env bash
# seed_data.sh — Insert sample data for development and testing
set -euo pipefail

AUTH_HOST="${AUTH_DB_HOST:-localhost}"
AUTH_PORT="${AUTH_DB_PORT:-5433}"
PRODUCT_HOST="${PRODUCT_DB_HOST:-localhost}"
PRODUCT_PORT="${PRODUCT_DB_PORT:-5434}"

echo "🌱 Seeding sample data..."

if kubectl get pod product-db-0 -n ecommerce >/dev/null 2>&1; then
    echo "  Running in Kubernetes cluster, using kubectl exec..."
    CMD="kubectl exec -i product-db-0 -n ecommerce -- psql -U product_user -d product_db"
else
    CMD="docker compose exec -T product-db psql -U ${PRODUCT_DB_USER:-product_user} -d ${PRODUCT_DB_NAME:-product_db}"
fi

# Seed categories into product DB
$CMD <<'SQL'
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

INSERT INTO products (id, name, description, price, stock, category_id, image_url, is_deleted, created_at, updated_at) VALUES
    (gen_random_uuid(), 'Wireless Headphones',   'Noise-cancelling Bluetooth headphones',   149.99, 100, (SELECT id FROM categories WHERE name = 'Electronics'), 'https://placehold.co/400x400?text=Headphones', false, now(), now()),
    (gen_random_uuid(), 'Laptop Stand',          'Adjustable aluminum laptop stand',         49.99,  200, (SELECT id FROM categories WHERE name = 'Electronics'), 'https://placehold.co/400x400?text=LaptopStand', false, now(), now()),
    (gen_random_uuid(), 'USB-C Hub',             '7-in-1 USB-C hub with HDMI',              39.99,  150, (SELECT id FROM categories WHERE name = 'Electronics'), 'https://placehold.co/400x400?text=USBHub', false, now(), now()),
    (gen_random_uuid(), 'Mechanical Keyboard',   'Cherry MX Brown switches, RGB backlit',   129.99,  75, (SELECT id FROM categories WHERE name = 'Electronics'), 'https://placehold.co/400x400?text=Keyboard', false, now(), now()),
    (gen_random_uuid(), 'Wireless Mouse',        'Ergonomic wireless mouse, 2.4GHz',        29.99,  300, (SELECT id FROM categories WHERE name = 'Electronics'), 'https://placehold.co/400x400?text=Mouse', false, now(), now()),
    (gen_random_uuid(), 'Cotton T-Shirt',        'Premium cotton crew neck t-shirt',         24.99,  500, (SELECT id FROM categories WHERE name = 'Clothing'), 'https://placehold.co/400x400?text=TShirt', false, now(), now()),
    (gen_random_uuid(), 'Denim Jeans',           'Slim fit denim jeans',                     59.99,  200, (SELECT id FROM categories WHERE name = 'Clothing'), 'https://placehold.co/400x400?text=Jeans', false, now(), now()),
    (gen_random_uuid(), 'Running Shoes',         'Lightweight running shoes',                89.99,  150, (SELECT id FROM categories WHERE name = 'Sports'), 'https://placehold.co/400x400?text=Shoes', false, now(), now()),
    (gen_random_uuid(), 'Yoga Mat',              'Non-slip exercise yoga mat',               34.99,  250, (SELECT id FROM categories WHERE name = 'Sports'), 'https://placehold.co/400x400?text=YogaMat', false, now(), now()),
    (gen_random_uuid(), 'Python Cookbook',        'Advanced Python recipes and patterns',     44.99,  100, (SELECT id FROM categories WHERE name = 'Books'), 'https://placehold.co/400x400?text=PythonBook', false, now(), now()),
    (gen_random_uuid(), 'Clean Code',            'Robert C. Martin - Clean Code',            39.99,  120, (SELECT id FROM categories WHERE name = 'Books'), 'https://placehold.co/400x400?text=CleanCode', false, now(), now()),
    (gen_random_uuid(), 'Coffee Maker',          'Drip coffee maker, 12-cup capacity',      79.99,  80,  (SELECT id FROM categories WHERE name = 'Home & Kitchen'), 'https://placehold.co/400x400?text=CoffeeMaker', false, now(), now()),
    (gen_random_uuid(), 'Cast Iron Skillet',     '12-inch pre-seasoned cast iron skillet',   34.99,  90,  (SELECT id FROM categories WHERE name = 'Home & Kitchen'), 'https://placehold.co/400x400?text=Skillet', false, now(), now()),
    (gen_random_uuid(), 'Board Game Set',        'Classic board game collection',            49.99,  60,  (SELECT id FROM categories WHERE name = 'Toys'), 'https://placehold.co/400x400?text=BoardGame', false, now(), now()),
    (gen_random_uuid(), 'Face Moisturizer',      'Daily hydrating face moisturizer',         19.99,  400, (SELECT id FROM categories WHERE name = 'Beauty'), 'https://placehold.co/400x400?text=Moisturizer', false, now(), now()),
    (gen_random_uuid(), 'Car Phone Mount',       'Magnetic dashboard phone mount',           14.99,  350, (SELECT id FROM categories WHERE name = 'Automotive'), 'https://placehold.co/400x400?text=PhoneMount', false, now(), now()),
    (gen_random_uuid(), 'Garden Tool Set',       '5-piece stainless steel garden tools',     29.99,  180, (SELECT id FROM categories WHERE name = 'Garden'), 'https://placehold.co/400x400?text=GardenTools', false, now(), now()),
    (gen_random_uuid(), 'Organic Coffee Beans',  '1kg premium organic coffee beans',         24.99,  200, (SELECT id FROM categories WHERE name = 'Food'),'https://placehold.co/400x400?text=CoffeeBeans', false, now(), now()),
    (gen_random_uuid(), 'Smartwatch',            'Fitness tracker with heart rate monitor', 199.99,  100, (SELECT id FROM categories WHERE name = 'Electronics'), 'https://placehold.co/400x400?text=Smartwatch', false, now(), now()),
    (gen_random_uuid(), 'Backpack',              'Water-resistant laptop backpack',           64.99,  175, (SELECT id FROM categories WHERE name = 'Clothing'), 'https://placehold.co/400x400?text=Backpack', false, now(), now())
ON CONFLICT DO NOTHING;
SQL
if [ -n "${PGPASSWORD:-}" ]; then unset PGPASSWORD; fi

echo "✅ Seeded 10 categories + 20 products."
echo ""
echo "To create test users, POST to http://localhost:8080/auth/register"
