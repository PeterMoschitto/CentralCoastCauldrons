from src.api.bottler import create_bottle_plan


def test_bottle_red_potions() -> None:
    """100 ml → at most 1 red potion."""
    result = create_bottle_plan(
        red_ml=100,
        green_ml=0,
        blue_ml=0,
        dark_ml=0,
        maximum_potion_capacity=1000,
        current_total_potions=0,
    )

    assert len(result) == 1
    assert result[0].potion_type == [100, 0, 0, 0]
    assert result[0].quantity == 1


def test_capacity_caps_total_brews() -> None:
    """Cannot brew more new potions than empty slots (red first, then green, then blue)."""
    result = create_bottle_plan(
        red_ml=10_000,
        green_ml=10_000,
        blue_ml=10_000,
        dark_ml=0,
        maximum_potion_capacity=50,
        current_total_potions=48,
    )
    # Only 2 slots: both go to red
    assert len(result) == 1
    assert result[0].potion_type == [100, 0, 0, 0]
    assert result[0].quantity == 2


def test_capacity_splits_across_colors_when_red_fits() -> None:
    result = create_bottle_plan(
        red_ml=100,
        green_ml=100,
        blue_ml=0,
        dark_ml=0,
        maximum_potion_capacity=50,
        current_total_potions=48,
    )
    # 2 slots: 1 red, 1 green
    assert len(result) == 2
    assert result[0].quantity == 1
    assert result[1].quantity == 1
