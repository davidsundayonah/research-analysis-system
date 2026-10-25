from dataclasses import dataclass


@dataclass
class Project:
    id: int | None = None
    name: str = ""
    research_title: str = ""
    researcher: str = ""
    institution: str = ""
    department: str = ""
    significance_level: float = 0.05
    multiplicity_method: str = "holm"
    status: str = "New"
    created_at: str | None = None
    updated_at: str | None = None
