import json
from decimal import Decimal
from io import StringIO

from seed.dataset import DatasetColumn
from seed.export_tabular import write_csv, write_json
from seed.metadata import TableId
from seed.streaming import GeneratedRecord


def test_csv_distinguishes_null_text_and_embedded_record_separators() -> None:
    table = TableId(schema="demo", table="items")
    columns = tuple(DatasetColumn(name, "text") for name in ['a"b', "empty", "null"])
    rows = [GeneratedRecord(table, 0, {'a"b': 'é,"word"\r\nnext', "empty": "", "null": None})]
    stream = StringIO(newline="")
    write_csv(stream, columns, iter(rows))
    assert stream.getvalue() == '"a""b","empty","null"\n"é,""word""\r\nnext","",\n'


def test_json_preserves_exact_relational_types_and_empty_tables() -> None:
    parent = TableId(schema="demo", table="parent")
    child = TableId(schema="demo", table="child")
    empty = TableId(schema="demo", table="empty")
    columns = (DatasetColumn("id", "bigint"), DatasetColumn("amount", "numeric"))
    child_columns = (DatasetColumn("parent_id", "bigint"), DatasetColumn("id", "integer"))
    big = 2**63 - 1
    rows = [GeneratedRecord(parent, 0, {"id": big, "amount": Decimal("123456789.012300")})]
    children = [GeneratedRecord(child, 0, {"parent_id": big, "id": 4})]
    stream = StringIO()
    write_json(
        stream,
        iter(
            [(parent, columns, iter(rows)), (child, child_columns, iter(children)), (empty, (), ())]
        ),
    )
    dataset = json.loads(stream.getvalue())
    assert dataset["version"] == 1
    first, second, third = dataset["tables"]
    assert first["rows"] == [[str(big), "123456789.012300"]]
    assert second["rows"] == [[first["rows"][0][0], 4]]
    assert third == {"table": {"schema": "demo", "table": "empty"}, "columns": [], "rows": []}
