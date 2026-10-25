# Research Analysis System

This application helps you enter, check, analyse, and report research data.

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

## 3. The normal workflow

For a quantitative project, use this order:

```text
Create Project -> Create or import questionnaire -> Enter or import real responses
-> Check data -> Define research questions -> Add hypotheses when needed
-> Link variables -> Run analysis -> Review results -> Generate Chapter Four -> Export
```

The guided workflow at the bottom of the window explains the next required step. If **Continue** is disabled, read the message below the progress bar.

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
