"""CiteVerify — evidence-first citation verification.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import html
import json
import time

import streamlit as st

from citeverify.citefix import correct_citation
from citeverify.config import Settings, get_settings
from citeverify.evidence import find_evidence, highlight
from citeverify.extract import ExtractionError, extract_claims_and_references
from citeverify.ingest import extract_pdf, extract_text
from citeverify.llm import LLMClient, LLMUnavailable
from citeverify.models import ClaimResult, Confidence, Reference, Report, Verdict
from citeverify.report import (
    CONFIDENCE_LABELS,
    VERDICT_LABELS,
    build_report,
    load_demo_report,
    report_to_json,
    report_to_markdown,
)
from citeverify.reliability import reliability_for_reference
from citeverify.resolve import ResolutionError, check_doi, resolve_all
from citeverify.verify import verify_claim, verify_claims

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


def inject_css(dark: bool = False) -> None:
    palette = {
        "bg": "#10191F" if dark else "#F7F3EA",
        "panel": "#19262D" if dark else "#FFFDF7",
        "text": "#E8F0F1" if dark else "#172026",
        "muted": "#A4B4BA" if dark else "#5B6570",
        "border": "#34464D" if dark else "#E4DACB",
        "accent": "#63C6B6" if dark else "#0F766E",
        "soft": "#20343A" if dark else "#F0FDFA",
        "soft_text": "#D3ECE7" if dark else "#134E4A",
        "input": "#142129" if dark else "#FFFFFF",
    }
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Inter:wght@400;500;600;700&display=swap');
    :root {{
      color-scheme: {"dark" if dark else "light"};
      --cv-bg:{palette["bg"]}; --cv-panel:{palette["panel"]};
      --cv-text:{palette["text"]}; --cv-muted:{palette["muted"]};
      --cv-border:{palette["border"]}; --cv-accent:{palette["accent"]};
      --cv-soft:{palette["soft"]}; --cv-soft-text:{palette["soft_text"]};
      --cv-input:{palette["input"]};
    }}
    html, body, .stApp, [data-testid="stAppViewContainer"] {{
      background:var(--cv-bg)!important; color:var(--cv-text)!important;
      font-family:Inter,system-ui,sans-serif;
    }}
    .block-container {{max-width:1000px;padding-top:1.2rem;padding-bottom:3rem;}}
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {{display:none!important;}}
    header[data-testid="stHeader"] {{background:transparent!important;}}
    h1,h2,h3,h4,p,li,label,.stMarkdown,.stMarkdown p,.stMarkdown li,
    [data-testid="stMarkdownContainer"],[data-testid="stCaptionContainer"],
    [data-testid="stWidgetLabel"],[data-testid="stFileUploaderDropzoneInstructions"] {{
      color:var(--cv-text)!important;
    }}
    h1,h2,h3,.cv-brand,.cv-title,.claim-card-title {{font-family:'Source Serif 4',Georgia,serif;}}
    a {{color:var(--cv-accent)!important;}}
    .cv-topbar {{display:flex;align-items:center;justify-content:center;padding:.15rem 0 1rem;}}
    .cv-brand {{font-size:2rem;font-weight:700;letter-spacing:-.04em;color:var(--cv-text);}}
    .cv-tag {{font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;color:var(--cv-muted);}}
    .cv-hero {{border-bottom:1px solid var(--cv-border);padding-bottom:.8rem;margin-bottom:1rem;}}
    .cv-kicker {{color:var(--cv-accent)!important;font-size:.72rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;}}
    .cv-title {{font-size:2rem;line-height:1.15;color:var(--cv-text);margin:.15rem 0 .3rem;}}
    .cv-sub,.small-muted,.source-line,.confidence-note {{color:var(--cv-muted)!important;}}
    .summary-card {{background:var(--cv-panel);border:1px solid var(--cv-border);border-radius:14px;padding:.8rem .9rem;}}
    .summary-value {{font-size:1.6rem;font-weight:700;color:var(--cv-text);}}
    .summary-label,.claim-card-eyebrow {{color:var(--cv-muted)!important;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;}}
    .claim-card-title {{font-size:1.4rem;font-weight:600;line-height:1.45;color:var(--cv-text)!important;margin:.5rem 0 1rem;}}
    .verdict-badge {{display:inline-block;padding:.32rem .72rem;border-radius:999px;font-size:.68rem;font-weight:700;text-transform:uppercase;}}
    .verdict-supported {{background:#DCFCE7;color:#166534!important;}}
    .verdict-partially_supported {{background:#FEF3C7;color:#92400E!important;}}
    .verdict-unsupported {{background:#FFEDD5;color:#9A3412!important;}}
    .verdict-contradicted {{background:#FEE2E2;color:#991B1B!important;}}
    .verdict-unverifiable {{background:#E5E7EB;color:#374151!important;}}
    .quote {{border-left:3px solid var(--cv-accent);padding:.8rem 1rem;background:var(--cv-soft);color:var(--cv-soft-text)!important;font-style:italic;border-radius:0 10px 10px 0;line-height:1.6;}}
    .hl-passage,[data-testid="stVerticalBlockBorderWrapper"] {{background:var(--cv-panel)!important;border:1px solid var(--cv-border)!important;border-radius:16px;}}
    .hl-passage mark {{background:#FFF3A3;color:#172026!important;padding:0 2px;border-radius:3px;}}
    .hl-passage .best {{background:#FFE082;color:#172026!important;padding:2px 3px;border-radius:4px;}}
    .stButton>button,.stDownloadButton>button {{border-radius:10px;border:1px solid var(--cv-border);min-height:2.6rem;background:var(--cv-panel);color:var(--cv-text)!important;}}
    .stButton>button[kind="primary"] {{background:var(--cv-accent)!important;color:#071A18!important;border-color:var(--cv-accent)!important;}}
    .stButton>button:disabled {{color:var(--cv-muted)!important;opacity:.4;}}
    [data-baseweb="input"]>div,[data-baseweb="textarea"]>div,[data-baseweb="select"]>div,
    [data-testid="stFileUploaderDropzone"] {{background:var(--cv-input)!important;border-color:var(--cv-border)!important;}}
    input,textarea,[data-baseweb="input"] input,[data-baseweb="textarea"] textarea {{color:var(--cv-text)!important;background:transparent!important;}}
    input::placeholder,textarea::placeholder {{color:var(--cv-muted)!important;opacity:1;}}
    [data-testid="stFileUploaderDropzone"] * {{color:var(--cv-text)!important;}}
    [data-testid="stProgressBar"]>div>div {{background:var(--cv-accent)!important;}}
    [data-testid="stPopover"] button {{color:var(--cv-text)!important;}}
    </style>
    """, unsafe_allow_html=True)



def init_state() -> None:
    defaults = {
        "report": None,
        "report_mode": None,
        "live_report": None,
        "doi_result": None,
        "doi_query": "",
        "dark_mode": False,
        "claim_index": 0,
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


def render_topbar() -> None:
    left, center, right = st.columns([1.2, 4.6, 1.5], vertical_alignment="center")
    with left:
        st.toggle("Dark mode", key="dark_mode", help="Switch between dark and light appearance.")
    with center:
        st.markdown('<div class="cv-topbar"><div class="cv-brand">CiteVerify</div></div>', unsafe_allow_html=True)
    with right:
        with st.popover("About me", use_container_width=True):
            st.markdown("### About CiteVerify")
            st.write("Researchers cite papers that often do not say what the citing sentence claims. Existing tools check whether a reference exists or is formatted correctly; CiteVerify checks **claim support**.")
            st.write("For each cited claim, it produces a verdict, a verbatim evidence quote, a confidence label, a DOI/source link, an optional suggested fix, and flags such as retracted.")
            st.markdown("**The design rule is simple: no verbatim quote, no verdict.** If the source text is insufficient, the claim is marked unverifiable.")



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
            verification_started = time.perf_counter()
            results = verify_claims(claims, references, llm)
            verification_seconds = time.perf_counter() - verification_started
            st.write(f"Verification finished in **{verification_seconds:.1f} seconds**.")
            if verification_seconds > 60:
                st.warning(
                    "Verification exceeded the 60-second target. API latency or "
                    "rate limiting may be the cause."
                )
            report = build_report(title, paper.filename, results, mode="live")
            st.session_state.report = report
            st.session_state.live_report = report
            st.session_state.report_mode = "live"
            st.session_state.claim_index = 0
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


def render_highlighted_evidence(result: ClaimResult) -> None:
    """Show where the claim's key terms appear in the source abstract. No LLM involved."""
    abstract = (result.reference.abstract if result.reference else None) or ""
    if not abstract.strip():
        return
    matches = find_evidence(result.claim.text, abstract, top_k=1)
    with st.expander("Highlighted evidence in the source abstract"):
        if not matches:
            st.caption("No overlapping terms between the claim and this abstract.")
            return
        match = matches[0]
        st.caption(
            f"{match['match']} term overlap (score {match['score']}). "
            "The brighter sentence is the closest match."
        )
        st.markdown(
            '<div class="hl-passage">'
            + highlight(match["paragraph"], set(match["matched_terms"]), match["best_sentence"])
            + "</div>",
            unsafe_allow_html=True,
        )
        for note in match["notes"]:
            st.warning(note)


def render_reliability(reference) -> None:
    analysis = reliability_for_reference(reference)
    st.write(
        f"**Source reliability:** {analysis['score']}/100 ({analysis['grade']})"
    )
    st.caption(
        "Based on the abstract and metadata only: not a quality judgement on the study."
    )
    st.dataframe(
        [
            {"Factor": f["factor"], "Score": f"{f['points']}/{f['max']}", "Detail": f["reason"]}
            for f in analysis["factors"]
        ],
        use_container_width=True,
        hide_index=True,
    )
    for flag in analysis["flags"]:
        st.warning(flag)


def render_citation_fix(reference) -> None:
    if not (reference.raw or "").strip():
        return
    fixed = correct_citation(reference.raw)
    st.write("**Citation check (APA 7)**")
    if fixed["missing"]:
        st.caption("Could not find: " + ", ".join(fixed["missing"]))
    for issue in fixed["issues"]:
        st.caption(f"• {issue}")
    st.markdown(f"Suggested: {fixed['corrected']}")


def render_claim(
    result: ClaimResult,
    index: int,
    total: int,
    settings: Settings,
    llm: LLMClient,
) -> None:
    with st.container(border=True):
        left, right = st.columns([5, 2])
        with left:
            st.markdown(
                f'<div class="claim-card-eyebrow">Claim {index} of {total} · '
                f'{html.escape(result.claim.section)} · '
                f'{html.escape(result.claim.citation_marker or "Citation not mapped")}</div>',
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(verdict_badge(result), unsafe_allow_html=True)
            st.markdown(
                f'<div class="confidence-note">Confidence: '
                f'{html.escape(confidence_label(result))}</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div class="claim-card-title">{html.escape(result.claim.text)}</div>',
            unsafe_allow_html=True,
        )

        source_title = result.source_title or "Unknown source"
        source_year = f" ({result.source_year})" if result.source_year else ""
        st.markdown(
            f'<div class="source-line">Cited source: {html.escape(source_title)}'
            f'{html.escape(source_year)}</div>',
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
            st.caption("No verbatim quote was found. This claim is marked unverifiable.")

        if result.reason:
            st.markdown("**Why this verdict?**")
            st.write(result.reason)
        if result.suggested_fix:
            st.info(f"**Suggested fix:** {result.suggested_fix}")

        render_highlighted_evidence(result)

        action_left, action_right = st.columns([3, 2])
        with action_left:
            if result.source_url:
                st.markdown(f"[Open cited source ↗]({result.source_url})")
            elif result.reference and result.reference.doi:
                st.markdown(f"[Open cited source ↗](https://doi.org/{result.reference.doi})")
            else:
                st.caption("No source link available.")
        with action_right:
            st.checkbox(
                "Reviewed",
                key=f"reviewed_{result.claim.id}",
                help="A human-review marker for this session.",
            )

        with st.expander("Try this claim against another PDF"):
            st.caption(
                "Upload a separate source document. CiteVerify will re-check only "
                "this claim against the uploaded PDF and replace its displayed result."
            )
            alternate_pdf = st.file_uploader(
                "Alternative source PDF",
                type=["pdf"],
                key=f"alternate_source_{result.claim.id}",
            )
            if st.button(
                "Verify claim against uploaded PDF",
                key=f"verify_alternate_{result.claim.id}",
                disabled=alternate_pdf is None,
                type="secondary",
            ):
                try:
                    with st.spinner("Checking this claim against the new PDF…"):
                        alternate_paper = extract_pdf(
                            alternate_pdf.getvalue(), alternate_pdf.name
                        )
                        alternate_text = alternate_paper.full_text.strip()
                        if len(alternate_text) < 80:
                            st.error("The uploaded PDF does not contain enough extractable text.")
                        else:
                            alternate_reference = Reference(
                                id=f"alternate_{result.claim.id}",
                                raw=alternate_pdf.name,
                                title=alternate_paper.title or alternate_pdf.name,
                                abstract=alternate_text[:30000],
                                resolved=True,
                                provider="user-uploaded PDF",
                            )
                            alternate_result = verify_claim(
                                result.claim, alternate_reference, llm
                            )
                            current_report = st.session_state.report
                            revised_results = list(current_report.results)
                            original_index = next(
                                (
                                    position
                                    for position, item in enumerate(revised_results)
                                    if item.claim.id == result.claim.id
                                ),
                                None,
                            )
                            if original_index is not None:
                                revised_results[original_index] = alternate_result
                                updated_report = current_report.model_copy(
                                    update={"results": revised_results}
                                )
                                st.session_state.report = updated_report
                                if st.session_state.report_mode == "live":
                                    st.session_state.live_report = updated_report
                                st.success("This claim has been re-checked against the uploaded PDF.")
                                st.rerun()
                except Exception as exc:
                    st.error(f"Could not verify against that PDF: {exc}")

        with st.expander("Source metadata and reference"):
            reference = result.reference
            if reference is None:
                st.caption("No matched source metadata.")
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
                if reference.provider != "user-uploaded PDF":
                    render_reliability(reference)
                    render_citation_fix(reference)


def render_report(report: Report, settings: Settings, llm: LLMClient) -> None:
    if report.mode == "demo":
        st.caption("Demo report · The citing paper is illustrative; the cited papers and abstracts are real.")
    st.markdown(f'<div class="cv-hero"><div class="cv-kicker">Research review</div><div class="cv-title">{html.escape(report.paper_title)}</div><div class="cv-sub">Review one cited claim at a time.</div></div>', unsafe_allow_html=True)
    shown = report.results
    if not shown:
        st.info("No claims were extracted from this paper.")
        return
    current_index = min(max(0, int(st.session_state.get("claim_index", 0))), len(shown)-1)
    render_claim(shown[current_index], current_index+1, len(shown), settings, llm)

    # Card controls are deliberately placed directly beneath the flashcard.
    st.markdown('<div class="cv-card-controls"></div>', unsafe_allow_html=True)
    left, middle, right = st.columns([1, 5, 1], vertical_alignment="center")
    with left:
        previous_clicked = st.button("←", key="previous_claim", help="Previous claim", disabled=current_index == 0, use_container_width=True)
    with middle:
        st.markdown(f'<div style="text-align:center;color:var(--cv-muted);font-weight:700;letter-spacing:.08em;padding:.55rem 0;">CLAIM {current_index+1:02d} / {len(shown):02d}</div>', unsafe_allow_html=True)
    with right:
        next_clicked = st.button("→", key="next_claim", help="Next claim", disabled=current_index == len(shown)-1, use_container_width=True)
    if previous_clicked:
        st.session_state.claim_index = max(0, current_index-1)
        st.rerun()
    if next_clicked:
        st.session_state.claim_index = min(len(shown)-1, current_index+1)
        st.rerun()
    st.progress((current_index+1)/len(shown))

    st.divider()
    st.markdown("**Finished reviewing?**")
    c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
    with c1:
        if st.button("Start over", key="start_over", use_container_width=True):
            st.session_state.report = None
            st.session_state.live_report = None
            st.session_state.report_mode = None
            st.session_state.claim_index = 0
            st.rerun()
    with c2:
        new_pdf = st.file_uploader("Upload a new PDF", type=["pdf"], key="new_report_pdf")
        if st.button("Analyze new PDF", key="analyze_new_pdf", type="primary", disabled=new_pdf is None, use_container_width=True):
            run_analysis(new_pdf, "", 8, settings, llm)
            st.rerun()



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
            "Python · Streamlit · PyMuPDF · Hugging Face sentence-transformers · "
            "Crossref · OpenAlex · Pydantic · Gemini source-grounded verification"
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


def render_empty_state(settings: Settings, llm: LLMClient) -> None:
    st.markdown('<div style="text-align:center;padding:4vh 0 1.5vh;color:var(--cv-muted);">Drop a research paper into the upload area to begin.</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader("Drop your PDF here", type=["pdf"], key="home_pdf", help="Choose a PDF or drag it into this upload area.")
    st.caption("Or paste the paper text")
    pasted = st.text_area("Paste paper text", height=86, placeholder="Paste the paper text, including its reference list.", label_visibility="collapsed", key="home_pasted")
    col1, col2 = st.columns([1, 3], vertical_alignment="center")
    with col1:
        max_claims = st.selectbox("Claims to review", [4, 6, 8, 10], index=2, label_visibility="collapsed")
    with col2:
        if st.button("Research claims", type="primary", use_container_width=True, disabled=(uploaded is None and not pasted.strip())):
            run_analysis(uploaded, pasted, int(max_claims), settings, llm)
            st.rerun()
    st.caption("CiteVerify checks claims against resolved source evidence. It is designed to support human review, not replace it.")



def main() -> None:
    st.set_page_config(
        page_title="CiteVerify — evidence, not verdicts",
        page_icon="✓",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_state()
    inject_css(dark=st.session_state.get("dark_mode", False))
    settings = get_settings()
    llm = LLMClient(settings)
    render_topbar()
    report = st.session_state.get("report")
    if report is None:
        render_empty_state(settings, llm)
    else:
        render_report(report, settings, llm)


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()