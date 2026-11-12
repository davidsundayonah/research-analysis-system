# Research Analysis System

This application helps you enter, check, analyse, and report research data. This guide is written as a working manual: follow the steps in order for your first real study, and use the later sections as a reference when you need a specific task.

> **Need help or want to suggest an update?** WhatsApp: [+234(0)7026792486](https://wa.me/2347026792486). In the desktop app, open **Help** in the left navigation for this guide.

## Quick demonstration with the included files

The repository includes practice datasets. They are for learning the workflow; do not cite their results as findings from a real study. For a real study, create a separate project and import only that study's approved data.

To open a preloaded walkthrough in the desktop app, run this from the repository folder:

```powershell
.\.venv\Scripts\python.exe tools\launch_guided_demo.py
```

It creates or reuses **Guided walkthrough — sample data (practice only)** in the app database, saves the two practice CSVs and a simulated transcript, runs descriptive, association, regression, and time-series examples, then opens the qualitative and time-series screens. The quantitative CSV remains the active project dataset; the time-series module opens its separate annual file. This is a persistent practice project, separate from any real study.

1. **Quantitative:** Open `test_research_data.csv` in a project. Start with descriptive summaries, then try a Spearman correlation between `SM_Hours` and `GPA`, followed by a one-predictor regression. Review warnings and diagnostics; this is test data, and association does not establish causation.
2. **Qualitative:** The quantitative CSV has no interview or open-ended text, so it cannot support qualitative coding. To see the coding screens without misrepresenting the survey, use [`sample_qualitative_transcript_demo.txt`](sample_qualitative_transcript_demo.txt). It is simulated practice text, not a response from the CSV. Save it as a transcript, create codes and themes, and code exact excerpts. For research, replace it with consented, de-identified source text and your own codebook.
3. **Time series:** Open `time_series_example.csv` in **Time-Series Analysis**. Select `Year` as the date and `Unemployment_Rate` as the outcome for a univariate example. The other economic-looking columns are explicitly synthetic. Review variable mappings, recommendations, stationarity checks, validation results, diagnostics, and forecasts before interpreting results.

The **Help** page in the application displays this README, so these steps and the support link are also available inside the running app. The in-app Help page reads this file directly, so improving the README improves the guide inside the desktop app too.

You can use it for:

- Paper questionnaires that you type into the computer.
- CSV or Excel files that already contain responses.
- Blank questionnaire documents in TXT, DOCX, PDF, JPG, JPEG, or PNG format.
- Interviews, transcripts, codes, themes, and qualitative findings.
- Studies that combine questionnaire and interview evidence.

You do not need to be a statistician to start. Follow the matching guide below and read every warning before using a result in your report.

## Start here: choose your situation

| Your situation | Start with |
|---|---|
| You have completed paper questionnaires | [A. Type paper questionnaires](#a-type-paper-questionnaires) |
| You already have a CSV or Excel file | [B. Import a spreadsheet](#b-import-a-spreadsheet) |
| You have one blank questionnaire document | [C. Build from a document](#c-build-from-a-blank-document) |
| You conducted interviews | [D. Analyse interviews](#d-analyse-interviews) |
| You have both questionnaire and interview data | [E. Mixed-methods study](#e-mixed-methods-study) |

## Contents

- [First real study: follow this sequence](#first-real-study-follow-this-sequence)
- [Install and open the application](#2-install-and-open-the-application)
- [Type paper questionnaires](#a-type-paper-questionnaires)
- [Import a spreadsheet](#b-import-a-spreadsheet)
- [Build a questionnaire from a document](#c-build-from-a-blank-document)
- [Analyse interviews](#d-analyse-interviews)
- [Analyse time-series data](#24-time-series-analysis)
- [Choose a research design and analysis](#4-choosing-a-research-design)
- [Understand and report results](#5-understanding-results)
- [Troubleshoot common problems](#8-common-problems)

## 1. The five ideas you need to know

- **Project**: one study. Keep unrelated studies in separate projects.
- **Questionnaire schema**: the approved list of questions and the rules for their answers.
- **Dataset**: the actual answers, with one respondent or observation per row.
- **Variable**: one column in a dataset, such as `Age`, `Gender`, or `GPA`.
- **Revision**: a protected saved version of a dataset. Cleaning creates a new revision so earlier data remains available.

For interviews:

- **Code**: a short label for an important idea in a transcript.
- **Theme**: a larger idea that groups related codes.
- **Excerpt**: the exact words copied from a transcript or open-ended answer.

## 2. Install and open the application

Open PowerShell in the project folder and run:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app.main
```

If `.venv` does not exist, create it first:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app.main
```

The application stores projects, database records, dataset snapshots, logs, and backups in `%APPDATA%\ResearchAnalysis`.

### Open the in-app guide

Select **Help** at the bottom of the desktop application's left sidebar to browse this complete guide inside the app. It includes the start-up steps, paper-entry and spreadsheet workflows, qualitative analysis, time-series analysis, reporting, troubleshooting, and data-protection guidance. The guide is included in the Windows desktop build.

## 2.1 Windows desktop build

The desktop application remains the primary full-featured interface. After installing the development dependencies, build a portable Windows executable with:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\build_windows.ps1
```

The output is `dist\ResearchAnalysis.exe`. Test it on a clean Windows machine before distribution. Packaged applications still write user data to `%APPDATA%\ResearchAnalysis`; they do not write a database into the installation folder.

## 2.2 Official download page

The website is a download page only. It does not expose desktop projects, accounts, analysis, or data management in a browser. It serves `dist\ResearchAnalysis.exe` when that file is present; otherwise, the download endpoint redirects to the latest GitHub release asset.

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\run_web.ps1
```

Open `http://127.0.0.1:8000/`. To publish a Windows download, push a `v*` version tag (for example, `v0.2.0`); the Windows release workflow tests the desktop application, builds the executable, and attaches `ResearchAnalysis.exe` to that GitHub release. The hosted page links to the latest release asset.

## 2.3 Tests and backups

Run the complete test suite with:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Use the desktop application's existing backup workflow for research databases. Before any hosted migration, stop writes, copy the SQLite database and its dataset storage together, verify the copy opens, and retain the original. No production migration is run by this repository configuration.

## 2.4 Time-series analysis

The desktop application has a separate **Time-Series Analysis** window in the sidebar. It can load project datasets or open CSV, XLSX, XLS, and text-based PDF tables; paste tabular data; and edit observations in the preview grid. Use **Back** to return to the previously viewed tab, or **Return to main app** to close the workspace and resume the main application. Loading different data returns to the preview and clears results belonging to the previous dataset. The workflow retains multiple columns, detects candidate time, numeric, and categorical fields, and lets the researcher assign one outcome and external predictors or multiple endogenous variables. Categorical fields are inspected but cannot be used directly in the current statistical models.

Before fitting, the window reports invalid or missing dates, duplicate timestamps, gaps, irregular intervals, missing/non-numeric values, constant fields, and apparent frequency mismatches. Proposed operations (for example, explicit duplicate handling, resampling, row exclusion, interpolation, or forward filling) require review and approval, operate on a working copy, and are saved in a preprocessing audit. The original imported observations are not silently changed. Invalid dates and incompatible variable frequencies need to be resolved by the researcher.

For one outcome, the module includes ARIMA/SARIMA, ADF, KPSS, Phillips-Perron, ACF/PACF, differencing, trend and seasonal decomposition, moving averages, chronological forecast comparison, residual diagnostics, and forecast intervals. Holdout metrics include MSE, RMSE, MAE, and MAPE where defined. ARIMA orders are configured by the researcher; the comparison table is not an automatic model-selection procedure. Exponential-smoothing intervals are approximate residual-scale intervals, not model-based confidence intervals.

For an outcome with explicitly selected external predictors, the module offers ARIMAX, SARIMAX, and regression-based forecasts. It checks predictor stationarity and does not automatically treat predictors as endogenous. Forecasts require date-aligned future predictor values; users may supply named scenarios or explicitly request independent predictor extrapolations. Estimated predictor paths are labeled, saved, and shown with the forecast, but the outcome prediction interval does not propagate uncertainty from the estimated predictor paths. Regression is restricted to series with level-stationarity evidence; nonstationary predictors require an explicit transformation or a separately justified cointegrating design.

For multiple endogenous variables, the module provides a stationarity-screened VAR workflow, Johansen trace-rank testing, VECM where compatible I(1) evidence and a non-saturated cointegration rank are supported, joint Granger-causality tests, lag selection, stability and residual checks, multivariate forecasts, IRFs, and VAR FEVD. VAR in levels is restricted to series with level-stationarity evidence. Orthogonalized IRFs depend on variable ordering. VECM forecasts currently do not include forecast intervals or FEVD, and multivariate diagnostics are narrower than the univariate residual suite.

Recommendations are based on selected roles, date regularity, sample size, missingness, variable variation, and ADF/KPSS stationarity screening. They distinguish recommended, conditional, and unsuitable methods; a displayed method name is not a guarantee of valid inference. Small samples and conflicting stationarity evidence require particular caution. Saved results retain model settings, test/evaluation output, predictor scenarios, recommendations, provenance, and preprocessing history for project reporting. The window supports CSV/XLSX/PDF/DOCX exports and saving edited data as a new project revision. New Word and Excel exports contain native Office charts with editable chart data; chart axes explicitly retain visible category/date ticks and numerical value ticks, as well as axis titles and units. PDF is a fixed-layout print copy and omits charts; use Word or Excel when you need to edit a chart. Chapter Four includes the saved time-series results and associated visualizations.

Known limitations: scanned-PDF OCR is not supported; PDF import requires selectable text. Automatic ARIMA order search, automatic seasonal detection from statistical tests, structural-break/unit-root adjustments, categorical encoding, exogenous cointegration testing, multivariate heteroskedasticity diagnostics, VECM forecast intervals, and multivariate model comparison are not implemented. Independent predictor extrapolation is optional and should be treated as an assumption, not observed future data. Review diagnostics, assumptions, and limitations before using results in academic or policy conclusions.

## 3. The normal workflow

For a quantitative project, use this order:

```text
Create Project -> Create or import questionnaire -> Enter or import real responses
-> Check data -> Define research questions -> Add hypotheses when needed
-> Link variables -> Run analysis -> Review results -> Generate Chapter Four -> Export
```

The guided workflow at the bottom of the window explains the next required step. If **Continue** is disabled, read the message below the progress bar. The steps below explain what to prepare, what to do in the app, and what to check before you rely on an analysis.

## First real study: follow this sequence

This is the recommended end-to-end path for a first quantitative study. It applies whether you are entering paper forms or importing an existing file. Complete the planning steps before running statistical tests; the app can calculate a statistic, but it cannot decide whether your question, measures, sample, or study design make that statistic meaningful.

### Before you open the app

1. **Confirm that you are allowed to use the data.** Follow your ethics approval, consent terms, institution rules, and applicable privacy requirements. Remove direct identifiers unless they are necessary and protected for your workflow. Do not put names, phone numbers, addresses, or other identifying details in variable names or analysis notes.
2. **Keep a safe source copy.** Save an unchanged copy of the original spreadsheet or scanned forms in an access-controlled location. The app's revisions are useful working history, but they are not a substitute for your approved source records and institutional backups.
3. **Write down the study question.** Make it specific enough to identify the population, outcome, and any group or predictor being studied. Example: “Among [defined participants], is [measured study-hours variable] associated with [measured outcome]?” Replace bracketed text with your actual study definitions.
4. **Check the approved protocol.** Confirm the planned sample, inclusion and exclusion rules, questionnaire version, outcome definitions, and analysis plan. Do not change these after seeing results just to obtain a preferred finding; document any justified deviation.
5. **Create a data dictionary.** For every column, record its meaning, permitted values, measurement level, missing-value rule, and source question. Decide how multi-select answers, reverse-worded items, composite scores, and open-ended responses are represented before importing.
6. **Decide how missing answers are represented.** Blank cells are the clearest default. If your source uses codes such as `99`, `-`, or `N/A`, decide whether these mean missing or are valid responses and apply one consistent documented rule. A number such as `999` is not automatically recognized as missing.
7. **For a time series, confirm the observation schedule.** Determine whether each row is a day, month, quarter, year, or another interval; whether dates mark the start or end of a period; how duplicate periods are resolved; and whether future predictor values are actually known.

### Create one project for one study

1. Start the application and open **Projects**.
2. Select **New Project**. Use a recognizable study name, not a participant name or confidential title. If you have multiple studies, create a separate project for each.
3. Enter the study title and researcher details that belong in reports. Check spelling because these details may be repeated in generated documents.
4. Set **Significance Level** and **Multiple-testing correction** to match your approved analysis plan. The default significance level is `0.05`; **Holm** is the default correction for multiple tests. Do not change these choices after seeing results to make a result appear significant. Ask your supervisor or statistician if you do not know which correction your study requires.
5. Create and open the project. Confirm that its name is visible before you import data or enter responses.

### Add and check the dataset

Use [Type paper questionnaires](#a-type-paper-questionnaires) if the responses exist only on paper. Use [Import a spreadsheet](#b-import-a-spreadsheet) if you already have a CSV or Excel workbook. Use [Build from a blank document](#c-build-from-a-blank-document) if you need to create a schema from the instrument.

After entry or import:

1. Open **Data** and confirm the displayed project and dataset are the ones you intend to work on.
2. Review **Data View** for a few records against the source forms or source spreadsheet. Check the first, middle, and last rows, and check any rows that produced warnings.
3. Open **Variable View**. Confirm each variable's label, type, measurement level, allowed values, valid count, and missing count. Numeric storage does not automatically mean a variable is continuous; a numeric code for “Strongly agree” is still an ordered response category.
4. Check IDs for uniqueness and make sure IDs do not contain identifying information unless the approved protocol requires it.
5. Record how many records were received, how many were excluded under the protocol, and why. Make sure these counts match the source records.
6. If you correct or recode anything, use **Data Cleaning**, inspect the proposed change, and save it as a new revision. Keep the original revision available and record the reason for each change.

### Define questions and analysis before looking for a result

1. Open **Research Questions** and add each question you actually intend to answer. Keep questions distinct: a question about describing a sample is different from a question about comparing groups or predicting an outcome.
2. For an inferential question, add the null hypothesis (H0) and alternative hypothesis (H1) that match your protocol. Use a descriptive question without a hypothesis when you are only summarizing what is present.
3. Open the variable-linking workflow and connect each question or hypothesis to the correct dataset variables. Check which variable is the outcome, which are predictors or grouping variables, and which rows are eligible under your study rules.
4. Select an analysis that matches the design and measurement level. The application's recommendation is a starting point, not a substitute for your protocol, supervisor, or statistician.
5. Before running, check whether the sample is independent or paired, how many groups there are, what values the variables contain, and whether the analysis assumptions are plausible. Do not choose a test only because it produces a small p-value.

### Run, review, and save an analysis

1. Open **Analysis**, select the intended question or hypothesis, then select the analysis and variables. Confirm that the active dataset revision is the one you checked.
2. Select **Run Selected Analysis**. If the app reports a warning or refuses to run, read the full message and resolve the underlying issue; do not work around it by silently deleting rows.
3. Review the sample size used, exclusions or missingness, descriptive summaries, estimates, uncertainty intervals, p-values, assumptions, and diagnostic warnings. A result with fewer observations than expected needs an explanation.
4. Check the direction and size of an estimate, not only whether its p-value crosses a threshold. Ask whether the estimate is meaningful in the real-world units and context of your study.
5. Save the result to the project. Add a clear label or note that identifies the question and data revision. Results are tied to the data used when they were run; changing data means you should rerun affected analyses.
6. If the result is unexpected, verify the source data, coding, missing-value rules, variable mapping, and analysis choice before interpreting it. Do not repeatedly try different tests until one supports the desired conclusion.

### Prepare a report and preserve the work

1. Open **Chapter Four** and generate the preview after the analyses you intend to report have been saved.
2. Check the project title, sample counts, dataset revision, research questions, analysis results, warnings, and quotations against your records.
3. Explain exclusions, missing data, deviations from the plan, and unresolved limitations in your own methods and results text. Generated wording does not know your study context.
4. Export to Word or Excel, open the exported file, and check every table, label, number, chart, and page break. Treat the export as a draft for review, not a submission-ready thesis.
5. Back up the application data folder and your original source data. Verify that the backup exists and can be restored according to your institution's policy.

### Keep a short decision log

For reproducibility, keep a separate note with the date, dataset revision, variable definitions, missing-value rules, exclusions, transformations, analysis choices, deviations from the plan, and who reviewed the results. The app stores useful project and analysis history, but a short human-readable decision log helps another researcher understand why you made each choice.

Use **Back** to return, **Continue** to move forward, and **Save and exit** to stop and resume later.

## A. Type paper questionnaires

Use this path when you have completed paper forms but no electronic dataset.

### A1. Create the project

1. Open **Projects**.
2. Select **New Project**.
3. Enter a name, such as `Customer Satisfaction Survey`.
4. Enter the study title and researcher details if known.
5. Leave the significance level at `0.05` unless your research plan says otherwise.
6. Create and open the project.

### A2. Build the questionnaire

1. Open **Data** and select **Questionnaire Builder**.
2. Enter a title and the expected number of questionnaires, for example `200`.
3. Add each question exactly as it appears on the paper form.
4. Give each question a unique variable name, such as `Gender`, `Age_Group`, `Service_Quality`, or `Comments`.
5. Choose the correct question type and measurement level.
6. Add allowed choices for closed and Likert questions.
7. Mark only genuinely essential questions as **Required**.
8. Approve the schema after checking every question.

The expected number is only a planning number. It does not create respondents or answers.

### A3. Enter and resume responses

1. In **Data**, select **Paper Entry**.
2. Enter a unique respondent ID, such as `R001`.
3. Type the answers from the paper questionnaire exactly as recorded.
4. Select **Save response**.
5. Repeat for each completed form.

To resume a saved respondent, open **Paper Entry**, select the respondent under **Resume respondent**, correct the fields, and save again. The progress line distinguishes expected, entered, complete, incomplete, and invalid records.

### A4. Check and analyse

1. Review validation warnings and correct invalid codes.
2. Add focused questions under **Research Questions**.
3. Add H0 and H1 for comparison, association, or prediction questions.
4. Link the correct variables and roles.
5. Run the recommended analysis.
6. Review N, warnings, statistics, p-values, confidence intervals, and interpretations.
7. Generate Chapter Four and export the report.

For an open-ended answer, preserve the respondent ID and copy the exact answer into the qualitative workflow. Do not invent or rewrite a quotation.

## B. Import a spreadsheet

Use this path when responses are already in CSV or Excel format.

Prepare the file with headings in the first row, one respondent per row, no merged cells, no instructions above the headings, and blank cells for unanswered questions. Do not use `-`, `N/A`, `unknown`, or `999` as missing values unless that rule is deliberately defined.

1. Open **Data** and select **Import Dataset**.
2. Choose the CSV or XLSX file.
3. Review the mapping screen when a questionnaire schema exists.
4. Confirm each spreadsheet column's questionnaire variable.
5. Check missing expected columns and unexpected columns.
6. Read invalid-row warnings.
7. Confirm the import only after reviewing the warnings.

The application preserves original rows and columns and creates a managed dataset snapshot.

Open **Variable View** to check each variable's name, label, type, measurement level, value labels, missing count, and valid count. Do not classify a five-point agreement item as continuous only because its stored values are numeric.

## C. Build from a blank document

1. Create a project and open **Data**.
2. Select **Questionnaire Builder** and create a draft schema.
3. Select **Extract questions from TXT/DOCX/PDF/image**.
4. Review every extracted question, section, number, and response choice.
5. Correct variable names and question types.
6. Add missing questions manually.
7. Approve only after review.
8. Generate a blank CSV or XLSX template.
9. Enter real answers or import a completed spreadsheet.

Extraction is an assistant, not an authority. Low-confidence text must be checked against the original document. The application never fills in missing wording or answer choices.

## D. Analyse interviews

1. Open **Qualitative**.
2. Store the interview guide.
3. Add each transcript with a participant ID or pseudonym and source name.
4. Create codes with clear meanings.
5. Group related codes under themes.
6. Select a transcript and save an exact coded excerpt.
7. Add analyst notes when useful.
8. Review themes against the original transcript before reporting them.

The number of coded excerpts does not automatically prove that a theme is important. Never call a qualitative theme statistically significant.

## E. Mixed-methods study

1. Complete the questionnaire or spreadsheet workflow.
2. Complete the interview workflow or code open-ended questionnaire responses.
3. Link both kinds of evidence to shared research questions where appropriate.
4. Explain whether qualitative evidence supports, extends, contextualizes, or contrasts with quantitative results.
5. Generate Chapter Four.
6. Confirm that numerical results and quotations remain separate and traceable.

Quantitative-only projects do not need transcripts. Qualitative-only projects do not need a numeric dataset.

## 4. Choosing a research design

| Design | Question | Typical analysis |
|---|---|---|
| Descriptive | What is present? | Frequencies, percentages, mean, median, spread |
| Comparison | Do groups differ? | t-test or one-way ANOVA |
| Association | Are variables related? | Pearson, Spearman, or chi-square |
| Prediction | Can one variable estimate another? | Linear regression |

Descriptive questions do not require hypotheses. Inferential questions require a complete H0 and H1 before analysis.

## 5. Understanding results

- **N** is the actual number of observations used by that analysis.
- **p-value** is evidence against H0 under the test assumptions; it is not the probability that your hypothesis is true.
- **Reject H0** means the result is inconsistent with H0 at the selected alpha.
- **Fail to reject H0** does not prove that no effect exists.
- **Correlation** shows association, not causation.
- **Warnings** about small groups, missingness, invalid values, or assumptions must be discussed in your report.

## 6. Data cleaning and revisions

Use **Data Cleaning** for renaming, recoding, missing-value rules, reverse scoring, and range groups.

1. Select an operation.
2. Review the proposed result.
3. Confirm the new variable or transformation.
4. Check the new dataset revision.
5. Keep the original revision available.

The application does not silently delete outliers, unusual respondents, or incomplete records.

## 7. Chapter Four and export

1. Open **Chapter Four**.
2. Select **Generate Chapter Four Preview**.
3. Read the project details, dataset revision, response counts, research findings, warnings, themes, and quotations.
4. Open **Export** and choose Word or Excel.
5. Open the exported file before submitting it.

Reports use saved analysis results and identify historical dataset revisions. If data changes, rerun the analysis and generate a new report.
The Word document and workbook include a **How to read this report** guide. Questionnaire labels are paired with their source column names; qualitative results separate themes, codes, definitions, and quotations; time-series reporting explains the ADF/PP and KPSS null hypotheses and forecast metrics. Mixed-methods results are kept distinct unless the researcher has documented how a theme relates to a research question. Review warnings, source notes, and unavailable statistics before publication.

## 8. Common problems

### Continue is disabled

Read the explanation beneath the progress bar. A dataset, research question, hypothesis, variable link, analysis, or export may still be required.

### Imported columns do not match

Use the mapping screen. A column name does not need to be identical if you explicitly map it to the correct questionnaire variable.

### A value is invalid

Check the approved choices and measurement level. Do not change an invalid response unless the original paper form supports the correction.

### The report is missing interview findings

Save an interview guide, transcript, code, and exact coded excerpt. A guide alone is not thematic analysis.

### I need to resume a respondent

Open Paper Entry and select the saved respondent under **Resume respondent**. Edit the fields and save again.

### I cannot extract an image

The Python packages are included in `requirements.txt`. Windows image OCR also requires the Tesseract OCR engine:

```powershell
winget install --id UB-Mannheim.TesseractOCR -e
```

## 9. Protecting your work

Back up `%APPDATA%\ResearchAnalysis` while the application is closed. Do not send identifiable transcripts or respondent data to an external AI service without appropriate permission and participant protection.

## 10. Developer commands

Start the application:

```powershell
.venv\Scripts\python.exe -m app.main
```

Run the full test suite:

```powershell
.venv\Scripts\python.exe -m pytest
```
