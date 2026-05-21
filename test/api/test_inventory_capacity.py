from unittest.mock import MagicMock, Mock, call, patch

from src.api.inventory import (
    CapacityPlan,
    decide_capacity_plan,
    deliver_capacity_plan,
)


def test_decide_capacity_plan_no_ml_when_headroom_fits_10k_barrel() -> None:
    plan = decide_capacity_plan(
        gold=50000,
        total_ml=0,
        max_ml=10000,
        total_potions=10,
        max_potions=50,
    )
    assert plan.ml_capacity == 0
    assert plan.potion_capacity == 0


def test_decide_capacity_plan_buys_ml_when_full_and_gold_allows() -> None:
    plan = decide_capacity_plan(
        gold=6400,
        total_ml=10000,
        max_ml=10000,
        total_potions=10,
        max_potions=50,
    )
    assert plan.ml_capacity == 1
    assert plan.potion_capacity == 0


def test_decide_capacity_plan_skips_ml_when_gold_below_reserve() -> None:
    plan = decide_capacity_plan(
        gold=2999,
        total_ml=10000,
        max_ml=10000,
        total_potions=10,
        max_potions=50,
    )
    assert plan.ml_capacity == 0


def test_decide_capacity_plan_ml_when_partial_headroom() -> None:
    plan = decide_capacity_plan(
        gold=5000,
        total_ml=9500,
        max_ml=10000,
        total_potions=10,
        max_potions=50,
    )
    assert plan.ml_capacity == 1


def test_decide_capacity_plan_two_ml_tiers_when_overfull() -> None:
    plan = decide_capacity_plan(
        gold=12000,
        total_ml=10500,
        max_ml=10000,
        total_potions=10,
        max_potions=50,
    )
    assert plan.ml_capacity == 2


def test_decide_capacity_plan_potion_tier_when_low_slots() -> None:
    plan = decide_capacity_plan(
        gold=6000,
        total_ml=0,
        max_ml=10000,
        total_potions=48,
        max_potions=50,
    )
    assert plan.ml_capacity == 0
    assert plan.potion_capacity == 1


class AnyConnection:
    def __eq__(self, other) -> bool:
        return True


@patch("src.api.inventory.db.engine.begin")
@patch("src.api.inventory.store_processed_response")
@patch("src.api.inventory.add_ledger_entry")
@patch("src.api.inventory.create_inventory_transaction")
@patch("src.api.inventory.get_processed_response")
def test_capacity_deliver_writes_ledger(
    mock_get_processed_response: Mock,
    mock_create_inventory_transaction: Mock,
    mock_add_ledger_entry: Mock,
    mock_store_processed_response: Mock,
    mock_engine_begin: Mock,
) -> None:
    mock_get_processed_response.return_value = None
    mock_create_inventory_transaction.return_value = 42
    mock_engine_begin.return_value.__enter__.return_value = MagicMock()
    mock_engine_begin.return_value.__exit__.return_value = None

    deliver_capacity_plan(CapacityPlan(potion_capacity=0, ml_capacity=2), order_id=501)

    mock_create_inventory_transaction.assert_called_once()
    mock_add_ledger_entry.assert_has_calls(
        [
            call(AnyConnection(), 42, "gold", "gold", -2000),
            call(AnyConnection(), 42, "capacity", "ml", 2),
        ],
        any_order=False,
    )
    mock_store_processed_response.assert_called_once()


@patch("src.api.inventory.db.engine.begin")
@patch("src.api.inventory.store_processed_response")
@patch("src.api.inventory.add_ledger_entry")
@patch("src.api.inventory.create_inventory_transaction")
@patch("src.api.inventory.get_processed_response")
def test_capacity_deliver_idempotent_retry(
    mock_get_processed_response: Mock,
    mock_create_inventory_transaction: Mock,
    mock_add_ledger_entry: Mock,
    mock_store_processed_response: Mock,
    mock_engine_begin: Mock,
) -> None:
    mock_get_processed_response.return_value = {"status": "ok"}
    mock_engine_begin.return_value.__enter__.return_value = MagicMock()
    mock_engine_begin.return_value.__exit__.return_value = None

    deliver_capacity_plan(CapacityPlan(potion_capacity=1, ml_capacity=1), order_id=9)

    mock_create_inventory_transaction.assert_not_called()
    mock_add_ledger_entry.assert_not_called()
    mock_store_processed_response.assert_not_called()
