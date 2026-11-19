"""CiteVerify — evidence-first citation verification.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import html
import json

import streamlit as st

from citeverify.config import Settings, get_settings
from citeverify.extract import ExtractionError, extract_claims_and_references
from citeverify.ingest import extract_pdf, extract_text
from citeverify.llm import LLMClient, LLMUnavailable
from citeverify.models import ClaimResult, Confidence, Report, Verdict
from citeverify.report import (
    CONFIDENCE_LABELS,
    VERDICT_LABELS,
    build_report,
    load_demo_report,
    report_to_json,
    report_to_markdown,
)
from citeverify.resolve import ResolutionError, check_doi, resolve_all
from citeverify.verify import verify_claims

VERDICT_CLASS = {
    Verdict.SUPPORTED: "supported",
    Verdict.PARTIALLY_SUPPORTED: "partially_supported",
    Verdict.UNSUPPORTED: "unsupported",
    Verdict.CONTRADICTED: "contradicted",
    Verdict.UNVERIFIABLE: "unverifiable",
}

SUMMARY_SPECS = [
    ("total", "Claims", "total"),
    ("supported", "Supported", "supported"),
    ("partially_supported", "Partial", "partially_supported"),
    ("unsupported", "Unsupported", "unsupported"),
    ("contradicted", "Contradicted", "contradicted"),
    ("unverifiable", "Unverifiable", "unverifiable"),
]

DEMO_RETRACTED_DOI = "10.1016/S0140-6736(97)11096-0"


def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Inter:wght@400;500;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', system-ui, -apple-system, sans-serif; }
        .stApp { background: #F7F3EA; }
        .block-container { padding-top: 3.4rem; padding-bottom: 4rem; max-width: 1180px; }
        h1, h2, h3 { font-family: 'Source Serif 4', Georgia, serif; color: #172026; }
        [data-testid="stSidebar"] { background: #EFE8DA; border-right: 1px solid #DED3C0; }
        [data-testid="stSidebar"] * { color: #24303A; }
        .cv-brand { font-family: 'Source Serif 4', Georgia, serif; font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; }
        .cv-tag { color: #6B5B47; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.12em; }
        .cv-hero { border-bottom: 1px solid #DED3C0; padding-bottom: 1rem; margin-bottom: 1.1rem; }
        .cv-kicker { color: #0F766E; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; }
        .cv-title { font-family: 'Source Serif 4', Georgia, serif; font-size: 2.25rem; line-height: 1.12; color: #172026; margin: 0.15rem 0 0.35rem; }
        .cv-sub { color: #5B6570; font-size: 1rem; }
        .summary-card { background: #FFFDF7; border: 1px solid #E4DACB; border-radius: 12px; padding: 0.7rem 0.85rem; min-height: 5.2rem; }
        .summary-value { font-family: 'Source Serif 4', Georgia, serif; font-size: 1.65rem; font-weight: 700; line-height: 1; color: #172026; }
        .summary-label { color: #6B5B47; font-size: 0.56rem; text-transform: uppercase; letter-spacing: 0.03em; margin-top: 0.3rem; white-space: nowrap; }
        .summary-card.supported { border-top: 4px solid #15803D; }
        .summary-card.partially_supported { border-top: 4px solid #B45309; }
        .summary-card.unsupported { border-top: 4px solid #C2410C; }
        .summary-card.contradicted { border-top: 4px solid #B91C1C; }
        .summary-card.unverifiable { border-top: 4px solid #6B7280; }
        .summary-card.total { border-top: 4px solid #0F766E; }
        .verdict-badge { display: inline-block; padding: 0.26rem 0.58rem; border-radius: 999px; font-size: 0.66rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; white-space: nowrap; }
        .verdict-supported { background: #DCFCE7; color: #166534; }
        .verdict-partially_supported { background: #FEF3C7; color: #92400E; }
        .verdict-unsupported { background: #FFEDD5; color: #9A3412; }
        .verdict-contradicted { background: #FEE2E2; color: #991B1B; }
        .verdict-unverifiable { background: #E5E7EB; color: #374151; }
        .confidence-note { color: #6B5B47; font-size: 0.76rem; margin-top: 0.2rem; }
        .quote { border-left: 3px solid #0F766E; padding: 0.45rem 0.8rem; background: #F0FDFA; color: #134E4A; font-style: italic; margin: 0.25rem 0 0.5rem; }
        .source-line { color: #5B6570; font-size: 0.82rem; margin-bottom: 0.4rem; }
        [data-testid="stVerticalBlockBorderWrapper"] { background: #FFFDF7; border-color: #E4DACB; border-radius: 14px; }
        .stButton > button { border-radius: 9px; }
        .stDownloadButton > button { border-radius: 9px; }
        .small-muted { color: #6B5B47; font-size: 0.82rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    defaults = {
        "report": None,
        "report_mode": None,
        "live_report": None,
        "doi_result": None,
        "doi_query": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def verdict_badge(result: ClaimResult) -> str:
    cls = VERDICT_CLASS.get(result.verdict, "unverifiable")
    label = VERDICT_LABELS.get(result.verdict, result.verdict.value)
    return f'<span class="verdict-badge verdict-{cls}">{html.escape(label)}</span>'


def confidence_label(result: ClaimResult) -> str:
    return CONFIDENCE_LABELS.get(result.confidence, result.confidence.value)


def render_sidebar(settings: Settings, llm: LLMClient):
    with st.sidebar:
        st.markdown('<div class="cv-brand">CiteVerify</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="cv-tag">Evidence, not verdicts</div>',
            unsafe_allow_html=True,
        )
        st.write("")
        mode = st.radio(
            "Mode",
            ["Demo report", "Analyze a paper"],
            index=0,
            label_visibility="collapsed",
        )

        uploaded = None
        pasted = ""
        max_claims = 8
        analyze_clicked = False

        if mode == "Demo report":
            st.info(
                "Prebuilt report. Works offline and needs no API key. "
                "The demo paper is illustrative; the cited sources are real."
            )
            if st.button("Reload demo", use_container_width=True):
                st.session_state.report = None
                st.session_state.report_mode = None
        else:
            st.caption("Upload a PDF or paste text. New-paper analysis needs an LLM key.")
            uploaded = st.file_uploader("Upload a paper", type=["pdf"])
            pasted = st.text_area(
                "…or paste paper text",
                height=150,
                placeholder="Paste the paper text, including the reference section.",
            )
            max_claims = st.slider("Maximum claims", 3, 10, 8)
            analyze_clicked = st.button(
                "Analyze paper", type="primary", use_container_width=True
            )
            if not settings.llm_configured:
                st.warning("No LLM_API_KEY configured. Use the demo report instead.")

        st.divider()
        st.markdown("#### DOI quick check")
        st.caption("Check retraction status and metadata without an LLM.")
        if st.button("Use example retracted DOI", use_container_width=True):
            st.session_state.doi_query = DEMO_RETRACTED_DOI
        doi_query = st.text_input(
            "DOI",
            key="doi_query",
            placeholder="10.1016/S0140-6736(97)11096-0",
            label_visibility="collapsed",
        )
        doi_clicked = st.button("Check DOI", use_container_width=True)

        if doi_clicked:
            if not doi_query.strip():
                st.warning("Enter a DOI first.")
            else:
                with st.spinner("Checking Crossref and OpenAlex…"):
                    try:
                        st.session_state.doi_result = check_doi(doi_query, settings)
                    except (ResolutionError, Exception) as exc:
                        st.session_state.doi_result = {"error": str(exc)}

        result = st.session_state.get("doi_result")
        if isinstance(result, dict) and result.get("error"):
            st.error(result["error"])
        elif result is not None:
            if result.is_retracted:
                st.error(f"Retracted source: {result.title or result.doi}")
            else:
                st.success(f"No retraction flag found: {result.title or result.doi}")
            if result.year:
                st.caption(f"{result.year} · {result.doi}")
            if result.url:
                st.markdown(f"[Open source ↗]({result.url})")
            st.caption("OpenAlex retraction status. Absence of a flag is not proof.")

        if st.session_state.get("report") is not None:
            report = st.session_state.report
            st.divider()
            st.markdown("#### Export")
            st.download_button(
                "Download Markdown",
                data=report_to_markdown(report),
                file_name="citeverify_report.md",
                mime="text/markdown",
                use_container_width=True,
            )
            st.download_button(
                "Download JSON",
                data=report_to_json(report),
                file_name="citeverify_report.json",
                mime="application/json",
                use_container_width=True,
            )

    return mode, uploaded, pasted, max_claims, analyze_clicked


def run_analysis(
    uploaded,
    pasted: str,
    max_claims: int,
    settings: Settings,
    llm: LLMClient,
) -> None:
    if uploaded is None and not pasted.strip():
        st.error("Upload a PDF or paste some paper text first.")
        return

    with st.status("Analyzing paper…", expanded=True) as status:
        try:
            st.write("Reading the paper…")
            if uploaded is not None:
                paper = extract_pdf(uploaded.getvalue(), uploaded.name)
            else:
                paper = extract_text(pasted, filename="pasted-text.txt")
            st.write(f"Loaded **{paper.title}** ({len(paper.pages)} page(s)).")

            st.write("Extracting cited claims and references…")
            title, claims, references = extract_claims_and_references(
                paper, llm, max_claims=max_claims
            )
            st.write(
                f"Found {len(claims)} cited claims and {len(references)} references."
            )

            st.write("Resolving sources through Crossref and OpenAlex…")
            references = resolve_all(references, settings)
            resolved = sum(1 for ref in references if ref.resolved)
            st.write(f"Resolved {resolved}/{len(references)} references.")

            st.write("Verifying claims against the source text…")
            results = verify_claims(claims, references, llm)
            report = build_report(title, paper.filename, results, mode="live")
            st.session_state.report = report
            st.session_state.live_report = report
            st.session_state.report_mode = "live"
            status.update(label="Analysis complete", state="complete")
        except LLMUnavailable as exc:
            status.update(label="Analysis needs an LLM key", state="error")
            st.error(str(exc))
        except (ExtractionError, ValueError) as exc:
            status.update(label="Could not extract claims", state="error")
            st.error(str(exc))
        except Exception as exc:
            status.update(label="Analysis failed", state="error")
            st.error(f"Something went wrong: {exc}")


def render_header(title: str, subtitle: str, kicker: str = "Citation forensics") -> None:
    st.markdown(
        f"""
        <div class="cv-hero">
          <div class="cv-kicker">{html.escape(kicker)}</div>
          <div class="cv-title">{html.escape(title)}</div>
          <div class="cv-sub">{html.escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary(report: Report) -> None:
    counts = report.summary
    columns = st.columns(len(SUMMARY_SPECS))
    for column, (key, label, css_class) in zip(columns, SUMMARY_SPECS):
        with column:
            st.markdown(
                f"""
                <div class="summary-card {css_class}">
                  <div class="summary-value">{counts.get(key, 0)}</div>
                  <div class="summary-label">{html.escape(label)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    if counts.get("flagged"):
        st.caption(f"{counts['flagged']} claim(s) carry a source or evidence flag.")


def render_claim(result: ClaimResult, index: int) -> None:
    with st.container(border=True):
        top_left, top_right = st.columns([5, 2])
        with top_left:
            st.caption(
                f"Claim {index}  ·  {result.claim.section}  ·  "
                f"{result.claim.citation_marker or 'citation not mapped'}"
            )
            st.markdown(f"**{result.claim.text}**")
        with top_right:
            st.markdown(verdict_badge(result), unsafe_allow_html=True)
            st.markdown(
                f'<div class="confidence-note">Confidence: '
                f"{html.escape(confidence_label(result))}</div>",
                unsafe_allow_html=True,
            )

        source_title = result.source_title or "Unknown source"
        source_year = f" ({result.source_year})" if result.source_year else ""
        st.markdown(
            f'<div class="source-line">Source: {html.escape(source_title)}'
            f"{html.escape(source_year)}</div>",
            unsafe_allow_html=True,
        )

        if result.flags:
            flag_text = ", ".join(flag.replace("_", " ") for flag in result.flags)
            if "retracted" in result.flags:
                st.error(f"Source flag: {flag_text}. This citation needs scrutiny.")
            else:
                st.warning(f"Source flag: {flag_text}.")

        st.markdown("**Evidence from the source**")
        if result.evidence_quote:
            st.markdown(
                f'<div class="quote">“{html.escape(result.evidence_quote)}”</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("No verbatim quote. The claim is marked unverifiable by design.")

        if result.reason:
            st.markdown(f"**Why:** {result.reason}")
        if result.suggested_fix:
            st.info(f"**Suggested fix:** {result.suggested_fix}")

        action_left, action_right = st.columns([3, 2])
        with action_left:
            if result.source_url:
                st.markdown(f"[Open source ↗]({result.source_url})")
            elif result.reference and result.reference.doi:
                st.markdown(f"[Open source ↗](https://doi.org/{result.reference.doi})")
            else:
                st.caption("No source link available.")
        with action_right:
            st.checkbox(
                "Reviewed",
                key=f"reviewed_{result.claim.id}",
                help="A human-review marker for the demo. It is not persisted.",
            )

        with st.expander("Source metadata and reference"):
            reference = result.reference
            if reference is None:
                st.caption("No reference matched.")
            else:
                if reference.title:
                    st.write(f"**Title:** {reference.title}")
                if reference.authors:
                    st.write(f"**Authors:** {', '.join(reference.authors[:8])}")
                if reference.year:
                    st.write(f"**Year:** {reference.year}")
                if reference.doi:
                    st.write(f"**DOI:** {reference.doi}")
                if reference.provider:
                    st.write(f"**Provider:** {reference.provider}")
                st.caption(reference.raw or "No raw reference text.")


def render_report(report: Report, settings: Settings) -> None:
    render_header(
        report.paper_title,
        "Claims checked against the cited sources. Every verdict needs evidence.",
        kicker="CiteVerify report",
    )
    if report.mode == "demo":
        st.info(
            "**Demo report.** The citing paper is illustrative; the cited papers and "
            "their abstracts are real. Upload your own paper to run the live pipeline."
        )

    render_summary(report)

    report_tab, eval_tab, about_tab = st.tabs(["Report", "Evaluation", "About"])
    with report_tab:
        options = [verdict.value for verdict in Verdict]
        selected = st.multiselect(
            "Filter by verdict",
            options=options,
            format_func=lambda value: VERDICT_LABELS[Verdict(value)],
            default=[],
            placeholder="All verdicts",
        )
        shown = report.results
        if selected:
            shown = [result for result in report.results if result.verdict.value in selected]
        if not shown:
            st.caption("No claims match that filter.")
        for index, result in enumerate(shown, start=1):
            render_claim(result, index)

    with eval_tab:
        render_evaluation(settings)

    with about_tab:
        render_about(settings)


def render_evaluation(settings: Settings) -> None:
    st.markdown("### Gold-set check")
    st.write(
        "A small hand-labelled set over real open-access abstracts. It is a sanity "
        "check, not a benchmark. The point is to show where the verifier agrees, "
        "where it fails, and whether it can anchor verdicts to a quote."
    )
    results_path = settings.gold_set_path.parent / "gold_set_results.json"
    if not results_path.exists():
        st.info("No evaluation results yet. Run the harness with an LLM key:")
        st.code("python scripts/evaluate.py", language="powershell")
        st.caption(
            "The demo report and the gold set are generated by "
            "`python scripts/make_demo.py`."
        )
        return

    data = json.loads(results_path.read_text(encoding="utf-8"))
    accuracy = data.get("accuracy", 0.0)
    quote_rate = data.get("quote_validity", 0.0)
    metric_left, metric_middle, metric_right = st.columns(3)
    metric_left.metric("Verdict agreement", f"{accuracy:.0%}")
    metric_middle.metric("Quote validity", f"{quote_rate:.0%}")
    metric_right.metric("Claims", data.get("total", 0))
    if accuracy < 0.8:
        st.warning(
            "This is below our target. That is useful: it exposes the hard cases "
            "and gives the pitch something honest to discuss."
        )
    rows = [
        {
            "Case": row["id"],
            "Expected": VERDICT_LABELS.get(Verdict(row["expected"]), row["expected"]),
            "Got": VERDICT_LABELS.get(Verdict(row["got"]), row["got"]),
            "Match": "yes" if row["correct"] else "no",
            "Quote": "yes" if row["quote_ok"] else "no",
        }
        for row in data.get("rows", [])
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("Small sample. Do not present this as a general accuracy claim.")


def render_about(settings: Settings) -> None:
    st.markdown("### What CiteVerify does")
    st.write(
        "It reads a paper, extracts claims that have citations, resolves each "
        "citation to its source, and asks a source-grounded model whether that "
        "source supports the claim. The important part is what it refuses to do: "
        "if it cannot find a verbatim quote, it marks the claim unverifiable."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("#### Pipeline")
        st.markdown(
            "1. Ingest the PDF or pasted text.\n"
            "2. Extract cited claims and the reference list.\n"
            "3. Resolve DOIs/titles through Crossref and OpenAlex.\n"
            "4. Compare each claim only against the retrieved source text.\n"
            "5. Validate the evidence quote and build the report."
        )
        st.markdown("#### Verdicts")
        st.markdown(
            "- **Supported** — direct support.\n"
            "- **Partially supported** — weaker or narrower support.\n"
            "- **Unsupported** — the source does not address it.\n"
            "- **Contradicted** — the source says the opposite.\n"
            "- **Unverifiable** — not enough source text for a responsible call."
        )
    with right:
        st.markdown("#### Deliberate limits")
        st.markdown(
            "- Abstract-level evidence by default; full-text retrieval is next.\n"
            "- Heuristic citation matching; unusual styles may fail.\n"
            "- Confidence is a rubric, not a calibrated probability.\n"
            "- Human review is part of the design, not an afterthought."
        )
        st.markdown("#### Stack")
        st.caption(
            "Python · Streamlit · PyMuPDF · Crossref · OpenAlex · Pydantic · "
            "one source-grounded LLM call per claim"
        )
    st.divider()
    render_deployment_diagnostics(settings)
    st.divider()
    st.caption(
        "Built for INNOVEDGE Hackathon 2026. CiteVerify is evidence for human "
        "review, not a final verdict on a paper."
    )


def render_deployment_diagnostics(settings: Settings) -> None:
    """Show what the running process actually loaded.

    Deployed apps cannot read the local .env, so the usual failure is a missing
    or misnamed environment variable. This reports presence and shape only —
    never the secret itself.
    """
    with st.expander("Deployment diagnostics"):
        key = settings.llm_api_key or ""
        st.write(
            {
                "LLM_API_KEY present": bool(key),
                "key length": len(key),
                "key format recognised": key.startswith(("AQ.", "AIza")),
                "LLM_MODEL": settings.llm_model,
                "LLM_BASE_URL": settings.llm_base_url or "(SDK default)",
                "CROSSREF_MAILTO": settings.crossref_mailto,
                "demo report found": settings.demo_report_path.exists(),
            }
        )
        if not key:
            st.warning(
                "Running without an API key, so only the demo report is available. "
                "On Render, confirm the variable is named exactly LLM_API_KEY, then "
                "trigger a new deploy — environment changes only reach a fresh "
                "instance."
            )


def render_empty_state() -> None:
    render_header(
        "Check the citation, not just the reference.",
        "Upload a paper and see which claims its sources actually support.",
        kicker="CiteVerify",
    )
    st.markdown(
        """
        <div style="background:#FFFDF7;border:1px solid #E4DACB;border-radius:16px;padding:1.2rem 1.4rem;">
          <h3 style="margin-top:0;">Start with the demo</h3>
          <p style="color:#5B6570;margin-bottom:.4rem;">
            The sidebar has a prebuilt report that needs no API key. It shows
            supported, partially supported, contradicted, unsupported, and
            unverifiable claims — each with a source quote and DOI link.
          </p>
          <p style="color:#5B6570;margin-bottom:0;">
            To analyze a new paper, switch to <b>Analyze a paper</b> and add an
            LLM key in <code>.env</code>.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    steps = st.columns(4)
    for column, (number, title, text) in zip(
        steps,
        [
            ("01", "Ingest", "PDF or pasted text. References included."),
            ("02", "Resolve", "DOI and title lookup via Crossref and OpenAlex."),
            ("03", "Verify", "Source-only comparison with a quote-or-abstain rule."),
            ("04", "Report", "Verdicts, evidence, confidence, and suggested fixes."),
        ],
    ):
        with column:
            st.markdown(
                f"""
                <div class="summary-card total">
                  <div class="summary-value">{number}</div>
                  <div class="summary-label">{html.escape(title)}</div>
                  <div class="small-muted" style="margin-top:.45rem;">{html.escape(text)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def main() -> None:
    st.set_page_config(
        page_title="CiteVerify — evidence, not verdicts",
        page_icon="✓",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    init_state()
    settings = get_settings()
    llm = LLMClient(settings)

    mode, uploaded, pasted, max_claims, analyze_clicked = render_sidebar(settings, llm)

    if mode == "Demo report":
        if st.session_state.report_mode != "demo":
            try:
                st.session_state.report = load_demo_report(settings.demo_report_path)
                st.session_state.report_mode = "demo"
            except Exception as exc:
                st.error(str(exc))
                st.session_state.report = None
    elif st.session_state.report_mode == "demo":
        st.session_state.report = st.session_state.get("live_report")
        st.session_state.report_mode = "live" if st.session_state.report else None

    if analyze_clicked:
        run_analysis(uploaded, pasted, max_claims, settings, llm)

    report = st.session_state.get("report")
    if report is None:
        render_empty_state()
    else:
        render_report(report, settings)


if __name__ == "__main__":
    main()
