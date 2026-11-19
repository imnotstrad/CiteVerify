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
from citeverify.pdf_export import PDFUnavailable, build_fixes_pdf
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
        "panel_alt": "#22343C" if dark else "#F0EBE1",
        "text": "#E8F0F1" if dark else "#172026",
        "muted": "#A4B4BA" if dark else "#5B6570",
        "border": "#34464D" if dark else "#E4DACB",
        "accent": "#63C6B6" if dark else "#0F766E",
        "soft": "#20343A" if dark else "#F0FDFA",
        "soft_text": "#D3ECE7" if dark else "#134E4A",
        "input": "#142129" if dark else "#FFFFFF",
        "success_bg": "#173B2B" if dark else "#DCFCE7",
        "success_text": "#B7F0C8" if dark else "#166534",
        "warning_bg": "#49391B" if dark else "#FEF3C7",
        "warning_text": "#F8D98A" if dark else "#92400E",
        "unsupported_bg": "#49301D" if dark else "#FFEDD5",
        "unsupported_text": "#FFD6A8" if dark else "#9A3412",
        "error_bg": "#482629" if dark else "#FEE2E2",
        "error_text": "#FFC1C1" if dark else "#991B1B",
        "info_bg": "#193744" if dark else "#DBEAFE",
        "info_text": "#B9E4F4" if dark else "#1E40AF",
        "neutral_bg": "#34424A" if dark else "#E5E7EB",
        "neutral_text": "#E2E8EC" if dark else "#374151",
    }
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Inter:wght@400;500;600;700&display=swap');
    :root {{
      color-scheme: {"dark" if dark else "light"};
      --cv-bg:{palette["bg"]}; --cv-panel:{palette["panel"]};
      --cv-panel-alt:{palette["panel_alt"]}; --cv-text:{palette["text"]};
      --cv-muted:{palette["muted"]}; --cv-border:{palette["border"]};
      --cv-accent:{palette["accent"]}; --cv-soft:{palette["soft"]};
      --cv-soft-text:{palette["soft_text"]}; --cv-input:{palette["input"]};
      --cv-success-bg:{palette["success_bg"]}; --cv-success-text:{palette["success_text"]};
      --cv-warning-bg:{palette["warning_bg"]}; --cv-warning-text:{palette["warning_text"]};
      --cv-unsupported-bg:{palette["unsupported_bg"]}; --cv-unsupported-text:{palette["unsupported_text"]};
      --cv-error-bg:{palette["error_bg"]}; --cv-error-text:{palette["error_text"]};
      --cv-info-bg:{palette["info_bg"]}; --cv-info-text:{palette["info_text"]};
      --cv-neutral-bg:{palette["neutral_bg"]}; --cv-neutral-text:{palette["neutral_text"]};
    }}

    /* Page and ordinary text */
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
      background:var(--cv-bg)!important;
      color:var(--cv-text)!important;
      font-family:Inter,system-ui,sans-serif;
    }}
    .block-container {{max-width:1000px;padding-top:1.2rem;padding-bottom:3rem;}}
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {{display:none!important;}}
    header[data-testid="stHeader"] {{background:transparent!important;}}
    h1,h2,h3,h4,p,li,label,
    [data-testid="stMarkdownContainer"],
    [data-testid="stWidgetLabel"] {{color:var(--cv-text)!important;}}
    [data-testid="stCaptionContainer"] {{color:var(--cv-muted)!important;}}
    h1,h2,h3,.cv-brand,.cv-title,.claim-card-title {{font-family:'Source Serif 4',Georgia,serif;}}
    a {{color:var(--cv-accent)!important;}}

    /* Brand and headings */
    .cv-topbar {{display:flex;align-items:center;justify-content:center;padding:.15rem 0 1rem;}}
    .cv-brand {{font-size:2rem;font-weight:700;letter-spacing:-.04em;color:var(--cv-text);}}
    .cv-tag {{font-size:.7rem;letter-spacing:.15em;text-transform:uppercase;color:var(--cv-muted);}}
    .cv-hero {{border-bottom:1px solid var(--cv-border);padding-bottom:.8rem;margin-bottom:1rem;}}
    .cv-kicker {{color:var(--cv-accent)!important;font-size:.72rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;}}
    .cv-title {{font-size:2rem;line-height:1.15;color:var(--cv-text);margin:.15rem 0 .3rem;}}
    .cv-sub,.small-muted,.source-line,.confidence-note {{color:var(--cv-muted)!important;}}

    /* Cards: each surface has a paired foreground */
    .summary-card {{background:var(--cv-panel);border:1px solid var(--cv-border);border-radius:14px;padding:.8rem .9rem;}}
    .summary-value {{font-size:1.6rem;font-weight:700;color:var(--cv-text)!important;}}
    .summary-label,.claim-card-eyebrow {{color:var(--cv-muted)!important;font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;}}
    .claim-card-title {{font-size:1.4rem;font-weight:600;line-height:1.45;color:var(--cv-text)!important;margin:.5rem 0 1rem;}}
    .verdict-badge {{display:inline-block;padding:.32rem .72rem;border-radius:999px;font-size:.68rem;font-weight:700;text-transform:uppercase;}}
    .verdict-supported {{background:var(--cv-success-bg);color:var(--cv-success-text)!important;}}
    .verdict-partially_supported {{background:var(--cv-warning-bg);color:var(--cv-warning-text)!important;}}
    .verdict-unsupported {{background:var(--cv-unsupported-bg);color:var(--cv-unsupported-text)!important;}}
    .verdict-contradicted {{background:var(--cv-error-bg);color:var(--cv-error-text)!important;}}
    .verdict-unverifiable {{background:var(--cv-neutral-bg);color:var(--cv-neutral-text)!important;}}
    .quote {{border-left:3px solid var(--cv-accent);padding:.8rem 1rem;background:var(--cv-soft);color:var(--cv-soft-text)!important;font-style:italic;border-radius:0 10px 10px 0;line-height:1.6;}}
    .hl-passage,[data-testid="stVerticalBlockBorderWrapper"] {{background:var(--cv-panel)!important;border:1px solid var(--cv-border)!important;border-radius:16px;}}
    .hl-passage mark {{background:#FFF3A3;color:#172026!important;padding:0 2px;border-radius:3px;}}
    .hl-passage .best {{background:#FFE082;color:#172026!important;padding:2px 3px;border-radius:4px;}}

    /* Buttons: normal, primary, popover trigger and file-picker button */
    .stButton>button,.stDownloadButton>button,
    [data-testid="stPopover"] > button,
    [data-testid="stFileUploader"] button {{
      border-radius:10px!important;
      border:1px solid var(--cv-border)!important;
      min-height:2.6rem;
      background:var(--cv-panel)!important;
      color:var(--cv-text)!important;
    }}
    .stButton>button[kind="primary"] {{
      background:var(--cv-accent)!important;
      color:#071A18!important;
      border-color:var(--cv-accent)!important;
    }}
    .stButton>button:disabled {{color:var(--cv-muted)!important;opacity:.55;}}
    [data-testid="stPopover"] > button:hover,
    [data-testid="stFileUploader"] button:hover,
    .stButton>button:hover {{border-color:var(--cv-accent)!important;}}

    /* Inputs and PDF drop zone */
    [data-baseweb="input"]>div,[data-baseweb="textarea"]>div,
    [data-baseweb="select"]>div,
    [data-testid="stFileUploaderDropzone"] {{
      background:var(--cv-input)!important;
      border:1px solid var(--cv-border)!important;
    }}
    input,textarea,[data-baseweb="input"] input,[data-baseweb="textarea"] textarea {{
      color:var(--cv-text)!important;background:transparent!important;
    }}
    input::placeholder,textarea::placeholder {{color:var(--cv-muted)!important;opacity:1;}}
    [data-testid="stFileUploaderDropzone"] {{
      border:1px dashed var(--cv-border)!important;
      border-radius:12px!important;
    }}
    [data-testid="stFileUploaderDropzone"] p,
    [data-testid="stFileUploaderDropzone"] span,
    [data-testid="stFileUploaderDropzone"] small {{
      color:var(--cv-text)!important;
    }}
    [data-testid="stFileUploader"] button {{
      background:var(--cv-panel)!important;
      color:var(--cv-text)!important;
    }}

    /* Streamlit message surfaces: keep text readable on the surface behind it */
    [data-testid="stAlert"] {{
      background:var(--cv-panel-alt)!important;
      border:1px solid var(--cv-border)!important;
      border-radius:12px!important;
    }}
    [data-testid="stAlert"] p,
    [data-testid="stAlert"] span,
    [data-testid="stAlert"] li {{color:var(--cv-text)!important;}}
    [data-testid="stExpander"] {{
      background:var(--cv-panel)!important;
      border:1px solid var(--cv-border)!important;
      border-radius:12px!important;
    }}
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary span {{color:var(--cv-text)!important;}}
    [data-testid="stMetric"] {{
      background:var(--cv-panel)!important;
      border:1px solid var(--cv-border)!important;
      border-radius:12px!important;padding:.7rem;
    }}
    [data-testid="stMetricLabel"],[data-testid="stMetricValue"],
    [data-testid="stMetricDelta"] {{color:var(--cv-text)!important;}}
    [data-testid="stDataFrame"],[data-testid="stTable"] {{
      background:var(--cv-panel)!important;color:var(--cv-text)!important;
    }}
    [data-testid="stCode"],.stCodeBlock {{
      background:var(--cv-panel-alt)!important;
      border:1px solid var(--cv-border)!important;
    }}
    [data-testid="stProgressBar"]>div>div {{background:var(--cv-accent)!important;}}
    [data-testid="stCheckbox"] label,[data-testid="stRadio"] label {{color:var(--cv-text)!important;}}

    /* Popover body: don't apply wildcard foreground overrides to buttons/icons. */
    [data-testid="stPopoverBody"] {{
      background:var(--cv-panel)!important;
      color:var(--cv-text)!important;
      border:1px solid var(--cv-border)!important;
    }}

    /* Streamlit wraps popover trigger text in nested elements; style those too. */
    [data-testid="stPopover"] > button,
    [data-testid="stPopover"] > button p,
    [data-testid="stPopover"] > button span,
    [data-testid="stPopover"] > button div {{
      color:var(--cv-text)!important;
      opacity:1!important;
    }}
    [data-testid="stPopoverBody"],
    [data-testid="stPopoverBody"] p,
    [data-testid="stPopoverBody"] span,
    [data-testid="stPopoverBody"] div,
    [data-testid="stPopoverBody"] label,
    [data-testid="stPopoverBody"] li,
    [data-testid="stPopoverBody"] strong,
    [data-testid="stPopoverBody"] h1,
    [data-testid="stPopoverBody"] h2,
    [data-testid="stPopoverBody"] h3 {{
      color:var(--cv-text)!important;
      opacity:1!important;
    }}
    [data-testid="stPopoverBody"] h1,
    [data-testid="stPopoverBody"] h2,
    [data-testid="stPopoverBody"] h3,
    [data-testid="stPopoverBody"] p,
    [data-testid="stPopoverBody"] strong {{color:var(--cv-text)!important;}}

    /* Dedicated About Us panel: solid surface and explicit high-contrast text. */
    .cv-about-panel {{
      background:var(--cv-panel)!important;
      color:var(--cv-text)!important;
      padding:.25rem .15rem;
      border-radius:10px;
    }}
    .cv-about-panel h3,
    .cv-about-panel p,
    .cv-about-panel strong {{
      color:var(--cv-text)!important;
      opacity:1!important;
    }}
    .cv-about-panel h3 {{margin:.2rem 0 .8rem;}}
    .cv-about-panel p {{line-height:1.6;margin:.55rem 0;}}
    .cv-about-panel strong {{font-weight:700;}}
    [data-testid="stPopoverBody"] *:not(svg):not(path) {{color:var(--cv-text)!important;}}
    [data-testid="stPopoverBody"] {{isolation:isolate;}}
    
    /* Source flags use a dedicated surface so their text never inherits
       Streamlit's default alert foreground colour. */
    .source-flag {{
      display:block;padding:.7rem .9rem;margin:.65rem 0;
      border:1px solid var(--cv-border);border-radius:10px;
      background:var(--cv-warning-bg);color:var(--cv-warning-text)!important;
      font-weight:600;line-height:1.45;
    }}
    .source-flag-retracted {{
      background:var(--cv-error-bg);color:var(--cv-error-text)!important;
      border-color:var(--cv-error-text);
    }}
    .source-flag * {{color:inherit!important;}}
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
        "stage": "home",  # home | reading
        "pending": None,
        "analysis_error": None,
        "home_error": None,
        "uploader_nonce": 0,
        "verify_seconds": None,
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
        with st.popover("About us", use_container_width=True):
            st.markdown(
                """
                <div class="cv-about-panel">
                  <h3>About CiteVerify</h3>
                  <p>Researchers cite papers that often do not say what the citing sentence claims. Existing tools check whether a reference exists or is formatted correctly; CiteVerify checks <strong>claim support</strong>.</p>
                  <p>For each cited claim, it produces a verdict, a verbatim evidence quote, a confidence label, a DOI/source link, an optional suggested fix, and flags such as retracted.</p>
                  <p><strong>The design rule is simple: no verbatim quote, no verdict.</strong> If the source text is insufficient, the claim is marked unverifiable.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )



READING_STEPS = [
    "Reading the paper",
    "Extracting claims and references",
    "Finding the cited sources",
    "Checking each claim",
]


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, (LLMUnavailable, ExtractionError, ValueError)):
        return text
    lowered = text.lower()
    if "401" in lowered or "api key" in lowered or "api_key" in lowered:
        return (
            f"{text} Check LLM_API_KEY and LLM_BASE_URL. "
            "Open 'About, evaluation and diagnostics' on the start screen to see what "
            "this app actually loaded."
        )
    return f"Something went wrong: {text}"


def render_steps(slot, current: int, detail: str = "") -> None:
    items = []
    for index, label in enumerate(READING_STEPS):
        if index < current:
            state, dot = "done", "✓"
        elif index == current:
            state, dot = "active", "●"
        else:
            state, dot = "", "○"
        extra = (
            f'<span class="detail">{html.escape(detail)}</span>'
            if index == current and detail
            else ""
        )
        items.append(
            f'<li class="{state}"><span class="dot">{dot}</span>'
            f"<span>{html.escape(label)}{extra}</span></li>"
        )
    slot.markdown(f'<ul class="cv-steps">{"".join(items)}</ul>', unsafe_allow_html=True)


def begin_analysis(pending: dict) -> None:
    st.session_state.pending = pending
    st.session_state.stage = "reading"
    st.session_state.analysis_error = None
    st.session_state.home_error = None


def on_file_uploaded() -> None:
    uploaded = st.session_state.get(f"home_pdf_{st.session_state.uploader_nonce}")
    if uploaded is None:
        return
    begin_analysis(
        {
            "kind": "file",
            "name": uploaded.name,
            "data": uploaded.getvalue(),
            "max_claims": int(st.session_state.get("max_claims_opt", 8)),
        }
    )


def on_analyze_text() -> None:
    text = st.session_state.get("home_pasted", "")
    if not text.strip():
        st.session_state.home_error = "Paste some paper text first."
        return
    begin_analysis(
        {"kind": "text", "text": text, "max_claims": int(st.session_state.get("max_claims_opt", 8))}
    )


def on_open_demo() -> None:
    try:
        demo = load_demo_report(get_settings().demo_report_path)
    except Exception as exc:  # missing demo file
        st.session_state.home_error = str(exc)
        return
    st.session_state.report = demo
    st.session_state.report_mode = "demo"
    st.session_state.claim_index = 0
    st.session_state.verify_seconds = None
    st.session_state.home_error = None


def go_home() -> None:
    """Back to the start screen. Bumping the nonce empties the upload box."""
    st.session_state.report = None
    st.session_state.live_report = None
    st.session_state.report_mode = None
    st.session_state.claim_index = 0
    st.session_state.verify_seconds = None
    st.session_state.stage = "home"
    st.session_state.pending = None
    st.session_state.analysis_error = None
    st.session_state.home_error = None
    st.session_state.uploader_nonce += 1


def analyze_pending(pending: dict, settings: Settings, llm: LLMClient, slot) -> Report:
    max_claims = int(pending.get("max_claims", 8))

    render_steps(slot, 0)
    if pending["kind"] == "file":
        paper = extract_pdf(pending["data"], pending["name"])
    else:
        paper = extract_text(pending["text"], filename="pasted-text.txt")

    render_steps(slot, 1, f"“{paper.title}” · {len(paper.pages)} page(s)")
    title, claims, references = extract_claims_and_references(
        paper, llm, max_claims=max_claims
    )

    render_steps(slot, 2, f"{len(claims)} claims, {len(references)} references")
    references = resolve_all(references, settings)
    resolved = sum(1 for ref in references if ref.resolved)

    render_steps(slot, 3, f"Matched {resolved} of {len(references)} references")

    def progress(done: int, total: int, _claim) -> None:
        render_steps(slot, 3, f"Checked {done} of {total} claims")

    started = time.perf_counter()
    results = verify_claims(claims, references, llm, progress=progress)
    st.session_state.verify_seconds = time.perf_counter() - started
    render_steps(slot, len(READING_STEPS))
    return build_report(title, paper.filename, results, mode="live")


def render_reading(settings: Settings, llm: LLMClient) -> None:
    render_header("Reading & extracting claims", "This usually takes under a minute.", "Working on it")
    error = st.session_state.analysis_error
    if error:
        st.error(error)
        st.button("← Try another paper", key="retry_home", type="primary", on_click=go_home)
        return

    slot = st.empty()
    render_steps(slot, 0)
    st.button("Cancel", key="cancel_analysis", on_click=go_home)

    try:
        report = analyze_pending(st.session_state.pending, settings, llm, slot)
    except Exception as exc:
        st.session_state.analysis_error = friendly_error(exc)
        st.rerun()
        return

    st.session_state.report = report
    st.session_state.live_report = report
    st.session_state.report_mode = "live"
    st.session_state.claim_index = 0
    st.session_state.stage = "home"
    st.session_state.pending = None
    st.rerun()


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
                st.markdown(
                    f'<div class="source-flag source-flag-retracted">Source flag: '
                    f'{html.escape(flag_text)}. This citation needs scrutiny.</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="source-flag">Source flag: '
                    f'{html.escape(flag_text)}.</div>',
                    unsafe_allow_html=True,
                )

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


def render_export(report: Report) -> None:
    """Shown on the last claim: a PDF listing every claim with its suggested fix."""
    with st.container(border=True):
        st.markdown("#### That was the last claim")
        st.caption(
            "Get a PDF listing every claim with its suggested fix, plus corrected "
            "reference formatting."
        )
        pdf_bytes = None
        try:
            pdf_bytes = build_fixes_pdf(report)
        except PDFUnavailable as exc:
            st.warning(f"{exc} The Markdown report below still works.")
        except Exception as exc:  # never let export break the cards
            st.error(f"Could not build the PDF: {exc}")

        if pdf_bytes is not None:
            st.download_button(
                "Create PDF with suggested fixes",
                data=pdf_bytes,
                file_name="citeverify_suggested_fixes.pdf",
                mime="application/pdf",
                type="primary",
                key="download_pdf",
                use_container_width=True,
            )
        md_col, json_col = st.columns(2)
        with md_col:
            st.download_button(
                "Download Markdown",
                data=report_to_markdown(report),
                file_name="citeverify_report.md",
                mime="text/markdown",
                key="download_md",
                use_container_width=True,
            )
        with json_col:
            st.download_button(
                "Download JSON",
                data=report_to_json(report),
                file_name="citeverify_report.json",
                mime="application/json",
                key="download_json",
                use_container_width=True,
            )


def render_report(report: Report, settings: Settings, llm: LLMClient) -> None:
    if report.mode == "demo":
        st.caption("Demo report · The citing paper is illustrative; the cited papers and abstracts are real.")
    st.markdown(f'<div class="cv-hero"><div class="cv-kicker">Research review</div><div class="cv-title">{html.escape(report.paper_title)}</div><div class="cv-sub">Review one cited claim at a time.</div></div>', unsafe_allow_html=True)
    shown = report.results
    if not shown:
        st.info("No claims were extracted from this paper.")
        st.button("Try a new PDF", key="new_pdf_empty", type="primary", on_click=go_home)
        return

    chips = "".join(
        f'<span class="verdict-badge verdict-{VERDICT_CLASS[verdict]}">'
        f"{report.summary.get(verdict.value, 0)} {html.escape(VERDICT_LABELS[verdict])}</span>"
        for verdict in Verdict
        if report.summary.get(verdict.value, 0) > 0
    )
    st.markdown(f'<div class="cv-chips">{chips}</div>', unsafe_allow_html=True)
    seconds = st.session_state.get("verify_seconds")
    if seconds is not None:
        st.caption(f"Verification finished in {seconds:.1f} seconds.")

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

    st.button(
        "Try a new PDF",
        key=f"new_pdf_{current_index}",
        on_click=go_home,
        help="Start over with another paper",
    )

    if current_index == len(shown) - 1:
        render_export(report)


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
    render_header(
        "Drop a paper. See which claims its sources support.",
        "Drop a PDF anywhere in the box below, or paste the text.",
    )
    if st.session_state.home_error:
        st.error(st.session_state.home_error)
    if not settings.llm_configured:
        st.warning(
            "No LLM_API_KEY is configured, so new papers can't be analyzed yet. "
            "You can still explore the demo report."
        )

    st.file_uploader(
        "Drop your PDF here",
        type=["pdf"],
        key=f"home_pdf_{st.session_state.uploader_nonce}",
        on_change=on_file_uploaded,
        help="Choose a PDF or drag it into this upload area. Analysis starts right away.",
    )
    st.markdown('<div class="cv-or">or paste text</div>', unsafe_allow_html=True)
    st.text_area(
        "Paste paper text",
        height=110,
        placeholder="Paste the paper text, including its reference list.",
        label_visibility="collapsed",
        key="home_pasted",
    )
    col1, col2 = st.columns([1, 3], vertical_alignment="center")
    with col1:
        st.select_slider(
            "Claims to review", options=[4, 6, 8, 10], value=8, key="max_claims_opt"
        )
    with col2:
        st.button(
            "Research claims",
            type="primary",
            use_container_width=True,
            on_click=on_analyze_text,
            key="analyze_text",
        )
    st.button("Try the demo report (no key needed)", key="open_demo", on_click=on_open_demo)
    st.caption("CiteVerify checks claims against resolved source evidence. It is designed to support human review, not replace it.")

    with st.expander("About, evaluation and diagnostics"):
        render_about(settings)


EXTRA_CSS = """
<style>
.cv-or {text-align:center;color:var(--cv-muted)!important;font-size:.8rem;text-transform:uppercase;letter-spacing:.12em;margin:.9rem 0 .4rem;}
.cv-chips {display:flex;flex-wrap:wrap;gap:.4rem;margin:.1rem 0 .8rem;}
.cv-steps {list-style:none;padding:0;margin:.6rem 0 .8rem;}
.cv-steps li {display:flex;gap:.75rem;align-items:baseline;padding:.6rem 0;color:var(--cv-muted);border-bottom:1px solid var(--cv-border);}
.cv-steps li .dot {width:1.3rem;text-align:center;font-weight:700;}
.cv-steps li.done {color:var(--cv-text);}
.cv-steps li.done .dot {color:var(--cv-accent);}
.cv-steps li.active {color:var(--cv-text);font-weight:600;}
.cv-steps li.active .dot {color:var(--cv-accent);animation:cvpulse 1s ease-in-out infinite;}
.cv-steps .detail {color:var(--cv-muted);font-weight:400;font-size:.85rem;display:block;}
@keyframes cvpulse {0%,100%{opacity:.25;}50%{opacity:1;}}
[data-testid="stFileUploaderDropzone"] {padding:2.2rem 1.5rem!important;}
.stButton>button:disabled {background:var(--cv-panel-alt)!important;cursor:not-allowed;}
</style>
"""


def main() -> None:
    st.set_page_config(
        page_title="CiteVerify — evidence, not verdicts",
        page_icon="✓",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    init_state()
    inject_css(dark=st.session_state.get("dark_mode", False))
    st.markdown(EXTRA_CSS, unsafe_allow_html=True)
    settings = get_settings()
    llm = LLMClient(settings)
    render_topbar()
    report = st.session_state.get("report")
    if report is None and st.session_state.stage == "reading" and st.session_state.pending is not None:
        render_reading(settings, llm)
    elif report is None:
        st.session_state.stage = "home"
        render_empty_state(settings, llm)
    else:
        render_report(report, settings, llm)


if __name__ == "__main__":
    main()
