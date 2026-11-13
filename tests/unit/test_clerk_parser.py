from datetime import UTC, datetime

import pytest

from deskpilot.clerk.parser import LayoutChanged, parse_announcements
from deskpilot.clerk.sources import SourceConfig, SourceConfigError, load_sources

HTML = """
<html><body><ul class="news">
  <li class="item"><a href="/a/1">  Scheduled   maintenance
      on 2026-11-20 </a><time datetime="2026-11-12T08:00:00Z">Nov 12</time></li>
  <li class="item"><a href="https://other.example/a/2#top">Exchange will list ABC</a><time datetime="soon">x</time></li>
  <li class="item"><span>No link here</span></li>
  <li class="item"><a href="javascript:void(0)">Bad link</a></li>
  <li class="item"><a href="/a/1">Repeat of the first link</a></li>
</ul></body></html>
"""


def make_source(**overrides):
    data = {
        "name": "demo",
        "url": "https://exch.example/news/",
        "item_selector": "li.item",
        "date_selector": "time",
    }
    data.update(overrides)
    return SourceConfig(**data)


def test_items_are_read_with_clean_titles_absolute_links_and_dates():
    result = parse_announcements(HTML, make_source())
    first, second = result.items
    assert first.title == "Scheduled maintenance on 2026-11-20"
    assert first.url == first.external_id == "https://exch.example/a/1"
    assert first.published_at == datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    assert first.source == "demo"
    assert second.url == "https://other.example/a/2"  # the #top fragment is dropped
    assert second.published_at is None  # an unreadable date does not lose the item


def test_unusable_elements_are_skipped_and_counted():
    assert parse_announcements(HTML, make_source()).skipped == 3  # no link, javascript:, repeat


def test_a_selector_that_matches_nothing_means_the_layout_changed():
    with pytest.raises(LayoutChanged, match="layout"):
        parse_announcements(HTML, make_source(item_selector="div.gone"))
    with pytest.raises(LayoutChanged):
        parse_announcements("", make_source())


def test_title_and_link_can_be_in_different_elements():
    html = '<article><h3>Exchange will delist ABC</h3><a href="/x">read more</a></article>'
    source = make_source(item_selector="article", title_selector="h3", date_selector=None)
    [item] = parse_announcements(html, source).items
    assert (item.title, item.url) == ("Exchange will delist ABC", "https://exch.example/x")


def test_a_date_can_be_read_from_the_text_and_is_taken_as_utc():
    html = '<li class="item"><a href="/x">T</a><span class="d">2026-11-12</span></li>'
    source = make_source(date_selector=".d", date_attribute=None)
    [item] = parse_announcements(html, source).items
    assert item.published_at == datetime(2026, 11, 12, tzinfo=UTC)


def test_very_long_titles_are_cut():
    html = f'<li class="item"><a href="/x">{"w" * 900}</a></li>'
    [item] = parse_announcements(html, make_source()).items
    assert len(item.title) == 500


# --- sources file ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "Bad Name"},
        {"url": "ftp://x"},
        {"item_selector": "li["},
        {"item_selector": ""},
        {"colour": "red"},
    ],
)
def test_invalid_source_settings_are_refused(overrides):
    with pytest.raises(ValueError):
        make_source(**overrides)


def write(tmp_path, text):
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_sources_file_loads_and_expands_the_project_folder(tmp_path):
    path = write(tmp_path, '- name: demo\n  url: "{ROOT_URI}/page.html"\n  item_selector: li\n')
    [source] = load_sources(path, root=tmp_path)
    assert source.url == tmp_path.resolve().as_uri() + "/page.html"
    assert source.url.startswith("file:///")


def test_duplicate_names_and_bad_files_are_refused(tmp_path):
    twice = '- {name: a, url: "https://x", item_selector: li}\n- {name: a, url: "https://y", item_selector: li}\n'
    with pytest.raises(SourceConfigError, match="unique"):
        load_sources(write(tmp_path, twice))
    with pytest.raises(SourceConfigError, match=r"source #1 \(a\)"):
        load_sources(write(tmp_path, '- {name: a, url: "nope", item_selector: li}\n'))
    with pytest.raises(SourceConfigError):
        load_sources(write(tmp_path, "not: a list"))
