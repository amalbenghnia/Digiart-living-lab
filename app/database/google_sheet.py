"""Thin wrapper around gspread. Kept separate from the repository so the
repository stays testable (it depends on this class, which can be mocked)
and so credential handling lives in exactly one place."""
from __future__ import annotations

import time

import gspread
from google.oauth2.service_account import Credentials

from app.core.config import Settings
from app.core.logging import get_logger
from app.exceptions.custom_exceptions import DataSourceUnavailableError

logger = get_logger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 1.0


class GoogleSheetClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: gspread.Client | None = None
        self._worksheet: gspread.Worksheet | None = None

    def _reset_connection(self) -> None:
        """Drop cached client/worksheet so the next call reconnects fresh."""
        self._client = None
        self._worksheet = None

    def _connect(self) -> gspread.Client:
        if self._client is not None:
            return self._client
        if not self._settings.google_service_account_json_path:
            raise DataSourceUnavailableError(
                "GOOGLE_SERVICE_ACCOUNT_JSON_PATH is not set — cannot connect to Google Sheets"
            )
        try:
            creds = Credentials.from_service_account_file(
                self._settings.google_service_account_json_path, scopes=_SCOPES
            )
            self._client = gspread.authorize(creds)
            return self._client
        except Exception as exc:  # noqa: BLE001 — we deliberately re-wrap everything here
            raise DataSourceUnavailableError(f"Google Sheets auth failed: {exc}") from exc

    def worksheet(self) -> gspread.Worksheet:
        if self._worksheet is not None:
            return self._worksheet
        if not self._settings.google_sheet_id:
            raise DataSourceUnavailableError("GOOGLE_SHEET_ID is not set")
        client = self._connect()
        try:
            sheet = client.open_by_key(self._settings.google_sheet_id)
            self._worksheet = sheet.worksheet(self._settings.google_sheet_worksheet_name)
            return self._worksheet
        except Exception as exc:  # noqa: BLE001
            raise DataSourceUnavailableError(f"Could not open worksheet: {exc}") from exc

    def _retry(self, operation_name: str, fn):
        """Retry a Google Sheets operation with exponential backoff.
        On connection failures (RemoteDisconnected, timeout, etc.), reset
        the cached connection so the next attempt reconnects fresh."""
        last_exc = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return fn()
            except DataSourceUnavailableError:
                raise  # config errors are not retryable
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    f"Google Sheets {operation_name} attempt {attempt}/{_MAX_RETRIES} failed: {exc}"
                )
                self._reset_connection()
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        raise DataSourceUnavailableError(
            f"Google Sheets {operation_name} failed after {_MAX_RETRIES} retries: {last_exc}"
        )

    def get_all_records(self) -> list[dict]:
        def _do():
            ws = self.worksheet()
            raw_headers = ws.row_values(1)
            # Deduplicate blank/empty headers so gspread doesn't crash
            seen: dict[str, int] = {}
            clean_headers = []
            for h in raw_headers:
                h = h.strip()
                if not h:
                    h = f"_blank_{len(seen)}"
                if h in seen:
                    seen[h] += 1
                    h = f"{h}_{seen[h]}"
                else:
                    seen[h] = 0
                clean_headers.append(h)
            return ws.get_all_records(expected_headers=clean_headers)
        return self._retry("get_all_records", _do)

    def append_row(self, row: list) -> None:
        def _do():
            self.worksheet().append_row(row)
        return self._retry("append_row", _do)

    def update_row_by_id(self, id_column: str, id_value: str, updates: dict[str, object]) -> None:
        """Find the row where `id_column` == id_value and update the given columns."""
        def _do():
            ws = self.worksheet()
            try:
                cell = ws.find(id_value)
            except gspread.exceptions.CellNotFound as exc:
                raise DataSourceUnavailableError(f"Row with {id_column}={id_value} not found") from exc

            header = ws.row_values(1)
            for col_name, value in updates.items():
                if col_name not in header:
                    continue
                col_index = header.index(col_name) + 1
                ws.update_cell(cell.row, col_index, value)
        self._retry("update_row_by_id", _do)

    def update_cell(self, row_index: int, col_index: int, value: str | int | float) -> None:
        def _do():
            self.worksheet().update_cell(row_index, col_index, value)
        return self._retry("update_cell", _do)

    def update_cells(self, cell_list: list[gspread.Cell]) -> None:
        """Batch update multiple cells in one API call."""
        def _do():
            self.worksheet().update_cells(cell_list)
        return self._retry("update_cells", _do)
