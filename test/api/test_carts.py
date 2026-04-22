from src.api.carts import has_insufficient_stock, summarize_checkout_totals


def test_summarize_checkout_totals_single_line() -> None:
    total_potions, total_gold = summarize_checkout_totals([(2, 12)])
    assert total_potions == 2
    assert total_gold == 24


def test_summarize_checkout_totals_multiple_lines() -> None:
    total_potions, total_gold = summarize_checkout_totals([(1, 10), (3, 5)])
    assert total_potions == 4
    assert total_gold == 25


def test_summarize_checkout_totals_empty() -> None:
    total_potions, total_gold = summarize_checkout_totals([])
    assert total_potions == 0
    assert total_gold == 0


def test_has_insufficient_stock_true_when_line_exceeds_stock() -> None:
    assert has_insufficient_stock([(2, 1)]) is True


def test_has_insufficient_stock_false_when_all_lines_fit_stock() -> None:
    assert has_insufficient_stock([(1, 5), (2, 2)]) is False


def test_has_insufficient_stock_true_when_one_of_many_lines_exceeds_stock() -> None:
    assert has_insufficient_stock([(1, 1), (2, 1)]) is True


def test_has_insufficient_stock_empty() -> None:
    assert has_insufficient_stock([]) is False