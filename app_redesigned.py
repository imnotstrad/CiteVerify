"""CiteVerify — redesigned UI entry point.

Run with: streamlit run app_redesigned.py
The original app.py is intentionally left unchanged.
"""
from __future__ import annotations

import html
import streamlit as st

import app as core
from citeverify.config import get_settings
from citeverify.llm import LLMClient
from citeverify.report import load_demo_report, report_to_json, report_to_markdown
from citeverify.resolve import check_doi, ResolutionError
from citeverify.models import Verdict
from citeverify.reliability import reliability_for_reference

st.set_page_config(
    page_title="CiteVerify | Research with confidence",
    page_icon="✓",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAV = ["Dashboard", "Analyze paper", "Research reports", "DOI verification", "Reliability analysis", "Settings"]

def styles():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Manrope:wght@500;600;700;800&display=swap');
    :root { --ink:#11183f; --muted:#68708e; --line:#e6e9f5; --paper:#ffffff; --canvas:#f6f7ff; --violet:#5546dc; --violet2:#786cf0; }
    html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
    .stApp { background:linear-gradient(135deg,#f7f8ff 0%,#f3f2ff 100%); color:var(--ink); }
    [data-testid="stAppViewContainer"] .main .block-container { max-width:1440px; padding-top:2rem; padding-bottom:3rem; }
    [data-testid="stSidebar"] { background:#11183f; border-right:0; }
    [data-testid="stSidebar"] * { color:#f7f7ff !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] label { background:transparent; border-radius:12px; padding:.55rem .7rem; }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background:#242c63; }
    .brand {font:800 1.55rem Manrope,sans-serif;letter-spacing:-.06em;color:#fff;padding:.5rem 0 0}
    .brand-sub {color:#aeb5e8;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;margin:0 0 1.5rem}
    .eyebrow {color:#6659e8;font-weight:800;font-size:.72rem;letter-spacing:.15em;text-transform:uppercase}
    .hero-title {font:800 clamp(2rem,4vw,3.2rem) Manrope,sans-serif;letter-spacing:-.055em;line-height:1.08;color:#11183f;margin:.3rem 0 .7rem}
    .hero-copy {font-size:1.02rem;color:#68708e;max-width:700px}
    .panel {background:#fff;border:1px solid #e7e9f5;border-radius:20px;padding:1.2rem 1.35rem;box-shadow:0 8px 28px rgba(36,39,92,.045)}
    .metric {background:#fff;border:1px solid #e7e9f5;border-radius:17px;padding:1rem 1.1rem;box-shadow:0 6px 20px rgba(36,39,92,.035);min-height:112px}
    .metric-label {color:#78809b;font-size:.76rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
    .metric-value {font:800 2rem Manrope,sans-serif;color:#11183f;margin-top:.25rem}
    .metric-note {font-size:.78rem;color:#8990a8}
    .section-title {font:800 1.2rem Manrope,sans-serif;color:#151c48;letter-spacing:-.025em}
    .stButton>button,.stDownloadButton>button {border-radius:12px;border:1px solid #e0e3f3;min-height:2.7rem;font-weight:700}
    .stButton>button[kind="primary"] {background:linear-gradient(100deg,#5144d8,#776af0);border:0;color:#fff}
    [data-testid="stFileUploader"] section {background:#f8f8ff;border:1.5px dashed #aaa4f6;border-radius:18px;padding:1.2rem}
    [data-testid="stVerticalBlockBorderWrapper"] {background:#fff;border:1px solid #e7e9f5;border-radius:18px}
    [data-baseweb="tab-list"] {gap:.5rem}
    [data-baseweb="tab"] {border-radius:10px 10px 0 0}
    .small-muted {color:#78809b;font-size:.82rem}
    </style>
    """, unsafe_allow_html=True)

def metric(label, value, note=""):
    st.markdown(f'<div class="metric"><div class="metric-label">{html.escape(label)}</div><div class="metric-value">{html.escape(str(value))}</div><div class="metric-note">{html.escape(note)}</div></div>', unsafe_allow_html=True)

def page_header(title, subtitle, kicker="CITEVERIFY WORKSPACE"):
    st.markdown(f'<div class="eyebrow">{kicker}</div><div class="hero-title">{html.escape(title)}</div><div class="hero-copy">{html.escape(subtitle)}</div>', unsafe_allow_html=True)
    st.write("")

def load_demo(settings):
    if st.session_state.get("report") is None or st.session_state.get("report_mode") != "demo":
        st.session_state.report = load_demo_report(settings.demo_report_path)
        st.session_state.report_mode = "demo"

def dashboard(report):
    page_header("Research with confidence.", "Verify whether the sources behind your research genuinely support the claims you make.")
    a,b = st.columns([1.45,1])
    with a:
        st.markdown('<div class="panel"><div class="eyebrow">Evidence-first research</div><div class="section-title" style="font-size:1.55rem;margin:.45rem 0">Every citation deserves a closer look.</div><p class="small-muted">CiteVerify traces cited claims to their sources, checks the evidence, and surfaces reliability signals so researchers can review with confidence.</p></div>', unsafe_allow_html=True)
        if st.button("＋  Analyze a research paper", type="primary", use_container_width=True):
            st.session_state.page = "Analyze paper"
            st.rerun()
    with b:
        st.markdown('<div class="panel"><div class="eyebrow">Your research companion</div><div class="section-title">From reference list to evidence trail</div><p class="small-muted">PDF ingestion · DOI resolution · claim verification · source reliability · citation fixes</p></div>', unsafe_allow_html=True)
    st.write("")
    if report:
        s=report.summary
        cols=st.columns(4)
        with cols[0]: metric("Claims checked",s.get("total",0),"Across the loaded report")
        with cols[1]: metric("Supported",s.get("supported",0),"Direct source support")
        with cols[2]: metric("Need attention",s.get("unsupported",0)+s.get("contradicted",0),"Unsupported or contradicted")
        with cols[3]: metric("Partially supported",s.get("partially_supported",0),"Review claim scope")
        st.write("")
        st.markdown('<div class="section-title">Latest research report</div>',unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(f"**{report.paper_title}**")
            st.caption(f"{len(report.results)} claims · {report.mode.title()} report")
            if st.button("Open report →",key="open_report"):
                st.session_state.page="Research reports"; st.rerun()
    else:
        st.info("Load the demo report or analyze a paper to see your research overview.")

def analyze_page(settings,llm):
    page_header("Analyze research paper", "Upload a PDF or paste research text to verify its citations.", "NEW ANALYSIS")
    with st.container(border=True):
        uploaded=st.file_uploader("Drop your research paper here or browse files",type=["pdf"],help="PDF files only")
        pasted=st.text_area("Or paste paper text",height=150,placeholder="Paste the paper text, including its reference section…")
        max_claims=st.slider("Maximum cited claims to analyze",3,10,8)
        if st.button("Analyze paper →",type="primary",disabled=(uploaded is None and not pasted.strip()),use_container_width=True):
            core.run_analysis(uploaded,pasted,max_claims,settings,llm)
            st.rerun()
    if not settings.llm_configured:
        st.warning("No LLM_API_KEY is configured. You can still explore the offline demo report.")

def reports_page(report,settings,llm):
    page_header("Research reports","Review claim-level evidence, verification outcomes, and suggested corrections.","REPORT LIBRARY")
    if report is None:
        st.info("No report loaded yet. Open Dashboard to load the demo, or analyze a paper.")
        return
    left,right=st.columns([3,1])
    with left: st.markdown(f"### {report.paper_title}")
    with right:
        st.download_button("Download JSON",report_to_json(report),"citeverify_report.json","application/json",use_container_width=True)
        st.download_button("Download Markdown",report_to_markdown(report),"citeverify_report.md","text/markdown",use_container_width=True)
    core.render_report(report,settings,llm)

def doi_page(settings):
    page_header("DOI verification","Check publication metadata and available retraction signals for a DOI.","SOURCE CHECK")
    doi=st.text_input("Digital Object Identifier",placeholder="10.xxxx/xxxxx",key="redesign_doi")
    if st.button("Verify DOI",type="primary",disabled=not doi.strip()):
        with st.spinner("Checking Crossref and OpenAlex…"):
            try: st.session_state.redesign_doi_result=check_doi(doi,settings)
            except Exception as exc: st.session_state.redesign_doi_result={"error":str(exc)}
    result=st.session_state.get("redesign_doi_result")
    if isinstance(result,dict) and result.get("error"): st.error(result["error"])
    elif result:
        with st.container(border=True):
            st.markdown(f"### {result.title or result.doi}")
            st.write(f"**DOI:** {result.doi}")
            st.write(f"**Year:** {result.year or 'Not available'}")
            st.write(f"**Retraction signal:** {'Flagged' if result.is_retracted else 'No flag found'}")
            if result.url: st.link_button("Open publication",result.url)
            st.caption("No retraction flag is not proof that a publication is reliable.")

def reliability_page(report):
    page_header("Research reliability","Inspect source-level reliability factors and warnings for each cited reference.","SOURCE INTELLIGENCE")
    if report is None: st.info("Load or generate a report to inspect its sources."); return
    seen=set()
    for result in report.results:
        ref=result.reference
        if not ref or ref.id in seen: continue
        seen.add(ref.id)
        analysis=reliability_for_reference(ref)
        with st.expander(ref.title or ref.raw or "Unidentified source"):
            st.metric("Reliability indicator",f"{analysis['score']}/100",analysis["grade"])
            st.caption("Metadata-based signal only; not a judgement of study validity.")
            st.dataframe([{"Factor":x["factor"],"Score":f"{x['points']}/{x['max']}","Explanation":x["reason"]} for x in analysis["factors"]],use_container_width=True,hide_index=True)
            for flag in analysis["flags"]: st.warning(flag)

def main():
    core.init_state()
    styles()
    settings=get_settings()
    llm=LLMClient(settings)
    if "page" not in st.session_state: st.session_state.page="Dashboard"
    with st.sidebar:
        st.markdown('<div class="brand">⚖ CiteVerify</div><div class="brand-sub">Research integrity workspace</div>',unsafe_allow_html=True)
        st.markdown(" ")
        page=st.radio("Workspace",NAV,index=NAV.index(st.session_state.page) if st.session_state.page in NAV else 0,label_visibility="collapsed",key="redesign_nav")
        st.session_state.page=page
        st.divider()
        st.caption("WORKSPACE STATUS")
        st.success("Demo mode available")
        st.caption("Evidence-first · Human-reviewed")
        st.divider()
        st.toggle("Dark mode (coming soon)",value=False,disabled=True)
    if st.session_state.get("report_mode") != "live" and st.session_state.get("report") is None:
        try: load_demo(settings)
        except Exception as exc: st.error(f"Could not load demo report: {exc}")
    report=st.session_state.get("report")
    if page=="Dashboard": dashboard(report)
    elif page=="Analyze paper": analyze_page(settings,llm)
    elif page=="Research reports": reports_page(report,settings,llm)
    elif page=="DOI verification": doi_page(settings)
    elif page=="Reliability analysis": reliability_page(report)
    else:
        page_header("Settings","Review the configuration used by this CiteVerify instance.","PREFERENCES")
        with st.container(border=True):
            st.markdown("### Runtime configuration")
            st.write({"LLM configured":settings.llm_configured,"Model":settings.llm_model,"Crossref mailto configured":bool(settings.crossref_mailto),"Demo report available":settings.demo_report_path.exists()})
            st.caption("Secrets are never displayed here. Configure keys through environment variables or your deployment secret manager.")
            st.markdown("### About")
            st.write("CiteVerify is an evidence-assistance tool. Its output supports human review and should not be treated as an automatic final judgement.")
    st.markdown('<div class="small-muted" style="text-align:center;margin-top:2.5rem">CiteVerify · Research smarter. Verify better.</div>',unsafe_allow_html=True)

if __name__=="__main__":
    main()
