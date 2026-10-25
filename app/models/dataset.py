from dataclasses import dataclass


@dataclass
class Dataset:
    id: int | None = None
    project_id: int | None = None
    filename: str = ""
    file_path: str = ""
    file_type: str = ""
    row_count: int = 0
    column_count: int = 0
    imported_at: str | None = None
