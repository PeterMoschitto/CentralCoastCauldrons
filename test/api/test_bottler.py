from unittest.mock import Mock, patch, call

from src.api.bottler import create_bottle_plan, post_deliver_bottles, PotionMixes


def test_bottle_pure_red_up_to_target() -> None:
    result = create_bottle_plan(
        red_ml=500,
        green_ml=0,
        blue_ml=0,
        dark_ml=0,
        catalog=[("RED", 100, 0, 0, 0, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [100, 0, 0, 0]
    assert result[0].quantity == 3


def test_no_bottling_when_pure_recipe_already_at_target() -> None:
    result = create_bottle_plan(
        red_ml=500,
        green_ml=0,
        blue_ml=0,
        dark_ml=0,
        catalog=[("RED", 100, 0, 0, 0, 3)],
    )

    assert result == []


def test_bottle_mixed_recipe_up_to_target() -> None:
    result = create_bottle_plan(
        red_ml=500,
        green_ml=0,
        blue_ml=500,
        dark_ml=0,
        catalog=[("PURPLE", 50, 0, 50, 0, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [50, 0, 50, 0]
    assert result[0].quantity == 6


def test_mixed_recipe_respects_available_ml() -> None:
    result = create_bottle_plan(
        red_ml=100,
        green_ml=0,
        blue_ml=100,
        dark_ml=0,
        catalog=[("PURPLE", 50, 0, 50, 0, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [50, 0, 50, 0]
    assert result[0].quantity == 2


def test_dark_recipe_is_supported() -> None:
    result = create_bottle_plan(
        red_ml=200,
        green_ml=200,
        blue_ml=200,
        dark_ml=200,
        catalog=[("DARK_MIX", 25, 25, 25, 25, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [25, 25, 25, 25]
    assert result[0].quantity == 6


def test_mixed_recipes_are_prioritized_before_pure_recipes() -> None:
    result = create_bottle_plan(
        red_ml=300,
        green_ml=300,
        blue_ml=300,
        dark_ml=0,
        catalog=[
            ("RED", 100, 0, 0, 0, 0),
            ("GREEN", 0, 100, 0, 0, 0),
            ("BLUE", 0, 0, 100, 0, 0),
            ("PURPLE", 50, 0, 50, 0, 0),
        ],
    )

    assert len(result) >= 1
    assert result[0].potion_type == [50, 0, 50, 0]


def test_lower_stock_mixed_recipe_is_filled_first() -> None:
    result = create_bottle_plan(
        red_ml=400,
        green_ml=400,
        blue_ml=400,
        dark_ml=0,
        catalog=[
            ("PURPLE", 50, 0, 50, 0, 5),
            ("ORANGE", 50, 50, 0, 0, 0),
        ],
    )

    assert len(result) >= 1
    assert result[0].potion_type == [50, 50, 0, 0]


def test_no_plan_when_no_recipe_can_be_bottled() -> None:
    result = create_bottle_plan(
        red_ml=10,
        green_ml=10,
        blue_ml=10,
        dark_ml=10,
        catalog=[
            ("RED", 100, 0, 0, 0, 0),
            ("PURPLE", 50, 0, 50, 0, 0),
            ("DARK_MIX", 25, 25, 25, 25, 0),
        ],
    )

    assert result == []


@patch("src.api.bottler.store_processed_response")
@patch("src.api.bottler.add_ledger_entry")
@patch("src.api.bottler._potion_sku_for_recipe")
@patch("src.api.bottler.create_inventory_transaction")
@patch("src.api.bottler.get_processed_response")
@patch("src.api.bottler.get_ml_balance")
def test_post_deliver_bottles_first_call_writes_ledger(
    mock_get_ml_balance: Mock,
    mock_get_processed_response: Mock,
    mock_create_inventory_transaction: Mock,
    mock_potion_sku_for_recipe: Mock,
    mock_add_ledger_entry: Mock,
    mock_store_processed_response: Mock,
) -> None:
    mock_get_processed_response.return_value = None
    mock_create_inventory_transaction.return_value = 55
    mock_potion_sku_for_recipe.return_value = "PURPLE"
    mock_get_ml_balance.return_value = 1000

    potions_delivered = [
        PotionMixes(potion_type=[50, 0, 50, 0], quantity=2),
    ]

    post_deliver_bottles(potions_delivered, order_id=999)

    mock_get_processed_response.assert_called_once()
    mock_create_inventory_transaction.assert_called_once()
    mock_potion_sku_for_recipe.assert_called_once()

    # red -100, blue -100, potion +2
    assert mock_add_ledger_entry.call_count == 3
    mock_add_ledger_entry.assert_has_calls(
        [
            call(AnyConnection(), 55, "ml", "red", -100),
            call(AnyConnection(), 55, "ml", "blue", -100),
            call(AnyConnection(), 55, "potion", "PURPLE", 2),
        ],
        any_order=False,
    )

    mock_store_processed_response.assert_called_once()


@patch("src.api.bottler.store_processed_response")
@patch("src.api.bottler.add_ledger_entry")
@patch("src.api.bottler._potion_sku_for_recipe")
@patch("src.api.bottler.create_inventory_transaction")
@patch("src.api.bottler.get_processed_response")
@patch("src.api.bottler.get_ml_balance")
def test_post_deliver_bottles_retry_does_nothing(
    mock_get_ml_balance: Mock,
    mock_get_processed_response: Mock,
    mock_create_inventory_transaction: Mock,
    mock_potion_sku_for_recipe: Mock,
    mock_add_ledger_entry: Mock,
    mock_store_processed_response: Mock,
) -> None:
    mock_get_processed_response.return_value = {"status": "ok"}

    potions_delivered = [
        PotionMixes(potion_type=[50, 0, 50, 0], quantity=2),
    ]

    post_deliver_bottles(potions_delivered, order_id=999)

    mock_get_ml_balance.assert_not_called()
    mock_create_inventory_transaction.assert_not_called()
    mock_potion_sku_for_recipe.assert_not_called()
    mock_add_ledger_entry.assert_not_called()
    mock_store_processed_response.assert_not_called()


class AnyConnection:
    def __eq__(self, other) -> bool:
        return True