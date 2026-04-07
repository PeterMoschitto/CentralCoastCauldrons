from src.api.bottler import create_bottle_plan


def test_bottle_red_potions() -> None:
    """100 ml → 1 red potion (version 1: all available ml per color)."""
    result = create_bottle_plan(
        red_ml=100,
        green_ml=0,
        blue_ml=0,
    )

    assert len(result) == 1
    assert result[0].potion_type == [100, 0, 0, 0]
    assert result[0].quantity == 1


def test_mixes_all_colors_independently() -> None:
    result = create_bottle_plan(
        red_ml=200,
        green_ml=100,
        blue_ml=0,
    )
    assert len(result) == 2
    assert result[0].quantity == 2
    assert result[1].quantity == 1
