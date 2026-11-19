import pymupdf

from citeverify.ingest import extract_pdf, extract_text


def _make_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A Test Paper on Citation Checking")
    page.insert_text((72, 100), "Abstract: This paper makes a cited claim [1].")
    page.insert_text((72, 200), "References")
    page.insert_text(
        (72, 220),
        "[1] Smith, J. (2020). A study of citations. https://doi.org/10.1234/test",
    )
    data = doc.tobytes()
    doc.close()
    return data


def test_extract_pdf_finds_title_and_references():
    paper = extract_pdf(_make_pdf(), "test.pdf")
    assert "A Test Paper" in paper.title
    assert "References" in paper.references_text
    assert "10.1234/test" in paper.references_text
    assert paper.filename == "test.pdf"


def test_extract_text_splits_references():
    paper = extract_text(
        "Pasted Paper\n\nA claim [1].\n\nReferences\n[1] Doe, A. (2021). Work.",
        filename="pasted.txt",
    )
    assert paper.title == "Pasted Paper"
    assert "Doe" in paper.references_text
