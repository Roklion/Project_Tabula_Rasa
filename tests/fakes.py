from __future__ import annotations

import re
from copy import deepcopy

from tabula_rasa.storage.google_sheets import WORKSHEET_HEADERS


class FakeWorksheet:
    def __init__(self, title: str, headers: tuple[str, ...]):
        self.title = title
        self.rows = [list(headers)]
        self.col_count = len(headers)

    def row_values(self, row: int) -> list[str]:
        return list(self.rows[row - 1]) if row <= len(self.rows) else []

    def get_all_values(self) -> list[list[str]]:
        return deepcopy(self.rows)

    def append_row(self, values: list[str], **_: object) -> None:
        self.rows.append(list(values))

    def append_rows(self, values: list[list[str]], **_: object) -> None:
        self.rows.extend(deepcopy(values))

    def add_cols(self, columns: int) -> None:
        self.col_count += columns
        for row in self.rows:
            row.extend([""] * columns)

    def update(
        self, values: list[list[str]], range_name: str, **_: object
    ) -> None:
        match = re.fullmatch(r"([A-Z]+)(\d+)(?::[A-Z]+\d+)?", range_name)
        if not match:
            raise AssertionError(f"Unexpected range: {range_name}")
        column_text, row_text = match.groups()
        column_index = 0
        for character in column_text:
            column_index = column_index * 26 + ord(character) - 64
        column_index -= 1
        row_index = int(row_text) - 1
        for row_offset, source_row in enumerate(values):
            target_index = row_index + row_offset
            while len(self.rows) <= target_index:
                self.rows.append([])
            target_row = self.rows[target_index]
            required_width = column_index + len(source_row)
            if len(target_row) < required_width:
                target_row.extend([""] * (required_width - len(target_row)))
            target_row[column_index:required_width] = list(source_row)

    def batch_update(
        self,
        data: list[dict[str, object]],
        **kwargs: object,
    ) -> None:
        for item in data:
            self.update(
                item["values"],
                range_name=str(item["range"]),
                **kwargs,
            )

    def delete_rows(self, row_number: int) -> None:
        del self.rows[row_number - 1]


class FakeWorkbook:
    title = "Test Ledger"

    def __init__(self, headers: dict[str, tuple[str, ...]] | None = None):
        headers = WORKSHEET_HEADERS if headers is None else headers
        self.sheets = {
            title: FakeWorksheet(title, columns) for title, columns in headers.items()
        }

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self.sheets.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        return self.sheets[title]

    def add_worksheet(
        self, title: str, rows: int, cols: int
    ) -> FakeWorksheet:
        del rows
        worksheet = FakeWorksheet(title, ())
        worksheet.col_count = cols
        self.sheets[title] = worksheet
        return worksheet
