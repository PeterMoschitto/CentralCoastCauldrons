# Version 4 - Develop a Data-Driven Shop Strategy

## Metric 1 — Time series: sales per potion by hour

Checkout writes each line item to sale_events as(`potion_sku`, `quantity`, `sold_at`, plus `sold_day` / `sold_hour`). Join `potions` so I only chart SKUs that exist in my catalog.

### SQL — hourly timeline

Buckets sales by calendar hour using `sold_at` so the chart reads left to right through real time

```sql
SELECT
  date_trunc('hour', sale_events.sold_at) AS sale_hour,
  potions.sku,
  potions.name AS potion_name,
  SUM(sale_events.quantity) AS units_sold
FROM sale_events
JOIN potions ON potions.sku = sale_events.potion_sku
GROUP BY date_trunc('hour', sale_events.sold_at), potions.sku, potions.name
ORDER BY sale_hour, potions.sku;
```

---

## Metric 2 — Barrel types: offering time, liquid, cost per ml


---

## Metric 3 — Class, species, and level vs potion type

Checkout logs `character_class`, `character_species`, and `level` on each `sale_events` row. Join `potions` on `potion_sku` so potion type uses my catalog `name`

I also used `COALESCE(..., 'unknown')` so missing demographics from older rows do not drop out of the join

### SQL — units sold by character class and potion

```sql
SELECT
  COALESCE(sale_events.character_class, 'unknown') AS character_class,
  potions.name AS potion_name,
  SUM(sale_events.quantity) AS units_sold
FROM sale_events
JOIN potions ON potions.sku = sale_events.potion_sku
GROUP BY COALESCE(sale_events.character_class, 'unknown'), potions.name
ORDER BY character_class, potion_name;
```

### SQL — units sold by species and potion

```sql
SELECT
  COALESCE(sale_events.character_species, 'unknown') AS character_species,
  potions.name AS potion_name,
  SUM(sale_events.quantity) AS units_sold
FROM sale_events
JOIN potions ON potions.sku = sale_events.potion_sku
GROUP BY COALESCE(sale_events.character_species, 'unknown'), potions.name
ORDER BY character_species, potion_name;
```

### SQL — units sold by level and potion
```sql
SELECT
  sale_events.level AS customer_level,
  potions.name AS potion_name,
  SUM(sale_events.quantity) AS units_sold
FROM sale_events
JOIN potions ON potions.sku = sale_events.potion_sku
WHERE sale_events.level IS NOT NULL
GROUP BY sale_events.level, potions.name
ORDER BY customer_level, potion_name;
```

---

## Metric 4 — Gold revenue by potion 

### SQL — total gold revenue per potion type

```sql
SELECT
  potions.name AS potion_name,
  SUM(sale_events.quantity * sale_events.unit_price) AS gold_revenue
FROM sale_events
JOIN potions ON potions.sku = sale_events.potion_sku
GROUP BY potions.name
ORDER BY gold_revenue DESC;
```