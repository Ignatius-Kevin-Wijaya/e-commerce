"""
Pagination utility.

LEARNING NOTES:
- Offset pagination: simple but slow for large offsets (DB scans skipped rows).
- Cursor pagination: fast and consistent, uses WHERE id > last_seen_id.
- We implement offset pagination here because it's simpler to learn first.
- In production with millions of rows, switch to cursor-based.
"""

from dataclasses import dataclass
from typing import Generic, List, TypeVar

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass
class PaginationParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self):
        self.page = max(1, self.page)
        self.page_size = min(max(1, self.page_size), MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass
class PaginatedResponse(Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    def to_dict(self) -> dict:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }
