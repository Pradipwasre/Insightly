"""Synthetic generator for the TheLook-style e-commerce schema.

Produces the same 7 CSV files, columns and value vocabularies as the real dataset described
in ``docs/data-catalog.md``, at a configurable scale. It lets CI, tests and a first demo run
without downloading 530 MB. For the real data, see "Get the data" in the README.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd

DCS = [
    (1, "Memphis TN", 35.1174, -89.9711),
    (2, "Chicago IL", 41.8369, -87.6847),
    (3, "Houston TX", 29.7604, -95.3698),
    (4, "Los Angeles CA", 34.05, -118.25),
    (5, "New Orleans LA", 29.95, -90.0667),
    (6, "Port Authority of New York/New Jersey NY/NJ", 40.634, -73.7834),
    (7, "Philadelphia PA", 39.95, -75.1667),
    (8, "Mobile AL", 30.6944, -88.0431),
    (9, "Charleston SC", 32.7833, -79.9333),
    (10, "Savannah GA", 32.0167, -81.1167),
]
CATEGORIES = [
    "Intimates",
    "Jeans",
    "Tops & Tees",
    "Fashion Hoodies & Sweatshirts",
    "Swim",
    "Sleep & Lounge",
    "Shorts",
    "Sweaters",
    "Accessories",
    "Active",
    "Outerwear & Coats",
    "Dresses",
    "Maternity",
    "Leggings",
    "Socks",
    "Socks & Hosiery",
    "Pants",
    "Pants & Capris",
    "Suits",
    "Suits & Sport Coats",
    "Underwear",
    "Blazers & Jackets",
    "Skirts",
    "Plus",
    "Jumpsuits & Rompers",
    "Clothing Sets",
]
BRANDS = [
    "Allegra K",
    "Calvin Klein",
    "Levi's",
    "Carhartt",
    "Columbia",
    "Hanes",
    "Nike",
    "Tommy Hilfiger",
    "Ralph Lauren",
    "Champion",
    "Puma",
    "Diesel",
    "Wrangler",
]
COUNTRIES = (
    [
        "China",
        "United States",
        "Brasil",
        "South Korea",
        "France",
        "United Kingdom",
        "Germany",
        "Spain",
        "Japan",
        "Australia",
    ],
    [0.34, 0.23, 0.15, 0.06, 0.05, 0.05, 0.04, 0.04, 0.02, 0.02],
)
USER_TRAFFIC = (["Search", "Organic", "Facebook", "Email", "Display"], [0.70, 0.15, 0.06, 0.05, 0.04])
EVENT_TRAFFIC = (["Email", "Adwords", "Facebook", "YouTube", "Organic"], [0.45, 0.30, 0.10, 0.10, 0.05])
BROWSERS = (["Chrome", "Safari", "Firefox", "IE", "Other"], [0.50, 0.20, 0.20, 0.05, 0.05])
STATUSES = (["Shipped", "Complete", "Processing", "Cancelled", "Returned"], [0.30, 0.25, 0.20, 0.15, 0.10])
START = pd.Timestamp("2019-01-02", tz="UTC")
END = pd.Timestamp("2024-03-01", tz="UTC")


def _ts(series: pd.Series) -> pd.Series:
    return series.dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def generate(out_dir: Path, n_users: int = 5000, seed: int = 7) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    span_s = int((END - START).total_seconds())

    def rand_time(n: int, lo: pd.Timestamp = START) -> pd.Series:
        lo_s = (lo - START).total_seconds() if isinstance(lo, pd.Timestamp) else 0
        return pd.Series(START + pd.to_timedelta(rng.integers(lo_s, span_s, n), unit="s"))

    # distribution_centers
    dcs = pd.DataFrame(DCS, columns=["id", "name", "latitude", "longitude"])

    # products
    n_products = max(200, n_users // 5)
    cost = np.round(rng.gamma(2.0, 14.0, n_products) + 0.5, 2)
    markup = rng.uniform(1.6, 2.6, n_products)
    retail = np.round(cost * markup, 2)
    retail[rng.choice(n_products, 3, replace=False)] = 0.02  # known dirty rows
    products = pd.DataFrame(
        {
            "id": np.arange(1, n_products + 1),
            "cost": cost,
            "category": rng.choice(CATEGORIES, n_products),
            "name": [f"Item {i}" for i in range(1, n_products + 1)],
            "brand": rng.choice(BRANDS, n_products),
            "retail_price": retail,
            "department": rng.choice(["Women", "Men"], n_products, p=[0.55, 0.45]),
            "sku": [uuid.UUID(int=int(rng.integers(0, 2**63))).hex for _ in range(n_products)],
            "distribution_center_id": rng.integers(1, 11, n_products),
        }
    )

    # users
    created = rand_time(n_users)
    users = pd.DataFrame(
        {
            "id": np.arange(1, n_users + 1),
            "first_name": rng.choice(["Asha", "Ravi", "Mei", "John", "Ana", "Kim", "Lea"], n_users),
            "last_name": rng.choice(["Patil", "Chen", "Smith", "Silva", "Park", "Martin"], n_users),
            "email": [f"user{i}@example.com" for i in range(1, n_users + 1)],
            "age": rng.integers(12, 71, n_users),
            "gender": rng.choice(["F", "M"], n_users),
            "state": rng.choice(
                ["California", "Texas", "Guangdong", "São Paulo", "Seoul", "Île-de-France"], n_users
            ),
            "street_address": [f"{i} Main Street" for i in range(1, n_users + 1)],
            "postal_code": rng.integers(10000, 99999, n_users).astype(str),
            "city": rng.choice(["Shanghai", "New York", "São Paulo", "Seoul", "Paris", "London"], n_users),
            "country": rng.choice(COUNTRIES[0], n_users, p=COUNTRIES[1]),
            "latitude": np.round(rng.uniform(-40, 60, n_users), 4),
            "longitude": np.round(rng.uniform(-120, 140, n_users), 4),
            "traffic_source": rng.choice(USER_TRAFFIC[0], n_users, p=USER_TRAFFIC[1]),
            "created_at": _ts(created),
        }
    )

    # orders
    n_orders = int(n_users * 1.25)
    o_user = rng.integers(1, n_users + 1, n_orders)
    o_created = created.iloc[o_user - 1].reset_index(drop=True) + pd.to_timedelta(
        rng.integers(3600, 400 * 86400, n_orders), unit="s"
    )
    o_created = o_created.clip(upper=END)
    status = rng.choice(STATUSES[0], n_orders, p=STATUSES[1])
    shipped = o_created + pd.to_timedelta(rng.integers(3600, 3 * 86400, n_orders), unit="s")
    delivered = shipped + pd.to_timedelta(rng.integers(86400, 6 * 86400, n_orders), unit="s")
    returned = delivered + pd.to_timedelta(rng.integers(86400, 10 * 86400, n_orders), unit="s")
    shipped = shipped.where(np.isin(status, ["Shipped", "Complete", "Returned"]))
    delivered = delivered.where(np.isin(status, ["Complete", "Returned"]))
    returned = returned.where(status == "Returned")
    num_items = rng.choice([1, 2, 3, 4], n_orders, p=[0.68, 0.2, 0.08, 0.04])
    genders = users["gender"].to_numpy()[o_user - 1]
    orders = pd.DataFrame(
        {
            "order_id": np.arange(1, n_orders + 1),
            "user_id": o_user,
            "status": status,
            "gender": genders,
            "created_at": _ts(o_created),
            "returned_at": _ts(returned),
            "shipped_at": _ts(shipped),
            "delivered_at": _ts(delivered),
            "num_of_item": num_items,
        }
    )

    # order_items + inventory_items (sold units)
    idx = np.repeat(np.arange(n_orders), num_items)
    n_items = len(idx)
    item_product = rng.integers(1, n_products + 1, n_items)
    p = products.set_index("id")
    sale_price = p.loc[item_product, "retail_price"].to_numpy()
    order_items = pd.DataFrame(
        {
            "id": np.arange(1, n_items + 1),
            "order_id": idx + 1,
            "user_id": o_user[idx],
            "product_id": item_product,
            "inventory_item_id": np.arange(1, n_items + 1),
            "status": status[idx],
            "created_at": orders["created_at"].to_numpy()[idx],
            "shipped_at": orders["shipped_at"].to_numpy()[idx],
            "delivered_at": orders["delivered_at"].to_numpy()[idx],
            "returned_at": orders["returned_at"].to_numpy()[idx],
            "sale_price": sale_price,
        }
    )

    n_unsold = n_items * 2
    inv_product = np.concatenate([item_product, rng.integers(1, n_products + 1, n_unsold)])
    n_inv = len(inv_product)
    inv_created = rand_time(n_inv) - pd.Timedelta(days=40)
    sold_at = pd.Series([pd.NaT] * n_inv, dtype="datetime64[ns, UTC]")
    sold_at.iloc[:n_items] = pd.to_datetime(order_items["created_at"], utc=True).to_numpy()
    pi = p.loc[inv_product]
    inventory = pd.DataFrame(
        {
            "id": np.arange(1, n_inv + 1),
            "product_id": inv_product,
            "created_at": _ts(inv_created),
            "sold_at": _ts(sold_at),
            "cost": pi["cost"].to_numpy(),
            "product_category": pi["category"].to_numpy(),
            "product_name": pi["name"].to_numpy(),
            "product_brand": pi["brand"].to_numpy(),
            "product_retail_price": pi["retail_price"].to_numpy(),
            "product_department": pi["department"].to_numpy(),
            "product_sku": pi["sku"].to_numpy(),
            "product_distribution_center_id": pi["distribution_center_id"].to_numpy(),
        }
    )

    # events: product -> cart -> purchase sessions, plus browse-only sessions
    rows = []
    eid = 1
    for _, it in order_items.iterrows():
        sid = uuid.UUID(int=int(rng.integers(0, 2**63))).hex
        t = pd.Timestamp(it["created_at"].replace(" UTC", ""), tz="UTC")
        for seq, et in enumerate(["home", "department", "product", "cart", "purchase"], 1):
            rows.append(
                (
                    eid,
                    int(it["user_id"]),
                    seq,
                    sid,
                    t - pd.Timedelta(minutes=6 - seq),
                    et,
                    f"/{et}/{int(it['product_id'])}",
                )
            )
            eid += 1
    n_browse = n_items * 2
    b_time = rand_time(n_browse)
    for k in range(n_browse):
        sid = uuid.UUID(int=int(rng.integers(0, 2**63))).hex
        uid = int(rng.integers(1, n_users + 1)) if rng.random() < 0.5 else None
        steps = ["home", "department", "product"] + (["cart", "cancel"] if rng.random() < 0.4 else [])
        for seq, et in enumerate(steps, 1):
            rows.append((eid, uid, seq, sid, b_time.iloc[k] + pd.Timedelta(minutes=seq), et, f"/{et}"))
            eid += 1
    ev = pd.DataFrame(
        rows, columns=["id", "user_id", "sequence_number", "session_id", "created_at", "event_type", "uri"]
    )
    n_ev = len(ev)
    ev["user_id"] = ev["user_id"].astype("Int64")
    ev["created_at"] = _ts(pd.to_datetime(ev["created_at"], utc=True))
    ev["ip_address"] = [f"10.0.{i % 255}.{(i // 255) % 255}" for i in range(n_ev)]
    ev["city"] = rng.choice(["Shanghai", "New York", "São Paulo"], n_ev)
    ev["state"] = rng.choice(["Guangdong", "New York", "São Paulo"], n_ev)
    ev["postal_code"] = rng.integers(10000, 99999, n_ev).astype(str)
    ev["browser"] = rng.choice(BROWSERS[0], n_ev, p=BROWSERS[1])
    ev["traffic_source"] = rng.choice(EVENT_TRAFFIC[0], n_ev, p=EVENT_TRAFFIC[1])
    events = ev[
        [
            "id",
            "user_id",
            "sequence_number",
            "session_id",
            "created_at",
            "ip_address",
            "city",
            "state",
            "postal_code",
            "browser",
            "traffic_source",
            "uri",
            "event_type",
        ]
    ]

    tables = {
        "distribution_centers": dcs,
        "products": products,
        "users": users,
        "orders": orders,
        "order_items": order_items,
        "inventory_items": inventory,
        "events": events,
    }
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    return {name: len(df) for name, df in tables.items()}
