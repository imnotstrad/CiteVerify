from citeverify.config import get_settings
from citeverify.report import load_demo_report, report_to_markdown


def test_demo_report_loads_and_summarizes():
    report = load_demo_report(get_settings().demo_report_path)
    assert report.summary["total"] == 10
    assert report.summary["supported"] == 4
    assert report.summary["contradicted"] == 2
    assert report.summary["partially_supported"] == 2
    assert report.summary["unsupported"] == 1
    assert report.summary["unverifiable"] == 1


def test_demo_markdown_contains_evidence():
    report = load_demo_report(get_settings().demo_report_path)
    markdown = report_to_markdown(report)
    assert "CiteVerify report" in markdown
    assert "Contradicted" in markdown
    assert "dispensing with recurrence and convolutions" in markdown
