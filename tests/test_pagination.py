"""Paged connector listings."""

from __future__ import annotations

import pytest

from connector_manager import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AsyncConnectorManager,
    ConnectorManager,
    ConnectorPage,
)


@pytest.fixture(scope="module")
def manager() -> ConnectorManager:
    with ConnectorManager() as m:
        yield m


# -- page maths ----------------------------------------------------------------


def test_page_metadata_of_a_middle_page(manager: ConnectorManager) -> None:
    page = manager.paginate_connectors(page=3, page_size=10)

    assert page.count == 10
    assert page.total == len(manager)
    assert (page.page, page.page_size, page.offset) == (3, 10, 20)
    assert page.pages == -(-page.total // 10)
    assert (page.has_previous, page.has_next) == (True, True)
    assert (page.previous_offset, page.next_offset) == (10, 30)
    assert (page.first_index, page.last_index) == (21, 30)


def test_first_page_has_no_previous(manager: ConnectorManager) -> None:
    page = manager.paginate_connectors(page_size=5)
    assert (page.page, page.offset) == (1, 0)
    assert page.has_previous is False and page.previous_offset is None
    assert page.has_next is True and page.next_offset == 5


def test_last_page_is_partial_and_has_no_next(manager: ConnectorManager) -> None:
    total = len(manager)
    page_size = 100
    last = -(-total // page_size)
    page = manager.paginate_connectors(page=last, page_size=page_size)

    assert page.page == last
    assert page.count == total - (last - 1) * page_size
    assert page.has_next is False and page.next_offset is None
    assert page.last_index == total


def test_page_past_the_end_is_empty_but_still_reports_the_total(
    manager: ConnectorManager,
) -> None:
    page = manager.paginate_connectors(page=9999, page_size=50)
    assert page.count == 0 and page.items == []
    assert page.total == len(manager)
    assert page.has_next is False and page.next_offset is None
    assert (page.first_index, page.last_index) == (0, 0)


def test_default_page_size(manager: ConnectorManager) -> None:
    assert manager.paginate_connectors().page_size == DEFAULT_PAGE_SIZE


def test_page_is_a_sequence(manager: ConnectorManager) -> None:
    page = manager.paginate_connectors(page_size=3)
    assert isinstance(page, ConnectorPage)
    assert len(page) == 3
    assert [c.id for c in page] == [c.id for c in page.items]
    assert page[0] is page.items[0]


# -- consistency ---------------------------------------------------------------


def test_pages_tile_the_full_listing_without_gaps_or_repeats(
    manager: ConnectorManager,
) -> None:
    walked = [c.id for page in manager.iter_connector_pages(page_size=97) for c in page]
    assert walked == [c.id for c in manager.list_connectors()]
    assert len(walked) == len(set(walked)) == len(manager)


def test_paging_matches_limit_offset_slicing(manager: ConnectorManager) -> None:
    page = manager.paginate_connectors(page=4, page_size=25)
    sliced = manager.list_connectors(limit=25, offset=75)
    assert [c.id for c in page] == [c.id for c in sliced]


def test_offset_wins_over_page_and_back_fills_the_page_number(
    manager: ConnectorManager,
) -> None:
    page = manager.paginate_connectors(page=1, page_size=20, offset=60)
    assert page.offset == 60 and page.page == 4


def test_ordering_is_stable_across_calls(manager: ConnectorManager) -> None:
    first = [c.id for c in manager.paginate_connectors(page=2, page_size=40)]
    again = [c.id for c in manager.paginate_connectors(page=2, page_size=40)]
    assert first == again


# -- filters + pagination ------------------------------------------------------


def test_total_reflects_the_filters_not_the_catalogue(manager: ConnectorManager) -> None:
    filtered = manager.paginate_connectors(page_size=5, auth_mode="TWO_STEP")
    assert filtered.total == len(manager.list_connectors(auth_mode="TWO_STEP"))
    assert filtered.total < len(manager)
    assert all(c.auth_mode.value == "TWO_STEP" for c in filtered)


def test_iter_pages_respects_filters(manager: ConnectorManager) -> None:
    walked = [
        c.id for page in manager.iter_connector_pages(page_size=7, category="crm") for c in page
    ]
    assert walked == [c.id for c in manager.list_connectors(category="crm")]
    assert all("crm" in manager.get_connector(cid).categories for cid in walked)


def test_a_filter_matching_nothing_yields_one_empty_page(manager: ConnectorManager) -> None:
    pages = list(manager.iter_connector_pages(page_size=10, search="definitely-no-such-connector"))
    assert len(pages) == 1
    assert pages[0].total == 0 and pages[0].count == 0 and pages[0].pages == 0


# -- serialisation -------------------------------------------------------------


def test_to_dict_carries_items_and_pagination(manager: ConnectorManager) -> None:
    payload = manager.paginate_connectors(page=2, page_size=3).to_dict()

    assert list(payload) == ["items", "pagination"]
    assert len(payload["items"]) == 3
    assert payload["pagination"]["page"] == 2
    assert payload["pagination"]["offset"] == 3
    assert "icon_svg" not in payload["items"][0]


def test_to_dict_can_inline_icons(manager: ConnectorManager) -> None:
    payload = manager.paginate_connectors(page_size=2).to_dict(include_icon=True)
    assert all("<svg" in item["icon_svg"] for item in payload["items"])


# -- input validation ----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page": -1},
        {"page": 1.5},
        {"page_size": 0},
        {"page_size": -10},
        {"page_size": MAX_PAGE_SIZE + 1},
        {"offset": -1},
    ],
)
def test_invalid_paging_arguments_are_rejected(
    manager: ConnectorManager, kwargs: dict
) -> None:
    with pytest.raises(ValueError):
        manager.paginate_connectors(**kwargs)


# -- async parity --------------------------------------------------------------


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_async_manager_paginates_identically() -> None:
    """Listing is bundled-data only, so it stays synchronous on both managers."""
    with ConnectorManager() as sync_manager:
        expected = sync_manager.paginate_connectors(page=2, page_size=15).to_dict()
    async with AsyncConnectorManager() as async_manager:
        actual = async_manager.paginate_connectors(page=2, page_size=15).to_dict()
    assert actual == expected
