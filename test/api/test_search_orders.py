from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.api.carts import (
    SEARCH_PAGE_SIZE,
    SearchResponse,
    SearchSortOptions,
    SearchSortOrder,
    _encode_search_cursor,
    search_orders,
)


def _fake_row(i: int) -> dict:
    dt = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    return {
        "id": i,
        "potion_sku": "RED",
        "customer_name": "Ada",
        "line_item_total": 100 + i,
        "sold_at": dt,
    }


@patch("src.api.carts.db.engine.begin")
def test_search_orders_maps_sale_events_to_line_items(mock_begin: MagicMock) -> None:
    fake_conn = MagicMock()
    mock_begin.return_value.__enter__.return_value = fake_conn
    mock_begin.return_value.__exit__.return_value = None

    dt = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    fake_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "id": 42,
            "potion_sku": "RED",
            "customer_name": "Ada",
            "line_item_total": 200,
            "sold_at": dt,
        }
    ]

    resp = search_orders()

    assert isinstance(resp, SearchResponse)
    assert resp.previous is None
    assert resp.next is None
    assert len(resp.results) == 1
    assert resp.results[0].line_item_id == 42
    assert resp.results[0].item_sku == "RED"
    assert resp.results[0].customer_name == "Ada"
    assert resp.results[0].line_item_total == 200
    assert resp.results[0].timestamp == dt.isoformat()


@patch("src.api.carts.db.engine.begin")
def test_search_orders_ilike_filters_and_sort_parameters(mock_begin: MagicMock) -> None:
    fake_conn = MagicMock()
    mock_begin.return_value.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.mappings.return_value.all.return_value = []

    search_orders(
        customer_name=" ada ",
        potion_sku=" red ",
        sort_col=SearchSortOptions.customer_name,
        sort_order=SearchSortOrder.asc,
    )

    fake_conn.execute.assert_called_once()
    _sql_text, params = fake_conn.execute.call_args[0]
    assert params["cust_pat"] == "%ada%"
    assert params["sku_pat"] == "%red%"
    assert params["limit"] == SEARCH_PAGE_SIZE + 1
    assert params["offset"] == 0
    compiled = str(_sql_text)
    assert "sale_events" in compiled
    assert "ILIKE :cust_pat" in compiled
    assert "ILIKE :sku_pat" in compiled
    assert "LIMIT :limit OFFSET :offset" in compiled.replace("\n", " ")
    assert "ORDER BY customer_name ASC, id ASC" in compiled.replace("\n", " ")


@patch("src.api.carts.db.engine.begin")
def test_search_orders_sort_line_item_total_desc(mock_begin: MagicMock) -> None:
    fake_conn = MagicMock()
    mock_begin.return_value.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.mappings.return_value.all.return_value = []

    search_orders(sort_col=SearchSortOptions.line_item_total, sort_order=SearchSortOrder.desc)

    sql_text = fake_conn.execute.call_args[0][0]
    body = str(sql_text).replace("\n", " ")
    assert "ORDER BY (quantity * unit_price) DESC, id DESC" in body


@patch("src.api.carts.db.engine.begin")
def test_search_orders_next_when_more_than_page_size(mock_begin: MagicMock) -> None:
    fake_conn = MagicMock()
    mock_begin.return_value.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.mappings.return_value.all.return_value = [
        _fake_row(i) for i in range(SEARCH_PAGE_SIZE + 1)
    ]

    resp = search_orders()

    assert len(resp.results) == SEARCH_PAGE_SIZE
    assert resp.next is not None
    assert resp.previous is None


@patch("src.api.carts.db.engine.begin")
def test_search_orders_previous_when_using_search_page(mock_begin: MagicMock) -> None:
    fake_conn = MagicMock()
    mock_begin.return_value.__enter__.return_value = fake_conn
    fake_conn.execute.return_value.mappings.return_value.all.return_value = [_fake_row(99)]

    token = _encode_search_cursor(
        {
            "cust": "",
            "sku": "",
            "sort_col": SearchSortOptions.timestamp.value,
            "sort_order": SearchSortOrder.desc.value,
            "offset": SEARCH_PAGE_SIZE,
        }
    )

    resp = search_orders(search_page=token)

    assert len(resp.results) == 1
    assert resp.previous is not None
    args, kwargs = fake_conn.execute.call_args
    assert args[1]["offset"] == SEARCH_PAGE_SIZE


def test_search_orders_invalid_search_page_raises() -> None:
    with pytest.raises(HTTPException) as exc_info:
        search_orders(search_page="@@@not-valid-base64@@@")
    assert exc_info.value.status_code == 400


def test_search_orders_search_page_query_mismatch_raises() -> None:
    token = _encode_search_cursor(
        {
            "cust": "bob",
            "sku": "",
            "sort_col": SearchSortOptions.timestamp.value,
            "sort_order": SearchSortOrder.desc.value,
            "offset": 0,
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        search_orders(customer_name="alice", search_page=token)
    assert exc_info.value.status_code == 400
