"""
SQL tools against a real business database (the demo shop, read-only role, row-level security):
parameterized templates, user_id from the verified caller, output minimisation, timeouts, and
the EVAL-09 hard gates (anonymous never reaches a private tool; user A never gets user B's rows).
"""

import json
from datetime import date
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url

from core.agent.tools.registry import ToolRegistry
from core.agent.tools.sql_tool import SqlTool, SqlToolDefinitionError, SqlToolSpec
from core.agent.tools.sql_tool_executor import SqlToolExecutor
from core.storage.business_db_probe import BusinessDbProbe
from core.storage.database import Database
from models.tool_context import ToolContext
from services.errors import InvalidRequestError
from services.sql_tool_catalog import SqlToolCatalog
from .conftest import TEST_DATABASE_URL

REPO = Path(__file__).resolve().parents[2]
BUSINESS_DB = "chatbot_business_test"
READER_PASSWORD = "reader-test-password-0123456789"
TOOLS = json.loads((REPO / "deploy/business_db/demo_tools.json").read_text(encoding="utf-8"))
TIERS = {"anonymous": 0, "user": 1, "premium": 2}
ANONYMOUS = ToolContext()
ALICE = ToolContext(user_id="user-42", tier_level=1)
BOB = ToolContext(user_id="user-99", tier_level=1)


def _dsn(database: str, user=None, password=None) -> str:
    url = make_url(TEST_DATABASE_URL).set(drivername="postgresql", database=database)
    if user:
        url = url.set(username=user, password=password)
    return url.render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def business():
    """The demo shop in its own database, reached through the read-only role."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    admin = await asyncpg.connect(_dsn(make_url(TEST_DATABASE_URL).database))
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", BUSINESS_DB):
            await admin.execute(f'CREATE DATABASE "{BUSINESS_DB}"')
        await admin.execute(f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chatbot_reader') THEN CREATE ROLE chatbot_reader LOGIN; END IF;
            END $$;
            ALTER ROLE chatbot_reader WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{READER_PASSWORD}';
            ALTER ROLE chatbot_reader SET default_transaction_read_only = on;
        """)
    finally:
        await admin.close()
    owner = await asyncpg.connect(_dsn(BUSINESS_DB))
    try:
        await owner.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        await owner.execute((REPO / "deploy/business_db/demo_schema.sql").read_text(encoding="utf-8"))
    finally:
        await owner.close()
    reader_url = make_url(TEST_DATABASE_URL).set(database=BUSINESS_DB, username="chatbot_reader", password=READER_PASSWORD)
    database = Database(reader_url.render_as_string(hide_password=False), pool_size=2)
    database.connect()
    yield database
    await database.close()


def _tool(business, definition, timeout_ms=3000):
    spec = SqlToolSpec(definition["name"], definition["description"], definition["args_schema"],
                       TIERS[definition.get("required_tier", "anonymous")], definition["sql_template"],
                       definition["allowed_columns"], definition.get("masked_columns", []), definition.get("row_limit", 20))
    return SqlTool(spec, SqlToolExecutor(business, timeout_ms), lambda: date.today(), 6000)


def _rows(result: str):
    return json.loads(result)["rows"]


@pytest.mark.asyncio
async def test_public_tool_binds_arguments_and_returns_only_allowed_columns(business):
    tool = _tool(business, TOOLS[0])
    rows = _rows(await tool.execute({"query": "áo"}, ANONYMOUS))
    assert {row["sku"] for row in rows} == {"TS-01", "TS-02"}
    assert set(rows[0]) == {"sku", "name", "price_vnd"}
    # A quote in the argument is data, not SQL.
    assert _rows(await tool.execute({"query": "x' OR '1'='1"}, ANONYMOUS)) == []
    assert "invalid arguments" in await tool.execute({"query": "áo", "extra": 1}, ANONYMOUS)


@pytest.mark.asyncio
@pytest.mark.hard_gate
async def test_user_a_never_receives_user_b_rows(business):
    tool = _tool(business, TOOLS[1])
    alice = _rows(await tool.execute({"period": "90 ngày qua"}, ALICE))
    bob = _rows(await tool.execute({"period": "90 ngày qua"}, BOB))
    assert {row["order_no"] for row in alice} == {"DH-1001", "DH-1002"}
    assert {row["order_no"] for row in bob} == {"DH-2001"}
    assert all(row["customer_phone"].startswith("•••") for row in alice + bob)
    assert "customer_user_id" not in alice[0]
    # A user id smuggled in as an argument is refused, never bound.
    assert "invalid arguments" in await tool.execute({"period": "90 ngày qua", "user_id": "user-99"}, ALICE)


@pytest.mark.asyncio
@pytest.mark.hard_gate
async def test_row_level_security_holds_even_for_a_template_without_a_user_filter(business):
    careless = {**TOOLS[1], "name": "careless", "args_schema": {"type": "object", "properties": {}},
                "sql_template": "SELECT order_no, customer_user_id FROM shop.v_orders",
                "allowed_columns": ["order_no", "customer_user_id"], "masked_columns": []}
    tool = _tool(business, careless)
    assert {row["customer_user_id"] for row in _rows(await tool.execute({}, ALICE))} == {"user-42"}
    assert _rows(await tool.execute({}, ANONYMOUS)) == []


@pytest.mark.asyncio
@pytest.mark.hard_gate
async def test_anonymous_callers_never_reach_a_private_tool(business):
    catalog_tools = [_tool(business, definition) for definition in TOOLS]

    class Source:
        def tools(self):
            return catalog_tools

    registry = ToolRegistry([], Source())
    names = lambda schemas: {schema["function"]["name"] for schema in schemas}  # noqa: E731
    assert names(registry.schemas(ANONYMOUS)) == {"get_product_price"}
    assert names(registry.schemas(ALICE)) == {"get_product_price", "list_my_orders"}
    assert [tool.name for tool in registry.locked(ANONYMOUS)] == ["list_my_orders"]
    refused = await registry.execute("list_my_orders", {"period": "tháng này"}, ANONYMOUS)
    assert refused.startswith("Error: no tool named")


@pytest.mark.asyncio
async def test_writes_and_slow_queries_are_stopped(business):
    sneaky = {**TOOLS[0], "name": "sneaky", "args_schema": {"type": "object", "properties": {}},
              "sql_template": "WITH gone AS (DELETE FROM shop.orders RETURNING order_no) SELECT order_no FROM gone",
              "allowed_columns": ["order_no"]}
    registry = ToolRegistry([_tool(business, sneaky)])
    assert "Error" in await registry.execute("sneaky", {}, ALICE)
    slow = {**TOOLS[0], "name": "slow", "args_schema": {"type": "object", "properties": {}},
            "sql_template": "SELECT 1 AS x FROM pg_sleep(1)", "allowed_columns": ["x"]}
    assert "took too long" in await _tool(business, slow, timeout_ms=100).execute({}, ANONYMOUS)
    owner = await asyncpg.connect(_dsn(BUSINESS_DB))
    try:
        assert await owner.fetchval("SELECT count(*) FROM shop.orders") == 3
    finally:
        await owner.close()


def test_unsafe_definitions_are_rejected(business):
    with pytest.raises(SqlToolDefinitionError, match="SELECT"):
        _tool(business, {**TOOLS[0], "sql_template": "DELETE FROM shop.orders"})
    with pytest.raises(SqlToolDefinitionError, match="undeclared"):
        _tool(business, {**TOOLS[0], "sql_template": "SELECT sku FROM shop.v_products WHERE sku = :other"})
    with pytest.raises(SqlToolDefinitionError, match="reserved"):
        _tool(business, {**TOOLS[0], "args_schema": {"type": "object", "properties": {"user_id": {"type": "string"}}}})


@pytest.mark.asyncio
async def test_catalog_sync_toggle_and_unknown_tiers(business, database):
    catalog = SqlToolCatalog(database, SqlToolExecutor(business, 3000), lambda tier: {"user": 1, "premium": 2}.get(tier, 0))
    assert await catalog.sync(TOOLS, "test") == ["get_product_price", "list_my_orders"]
    assert {tool.name for tool in catalog.tools()} == {"get_product_price", "list_my_orders"}
    await catalog.set_enabled("list_my_orders", False, "test")
    assert {tool.name for tool in catalog.tools()} == {"get_product_price"}
    with pytest.raises(InvalidRequestError, match="unknown required_tier"):
        await catalog.sync([{**TOOLS[1], "name": "typo", "required_tier": "usr"}], "test")


@pytest.mark.asyncio
async def test_business_db_probe_accepts_the_reader_and_flags_the_owner(business):
    reader = make_url(TEST_DATABASE_URL).set(database=BUSINESS_DB, username="chatbot_reader", password=READER_PASSWORD)
    assert await BusinessDbProbe(reader.render_as_string(hide_password=False)).problems() == []
    owner = make_url(TEST_DATABASE_URL).set(database=BUSINESS_DB)
    assert await BusinessDbProbe(owner.render_as_string(hide_password=False)).problems()
