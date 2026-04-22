from src.api.bottler import create_bottle_plan


def test_bottle_pure_red_up_to_target() -> None:
    """
    Pure recipes bottle only enough to reach PURE_TARGET.
    Current quantity is 0, so red should be bottled up to target stock.
    """
    result = create_bottle_plan(
        red_ml=500,
        green_ml=0,
        blue_ml=0,
        dark_ml=0,
        catalog=[(100, 0, 0, 0, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [100, 0, 0, 0]
    assert result[0].quantity == 3


def test_no_bottling_when_pure_recipe_already_at_target() -> None:
    """
    If a pure recipe is already at target quantity, create_bottle_plan should not bottle more.
    """
    result = create_bottle_plan(
        red_ml=500,
        green_ml=0,
        blue_ml=0,
        dark_ml=0,
        catalog=[(100, 0, 0, 0, 3)],
    )

    assert result == []


def test_bottle_mixed_recipe_up_to_target() -> None:
    """
    Mixed recipes bottle only enough to reach MIXED_TARGET.
    Purple (50/0/50/0) should bottle up to target stock.
    """
    result = create_bottle_plan(
        red_ml=500,
        green_ml=0,
        blue_ml=500,
        dark_ml=0,
        catalog=[(50, 0, 50, 0, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [50, 0, 50, 0]
    assert result[0].quantity == 6


def test_mixed_recipe_respects_available_ml() -> None:
    """
    Even if target is higher, bottling is limited by available raw ml.
    For purple, 100 red and 100 blue can only make 2 bottles.
    """
    result = create_bottle_plan(
        red_ml=100,
        green_ml=0,
        blue_ml=100,
        dark_ml=0,
        catalog=[(50, 0, 50, 0, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [50, 0, 50, 0]
    assert result[0].quantity == 2


def test_dark_recipe_is_supported() -> None:
    """
    Dark recipes are fully supported.
    Four-way mix uses 25 ml of each color per bottle.
    """
    result = create_bottle_plan(
        red_ml=200,
        green_ml=200,
        blue_ml=200,
        dark_ml=200,
        catalog=[(25, 25, 25, 25, 0)],
    )

    assert len(result) == 1
    assert result[0].potion_type == [25, 25, 25, 25]
    assert result[0].quantity == 6


def test_mixed_recipes_are_prioritized_before_pure_recipes() -> None:
    """
    Mixed recipes should be considered before pure recipes.
    With enough stock for both, purple should be bottled first and use shared ingredients.
    """
    result = create_bottle_plan(
        red_ml=300,
        green_ml=300,
        blue_ml=300,
        dark_ml=0,
        catalog=[
            (100, 0, 0, 0, 0),   # pure red
            (0, 100, 0, 0, 0),   # pure green
            (0, 0, 100, 0, 0),   # pure blue
            (50, 0, 50, 0, 0),   # purple
        ],
    )

    assert len(result) >= 1
    assert result[0].potion_type == [50, 0, 50, 0]


def test_lower_stock_mixed_recipe_is_filled_first() -> None:
    """
    Among mixed recipes, lower current quantity should be prioritized first.
    """
    result = create_bottle_plan(
        red_ml=400,
        green_ml=400,
        blue_ml=400,
        dark_ml=0,
        catalog=[
            (50, 0, 50, 0, 5),   # purple nearly at target
            (50, 50, 0, 0, 0),   # orange low stock
        ],
    )

    assert len(result) >= 1
    assert result[0].potion_type == [50, 50, 0, 0]


def test_no_plan_when_no_recipe_can_be_bottled() -> None:
    """
    If no recipe has enough raw ml to make even one bottle, return an empty plan.
    """
    result = create_bottle_plan(
        red_ml=10,
        green_ml=10,
        blue_ml=10,
        dark_ml=10,
        catalog=[
            (100, 0, 0, 0, 0),
            (50, 0, 50, 0, 0),
            (25, 25, 25, 25, 0),
        ],
    )

    assert result == []