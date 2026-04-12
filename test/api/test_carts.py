from src.api.carts import has_insufficient_stock, summarize_checkout_totals


def test_summarize_checkout_totals_single_line() -> None:
    total_potions, total_gold = summarize_checkout_totals([(2, 12)])
    assert total_potions == 2
    assert total_gold == 24


def test_summarize_checkout_totals_mixed_skus() -> None:
    """Multiple lines behave like barrel tests: pure inputs → pure outputs."""
    total_potions, total_gold = summarize_checkout_totals([(1, 10), (3, 5)])
    assert total_potions == 4
    assert total_gold == 25


def test_has_insufficient_stock() -> None:
    assert has_insufficient_stock([(2, 1)]) is True
    assert has_insufficient_stock([(1, 5), (2, 2)]) is False
    assert has_insufficient_stock([(1, 1), (2, 1)]) is True
