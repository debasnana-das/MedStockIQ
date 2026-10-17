"""In-memory readers for supported tabular upload formats."""

from __future__ import annotations

import pandas as pd
from io import BytesIO


MAX_PROFILE_ROWS = 20_000
SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}


def read_tabular_content(filename: str, content: bytes) -> tuple[pd.DataFrame, bool]:
    """Parse CSV/XLSX bytes, profiling at most MAX_PROFILE_ROWS rows.

    Returns (dataframe, truncated). The file is read in memory and is not written
    to disk by this parser. For XLSX, the first worksheet is used in this MVP.
    """
    suffix = "." + filename.rsplit(".", maxsplit=1)[-1].casefold() if "." in filename else ""
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError("Unsupported file type. Upload a CSV or XLSX file for this prototype.")
    if not content:
        raise ValueError("The uploaded file is empty.")

    if suffix == ".csv":
        try:
            frame = pd.read_csv(BytesIO(content), nrows=MAX_PROFILE_ROWS, low_memory=False)
        except UnicodeDecodeError:
            frame = pd.read_csv(
                BytesIO(content),
                nrows=MAX_PROFILE_ROWS,
                low_memory=False,
                encoding="cp1252",
            )
    else:
        frame = pd.read_excel(
            BytesIO(content),
            engine="openpyxl",
            nrows=MAX_PROFILE_ROWS,
        )

    if len(frame.columns) == 0:
        raise ValueError("No columns were found. Check whether the file has a header row.")
    if frame.empty:
        raise ValueError("The file contains headers but no data rows.")

    # A file is considered truncated when it reaches the profiling cap. This
    # deliberately errs on the side of warning the user.
    truncated = len(frame.index) >= MAX_PROFILE_ROWS
    return frame, truncated
