# Data catalog (source dataset)

> Raw source description. The curated tables the agent sees are defined in
> `semantic_layer/tables.yaml`; curation rules are in `src/insightly/data/curate.py`.

- Purpose: single reference for the datasets going into production for the GenAI project
- Domain: online fashion retail (Women and Men apparel), global customers, 10 US distribution centers
- Period covered: 2019-01 to 2024-03
- Format: 7 CSV files, same data also intended for `ecommerce.db` (SQLite)
- Timestamp format in every file: text like `2023-09-23 08:12:00 UTC` (some have microseconds). Parse as UTC datetime.

## 1. File Inventory

- `distribution_centers.csv`: 10 rows, 4 cols, 369 B. Warehouse master data
- `products.csv`: 29,120 rows, 9 cols, 4.3 MB. Product catalog
- `users.csv`: 100,000 rows, 15 cols, 16.6 MB. Customer profiles
- `orders.csv`: 125,530 rows, 9 cols, 9.8 MB. One row per order
- `order_items.csv`: 181,891 rows, 11 cols, 19 MB. One row per item inside an order
- `inventory_items.csv`: 491,098 rows, 12 cols, 92.5 MB. One row per physical stock unit
- `events.csv`: 2,427,931 rows, 13 cols, 385.6 MB. Website clickstream
- `ecommerce.db`: uploaded file is 0 bytes (empty). Rebuild it from the CSVs before use
- `ecommerce-data-description.docx`: original column descriptions (source of the descriptions below)

## 2. Relationships (all foreign keys verified, 100% match, no orphans)

- `products.distribution_center_id` -> `distribution_centers.id`
- `inventory_items.product_id` -> `products.id`
- `inventory_items.product_distribution_center_id` -> `distribution_centers.id`
- `orders.user_id` -> `users.id`
- `order_items.order_id` -> `orders.order_id`
- `order_items.user_id` -> `users.id`
- `order_items.product_id` -> `products.id`
- `order_items.inventory_item_id` -> `inventory_items.id`
- `events.user_id` -> `users.id` (nullable, see notes)
- Join path for revenue by category: `order_items` -> `products` (category)
- Join path for user behavior: `events` -> `users` -> `orders`

## 3. Table Details

### distribution_centers
- id (INTEGER, PK): distribution center id, 1 to 10
- name (STRING): city and state label, e.g. `Memphis TN`, `Chicago IL`, `Houston TX`, `Los Angeles CA`, `New Orleans LA`, `Port Authority of New York/New Jersey NY/NJ`, `Philadelphia PA`, `Mobile AL`, `Charleston SC`, `Savannah GA`
- latitude (FLOAT): latitude of the center
- longitude (FLOAT): longitude of the center

### products
- id (INTEGER, PK): product id
- cost (FLOAT): acquisition cost. Range 0.008 to 557.15, mean 28.48
- category (STRING): 26 values, e.g. Intimates, Jeans, Tops & Tees, Fashion Hoodies & Sweatshirts, Swim, Sleep & Lounge, Shorts, Sweaters, Accessories, Active, Outerwear & Coats, Dresses, Maternity, Leggings
- name (STRING): product name. 2 nulls
- brand (STRING): 2,756 distinct brands. 24 nulls
- retail_price (FLOAT): selling price. Range 0.02 to 999, mean 59.22
- department (STRING): `Women` (15,989) or `Men` (13,131)
- sku (STRING): 32-char hash identifier
- distribution_center_id (INTEGER, FK): home distribution center

### users
- id (INTEGER, PK)
- first_name, last_name, email (STRING): personal data (PII)
- age (INTEGER): 12 to 70, mean 41
- gender (STRING): `F` (50,312) or `M` (49,688)
- state (STRING): 229 distinct values
- street_address, postal_code, city (STRING): city has 1,046 nulls
- country (STRING): 16 values. Top: China 33.8k, United States 22.6k, Brasil 14.9k, South Korea 5.4k, France 4.7k, United Kingdom 4.6k, Germany 4.0k, Spain 3.9k, Japan 2.4k, Australia 2.1k
- latitude, longitude (FLOAT): user location
- traffic_source (STRING): Search 69,961, Organic 15,016, Facebook 5,898, Email 5,045, Display 4,080
- created_at (TIMESTAMP): signup time, 2019-01-02 to 2024-02-25

### orders
- order_id (INTEGER, PK)
- user_id (INTEGER, FK)
- status (STRING): Shipped 37,813, Complete 31,122, Processing 25,211, Cancelled 18,967, Returned 12,417
- gender (STRING): `F` 63,150, `M` 62,380 (copied from the user)
- created_at (TIMESTAMP): 2019-01-16 to 2024-02-26
- returned_at (TIMESTAMP): null for 113,113 rows (not returned)
- shipped_at (TIMESTAMP): null for 44,178 rows
- delivered_at (TIMESTAMP): null for 81,991 rows
- num_of_item (INTEGER): 1 to 4, mean 1.45

### order_items
- id (INTEGER, PK)
- order_id (INTEGER, FK)
- user_id (INTEGER, FK)
- product_id (INTEGER, FK)
- inventory_item_id (INTEGER, FK)
- status (STRING): Shipped 54,943, Complete 44,889, Processing 36,440, Cancelled 27,474, Returned 18,145
- created_at (TIMESTAMP): 2019-01-17 to 2024-03-01
- shipped_at (TIMESTAMP): null for 63,914 rows
- delivered_at (TIMESTAMP): null for 118,857 rows
- returned_at (TIMESTAMP): null for 163,746 rows
- sale_price (FLOAT): 0.02 to 999, mean 59.61

### inventory_items
- id (INTEGER, PK)
- product_id (INTEGER, FK)
- created_at (TIMESTAMP): stock added, 2018-11-22 to 2024-03-01
- sold_at (TIMESTAMP): null for 309,207 rows (still unsold)
- cost (FLOAT)
- product_category, product_name, product_brand, product_retail_price, product_department, product_sku (denormalized copy of products). name has 31 nulls, brand has 389 nulls
- product_distribution_center_id (INTEGER, FK)

### events
- id (INTEGER, PK)
- user_id (INTEGER, FK): null for 1,125,088 rows (anonymous visitors)
- sequence_number (INTEGER): order of the event inside a session, 1 to 13
- session_id (STRING): UUID
- created_at (TIMESTAMP): 2019-01-02 to 2024-03-01
- ip_address, city, state, postal_code (STRING): visitor location
- browser (STRING): Chrome 1,214,885, Safari 485,282, Firefox 484,712, IE 122,399, Other 120,653
- traffic_source (STRING): Email 1,089,815, Adwords 730,878, Facebook 245,620, YouTube 242,502, Organic 119,116
- uri (STRING): page path, 35,530 distinct values
- event_type (STRING): product 844,365, cart 594,770, department 594,407, purchase 181,891, cancel 124,641, home 87,857

## 4. Business Rules and Gotchas

- Null shipped_at, delivered_at, returned_at is normal and means the stage was never reached
- `purchase` events (181,891) equal the number of `order_items` rows
- `orders.status` and `order_items.status` are separate. An item can differ from its parent order
- Revenue should usually exclude `Cancelled` and `Returned` items
- Profit per item = `order_items.sale_price` minus `inventory_items.cost`
- Category overlaps exist: `Socks` and `Socks & Hosiery`, `Pants` and `Pants & Capris`, `Suits` and `Suits & Sport Coats`. Group them if reporting at a high level
- `users.traffic_source` uses `Search`, but `events.traffic_source` uses `Adwords`. Values are not the same vocabulary
- `users.country` uses `Brasil` spelling
- `users` contains PII (name, email, address). Mask or exclude before sending to any LLM
- Some rows have very low prices (0.02), likely test or dirty data. Check before price analysis
- Total size is about 530 MB, so never load full CSVs into a prompt. Use SQL or sampled schema only
