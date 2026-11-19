# CiteVerify

**Evidence, not verdicts.** Upload a paper; CiteVerify checks whether its cited sources actually support its claims.

Built for the INNOVEDGE Hackathon 2026, Problem Statement 03.

## What it is

Researchers cite papers that often do not say what the citing sentence claims. Existing tools check whether a reference exists or is formatted correctly; CiteVerify checks **claim support**.

For each cited claim, it produces:

- a verdict: `supported`, `partially_supported`, `unsupported`, `contradicted`, or `unverifiable`
- a verbatim evidence quote from the source
- a confidence label
- a DOI/source link
- an optional suggested fix
- flags such as `retracted`

The design rule is simple: **no verbatim quote, no verdict**. If the source text is insufficient, the claim is marked unverifiable.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/make_demo.py
streamlit run app.py
```

The **Demo report** works without an API key and without network access. It is an illustrative citing paper built over real open-access abstracts.

## Live analysis

Copy `.env.example` to `.env` and set an LLM key:

```powershell
Copy-Item .env.example .env
# edit .env
```

```env
LLM_API_KEY=...
LLM_MODEL=gpt-4o-mini
CROSSREF_MAILTO=you@example.com
```

Then switch to **Analyze a paper** in the app, upload a PDF (or paste text), and run the pipeline.

The live pipeline:

1. Extracts text and the reference section with PyMuPDF.
2. Extracts cited claims and references with a structured LLM call.
3. Resolves DOIs/titles through Crossref and OpenAlex.
4. Compares each claim only against the retrieved source text.
5. Validates the evidence quote and builds the report.

## Demo and evaluation

```powershell
python scripts/make_demo.py      # rebuild demo report + gold set
python scripts/evaluate.py       # requires LLM_API_KEY
```

The gold set is a small hand-labelled sanity check over real abstracts. It is **not** a benchmark. The evaluation tab in the app reads `data/gold_set_results.json` after the harness runs.

## DOI quick check

The sidebar can check any DOI for retraction status and metadata without an LLM. Example retracted DOI:

```text
10.1016/S0140-6736(97)11096-0
```

## Repo layout

```text
app.py                     Streamlit UI
citeverify/
  doi.py                   DOI normalization
  ingest.py                PDF/text ingestion
  extract.py               claim + reference extraction
  resolve.py               Crossref/OpenAlex resolution
  verify.py                source-grounded verdicts
  report.py                report assembly + export
  llm.py                   structured JSON LLM wrapper
  models.py                shared Pydantic models
data/
  demo/demo_report.json    offline demo
  gold_set.json            hand-labelled evaluation cases
scripts/
  make_demo.py             rebuild demo + gold set
  evaluate.py              run the gold-set harness
tests/                     unit tests
```

## Limitations

- Abstract-level evidence by default; full-text retrieval is future work.
- Citation-to-reference matching is heuristic.
- Confidence labels are a rubric, not a calibrated probability.
- The demo paper is illustrative; the cited sources and abstracts are real.
- CiteVerify is evidence for human review, not a final verdict on a paper.

## Tests

```powershell
pytest -q
```
