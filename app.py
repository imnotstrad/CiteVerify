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
from citeverify.llm import LLMClient, LLMUnavailable, error_detail
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
    ("partially_supported", "Partially supported", "partially_supported"),
    ("unsupported", "Unsupported", "unsupported"),
    ("contradicted", "Contradicted", "contradicted"),
    ("unverifiable", "Unverifiable", "unverifiable"),
]

DEMO_RETRACTED_DOI = "10.1016/S0140-6736(97)11096-0"


def inject_css(dark: bool = False) -> None:
    palette = {
        "bg": "#0A0F13" if dark else "#F5F1E8",
        "panel": "#121A20" if dark else "#FFFCF5",
        "panel_alt": "#1A242B" if dark else "#ECE6DA",
        "text": "#EEF3F4" if dark else "#172126",
        "muted": "#A6B4BB" if dark else "#5C6870",
        "border": "#2D3A42" if dark else "#DED5C7",
        "accent": "#63E0CB" if dark else "#0E6F66",
        "accent_contrast": "#071A18" if dark else "#FFFFFF",
        "soft": "#102D2A" if dark else "#E9F6F2",
        "soft_text": "#C8F5ED" if dark else "#0F4F49",
        "input": "#0E161B" if dark else "#FFFFFF",
        "success_bg": "#12382A" if dark else "#DCFCE7",
        "success_text": "#B7F0C8" if dark else "#166534",
        "warning_bg": "#42340F" if dark else "#FEF3C7",
        "warning_text": "#F8D98A" if dark else "#92400E",
        "unsupported_bg": "#44290F" if dark else "#FFEDD5",
        "unsupported_text": "#FFD6A8" if dark else "#9A3412",
        "error_bg": "#43202A" if dark else "#FEE2E2",
        "error_text": "#FFC1C1" if dark else "#991B1B",
        "info_bg": "#12303F" if dark else "#DBEAFE",
        "info_text": "#B9E4F4" if dark else "#1E40AF",
        "neutral_bg": "#2E3A43" if dark else "#E5E7EB",
        "neutral_text": "#E2E8EC" if dark else "#374151",
        "border_strong": "#43535D" if dark else "#C9BCA8",
        "shadow": "0 18px 50px rgba(0,0,0,.45)" if dark else "0 14px 40px rgba(36,28,15,.08)",
        "mark_bg": "#6A5410" if dark else "#FFF3A3",
        "best_bg": "#8A6D0B" if dark else "#FFE082",
        "mark_text": "#FFF6D6" if dark else "#172026",
    }
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Inter:wght@400;500;600;700&display=swap');
    :root {{
      color-scheme: {"dark" if dark else "light"};
      --cv-bg:{palette["bg"]}; --cv-panel:{palette["panel"]};
      --cv-panel-alt:{palette["panel_alt"]}; --cv-text:{palette["text"]};
      --cv-muted:{palette["muted"]}; --cv-border:{palette["border"]};
      --cv-accent:{palette["accent"]}; --cv-accent-contrast:{palette["accent_contrast"]};
      --cv-soft:{palette["soft"]};
      --cv-soft-text:{palette["soft_text"]}; --cv-input:{palette["input"]};
      --cv-serif:'Source Serif 4',Georgia,serif;
      --cv-sans:Inter,system-ui,sans-serif;
      --cv-success-bg:{palette["success_bg"]}; --cv-success-text:{palette["success_text"]};
      --cv-warning-bg:{palette["warning_bg"]}; --cv-warning-text:{palette["warning_text"]};
      --cv-unsupported-bg:{palette["unsupported_bg"]}; --cv-unsupported-text:{palette["unsupported_text"]};
      --cv-error-bg:{palette["error_bg"]}; --cv-error-text:{palette["error_text"]};
      --cv-info-bg:{palette["info_bg"]}; --cv-info-text:{palette["info_text"]};
      --cv-neutral-bg:{palette["neutral_bg"]}; --cv-neutral-text:{palette["neutral_text"]};
      --cv-border-strong:{palette["border_strong"]}; --cv-shadow:{palette["shadow"]};
      --cv-mark-bg:{palette["mark_bg"]}; --cv-best-bg:{palette["best_bg"]}; --cv-mark-text:{palette["mark_text"]};
    }}

    /* Page and ordinary text */
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{
      background:var(--cv-bg)!important;
      color:var(--cv-text)!important;
      font-family:Inter,system-ui,sans-serif;
    }}
    .block-container {{max-width:1120px;padding-top:1.1rem;padding-bottom:3.5rem;}}
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
    .hl-passage,.st-key-cv_claim_card,.st-key-cv_export_card,.st-key-cv_reading_card {{background:var(--cv-panel)!important;border:1px solid var(--cv-border)!important;border-radius:16px;}}
    .hl-passage mark {{background:#FFF3A3;color:#172026!important;padding:0 2px;border-radius:3px;}}
    .hl-passage .best {{background:#FFE082;color:#172026!important;padding:2px 3px;border-radius:4px;}}

    /* Buttons: normal, primary, popover trigger and file-picker button */
    [data-testid="stButton"] button,[data-testid="stDownloadButton"] button,
    [data-testid="stPopover"] > button,
    [data-testid="stFileUploader"] button {{
      border-radius:10px!important;
      border:1px solid var(--cv-border)!important;
      min-height:2.75rem;
      background:var(--cv-panel)!important;
      color:var(--cv-text)!important;
    }}
    [data-testid="stButton"] button[kind="primary"],
    [data-testid="stDownloadButton"] button[kind="primary"] {{
      background:var(--cv-accent)!important;
      color:var(--cv-accent-contrast)!important;
      border-color:var(--cv-accent)!important;
    }}
    [data-testid="stButton"] button[kind="primary"] *,
    [data-testid="stDownloadButton"] button[kind="primary"] * {{
      color:var(--cv-accent-contrast)!important;
    }}
    [data-testid="stButton"] button:disabled {{color:var(--cv-muted)!important;opacity:.55;}}
    [data-testid="stPopover"] > button:hover,
    [data-testid="stFileUploader"] button:hover,
    [data-testid="stButton"] button:hover {{border-color:var(--cv-accent)!important;}}

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
    with st.container(key="cv_topbar"):
        left, right = st.columns([5, 1.2], vertical_alignment="center")
        with left:
            st.markdown(
                """
                <div class="cv-brand-lockup">
                  <span class="cv-mark" aria-hidden="true">
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2.1"
                         stroke-linecap="round" stroke-linejoin="round">
                      <path d="M5 4h9l5 5v11H5z"></path>
                      <path d="M14 4v5h5"></path>
                      <path d="M8.6 14.2l2.2 2.2 4.4-4.4"></path>
                    </svg>
                  </span>
                  <span>
                    <span class="cv-brand">CiteVerify</span>
                    <span class="cv-brand-sub">Evidence, not verdicts</span>
                  </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            st.toggle(
                "Dark mode",
                key="dark_mode",
                help="Switch between dark and light appearance.",
            )



READING_STEPS = [
    "Reading the paper",
    "Extracting claims and references",
    "Finding the cited sources",
    "Checking each claim",
]


def friendly_error(exc: Exception, settings: Settings | None = None) -> str:
    text = error_detail(exc)
    if isinstance(exc, (LLMUnavailable, ExtractionError, ValueError)):
        return text
    lowered = text.lower()
    if "404" in lowered or "not_found" in lowered or "no longer available" in lowered:
        model = settings.llm_model if settings else "the configured model"
        return (
            f"The model '{model}' is not available on the configured endpoint. "
            "Set LLM_MODEL to a supported model (gemini-3.5-flash-lite works with "
            "the Gemini endpoint) and redeploy. "
            f"Provider said: {text}"
        )
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
    render_header("Reading the paper", "This usually takes under a minute.", "Working on it")
    error = st.session_state.analysis_error
    if error:
        st.error(error)
        st.button("← Try another paper", key="retry_home", type="primary", on_click=go_home)
        return

    with st.container(border=True, key="cv_reading_card"):
        slot = st.empty()
        render_steps(slot, 0)
    st.button("Cancel", key="cancel_analysis", on_click=go_home)

    try:
        report = analyze_pending(st.session_state.pending, settings, llm, slot)
    except Exception as exc:
        st.session_state.analysis_error = friendly_error(exc, settings)
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
    """A compact, readable verdict distribution. No metric wall."""
    counts = report.summary
    total = counts.get("total") or len(report.results)
    if not total:
        return

    segments: list[str] = []
    legend: list[str] = []
    spoken: list[str] = []
    for key, label, css_class in SUMMARY_SPECS:
        if key == "total":
            continue
        count = counts.get(key, 0)
        if not count:
            continue
        width = 100 * count / total
        segments.append(
            f'<span class="cv-seg-{css_class}" style="width:{width:.2f}%"></span>'
        )
        legend.append(
            f'<span class="cv-legend-item"><span class="cv-dot cv-dot-{css_class}"></span>'
            f"{count} {html.escape(label.lower())}</span>"
        )
        spoken.append(f"{count} {label.lower()}")

    st.markdown(
        f"""
        <div class="cv-summary">
          <div class="cv-summary-top">
            <span class="cv-summary-label">Verdict distribution</span>
            <span class="cv-summary-total">{total} claims</span>
          </div>
          <div class="cv-summary-bar" role="img"
               aria-label="{html.escape(', '.join(spoken))}">
            {''.join(segments)}
          </div>
          <div class="cv-summary-legend">{''.join(legend)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if counts.get("flagged"):
        st.caption(f"{counts['flagged']} claims carry a source or evidence flag.")


def render_highlighted_evidence(result: ClaimResult) -> None:
    """Show where the claim's key terms appear in the source abstract. No LLM involved."""
    abstract = (result.reference.abstract if result.reference else None) or ""
    if not abstract.strip():
        return
    matches = find_evidence(result.claim.text, abstract, top_k=1)
    with st.expander("Highlighted evidence in the abstract"):
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
        width="stretch",
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
    with st.container(border=True, key="cv_claim_card"):
        source_title = result.source_title or "Unknown source"
        source_year = f" ({result.source_year})" if result.source_year else ""
        section = result.claim.section or "Section not mapped"
        marker = result.claim.citation_marker or "Citation not mapped"

        st.markdown(
            f"""
            <div class="cv-claim-head">
              <div>
                <div class="cv-claim-meta">Claim {index:02d} of {total:02d}</div>
                <div class="cv-claim-context">{html.escape(section)} · {html.escape(marker)}</div>
              </div>
              <div class="cv-claim-verdict">
                {verdict_badge(result)}
                <div class="cv-confidence">Confidence: {html.escape(confidence_label(result))}</div>
              </div>
            </div>
            <div class="cv-claim-title">{html.escape(result.claim.text)}</div>
            <div class="cv-source">
              <span class="cv-source-label">Cited source</span>
              <span class="cv-source-title">{html.escape(source_title)}{html.escape(source_year)}</span>
            </div>
            """,
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

        st.markdown('<div class="cv-section-label">Evidence from the source</div>', unsafe_allow_html=True)
        if result.evidence_quote:
            st.markdown(
                f'<blockquote class="cv-quote">“{html.escape(result.evidence_quote)}”</blockquote>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="cv-empty-quote">No verbatim quote was found. '
                "This claim is marked unverifiable.</div>",
                unsafe_allow_html=True,
            )

        if result.reason:
            st.markdown('<div class="cv-section-label">Why this verdict</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="cv-reason">{html.escape(result.reason)}</div>', unsafe_allow_html=True)
        if result.suggested_fix:
            fix = html.escape(result.suggested_fix).replace("\n", "<br>")
            st.markdown(
                f'<div class="cv-fix"><div class="cv-fix-label">Suggested fix</div>'
                f'<div class="cv-fix-text">{fix}</div></div>',
                unsafe_allow_html=True,
            )

        render_highlighted_evidence(result)

        action_left, action_middle, action_right = st.columns(
            [3, 1.6, 1.2], vertical_alignment="center"
        )
        with action_left:
            if result.source_url:
                st.markdown(
                    f'<div class="cv-action-link"><a href="{html.escape(result.source_url, quote=True)}" '
                    'target="_blank" rel="noopener">Open cited source ↗</a></div>',
                    unsafe_allow_html=True,
                )
            elif result.reference and result.reference.doi:
                st.markdown(
                    f'<div class="cv-action-link"><a href="https://doi.org/'
                    f'{html.escape(result.reference.doi, quote=True)}" target="_blank" '
                    'rel="noopener">Open cited source ↗</a></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No source link available.")
        with action_middle:
            st.button(
                "Try a new PDF",
                key=f"new_pdf_{result.claim.id}",
                on_click=go_home,
                help="Start over with a different paper.",
                width="stretch",
            )
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
    with st.container(border=True, key="cv_export_card"):
        copy_col, download_col = st.columns([3, 2], vertical_alignment="center")
        with copy_col:
            st.markdown('<div class="cv-kicker">Review complete</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="cv-export-title">Take the fixes with you.</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "A PDF listing every claim, its suggested fix, and corrected "
                "reference formatting."
            )
        with download_col:
            pdf_bytes = None
            try:
                pdf_bytes = build_fixes_pdf(report)
            except PDFUnavailable as exc:
                st.warning(f"{exc} The Markdown report still works.")
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
                    width="stretch",
                )

        with st.expander("Download other formats"):
            md_col, json_col = st.columns(2)
            with md_col:
                st.download_button(
                    "Download Markdown",
                    data=report_to_markdown(report),
                    file_name="citeverify_report.md",
                    mime="text/markdown",
                    key="download_md",
                    width="stretch",
                )
            with json_col:
                st.download_button(
                    "Download JSON",
                    data=report_to_json(report),
                    file_name="citeverify_report.json",
                    mime="application/json",
                    key="download_json",
                    width="stretch",
                )


def render_report(report: Report, settings: Settings, llm: LLMClient) -> None:
    shown = report.results
    demo = report.mode == "demo"
    meta = (
        '<span class="cv-demo-badge">Demo</span>'
        "The citing paper is illustrative; the cited papers and abstracts are real."
        if demo
        else f"Live analysis of {len(shown)} cited claims"
    )
    st.markdown(
        f"""
        <div class="cv-report-head">
          <div class="cv-kicker">Research review</div>
          <div class="cv-report-title">{html.escape(report.paper_title)}</div>
          <div class="cv-report-meta">{meta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not shown:
        st.info("No claims were extracted from this paper.")
        st.button("Try a new PDF", key="new_pdf_empty", type="primary", on_click=go_home)
        return

    render_summary(report)
    seconds = st.session_state.get("verify_seconds")
    if seconds is not None:
        st.caption(f"Verification finished in {seconds:.1f} seconds.")

    current_index = min(max(0, int(st.session_state.get("claim_index", 0))), len(shown)-1)
    render_claim(shown[current_index], current_index+1, len(shown), settings, llm)

    # Card controls stay directly beneath the flashcard.
    left, middle, right = st.columns([1.25, 3.5, 1.25], vertical_alignment="center")
    with left:
        previous_clicked = st.button(
            "← Previous",
            key="previous_claim",
            help="First claim — there is no previous claim" if current_index == 0 else "Previous claim",
            disabled=current_index == 0,
            width="stretch",
        )
    with middle:
        st.markdown(
            f'<div class="cv-counter">Claim {current_index+1} of {len(shown)}</div>',
            unsafe_allow_html=True,
        )
    with right:
        next_clicked = st.button(
            "Next →",
            key="next_claim",
            help="Last claim — there is no next claim" if current_index == len(shown) - 1 else "Next claim",
            disabled=current_index == len(shown) - 1,
            width="stretch",
        )
    if previous_clicked:
        st.session_state.claim_index = max(0, current_index-1)
        st.rerun()
    if next_clicked:
        st.session_state.claim_index = min(len(shown)-1, current_index+1)
        st.rerun()
    st.progress((current_index+1)/len(shown))

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
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption("Small sample. Do not present this as a general accuracy claim.")


def render_about(settings: Settings) -> None:
    st.markdown("### About CiteVerify")
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
            "Python, Streamlit, PyMuPDF, Hugging Face sentence-transformers, "
            "Crossref, OpenAlex, Pydantic, and Gemini source-grounded verification."
        )
    st.divider()
    render_deployment_diagnostics(settings)


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
    if st.session_state.home_error:
        st.error(st.session_state.home_error)

    hero_col, upload_col = st.columns([1.1, 0.9], gap="large", vertical_alignment="center")
    with hero_col:
        st.markdown(
            """
            <div class="cv-hero">
              <div class="cv-kicker">Evidence-first citation review</div>
              <div class="cv-display">Does the source actually say that?</div>
              <div class="cv-lede">
                CiteVerify reads the cited claims in a paper, finds the sources,
                and shows you the evidence behind every verdict.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.button(
            "Try the demo report",
            key="open_demo",
            on_click=on_open_demo,
            type="primary",
            icon=":material/play_arrow:",
        )
        st.markdown(
            '<div class="cv-demo-note">No key needed. Ten claims, about 30 seconds.</div>',
            unsafe_allow_html=True,
        )

    with upload_col:
        with st.container(border=True, key="cv_upload_card"):
            st.markdown(
                """
                <div class="cv-card-kicker">Start a review</div>
                <div class="cv-card-title">Check a paper</div>
                <div class="cv-card-copy">Upload a PDF or paste text. We extract the cited claims and check each one against its source.</div>
                """,
                unsafe_allow_html=True,
            )
            pdf_tab, text_tab = st.tabs(["Upload a PDF", "Paste text"])
            with pdf_tab:
                st.file_uploader(
                    "Upload a PDF",
                    type=["pdf"],
                    key=f"home_pdf_{st.session_state.uploader_nonce}",
                    on_change=on_file_uploaded,
                    help="Choose a PDF or drag it into this area. Analysis starts right away.",
                    label_visibility="collapsed",
                )
                st.caption("PDF only, up to 200 MB. Analysis starts when you choose a file.")
                if not settings.llm_configured:
                    st.caption("Live uploads need an API key. The demo works without one.")
            with text_tab:
                st.text_area(
                    "Paste paper text",
                    height=110,
                    placeholder="Paste the paper text, including its reference list.",
                    label_visibility="collapsed",
                    key="home_pasted",
                )
                control_col, action_col = st.columns([1, 1.35], vertical_alignment="bottom")
                with control_col:
                    st.select_slider(
                        "Claims to review",
                        options=[4, 6, 8, 10],
                        value=8,
                        key="max_claims_opt",
                    )
                with action_col:
                    st.button(
                        "Research claims",
                        type="primary",
                        width="stretch",
                        on_click=on_analyze_text,
                        key="analyze_text",
                    )
                if not settings.llm_configured:
                    st.caption("Live analysis needs an API key. The demo works without one.")

    st.markdown(
        '<div class="cv-section-head" id="how-it-works">How a review works</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="cv-section-copy">One paper in, one claim at a time out. '
        "Every verdict is anchored to a verbatim quote.</div>",
        unsafe_allow_html=True,
    )
    step_one, step_two, step_three = st.columns(3, gap="large")
    steps = [
        (
            step_one,
            "01",
            "Upload a paper",
            "PDF or pasted text. We extract the claims that carry citations.",
        ),
        (
            step_two,
            "02",
            "We find the sources",
            "DOIs and titles are resolved through Crossref and OpenAlex.",
        ),
        (
            step_three,
            "03",
            "You see the evidence",
            "Each claim gets a verdict, a quote, and a link to the source.",
        ),
    ]
    for column, number, title, copy in steps:
        with column:
            st.markdown(
                f'<div class="cv-step"><div class="cv-step-index">{number}</div>'
                f'<div class="cv-step-title">{html.escape(title)}</div>'
                f'<div class="cv-step-copy">{html.escape(copy)}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        '<div class="cv-principle"><strong>No quote, no verdict.</strong> '
        "If the source text does not support a responsible check, the claim is "
        "marked unverifiable.</div>",
        unsafe_allow_html=True,
    )

    with st.expander("About CiteVerify, evaluation and diagnostics"):
        render_about(settings)
    st.markdown(
        '<div class="cv-footer">Built for INNOVEDGE Hackathon 2026. '
        "CiteVerify is evidence for human review, not a final verdict on a paper.</div>",
        unsafe_allow_html=True,
    )


EXTRA_CSS = """
<style>
/* ---------- Page shell ---------- */
.block-container {padding-top:1.1rem!important;}
[data-testid="stAppViewContainer"] > .main {background:var(--cv-bg);}
[data-testid="stHeader"] {background:transparent!important;}
[data-testid="stToolbar"] {right:1rem;}
body, [data-testid="stMarkdownContainer"] p {line-height:1.6;}

/* ---------- Top bar ---------- */
.st-key-cv_topbar {border-bottom:1px solid var(--cv-border);padding-bottom:.85rem;margin-bottom:1.8rem;}
.st-key-cv_topbar [data-testid="stColumn"]:last-child {display:flex;justify-content:flex-end;align-items:center;}
.cv-brand-lockup {display:flex;align-items:center;gap:.7rem;}
.cv-mark {display:grid;place-items:center;width:2.15rem;height:2.15rem;border-radius:10px;background:var(--cv-accent);color:var(--cv-accent-contrast);flex:0 0 auto;box-shadow:0 4px 12px rgba(0,0,0,.08);}
.cv-brand {display:block;font-family:var(--cv-serif);font-size:1.5rem;font-weight:700;letter-spacing:-.025em;line-height:1;color:var(--cv-text);}
.cv-brand-sub {display:block;font-size:.72rem;line-height:1.2;color:var(--cv-muted);margin-top:.2rem;}
.st-key-cv_topbar [data-testid="stCheckbox"] label p {font-size:.8rem!important;color:var(--cv-muted)!important;}
.st-key-cv_topbar [data-testid="stCheckbox"] {margin:0!important;}
.st-key-cv_topbar [data-testid="stCheckbox"] label > div:first-of-type {background:var(--cv-border-strong)!important;}
.st-key-cv_topbar [data-testid="stCheckbox"] label > div:first-of-type > div {background:var(--cv-panel)!important;}
.st-key-cv_topbar [data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type {background:var(--cv-accent)!important;}
.st-key-cv_topbar [data-testid="stCheckbox"] label:has(input:checked) > div:first-of-type > div {background:var(--cv-accent-contrast)!important;}

/* ---------- Hero ---------- */
.cv-hero {border:0!important;padding:0!important;margin:0!important;}
.cv-kicker {color:var(--cv-accent)!important;font-size:.76rem;font-weight:700;letter-spacing:.035em;text-transform:none;}
.cv-display {font-family:var(--cv-serif);font-size:clamp(2.5rem,4.8vw,4.1rem);font-weight:600;line-height:1.02;letter-spacing:-.035em;color:var(--cv-text);margin:.5rem 0 1rem;max-width:12ch;}
.cv-lede {font-size:1.05rem;line-height:1.7;color:var(--cv-muted)!important;max-width:52ch;margin:0 0 1.15rem;}
.cv-demo-note {color:var(--cv-muted)!important;font-size:.78rem;margin-top:.35rem;}
.cv-hero .stButton button {min-height:3rem!important;padding:0 1.25rem!important;font-size:.95rem!important;}
.cv-hero .stButton {margin-top:.1rem;}

/* ---------- Upload card ---------- */
.st-key-cv_upload_card {background:var(--cv-panel)!important;border:1px solid var(--cv-border)!important;border-radius:20px!important;box-shadow:var(--cv-shadow);padding:1.15rem 1.15rem .85rem!important;}
.cv-card-kicker {font-size:.72rem;font-weight:600;letter-spacing:.01em;color:var(--cv-accent);}
.cv-card-title {font-family:var(--cv-serif);font-size:1.65rem;font-weight:600;line-height:1.15;color:var(--cv-text);margin:.25rem 0 .3rem;}
.cv-card-copy {font-size:.88rem;line-height:1.55;color:var(--cv-muted);margin:0 0 .65rem;}
.st-key-cv_upload_card [data-testid="stFileUploaderDropzone"] {padding:1.7rem 1.1rem!important;border-radius:13px!important;background:var(--cv-panel-alt)!important;transition:border-color .15s,background .15s;}
.st-key-cv_upload_card [data-testid="stFileUploaderDropzone"]:hover {border-color:var(--cv-accent)!important;border-style:solid!important;background:var(--cv-soft)!important;}
.st-key-cv_upload_card [data-testid="stFileUploaderDropzone"] p,
.st-key-cv_upload_card [data-testid="stFileUploaderDropzone"] span {font-size:.9rem!important;}
.st-key-cv_upload_card [data-testid="stFileUploader"] {margin-bottom:.1rem;}
.st-key-cv_upload_card [data-testid="stCaptionContainer"] {margin-top:.35rem;}
.st-key-cv_upload_card [data-testid="stTabs"] {margin-top:.25rem;}

/* ---------- Tabs as a segmented control ---------- */
[data-testid="stTabs"] > div[data-orientation="horizontal"] {gap:.2rem;background:var(--cv-panel-alt);padding:.22rem;border-radius:10px;border:1px solid var(--cv-border);}
[data-testid="stTab"] {border-radius:8px!important;padding:.48rem .8rem!important;font-size:.85rem!important;font-weight:600!important;color:var(--cv-muted)!important;background:transparent!important;outline:none!important;}
[data-testid="stTab"][aria-selected="true"] {background:var(--cv-panel)!important;color:var(--cv-text)!important;box-shadow:0 1px 3px rgba(0,0,0,.08);}
[data-testid="stTab"] p {font-size:.85rem!important;font-weight:600!important;}
[data-testid="stTab"][aria-selected="true"] p {color:var(--cv-text)!important;}
[data-testid="stTab"] .react-aria-SelectionIndicator {display:none!important;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {display:none!important;}

/* ---------- How it works ---------- */
.cv-section-head {font-family:var(--cv-serif);font-size:1.7rem;font-weight:600;line-height:1.2;color:var(--cv-text);margin:2.3rem 0 .4rem;letter-spacing:-.015em;}
.cv-section-copy {font-size:.92rem;line-height:1.6;color:var(--cv-muted);max-width:62ch;margin:0 0 1.15rem;}
.cv-step {border-top:1px solid var(--cv-border);padding-top:.8rem;height:100%;}
.cv-step-index {font-size:.72rem;font-weight:700;letter-spacing:.08em;color:var(--cv-accent);}
.cv-step-title {font-size:1rem;font-weight:600;line-height:1.35;color:var(--cv-text);margin:.3rem 0 .2rem;}
.cv-step-copy {font-size:.87rem;line-height:1.55;color:var(--cv-muted);}
.cv-principle {margin:1.65rem 0 1.4rem;padding:.9rem 1.05rem;border-left:3px solid var(--cv-accent);border-radius:0 12px 12px 0;background:var(--cv-soft);color:var(--cv-soft-text)!important;font-size:.92rem;line-height:1.6;}
.cv-principle strong {color:var(--cv-soft-text)!important;}
.cv-footer {margin-top:1.8rem;color:var(--cv-muted)!important;font-size:.78rem;line-height:1.55;}

/* ---------- Report header and summary ---------- */
.cv-report-head {margin:0 0 1.15rem;}
.cv-report-title {font-family:var(--cv-serif);font-size:clamp(2.05rem,3.8vw,3rem);font-weight:600;line-height:1.08;letter-spacing:-.03em;color:var(--cv-text);margin:.35rem 0 .45rem;max-width:24ch;}
.cv-report-meta {font-size:.85rem;line-height:1.5;color:var(--cv-muted);}
.cv-demo-badge {display:inline-block;margin-right:.4rem;padding:.16rem .5rem;border-radius:999px;background:var(--cv-soft);color:var(--cv-soft-text);font-size:.68rem;font-weight:700;vertical-align:.05em;}
.cv-summary {margin:.35rem 0 1.45rem;}
.cv-summary-top {display:flex;justify-content:space-between;align-items:baseline;gap:1rem;margin-bottom:.45rem;}
.cv-summary-label {font-size:.74rem;font-weight:600;letter-spacing:.01em;color:var(--cv-muted);}
.cv-summary-total {font-size:.8rem;color:var(--cv-muted);}
.cv-summary-bar {display:flex;gap:2px;height:9px;border-radius:999px;overflow:hidden;background:var(--cv-panel-alt);}
.cv-summary-bar span {display:block;height:100%;min-width:3px;}
.cv-seg-supported {background:var(--cv-success-text);}
.cv-seg-partially_supported {background:var(--cv-warning-text);}
.cv-seg-unsupported {background:var(--cv-unsupported-text);}
.cv-seg-contradicted {background:var(--cv-error-text);}
.cv-seg-unverifiable {background:var(--cv-neutral-text);}
.cv-summary-legend {display:flex;flex-wrap:wrap;gap:.35rem 1rem;margin-top:.55rem;font-size:.78rem;color:var(--cv-muted);}
.cv-legend-item {display:inline-flex;align-items:center;gap:.35rem;white-space:nowrap;}
.cv-dot {display:inline-block;width:.5rem;height:.5rem;border-radius:999px;flex:0 0 auto;}
.cv-dot-supported {background:var(--cv-success-text);}
.cv-dot-partially_supported {background:var(--cv-warning-text);}
.cv-dot-unsupported {background:var(--cv-unsupported-text);}
.cv-dot-contradicted {background:var(--cv-error-text);}
.cv-dot-unverifiable {background:var(--cv-neutral-text);}

/* ---------- Claim card ---------- */
.st-key-cv_claim_card,.st-key-cv_export_card,.st-key-cv_reading_card {border:1px solid var(--cv-border)!important;border-radius:18px!important;box-shadow:var(--cv-shadow);background:var(--cv-panel)!important;padding:1.15rem 1.2rem!important;}
.st-key-cv_claim_card > div,.st-key-cv_export_card > div,.st-key-cv_reading_card > div {padding:0!important;}
.cv-claim-head {display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap;margin-bottom:.65rem;}
.cv-claim-meta {font-size:.74rem;font-weight:600;letter-spacing:.01em;color:var(--cv-muted);}
.cv-claim-context {font-size:.77rem;color:var(--cv-muted);margin-top:.2rem;}
.cv-claim-verdict {display:flex;flex-direction:column;align-items:flex-end;gap:.25rem;text-align:right;}
.cv-confidence {font-size:.74rem;color:var(--cv-muted);}
.cv-claim-title {font-family:var(--cv-serif);font-size:clamp(1.45rem,2.3vw,1.95rem);font-weight:600;line-height:1.3;letter-spacing:-.015em;color:var(--cv-text);margin:.55rem 0 .9rem;max-width:34ch;}
.cv-source {display:flex;flex-direction:column;gap:.15rem;padding:.65rem .8rem;margin:0 0 1rem;background:var(--cv-panel-alt);border-radius:10px;}
.cv-source-label {font-size:.7rem;font-weight:600;letter-spacing:.01em;color:var(--cv-muted);}
.cv-source-title {font-size:.9rem;line-height:1.45;color:var(--cv-text);}
.cv-section-label {font-size:.74rem;font-weight:600;letter-spacing:.01em;color:var(--cv-muted);margin:1.15rem 0 .45rem;}
.cv-quote {margin:0;padding:1rem 1.1rem;border-left:3px solid var(--cv-accent);border-radius:0 12px 12px 0;background:var(--cv-soft);color:var(--cv-soft-text)!important;font-family:var(--cv-serif);font-size:1.06rem;line-height:1.65;}
.cv-empty-quote {padding:.85rem 1rem;border:1px dashed var(--cv-border);border-radius:10px;color:var(--cv-muted);font-size:.88rem;line-height:1.55;}
.cv-reason {margin:0;font-size:.94rem;line-height:1.65;color:var(--cv-text);}
.cv-fix {margin:1.1rem 0 .2rem;padding:.85rem 1rem;border:1px solid var(--cv-border);border-left:3px solid var(--cv-accent);border-radius:10px;background:var(--cv-panel-alt);}
.cv-fix-label {font-size:.72rem;font-weight:600;letter-spacing:.01em;color:var(--cv-accent);}
.cv-fix-text {margin-top:.25rem;font-size:.93rem;line-height:1.6;color:var(--cv-text);}

/* ---------- Actions and navigation ---------- */
.cv-action-link {font-size:.85rem;line-height:1.45;}
.cv-action-link a {font-weight:600;}
[data-testid="stButton"] button {font-weight:600!important;font-size:.88rem!important;border-radius:10px!important;}
[data-testid="stButton"] button[kind="primary"] {box-shadow:0 6px 16px rgba(0,0,0,.1);}
[data-testid="stButton"] button[kind="primary"]:hover:not(:disabled) {filter:brightness(1.06);background:var(--cv-accent)!important;}
[data-testid="stButton"] button:disabled {border-style:dashed!important;background:var(--cv-panel-alt)!important;cursor:not-allowed;}
.cv-counter {text-align:center;color:var(--cv-muted)!important;font-weight:600;font-size:.8rem;letter-spacing:.035em;padding:.55rem 0;}
[data-testid="stProgress"] > div {height:4px!important;border-radius:999px!important;background:var(--cv-border)!important;}
[data-testid="stProgress"] > div > div {background:var(--cv-accent)!important;border-radius:999px!important;}
.cv-export-title {font-family:var(--cv-serif);font-size:1.65rem;font-weight:600;line-height:1.2;letter-spacing:-.02em;color:var(--cv-text);margin:.25rem 0 .35rem;}

/* ---------- Reading state ---------- */
.cv-steps {list-style:none;padding:0;margin:.4rem 0 .5rem;}
.cv-steps li {display:flex;gap:.8rem;align-items:baseline;padding:.62rem 0;color:var(--cv-muted);border-bottom:1px solid var(--cv-border);font-size:.92rem;}
.cv-steps li:last-child {border-bottom:0;}
.cv-steps li .dot {width:1.35rem;text-align:center;font-weight:700;color:var(--cv-border-strong);}
.cv-steps li.done {color:var(--cv-text);}
.cv-steps li.done .dot {color:var(--cv-accent);}
.cv-steps li.active {color:var(--cv-text);font-weight:600;}
.cv-steps li.active .dot {color:var(--cv-accent);animation:cvpulse 1s ease-in-out infinite;}
.cv-steps .detail {color:var(--cv-muted);font-weight:400;font-size:.83rem;display:block;margin-top:.1rem;}
@keyframes cvpulse {0%,100%{opacity:.25;}50%{opacity:1;}}

/* ---------- Existing contrast fixes ---------- */
[data-testid="stExpander"] {background:var(--cv-panel)!important;border:1px solid var(--cv-border)!important;border-radius:12px!important;}
[data-testid="stExpander"] details[open] summary {border-bottom:1px solid var(--cv-border);}
[data-testid="stExpander"] details > summary {background:var(--cv-panel-alt)!important;border-radius:11px;}
[data-testid="stExpander"] details[open] > summary {border-radius:11px 11px 0 0;}
[data-testid="stExpander"] details > summary p,
[data-testid="stExpander"] details > summary span {color:var(--cv-text)!important;}
[data-testid="stAlert"] {background:var(--cv-panel-alt)!important;border:1px solid var(--cv-border)!important;border-radius:12px!important;}
[data-testid="stAlertContainer"],
[data-testid="stAlertContentInfo"],
[data-testid="stAlertContentSuccess"],
[data-testid="stAlertContentWarning"],
[data-testid="stAlertContentError"] {background:transparent!important;background-color:transparent!important;color:var(--cv-text)!important;}
[data-testid="stAlertContentInfo"] *,
[data-testid="stAlertContentSuccess"] *,
[data-testid="stAlertContentWarning"] *,
[data-testid="stAlertContentError"] * {color:var(--cv-text)!important;}
.hl-passage mark {background:var(--cv-mark-bg)!important;color:var(--cv-mark-text)!important;}
.hl-passage .best {background:var(--cv-best-bg)!important;color:var(--cv-mark-text)!important;}
.verdict-badge {font-size:.64rem;letter-spacing:.055em;padding:.28rem .58rem;box-shadow:inset 0 0 0 1px currentColor;}
.source-flag {display:block;padding:.7rem .9rem;margin:.75rem 0;border:1px solid var(--cv-border);border-radius:10px;background:var(--cv-warning-bg);color:var(--cv-warning-text)!important;font-weight:600;line-height:1.45;}
.source-flag * {color:inherit!important;}
.source-flag-retracted {background:var(--cv-error-bg);color:var(--cv-error-text)!important;border-color:var(--cv-error-text);}

/* ---------- Streamlit controls ---------- */
.st-key-cv_topbar [role="switch"][aria-checked="true"] {accent-color:var(--cv-accent);}
.st-key-cv_topbar [role="switch"][aria-checked="false"] {accent-color:var(--cv-border-strong);}
[data-testid="stSlider"] [role="slider"] {background:var(--cv-accent)!important;box-shadow:0 0 0 3px var(--cv-panel);}
[data-testid="stSlider"] [data-testid="stTickBarMin"],[data-testid="stSlider"] [data-testid="stTickBarMax"],
[data-testid="stSliderThumbValue"] {color:var(--cv-text)!important;}
[data-testid="stProgressBar"]>div>div {background:var(--cv-accent)!important;}
:focus-visible {outline:2px solid var(--cv-accent)!important;outline-offset:2px;}
::selection {background:var(--cv-accent);color:var(--cv-accent-contrast);}
::-webkit-scrollbar {width:10px;height:10px;}
::-webkit-scrollbar-thumb {background:var(--cv-border-strong);border-radius:8px;}
::-webkit-scrollbar-track {background:transparent;}

/* ---------- Responsive ---------- */
.st-key-cv_topbar [data-testid="stHorizontalBlock"] {flex-wrap:nowrap!important;align-items:center!important;}
.st-key-cv_topbar [data-testid="stColumn"] {min-width:0!important;width:auto!important;}
.st-key-cv_topbar [data-testid="stColumn"]:first-child {flex:1 1 auto!important;}
.st-key-cv_topbar [data-testid="stColumn"]:last-child {flex:0 0 auto!important;}
@media (max-width:700px) {
  .block-container {padding-top:.7rem!important;}
  .cv-display {font-size:2.45rem;max-width:14ch;}
  .cv-report-title {font-size:2.05rem;}
  .cv-claim-title {font-size:1.5rem;}
  .cv-claim-verdict {align-items:flex-start;text-align:left;}
  .st-key-cv_topbar [data-testid="stColumn"]:last-child {justify-content:flex-start;}
  .cv-summary-legend {gap:.3rem .7rem;}
}
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
