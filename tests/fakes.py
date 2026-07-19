from __future__ import annotations

import re
from copy import deepcopy

from storage.google_sheets import WORKSHEET_HEADERS


class FakeWorksheet:
    def __init__(self, title: str, headers: tuple[str, ...]):
        self.title = title
        self.rows = [list(headers)]

    def row_values(self, row: int) -> list[str]:
        return list(self.rows[row - 1]) if row <= len(self.rows) else []

    def get_all_values(self) -> list[list[str]]:
        return deepcopy(self.rows)

    def append_row(self, values: list[str], **_: object) -> None:
        self.rows.append(list(values))

    def append_rows(self, values: list[list[str]], **_: object) -> None:
        self.rows.extend(deepcopy(values))

    def update(
        self, values: list[list[str]], range_name: str, **_: object
    ) -> None:
        match = re.fullmatch(r"A(\d+)", range_name)
        if not match:
            raise AssertionError(f"Unexpected range: {range_name}")
        row_index = int(match.group(1)) - 1
        self.rows[row_index] = list(values[0])

    def delete_rows(self, row_number: int) -> None:
        del self.rows[row_number - 1]


class FakeWorkbook:
    title = "Test Ledger"

    def __init__(self, headers: dict[str, tuple[str, ...]] | None = None):
        headers = headers or WORKSHEET_HEADERS
        self.sheets = {
            title: FakeWorksheet(title, columns) for title, columns in headers.items()
        }

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self.sheets.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        return self.sheets[title]
