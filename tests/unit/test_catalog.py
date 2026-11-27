"""Conservatively recognize numeric PostgreSQL checks."""

import pytest

from seed.postgres.catalog import numeric_bounds


def test_numeric_comparisons_and_quoted_identifiers() -> None:
    bounds = numeric_bounds('((1 <= "A AND B") AND ("A AND B" < (3)::numeric))', "A AND B")
    assert [(bound.operator, bound.value) for bound in bounds] == [(">=", "1"), ("<", "3")]


@pytest.mark.parametrize(
    "expression",
    [
        "amount > 0 OR amount < 100",
        "amount > (1 + 2)",
        "amount::integer > 0",
        "amount > another",
        "myfunc(amount) > 0",
        "amount > 'NaN'::numeric",
        "amount > 0 AND",
    ],
)
def test_unrecognized_expressions_are_not_supported(expression: str) -> None:
    assert numeric_bounds(expression, "amount") == ()
