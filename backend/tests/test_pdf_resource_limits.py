"""Real PDF worker limits and process lifecycle (no external services)."""
import pytest
import pymupdf

from backend import file_parser


def make_pdf(pages=1):
    with pymupdf.open() as doc:
        for _ in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), 'PDF_RESOURCE_TEST document text')
        return doc.tobytes()


def test_pdf_page_limit_prevents_parsing(monkeypatch):
    monkeypatch.setenv('PDF_MAX_PAGES', '1')
    with pytest.raises(ValueError, match='page limit'):
        file_parser.parse_pdf(make_pdf(2))


def test_small_pdf_layout_is_preserved_from_any_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert 'PDF_RESOURCE_TEST' in file_parser.parse_pdf(make_pdf())


def test_corrupt_pdf_is_a_limit_error():
    with pytest.raises(file_parser.PdfParseLimit, match='Unable to parse PDF'):
        file_parser.parse_pdf(b'%PDF-not-valid')


def test_timeout_kills_and_reaps_worker_and_releases_slot(monkeypatch):
    import subprocess
    spawned = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(file_parser.subprocess, 'Popen', capture)
    monkeypatch.setenv('PDF_PARSE_TIMEOUT_SECONDS', '0.000001')
    with pytest.raises(file_parser.PdfParseLimit, match='time limit'):
        file_parser.parse_pdf(make_pdf())
    assert len(spawned) == 1
    assert spawned[0].poll() is not None
    assert spawned[0].stdin.closed and spawned[0].stdout.closed
    monkeypatch.setenv('PDF_PARSE_TIMEOUT_SECONDS', '20')
    assert 'PDF_RESOURCE_TEST' in file_parser.parse_pdf(make_pdf())


def test_concurrent_pdf_admission_refuses_without_starting_process(monkeypatch):
    from unittest.mock import Mock
    process = Mock()
    monkeypatch.setattr(file_parser.subprocess, 'Popen', process)
    assert file_parser._PDF_PARSE_SLOTS.acquire(blocking=False)
    assert file_parser._PDF_PARSE_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(file_parser.PdfParseBusy, match='busy'):
            file_parser.parse_pdf(make_pdf())
        process.assert_not_called()
    finally:
        file_parser._PDF_PARSE_SLOTS.release()
        file_parser._PDF_PARSE_SLOTS.release()


def test_real_pdf_output_is_bounded():
    with pymupdf.open() as doc:
        for _ in range(30):
            page = doc.new_page()
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 780),
                                ('OUTPUT_LIMIT ' + 'word ' * 10 + '\n') * 40, fontsize=8)
        content = doc.tobytes()
    text = file_parser.parse_pdf(content)
    assert len(text) <= 50_000
    assert text.endswith('[PDF text truncated at output limit]')
