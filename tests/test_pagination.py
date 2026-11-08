import pytest
from pydantic import ValidationError

from app.schemas.base import PageParams, build_pagination


def test_page_params_defaults() -> None:
    p = PageParams()
    assert p.page == 1
    assert p.page_size == 25
    assert p.offset == 0


def test_page_params_rejects_page_zero() -> None:
    with pytest.raises(ValidationError):
        PageParams(page=0)


def test_page_params_rejects_oversized_page_size() -> None:
    with pytest.raises(ValidationError):
        PageParams(page_size=101)


@pytest.mark.parametrize(
    ("page", "page_size", "total", "exp_total_pages", "exp_has_next", "exp_has_prev"),
    [
        (1, 25, 0, 0, False, False),
        (1, 25, 24, 1, False, False),
        (1, 25, 25, 1, False, False),
        (1, 25, 26, 2, True, False),
        (2, 25, 26, 2, False, True),
        (3, 10, 45, 5, True, True),
    ],
)
def test_build_pagination(
    page: int,
    page_size: int,
    total: int,
    exp_total_pages: int,
    exp_has_next: bool,
    exp_has_prev: bool,
) -> None:
    meta = build_pagination(PageParams(page=page, page_size=page_size), total)
    assert meta.total_pages == exp_total_pages
    assert meta.has_next == exp_has_next
    assert meta.has_prev == exp_has_prev
    assert meta.first_index == (page - 1) * page_size
    assert meta.offset == meta.first_index
