"""Verify that preview stays legible and treats database values as text."""

from io import StringIO

from rich.console import Console

from seed.metadata import TableId
from seed.reporting.dataset import DatasetColumn, TableSample
from seed.reporting.terminal import preview_summary


def test_preview_narrow_layout_preserves_plain_and_escaped_cells() -> None:
    sample = TableSample(
        TableId(schema="public", table="items"),
        tuple(DatasetColumn(column, "text") for column in ("[red]", "second", "third", "fourth")),
        (("item\x1b", "two", "three", "four"),),
    )
    output = StringIO()
    console = Console(file=output, width=35, force_terminal=False)
    console.print(preview_summary(sample, planned=10, width=console.width))
    text = output.getvalue()
    assert "public.items" in text and "1 of 10 rows" in text
    assert "Column" in text and "[red]" in text
    assert "item\\u001b" in text and "\x1b" not in text
    assert all(len(line) <= 35 for line in text.splitlines())
