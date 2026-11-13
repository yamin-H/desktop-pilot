import pytest

from deskpilot.rag.loader import DocumentLoadError, parse_document


def make_pdf(pages: list[str]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        if text:
            pdf.multi_cell(0, 8, text)
    return bytes(pdf.output())


def parse_md(text: str):
    return parse_document(text.encode(), "doc.md")


def test_markdown_is_split_by_headings_with_the_full_heading_path():
    document = parse_md(
        "# Runbook\n\nIntro text.\n\n## Missing\n\nCheck the feed.\n\n### Detail\n\nMore."
    )
    assert document.title == "Runbook"
    assert [(s.heading, s.text) for s in document.sections] == [
        ("Runbook", "Intro text."),
        ("Runbook > Missing", "Check the feed."),
        ("Runbook > Missing > Detail", "More."),
    ]


def test_a_new_heading_of_the_same_level_replaces_the_old_one_in_the_path():
    document = parse_md("# R\n\n## One\n\na\n\n## Two\n\nb")
    assert [s.heading for s in document.sections] == ["R > One", "R > Two"]


def test_text_before_the_first_heading_has_no_heading():
    document = parse_md("Loose text.\n\n# Title\n\nBody.")
    assert [(s.heading, s.text) for s in document.sections] == [
        (None, "Loose text."),
        ("Title", "Body."),
    ]


def test_headings_without_text_make_no_section():
    document = parse_md("# Title\n\n## Empty\n\n## Full\n\nText.")
    assert [s.heading for s in document.sections] == ["Title > Full"]


def test_a_hash_inside_a_code_block_is_not_a_heading():
    document = parse_md("# Title\n\n```\n# not a heading\nrun it\n```\n\nAfter.")
    [section] = document.sections
    assert "# not a heading" in section.text
    assert section.heading == "Title"


def test_without_a_top_heading_the_file_name_is_the_title():
    assert parse_document(b"## Only\n\ntext", "my-notes.md").title == "my-notes"


def test_windows_line_endings_and_a_byte_order_mark_are_handled():
    data = "\ufeff# Title\r\n\r\nBody text.\r\n".encode()
    document = parse_document(data, "doc.md")
    assert (document.title, document.sections[0].text) == ("Title", "Body text.")


def test_plain_text_is_one_section_titled_by_its_file_name():
    document = parse_document(b"Some plain text.\n", "notes.txt")
    assert document.title == "notes"
    assert [(s.heading, s.text) for s in document.sections] == [(None, "Some plain text.")]


def test_a_pdf_gives_one_section_per_page_with_page_numbers():
    document = parse_document(make_pdf(["Withdrawal limits apply.", "Second page text."]), "x.pdf")
    assert [s.page for s in document.sections] == [1, 2]
    assert "Withdrawal limits" in document.sections[0].text
    assert "Second page" in document.sections[1].text
    assert all(s.heading is None for s in document.sections)


def test_blank_pdf_pages_are_skipped_but_page_numbers_stay_true():
    document = parse_document(make_pdf(["First.", "", "Third."]), "x.pdf")
    assert [s.page for s in document.sections] == [1, 3]


def test_a_pdf_without_text_is_refused_with_the_reason():
    with pytest.raises(DocumentLoadError, match="OCR"):
        parse_document(make_pdf([""]), "scan.pdf")


def test_a_broken_pdf_is_refused():
    with pytest.raises(DocumentLoadError, match="PDF"):
        parse_document(b"this is not a pdf", "bad.pdf")


@pytest.mark.parametrize("name", ["a.md", "a.txt"])
@pytest.mark.parametrize("data", [b"", b"  \n\n  "])
def test_empty_documents_are_refused(name, data):
    with pytest.raises(DocumentLoadError, match="empty"):
        parse_document(data, name)


def test_text_that_is_not_utf8_is_refused():
    with pytest.raises(DocumentLoadError, match="UTF-8"):
        parse_document(b"\xff\xfe\x00\x81", "a.txt")


@pytest.mark.parametrize("name", ["a.docx", "a.html", "noextension"])
def test_other_file_types_are_refused_and_the_supported_ones_are_listed(name):
    with pytest.raises(DocumentLoadError, match=r"supported: \.md"):
        parse_document(b"text", name)
