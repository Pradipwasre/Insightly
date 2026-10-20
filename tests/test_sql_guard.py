import pytest

from insightly.agent.sql_guard import check_sql

ALLOWED = {"orders", "order_items", "products", "users"}


def test_select_is_allowed_and_limited():
    r = check_sql("SELECT o.status, COUNT(*) AS n FROM orders AS o GROUP BY 1", ALLOWED, 100)
    assert r.ok and "LIMIT 100" in r.sql and r.tables == ["orders"]


def test_existing_limit_kept():
    r = check_sql("SELECT * FROM orders LIMIT 5", ALLOWED, 100)
    assert r.ok and "LIMIT 5" in r.sql and "LIMIT 100" not in r.sql


def test_cte_names_are_not_tables():
    sql = "WITH x AS (SELECT user_id FROM orders) SELECT COUNT(*) FROM x"
    assert check_sql(sql, ALLOWED).ok


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "DELETE FROM orders",
        "INSERT INTO orders VALUES (1)",
        "UPDATE orders SET status = 'x'",
        "CREATE TABLE t AS SELECT 1",
        "SELECT 1; DROP TABLE orders",
    ],
)
def test_writes_and_multi_statements_blocked(sql):
    assert not check_sql(sql, ALLOWED).ok


def test_unknown_table_blocked():
    r = check_sql("SELECT * FROM users_pii", ALLOWED)
    assert not r.ok and "not allowed" in r.error


def test_other_database_blocked():
    assert not check_sql("SELECT * FROM finance.salaries", ALLOWED | {"salaries"}).ok


def test_pii_column_blocked():
    r = check_sql("SELECT email FROM users", ALLOWED)
    assert not r.ok and "PII" in r.error


def test_unparseable():
    assert not check_sql("SELEC FROM WHERE", ALLOWED).ok
