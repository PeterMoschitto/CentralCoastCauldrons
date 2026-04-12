from src.api.bottler import create_bottle_plan

# Catalog order matches greedy consumption: pure red, then green, then blue (like DB seed order).
_CATALOG_RGB = [
    (100, 0, 0, 0),
    (0, 100, 0, 0),
    (0, 0, 100, 0),
]


def test_bottle_red_potions() -> None:
    """100 ml → 1 red potion when catalog includes pure red."""
    result = create_bottle_plan(
        100,
        0,
        0,
        0,
        catalog=[(100, 0, 0, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [100, 0, 0, 0]
    assert result[0].quantity == 1


def test_mixes_all_colors_independently() -> None:
    result = create_bottle_plan(
        200,
        100,
        0,
        0,
        catalog=_CATALOG_RGB,
    )
    assert len(result) == 2
    assert result[0].quantity == 2
    assert result[1].quantity == 1


def test_mixed_recipe_uses_multiple_colors() -> None:
    """50/50 red-blue needs both red and blue ml in the right ratio."""
    result = create_bottle_plan(
        100,
        0,
        100,
        0,
        catalog=[(50, 0, 50, 0)],
    )
    assert len(result) == 1
    assert result[0].potion_type == [50, 0, 50, 0]
    assert result[0].quantity == 2


def test_recipe_with_dark_uses_dark_ml() -> None:
    """Equal four-way mix: 25 ml of each color per 100 ml bottle."""
    result = create_bottle_plan(
        100,
        100,
        100,
        100,
        catalog=[(25, 25, 25, 25)],
    )
    assert len(result) == 1
    assert result[0].potion_type == [25, 25, 25, 25]
    assert result[0].quantity == 4
