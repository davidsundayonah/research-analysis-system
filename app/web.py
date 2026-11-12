"""Official download page for the Windows desktop application."""

from html import escape
import os
from pathlib import Path
import tomllib

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_FILENAME = "ResearchAnalysis.exe"
LATEST_RELEASE_DOWNLOAD = (
    "https://github.com/davidsundayonah/research-analysis-system/"
    "releases/latest/download/ResearchAnalysis.exe"
)


def _application_version() -> str:
    project = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return str(project["project"]["version"])


def _landing_page(version: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Download Research Analysis System, a Windows desktop application for research data management, statistical analysis, and reporting.">
  <meta name="theme-color" content="#f5f7fa">
  <title>Research Analysis System — Windows desktop app</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      color: #172033;
      background: #f5f7fa;
      font-synthesis: none;
      text-rendering: optimizeLegibility;
      -webkit-font-smoothing: antialiased;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-width: 320px; }}
    a {{ color: inherit; }}
    .page {{ max-width: 1080px; margin: 0 auto; padding: 0 28px; }}
    .topbar {{
      display: flex; align-items: center; gap: 12px; min-height: 76px;
      border-bottom: 1px solid #e2e8f0;
    }}
    .brand-mark {{
      display: grid; width: 38px; height: 38px; place-items: center;
      border-radius: 11px; background: #2563eb; color: white;
      font-size: 15px; font-weight: 800; letter-spacing: -.04em;
    }}
    .brand-name {{ font-size: 15px; font-weight: 700; letter-spacing: -.02em; }}
    .desktop-tag {{
      margin-left: auto; padding: 7px 11px; border: 1px solid #dbe4f0;
      border-radius: 999px; color: #475569; font-size: 12px; font-weight: 650;
    }}
    main {{ padding: 76px 0 54px; }}
    .hero {{
      display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, .7fr);
      align-items: center; gap: 58px;
    }}
    .eyebrow {{
      margin: 0 0 16px; color: #2563eb; font-size: 12px;
      font-weight: 750; letter-spacing: .12em; text-transform: uppercase;
    }}
    h1 {{
      max-width: 660px; margin: 0; font-size: clamp(38px, 5vw, 58px);
      line-height: 1.06; letter-spacing: -.055em;
    }}
    .intro {{
      max-width: 600px; margin: 22px 0 28px; color: #526179;
      font-size: 18px; line-height: 1.7;
    }}
    .download {{
      display: inline-flex; min-height: 54px; align-items: center;
      justify-content: center; gap: 12px; padding: 0 22px;
      border: 0; border-radius: 9px; background: #2563eb; color: white;
      font-size: 16px; font-weight: 700; text-decoration: none;
      box-shadow: 0 7px 18px rgb(37 99 235 / 20%);
      transition: background .15s ease, transform .15s ease;
    }}
    .download:hover {{ background: #1d4ed8; transform: translateY(-1px); }}
    .download:focus-visible {{ outline: 3px solid #93c5fd; outline-offset: 3px; }}
    .download svg {{ width: 19px; height: 19px; }}
    .release-meta {{ margin: 13px 0 0; color: #64748b; font-size: 13px; }}
    .release-meta strong {{ color: #334155; }}
    .product-card {{
      padding: 28px; border: 1px solid #e2e8f0; border-radius: 16px;
      background: white; box-shadow: 0 16px 42px rgb(15 23 42 / 6%);
    }}
    .product-icon {{
      display: grid; width: 54px; height: 54px; place-items: center;
      margin-bottom: 23px; border-radius: 14px; background: #eff6ff; color: #2563eb;
    }}
    .product-icon svg {{ width: 27px; height: 27px; }}
    .product-card h2 {{ margin: 0 0 9px; font-size: 19px; letter-spacing: -.025em; }}
    .product-card > p {{ margin: 0; color: #64748b; font-size: 14px; line-height: 1.65; }}
    .feature-list {{ display: grid; gap: 13px; margin: 23px 0 0; padding: 0; list-style: none; }}
    .feature-list li {{ display: flex; align-items: flex-start; gap: 10px; color: #334155; font-size: 13px; line-height: 1.5; }}
    .check {{ flex: 0 0 18px; color: #16a34a; font-weight: 800; }}
    .details {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 18px;
      margin-top: 70px;
    }}
    .detail-card {{
      padding: 25px 27px; border: 1px solid #e2e8f0; border-radius: 13px;
      background: white;
    }}
    .detail-card h2 {{ margin: 0 0 17px; font-size: 16px; letter-spacing: -.02em; }}
    .requirements {{ display: grid; gap: 12px; margin: 0; }}
    .requirements div {{ display: flex; justify-content: space-between; gap: 16px; font-size: 13px; }}
    .requirements dt {{ color: #64748b; }}
    .requirements dd {{ margin: 0; color: #263449; font-weight: 600; text-align: right; }}
    .steps {{ display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }}
    .steps li {{ display: grid; grid-template-columns: 25px 1fr; gap: 10px; color: #526179; font-size: 13px; line-height: 1.55; }}
    .step-number {{
      display: grid; width: 23px; height: 23px; place-items: center;
      border-radius: 50%; background: #eff6ff; color: #2563eb;
      font-size: 11px; font-weight: 750;
    }}
    .note {{
      display: flex; gap: 11px; margin-top: 18px; padding: 14px 16px;
      border: 1px solid #dbeafe; border-radius: 9px;
      background: #eff6ff; color: #40536f; font-size: 12px; line-height: 1.6;
    }}
    .note strong {{ color: #1e3a8a; }}
    footer {{
      display: flex; justify-content: space-between; gap: 20px;
      padding: 21px 0 26px; border-top: 1px solid #e2e8f0;
      color: #718096; font-size: 12px;
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 0 20px; }}
      main {{ padding-top: 49px; }}
      .hero {{ grid-template-columns: 1fr; gap: 35px; }}
      .details {{ grid-template-columns: 1fr; margin-top: 42px; }}
      .product-card {{ max-width: none; }}
    }}
    @media (max-width: 420px) {{
      .desktop-tag {{ font-size: 11px; }}
      .intro {{ font-size: 16px; }}
      footer {{ flex-direction: column; gap: 7px; }}
      .requirements div {{ flex-direction: column; gap: 2px; }}
      .requirements dd {{ text-align: left; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{ scroll-behavior: auto !important; transition-duration: .01ms !important; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <header class="topbar">
      <div class="brand-mark" aria-hidden="true">RA</div>
      <div class="brand-name">Research Analysis System</div>
      <div class="desktop-tag">Windows desktop application</div>
    </header>
    <main>
      <section class="hero" aria-labelledby="product-title">
        <div>
          <p class="eyebrow">Research workflows, in one desktop app</p>
          <h1 id="product-title">Research Analysis System</h1>
          <p class="intro">Organize research projects, work with questionnaire and spreadsheet data, run statistical and qualitative analyses, and prepare clear reports—all in a Windows desktop application.</p>
          <a class="download" href="/download" aria-label="Download Research Analysis System for Windows">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <path d="m7 10 5 5 5-5M12 15V3"/>
            </svg>
            Download for Windows
          </a>
          <p class="release-meta">Version <strong>{escape(version)}</strong> · 64-bit Windows · Portable executable</p>
        </div>
        <aside class="product-card" aria-label="Application overview">
          <div class="product-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="3"/>
              <path d="M8 16v-4m4 4V8m4 8v-6"/>
            </svg>
          </div>
          <h2>Built for your research</h2>
          <p>A focused workspace for the full research process, from organizing source data to reviewing analysis and exporting reports.</p>
          <ul class="feature-list">
            <li><span class="check" aria-hidden="true">✓</span><span>Questionnaire, spreadsheet, and project data management</span></li>
            <li><span class="check" aria-hidden="true">✓</span><span>Statistical, qualitative, and time-series analysis tools</span></li>
            <li><span class="check" aria-hidden="true">✓</span><span>Research reports and desktop file exports</span></li>
          </ul>
        </aside>
      </section>
      <section class="details" aria-label="Requirements and installation">
        <article class="detail-card">
          <h2>System requirements</h2>
          <dl class="requirements">
            <div><dt>Operating system</dt><dd>Windows 10 or later (64-bit)</dd></div>
            <div><dt>Memory</dt><dd>4 GB RAM minimum; 8 GB recommended</dd></div>
            <div><dt>Storage</dt><dd>500 MB free space recommended</dd></div>
            <div><dt>Internet</dt><dd>Only needed to download the application</dd></div>
          </dl>
        </article>
        <article class="detail-card">
          <h2>Get started</h2>
          <ol class="steps">
            <li><span class="step-number">1</span><span>Download the Windows executable using the button above.</span></li>
            <li><span class="step-number">2</span><span>Open the downloaded <strong>ResearchAnalysis.exe</strong> file.</span></li>
            <li><span class="step-number">3</span><span>Follow any Windows security prompt, then create or open a project.</span></li>
          </ol>
          <div class="note"><span aria-hidden="true">i</span><span><strong>Desktop application:</strong> analysis runs on your Windows computer. This website is only for product information and downloads; it does not provide browser-based research tools.</span></div>
        </article>
      </section>
    </main>
    <footer><span>Research Analysis System</span><span>Windows desktop software · Version {escape(version)}</span></footer>
  </div>
</body>
</html>"""


def create_app(download_path: str | Path | None = None) -> FastAPI:
    """Create the public download page and executable endpoint."""
    configured_path = download_path or os.environ.get(
        "RESEARCH_ANALYSIS_DOWNLOAD_PATH"
    )
    executable = (
        Path(configured_path)
        if configured_path
        else PROJECT_ROOT / "dist" / DOWNLOAD_FILENAME
    )
    executable = executable.resolve()
    version = _application_version()

    app = FastAPI(
        title="Research Analysis System Downloads",
        version=version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.download_path = executable
    app.state.release_download_url = os.environ.get(
        "RESEARCH_ANALYSIS_RELEASE_DOWNLOAD_URL", LATEST_RELEASE_DOWNLOAD
    )

    @app.get("/", response_class=HTMLResponse)
    async def landing_page():
        return HTMLResponse(
            _landing_page(version),
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.get("/download", name="download")
    async def download_application():
        if executable.is_file():
            return FileResponse(
                executable,
                media_type="application/vnd.microsoft.portable-executable",
                filename=DOWNLOAD_FILENAME,
                headers={"X-Content-Type-Options": "nosniff"},
            )
        return RedirectResponse(
            app.state.release_download_url,
            status_code=302,
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
