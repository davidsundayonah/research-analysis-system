import sqlite3
import json
import os
import shutil
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class Database:
    def __init__(self, database_path=None, *, check_same_thread=True):
        self.database_path = Path(
            database_path
            if database_path is not None
            else self.default_database_path()
        ).resolve()

        self.database_dir = self.database_path.parent
        self.database_dir.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=check_same_thread,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")

        self.create_tables()

    @staticmethod
    def default_database_path():
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / ".local" / "share"
        return base / "ResearchAnalysis" / "research_analysis.db"

    # =========================================================
    # DATABASE TABLES
    # =========================================================

    def create_tables(self):
        migrations = (
            self._create_initial_schema,
            self._create_research_questions_schema,
            self._create_hypotheses_schema,
            self._add_research_question_design_schema,
            self._split_hypothesis_fields,
            self._create_variable_link_and_result_schema,
            self._create_analysis_runs_schema,
            self._add_dataset_revision_schema,
            self._add_variable_metadata_schema,
            self._create_qualitative_schema,
            self._add_analysis_governance_schema,
            self._add_qualitative_governance_schema,
            self._create_time_series_analysis_schema,
            self._create_web_accounts_schema,
        )
        version = self.connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        if version > len(migrations):
            raise RuntimeError(
                f"Database schema version {version} is newer than supported."
            )

        while version < len(migrations):
            with self.connection:
                migrations[version]()
                version += 1
                self.connection.execute(
                    f"PRAGMA user_version = {version}"
                )

        # Keep the established public migration version stable.  These tables
        # are additive and can be installed idempotently for databases that
        # already reached the prior version.
        self._create_questionnaire_schema()

    def _create_initial_schema(self):
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                research_title TEXT,
                researcher TEXT,
                institution TEXT,
                department TEXT,
                significance_level REAL DEFAULT 0.05,
                status TEXT DEFAULT 'New',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                row_count INTEGER DEFAULT 0,
                column_count INTEGER DEFAULT 0,
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE CASCADE
            )
        """)

    def _create_research_questions_schema(self):
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS research_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE CASCADE
            )
        """)

    def _create_hypotheses_schema(self):
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS hypotheses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                research_question_id INTEGER NOT NULL,
                hypothesis TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (research_question_id)
                    REFERENCES research_questions(id)
                    ON DELETE CASCADE
            )
        """)

    def _add_research_question_design_schema(self):
        self.connection.execute(
            "ALTER TABLE research_questions ADD COLUMN code TEXT"
        )
        self.connection.execute(
            "ALTER TABLE research_questions "
            "ADD COLUMN position INTEGER NOT NULL DEFAULT 0"
        )
        self.connection.execute(
            "ALTER TABLE research_questions "
            "ADD COLUMN design_type TEXT NOT NULL DEFAULT 'descriptive'"
        )
        self.connection.execute(
            "ALTER TABLE research_questions "
            "ADD COLUMN proposed_test TEXT NOT NULL DEFAULT ''"
        )

        project_ids = self.connection.execute(
            "SELECT DISTINCT project_id FROM research_questions"
        ).fetchall()
        for project_row in project_ids:
            questions = self.connection.execute(
                """
                SELECT id
                FROM research_questions
                WHERE project_id = ?
                ORDER BY id
                """,
                (project_row[0],),
            ).fetchall()
            for position, question_row in enumerate(questions, start=1):
                self.connection.execute(
                    """
                    UPDATE research_questions
                    SET code = ?, position = ?
                    WHERE id = ?
                    """,
                    (f"RQ{position}", position, question_row[0]),
                )

        self.connection.execute(
            """
            CREATE UNIQUE INDEX research_questions_project_code
            ON research_questions(project_id, lower(trim(code)))
            """
        )

    def _split_hypothesis_fields(self):
        self.connection.execute(
            """
            ALTER TABLE hypotheses
            ADD COLUMN null_hypothesis TEXT NOT NULL DEFAULT ''
            """
        )
        self.connection.execute(
            """
            ALTER TABLE hypotheses
            ADD COLUMN alternative_hypothesis TEXT NOT NULL DEFAULT ''
            """
        )
        self.connection.execute(
            """
            ALTER TABLE hypotheses
            ADD COLUMN directionality TEXT NOT NULL DEFAULT 'non-directional'
            """
        )
        self.connection.execute(
            """
            UPDATE hypotheses
            SET alternative_hypothesis = COALESCE(hypothesis, '')
            """
        )

    def _create_variable_link_and_result_schema(self):
        self.connection.execute("""
            CREATE TABLE dataset_variables (
                dataset_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                data_type TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (dataset_id, name),
                FOREIGN KEY (dataset_id)
                    REFERENCES datasets(id)
                    ON DELETE CASCADE
            )
        """)
        self.connection.execute("""
            CREATE TABLE research_question_variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                research_question_id INTEGER NOT NULL,
                dataset_id INTEGER NOT NULL,
                variable_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (
                    role IN ('outcome', 'predictor', 'grouping')
                ),
                UNIQUE (research_question_id, dataset_id, variable_name),
                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (research_question_id)
                    REFERENCES research_questions(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (dataset_id)
                    REFERENCES datasets(id)
                    ON DELETE CASCADE
            )
        """)

    def _create_analysis_runs_schema(self):
        self.connection.execute("""
            CREATE TABLE analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                research_question_id INTEGER NOT NULL,
                hypothesis_id INTEGER,
                dataset_id INTEGER NOT NULL,
                dataset_signature TEXT NOT NULL,
                actual_test TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                hypothesis_decision TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (research_question_id)
                    REFERENCES research_questions(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (hypothesis_id)
                    REFERENCES hypotheses(id)
                    ON DELETE SET NULL,
                FOREIGN KEY (dataset_id)
                    REFERENCES datasets(id)
                    ON DELETE RESTRICT
            )
        """)
        self.connection.execute("""
            CREATE TABLE analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                research_question_id INTEGER NOT NULL,
                actual_test TEXT NOT NULL,
                result_summary TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id)
                    REFERENCES projects(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (research_question_id)
                    REFERENCES research_questions(id)
                    ON DELETE CASCADE
            )
        """)

    def _add_dataset_revision_schema(self):
        columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(datasets)")
        }
        additions = {
            "source_path": "TEXT",
            "content_hash": "TEXT",
            "revision_number": "INTEGER NOT NULL DEFAULT 1",
            "revision_of": "INTEGER",
            "is_active": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE datasets ADD COLUMN {name} {definition}"
                )

        self.connection.execute(
            "UPDATE datasets SET source_path = file_path WHERE source_path IS NULL"
        )
        self.connection.execute(
            "UPDATE datasets SET is_active = 1 WHERE is_active IS NULL"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS datasets_project_active "
            "ON datasets(project_id, is_active, imported_at, id)"
        )

    def _add_variable_metadata_schema(self):
        columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(dataset_variables)")
        }
        additions = {
            "label": "TEXT NOT NULL DEFAULT ''",
            "measure": "TEXT NOT NULL DEFAULT ''",
            "value_labels_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE dataset_variables ADD COLUMN {name} {definition}"
                )

    def _create_qualitative_schema(self):
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS interview_guides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS interview_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                participant_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS qualitative_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                theme TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (project_id, code),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS transcript_codings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript_id INTEGER NOT NULL,
                code_id INTEGER NOT NULL,
                excerpt TEXT NOT NULL,
                analyst_note TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (transcript_id) REFERENCES interview_transcripts(id) ON DELETE CASCADE,
                FOREIGN KEY (code_id) REFERENCES qualitative_codes(id) ON DELETE CASCADE
            )
        """)

    def _add_analysis_governance_schema(self):
        columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(projects)")
        }
        if "multiplicity_method" not in columns:
            self.connection.execute(
                "ALTER TABLE projects ADD COLUMN multiplicity_method TEXT NOT NULL DEFAULT 'holm'"
            )

    def _add_qualitative_governance_schema(self):
        guide_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(interview_guides)")}
        if "version" not in guide_columns:
            self.connection.execute("ALTER TABLE interview_guides ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
        coding_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(transcript_codings)")}
        if "coder" not in coding_columns:
            self.connection.execute("ALTER TABLE transcript_codings ADD COLUMN coder TEXT NOT NULL DEFAULT 'primary'")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS qualitative_codebook_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, version),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS qualitative_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id INTEGER,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)

    def _create_time_series_analysis_schema(self):
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS time_series_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                dataset_id INTEGER,
                data_source TEXT NOT NULL DEFAULT '',
                indicator_name TEXT NOT NULL DEFAULT '',
                methodology TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                units TEXT NOT NULL DEFAULT '',
                downloaded_date TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
            )
        """)
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS time_series_analyses_project "
            "ON time_series_analyses(project_id, created_at, id)"
        )

    def _create_web_accounts_schema(self):
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                csrf_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
            )
        """)
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS web_sessions_user ON web_sessions(user_id)"
        )
        project_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(projects)")
        }
        if "owner_user_id" not in project_columns:
            self.connection.execute(
                "ALTER TABLE projects ADD COLUMN owner_user_id INTEGER "
                "REFERENCES web_users(id) ON DELETE CASCADE"
            )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS projects_owner_updated "
            "ON projects(owner_user_id, updated_at DESC)"
        )

    def _create_questionnaire_schema(self):
        """Create the project-scoped questionnaire and paper-entry store.

        Questionnaire definitions are deliberately separate from imported datasets.
        This lets a researcher design a form before entering responses, while old
        datasets and analyses continue to use their existing revision identifiers.
        """
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS questionnaire_schemas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                instructions TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                expected_sample_size INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, version),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS questionnaire_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                question_number TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL,
                variable_name TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                question_type TEXT NOT NULL,
                data_type TEXT NOT NULL,
                measure TEXT NOT NULL,
                required INTEGER NOT NULL DEFAULT 0,
                options_json TEXT NOT NULL DEFAULT '[]',
                missing_values_json TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(schema_id) REFERENCES questionnaire_schemas(id) ON DELETE CASCADE,
                UNIQUE(schema_id, variable_name)
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS paper_entry_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                schema_id INTEGER NOT NULL,
                respondent_id TEXT NOT NULL,
                responses_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'blank',
                valid INTEGER NOT NULL DEFAULT 1,
                validation_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(schema_id, respondent_id),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(schema_id) REFERENCES questionnaire_schemas(id) ON DELETE CASCADE
            )
        """)
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS questionnaire_questions_order "
            "ON questionnaire_questions(schema_id, position)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS paper_entry_records_schema "
            "ON paper_entry_records(schema_id, status)"
        )
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS open_ended_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                schema_id INTEGER,
                respondent_id TEXT NOT NULL,
                question_variable TEXT NOT NULL,
                response_text TEXT NOT NULL,
                source_record_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(schema_id) REFERENCES questionnaire_schemas(id) ON DELETE SET NULL,
                FOREIGN KEY(source_record_id) REFERENCES paper_entry_records(id) ON DELETE SET NULL
            )
        """)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS qualitative_themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                research_question_id INTEGER,
                approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, name),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(research_question_id) REFERENCES research_questions(id) ON DELETE SET NULL
            )
        """)

    # =========================================================
    # QUESTIONNAIRES AND PAPER DATA ENTRY
    # =========================================================

    def create_questionnaire_schema(self, project_id, title, instructions="", expected_sample_size=None):
        self._require_project(project_id)
        title = str(title or "").strip()
        if not title:
            raise ValueError("Questionnaire title is required.")
        if expected_sample_size is not None:
            expected_sample_size = int(expected_sample_size)
            if expected_sample_size < 0:
                raise ValueError("Expected sample size cannot be negative.")
        version = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM questionnaire_schemas WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
        cursor = self.connection.execute(
            """INSERT INTO questionnaire_schemas
               (project_id, version, title, instructions, expected_sample_size)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, version, title, str(instructions or "").strip(), expected_sample_size),
        )
        self.connection.commit()
        return cursor.lastrowid

    def get_questionnaire_schema(self, schema_id):
        return self.connection.execute(
            "SELECT * FROM questionnaire_schemas WHERE id = ?", (schema_id,)
        ).fetchone()

    def get_project_questionnaire_schemas(self, project_id):
        return self.connection.execute(
            "SELECT * FROM questionnaire_schemas WHERE project_id = ? ORDER BY version DESC",
            (project_id,),
        ).fetchall()

    @staticmethod
    def _questionnaire_json(value, default):
        if value is None:
            return default
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError("Questionnaire metadata must be valid JSON.") from error
            return decoded
        return value

    def add_questionnaire_question(self, schema_id, prompt, variable_name, question_type="short_text",
                                   data_type="text", measure="text", *, section="", question_number="",
                                   label="", required=False, options=None, missing_values=None, notes=""):
        schema = self.get_questionnaire_schema(schema_id)
        if schema is None:
            raise ValueError("Questionnaire schema does not exist.")
        if schema["status"] == "approved":
            raise ValueError("Approved questionnaires are immutable; create a new version to edit them.")
        prompt, variable_name = str(prompt or "").strip(), str(variable_name or "").strip()
        if not prompt or not variable_name:
            raise ValueError("Question wording and variable name are required.")
        from app.questionnaire import validate_question_definition
        validate_question_definition(variable_name, question_type, data_type, measure, options or [])
        position = self.connection.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM questionnaire_questions WHERE schema_id = ?",
            (schema_id,),
        ).fetchone()[0]
        cursor = self.connection.execute(
            """INSERT INTO questionnaire_questions
               (schema_id, position, section, question_number, prompt, variable_name, label,
                question_type, data_type, measure, required, options_json, missing_values_json, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (schema_id, position, str(section or "").strip(), str(question_number or "").strip(),
             prompt, variable_name, str(label or prompt).strip(), question_type, data_type, measure,
             int(bool(required)), json.dumps(options or [], ensure_ascii=False),
             json.dumps(missing_values or [], ensure_ascii=False), str(notes or "").strip()),
        )
        self.connection.commit()
        return cursor.lastrowid

    def get_questionnaire_questions(self, schema_id):
        return self.connection.execute(
            "SELECT * FROM questionnaire_questions WHERE schema_id = ? ORDER BY position, id",
            (schema_id,),
        ).fetchall()

    def approve_questionnaire_schema(self, schema_id):
        schema = self.get_questionnaire_schema(schema_id)
        if schema is None:
            raise ValueError("Questionnaire schema does not exist.")
        if not self.get_questionnaire_questions(schema_id):
            raise ValueError("Add at least one question before approving the questionnaire.")
        with self.connection:
            self.connection.execute(
                "UPDATE questionnaire_schemas SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (schema_id,),
            )
        return True

    def create_paper_entry_record(self, project_id, schema_id, respondent_id):
        schema = self.get_questionnaire_schema(schema_id)
        if schema is None or schema["project_id"] != project_id:
            raise ValueError("Questionnaire does not belong to this project.")
        respondent_id = str(respondent_id or "").strip()
        if not respondent_id:
            raise ValueError("Respondent ID is required.")
        try:
            cursor = self.connection.execute(
                "INSERT INTO paper_entry_records (project_id, schema_id, respondent_id) VALUES (?, ?, ?)",
                (project_id, schema_id, respondent_id),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError("Respondent ID already exists for this questionnaire.") from error
        return cursor.lastrowid

    def save_paper_entry_record(self, record_id, responses):
        record = self.connection.execute(
            "SELECT * FROM paper_entry_records WHERE id = ?", (record_id,)
        ).fetchone()
        if record is None:
            raise ValueError("Paper-entry record does not exist.")
        from app.questionnaire import validate_responses
        questions = self.get_questionnaire_questions(record["schema_id"])
        cleaned, errors = validate_responses(questions, responses or {})
        answered = sum(value not in (None, "") for value in cleaned.values())
        required_names = {q["variable_name"] for q in questions if q["required"]}
        complete = required_names.issubset({name for name, value in cleaned.items() if value not in (None, "")})
        status = "invalid" if errors else ("complete" if complete else ("incomplete" if answered else "blank"))
        with self.connection:
            self.connection.execute(
                """UPDATE paper_entry_records
                   SET responses_json = ?, status = ?, valid = ?, validation_json = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (json.dumps(cleaned, ensure_ascii=False), status, int(not errors),
                 json.dumps(errors, ensure_ascii=False), record_id),
            )
        return {"status": status, "valid": not errors, "errors": errors, "responses": cleaned}

    def get_paper_entry_records(self, schema_id):
        return self.connection.execute(
            "SELECT * FROM paper_entry_records WHERE schema_id = ? ORDER BY id", (schema_id,)
        ).fetchall()

    def get_paper_entry_record(self, record_id):
        return self.connection.execute(
            "SELECT * FROM paper_entry_records WHERE id = ?", (record_id,)
        ).fetchone()

    def get_paper_entry_progress(self, schema_id):
        schema = self.get_questionnaire_schema(schema_id)
        records = self.get_paper_entry_records(schema_id)
        return {
            "expected": schema["expected_sample_size"] if schema else None,
            "entered": sum(row["status"] != "blank" for row in records),
            "complete": sum(row["status"] == "complete" for row in records),
            "incomplete": sum(row["status"] == "incomplete" for row in records),
            "valid": sum(bool(row["valid"]) and row["status"] != "blank" for row in records),
            "invalid": sum(not bool(row["valid"]) and row["status"] != "blank" for row in records),
        }

    def create_open_ended_response(self, project_id, respondent_id, question_variable, response_text,
                                   schema_id=None, source_record_id=None):
        self._require_project(project_id)
        respondent_id = str(respondent_id or '').strip()
        question_variable = str(question_variable or '').strip()
        response_text = str(response_text or '')
        if not respondent_id or not question_variable or not response_text.strip():
            raise ValueError("Respondent ID, question variable, and response text are required.")
        if schema_id is not None:
            schema = self.get_questionnaire_schema(schema_id)
            if schema is None or schema["project_id"] != project_id:
                raise ValueError("Questionnaire does not belong to this project.")
        cursor = self.connection.execute(
            """INSERT INTO open_ended_responses
               (project_id, schema_id, respondent_id, question_variable, response_text, source_record_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, schema_id, respondent_id, question_variable, response_text, source_record_id),
        )
        self.connection.commit()
        return cursor.lastrowid

    def get_open_ended_responses(self, project_id, question_variable=None):
        if question_variable:
            return self.connection.execute(
                "SELECT * FROM open_ended_responses WHERE project_id = ? AND question_variable = ? ORDER BY id",
                (project_id, question_variable),
            ).fetchall()
        return self.connection.execute(
            "SELECT * FROM open_ended_responses WHERE project_id = ? ORDER BY id", (project_id,)
        ).fetchall()

    def create_qualitative_theme(self, project_id, name, description='', research_question_id=None, approved=False):
        self._require_project(project_id)
        name = str(name or '').strip()
        if not name:
            raise ValueError("Theme name is required.")
        if research_question_id is not None:
            question = self.get_research_question(project_id, research_question_id)
            if question is None:
                raise ValueError("Research question does not belong to this project.")
        try:
            cursor = self.connection.execute(
                """INSERT INTO qualitative_themes
                   (project_id, name, description, research_question_id, approved)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, name, str(description or '').strip(), research_question_id, int(bool(approved))),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError("Theme name already exists in this project.") from error
        return cursor.lastrowid

    def get_qualitative_themes(self, project_id, approved_only=False):
        query = "SELECT * FROM qualitative_themes WHERE project_id = ?"
        params = [project_id]
        if approved_only:
            query += " AND approved = 1"
        return self.connection.execute(query + " ORDER BY name", params).fetchall()

    def _require_project(self, project_id):
        if self.get_project(project_id) is None:
            raise ValueError("Project does not exist.")

    def save_interview_guide(self, project_id, title, content):
        self._require_project(project_id)
        title, content = str(title or '').strip(), str(content or '').strip()
        if not title or not content:
            raise ValueError("Interview guide title and content are required.")
        existing = self.get_interview_guide(project_id)
        version = int(existing["version"] if existing and "version" in existing.keys() else 0) + 1
        with self.connection:
            self.connection.execute(
                """INSERT INTO interview_guides (project_id, title, content)
                   VALUES (?, ?, ?)
                   ON CONFLICT(project_id) DO UPDATE SET title=excluded.title,
                   content=excluded.content, version=?, updated_at=CURRENT_TIMESTAMP""",
                (project_id, title, content, version),
            )
        self.record_qualitative_audit(project_id, "save", "interview_guide", existing["id"] if existing else None, {"version": version})
        return self.connection.execute(
            "SELECT id FROM interview_guides WHERE project_id = ?", (project_id,)
        ).fetchone()[0]

    def get_interview_guide(self, project_id):
        return self.connection.execute(
            "SELECT * FROM interview_guides WHERE project_id = ?", (project_id,)
        ).fetchone()

    def create_interview_transcript(self, project_id, participant_id, source_name, content):
        self._require_project(project_id)
        values = [str(value or '').strip() for value in (participant_id, source_name, content)]
        if not all(values):
            raise ValueError("Participant, source name, and transcript content are required.")
        cursor = self.connection.execute(
            """INSERT INTO interview_transcripts
               (project_id, participant_id, source_name, content)
               VALUES (?, ?, ?, ?)""", (project_id, *values)
        )
        self.connection.commit()
        self.record_qualitative_audit(project_id, "create", "interview_transcript", cursor.lastrowid, {"source_name": values[1]})
        return cursor.lastrowid

    def get_interview_transcripts(self, project_id):
        return self.connection.execute(
            "SELECT * FROM interview_transcripts WHERE project_id = ? ORDER BY id",
            (project_id,),
        ).fetchall()

    def create_qualitative_code(self, project_id, code, theme, description=''):
        self._require_project(project_id)
        code, theme = str(code or '').strip(), str(theme or '').strip()
        if not code or not theme:
            raise ValueError("Code and theme are required.")
        cursor = self.connection.execute(
            """INSERT INTO qualitative_codes (project_id, code, theme, description)
               VALUES (?, ?, ?, ?)""", (project_id, code, theme, str(description or '').strip())
        )
        self.connection.commit()
        self.record_qualitative_audit(project_id, "create", "qualitative_code", cursor.lastrowid, {"code": code, "theme": theme})
        self.save_codebook_version(project_id)
        return cursor.lastrowid

    def get_qualitative_codes(self, project_id):
        return self.connection.execute(
            "SELECT * FROM qualitative_codes WHERE project_id = ? ORDER BY theme, code",
            (project_id,),
        ).fetchall()

    def create_transcript_coding(self, project_id, transcript_id, code_id, excerpt, analyst_note='', coder='primary'):
        transcript = self.connection.execute(
            "SELECT id FROM interview_transcripts WHERE id = ? AND project_id = ?",
            (transcript_id, project_id),
        ).fetchone()
        code = self.connection.execute(
            "SELECT id FROM qualitative_codes WHERE id = ? AND project_id = ?",
            (code_id, project_id),
        ).fetchone()
        excerpt = str(excerpt or '').strip()
        if transcript is None or code is None or not excerpt:
            raise ValueError("Select a valid project transcript/code and enter an excerpt.")
        cursor = self.connection.execute(
            """INSERT INTO transcript_codings
               (transcript_id, code_id, excerpt, analyst_note, coder)
               VALUES (?, ?, ?, ?, ?)""",
            (transcript_id, code_id, excerpt, str(analyst_note or '').strip(), str(coder or 'primary').strip()),
        )
        self.connection.commit()
        self.record_qualitative_audit(project_id, "create", "transcript_coding", cursor.lastrowid, {"coder": str(coder or 'primary').strip()})
        return cursor.lastrowid

    def get_qualitative_codings(self, project_id):
        return self.connection.execute(
            """SELECT tc.*, it.participant_id, it.source_name, qc.code, qc.theme
               FROM transcript_codings tc
               JOIN interview_transcripts it ON it.id = tc.transcript_id
               JOIN qualitative_codes qc ON qc.id = tc.code_id
               WHERE it.project_id = ? ORDER BY tc.id""", (project_id,)
        ).fetchall()

    def get_qualitative_summary(self, project_id):
        return self.connection.execute(
            """SELECT qc.theme, qc.code, qc.description, COUNT(tc.id) AS coded_excerpts
               FROM qualitative_codes qc
               LEFT JOIN transcript_codings tc ON tc.code_id = qc.id
               WHERE qc.project_id = ?
               GROUP BY qc.id ORDER BY qc.theme, qc.code""", (project_id,)
        ).fetchall()

    def record_qualitative_audit(self, project_id, action, entity, entity_id=None, details=None):
        self._require_project(project_id)
        self.connection.execute(
            """INSERT INTO qualitative_audit_log (project_id, action, entity, entity_id, details_json)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, str(action), str(entity), entity_id, json.dumps(details or {}, sort_keys=True)),
        )
        self.connection.commit()

    def get_qualitative_audit_log(self, project_id):
        return self.connection.execute(
            "SELECT * FROM qualitative_audit_log WHERE project_id = ? ORDER BY id", (project_id,)
        ).fetchall()

    def save_codebook_version(self, project_id):
        codes = [dict(row) for row in self.get_qualitative_codes(project_id)]
        current = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM qualitative_codebook_versions WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        version = int(current) + 1
        self.connection.execute(
            "INSERT INTO qualitative_codebook_versions (project_id, version, snapshot_json) VALUES (?, ?, ?)",
            (project_id, version, json.dumps(codes, sort_keys=True)),
        )
        self.connection.commit()
        self.record_qualitative_audit(project_id, "snapshot", "codebook", version, {"code_count": len(codes)})
        return version

    def get_codebook_versions(self, project_id):
        return self.connection.execute(
            "SELECT * FROM qualitative_codebook_versions WHERE project_id = ? ORDER BY version", (project_id,)
        ).fetchall()

    # =========================================================
    # PROJECTS
    # =========================================================

    def create_project(
        self,
        name,
        research_title="",
        researcher="",
        institution="",
        department="",
        significance_level=0.05,
        multiplicity_method="holm",
        owner_user_id=None,
    ):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Project name cannot be empty.")
        significance_level = float(significance_level)
        if not 0 < significance_level < 1:
            raise ValueError("Significance level must be between 0 and 1.")
        multiplicity_method = str(multiplicity_method or "holm").strip().lower()
        if multiplicity_method not in {"none", "bonferroni", "holm", "fdr_bh"}:
            raise ValueError("Multiplicity method must be none, bonferroni, holm, or fdr_bh.")

        cursor = self.connection.execute(
            """
            INSERT INTO projects (
                name,
                research_title,
                researcher,
                institution,
                department,
                significance_level,
                multiplicity_method,
                owner_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                research_title,
                researcher,
                institution,
                department,
                significance_level,
                multiplicity_method,
                owner_user_id,
            ),
        )

        self.connection.commit()

        return cursor.lastrowid

    def get_projects(self, owner_user_id=None):
        if owner_user_id is not None:
            return self.connection.execute(
                """
                SELECT * FROM projects
                WHERE owner_user_id = ?
                ORDER BY updated_at DESC
                """,
                (owner_user_id,),
            ).fetchall()
        cursor = self.connection.execute(
            """
            SELECT *
            FROM projects
            ORDER BY updated_at DESC
            """
        )

        return cursor.fetchall()

    def get_dashboard_metrics(self, owner_user_id=None):
        if owner_user_id is not None:
            row = self.connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM projects WHERE owner_user_id = ?) AS projects,
                    (SELECT COUNT(*) FROM analysis_runs r
                     JOIN projects p ON p.id = r.project_id
                     WHERE p.owner_user_id = ?) AS analyses,
                    (SELECT COUNT(*) FROM projects
                     WHERE owner_user_id = ? AND lower(trim(status)) = 'completed') AS completed
                """,
                (owner_user_id, owner_user_id, owner_user_id),
            ).fetchone()
            return {name: int(row[name]) for name in ("projects", "analyses", "completed")}
        row = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM projects) AS projects,
                (SELECT COUNT(*) FROM analysis_runs) AS analyses,
                (
                    SELECT COUNT(*)
                    FROM projects
                    WHERE lower(trim(status)) = 'completed'
                ) AS completed
            """
        ).fetchone()
        return {name: int(row[name]) for name in ("projects", "analyses", "completed")}

    def get_project(self, project_id):
        cursor = self.connection.execute(
            """
            SELECT *
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        )

        return cursor.fetchone()

    def get_project_for_user(self, project_id, owner_user_id):
        return self.connection.execute(
            """
            SELECT * FROM projects
            WHERE id = ? AND owner_user_id = ?
            """,
            (project_id, owner_user_id),
        ).fetchone()

    def create_web_user(self, email, password_hash):
        cursor = self.connection.execute(
            "INSERT INTO web_users (email, password_hash) VALUES (?, ?)",
            (str(email).strip().lower(), password_hash),
        )
        self.connection.commit()
        return cursor.lastrowid

    def get_web_user_by_email(self, email):
        return self.connection.execute(
            "SELECT * FROM web_users WHERE email = ? COLLATE NOCASE",
            (str(email).strip(),),
        ).fetchone()

    def get_web_user(self, user_id):
        return self.connection.execute(
            "SELECT id, email, created_at FROM web_users WHERE id = ?",
            (user_id,),
        ).fetchone()

    def create_web_session(self, token_hash, user_id, csrf_hash, expires_at):
        with self.connection:
            self.connection.execute(
                "DELETE FROM web_sessions WHERE expires_at <= CURRENT_TIMESTAMP"
            )
            self.connection.execute(
                """
                INSERT INTO web_sessions (token_hash, user_id, csrf_hash, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, user_id, csrf_hash, expires_at),
            )

    def get_web_session(self, token_hash):
        return self.connection.execute(
            """
            SELECT s.token_hash, s.user_id, s.csrf_hash, s.expires_at,
                   u.email
            FROM web_sessions s
            JOIN web_users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > CURRENT_TIMESTAMP
            """,
            (token_hash,),
        ).fetchone()

    def delete_web_session(self, token_hash):
        with self.connection:
            self.connection.execute(
                "DELETE FROM web_sessions WHERE token_hash = ?", (token_hash,)
            )

    def delete_project(self, project_id):
        datasets = self.get_project_datasets(project_id)
        with self.connection:
            self.connection.execute(
                """
                DELETE FROM projects
                WHERE id = ?
                """,
                (project_id,),
            )
        return datasets

    # =========================================================
    # DATASETS
    # =========================================================

    def create_dataset(
        self,
        project_id,
        filename,
        file_path,
        file_type,
        row_count,
        column_count,
        *,
        source_path=None,
        content_hash=None,
        revision_number=1,
        revision_of=None,
        is_active=True,
    ):
        source_path = source_path or file_path
        with self.connection:
            if is_active:
                self.connection.execute(
                    "UPDATE datasets SET is_active = 0 WHERE project_id = ?",
                    (project_id,),
                )
            cursor = self.connection.execute(
            """
            INSERT INTO datasets (
                project_id,
                filename,
                file_path,
                file_type,
                row_count,
                column_count,
                source_path,
                content_hash,
                revision_number,
                revision_of,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                filename,
                file_path,
                file_type,
                row_count,
                column_count,
                source_path,
                content_hash,
                revision_number,
                revision_of,
                int(bool(is_active)),
            ),
            )

        return cursor.lastrowid

    def create_dataset_revision(self, source_dataset_id, dataframe, *, label=None):
        source = self.get_dataset(source_dataset_id)
        if source is None:
            raise ValueError("Source dataset does not exist.")
        revision_number = int(source["revision_number"] or 1) + 1
        prefix = str(label or Path(source["filename"]).stem).strip() or "Dataset"
        revision_id = self.create_dataset_from_frame(
            source["project_id"],
            f"{prefix} (revision {revision_number}).csv",
            dataframe,
            source_path=source["source_path"] or source["file_path"],
            revision_number=revision_number,
            revision_of=source_dataset_id,
        )
        self.clone_dataset_links(source_dataset_id, revision_id)
        self.replace_dataset_variables(
            revision_id,
            [(str(column), str(dtype)) for column, dtype in dataframe.dtypes.items()],
        )
        return revision_id

    def create_dataset_from_frame(
        self,
        project_id,
        filename,
        dataframe,
        *,
        source_path=None,
        revision_number=1,
        revision_of=None,
    ):
        self._require_project(project_id)
        if dataframe is None or not hasattr(dataframe, "to_csv"):
            raise TypeError("A tabular dataframe is required to create a managed dataset.")

        snapshot_dir = self.database_dir / "datasets"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{uuid4().hex}.csv"
        dataframe.to_csv(snapshot_path, index=False)
        digest = hashlib.sha256()
        with snapshot_path.open("rb") as snapshot:
            for block in iter(lambda: snapshot.read(1024 * 1024), b""):
                digest.update(block)
        revision_id = self.create_dataset(
            project_id=project_id,
            filename=filename,
            file_path=str(snapshot_path),
            file_type="csv",
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            source_path=source_path or str(snapshot_path),
            content_hash=digest.hexdigest(),
            revision_number=revision_number,
            revision_of=revision_of,
        )
        self.replace_dataset_variables(
            revision_id,
            [(str(column), str(dtype)) for column, dtype in dataframe.dtypes.items()],
        )
        return revision_id

    def get_project_datasets(self, project_id):
        cursor = self.connection.execute(
            """
            SELECT *
            FROM datasets
            WHERE project_id = ?
            ORDER BY is_active DESC, imported_at DESC, id DESC
            """,
            (project_id,),
        )

        return cursor.fetchall()

    def get_active_dataset(self, project_id):
        return self.connection.execute(
            """
            SELECT * FROM datasets
            WHERE project_id = ? AND is_active = 1
            ORDER BY imported_at DESC, id DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()

    def set_active_dataset(self, project_id, dataset_id):
        dataset = self.get_dataset(dataset_id)
        if dataset is None or dataset["project_id"] != project_id:
            raise ValueError("Dataset does not belong to this project.")
        with self.connection:
            self.connection.execute(
                "UPDATE datasets SET is_active = 0 WHERE project_id = ?",
                (project_id,),
            )
            self.connection.execute(
                "UPDATE datasets SET is_active = 1 WHERE id = ?",
                (dataset_id,),
            )
        return True

    def get_dataset(self, dataset_id):
        cursor = self.connection.execute(
            """
            SELECT *
            FROM datasets
            WHERE id = ?
            """,
            (dataset_id,),
        )

        return cursor.fetchone()

    def delete_dataset(self, dataset_id):
        self.connection.execute(
            """
            DELETE FROM datasets
            WHERE id = ?
            """,
            (dataset_id,),
        )

        self.connection.commit()

    def replace_dataset_variables(self, dataset_id, variables):
        dataset = self.get_dataset(dataset_id)
        if dataset is None:
            raise ValueError("Dataset does not exist.")

        existing = {
            row["name"]: row
            for row in self.get_dataset_variables(dataset_id)
        }
        normalized = [
            (str(name), str(data_type), position, existing.get(str(name)))
            for position, (name, data_type) in enumerate(variables)
        ]
        with self.connection:
            self.connection.execute(
                "DELETE FROM dataset_variables WHERE dataset_id = ?",
                (dataset_id,),
            )
            self.connection.executemany(
                """
                INSERT INTO dataset_variables (
                    dataset_id, name, data_type, position,
                    label, measure, value_labels_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        dataset_id,
                        name,
                        data_type,
                        position,
                        old["label"] if old else name,
                        old["measure"] if old else "",
                        old["value_labels_json"] if old else "{}",
                    )
                    for name, data_type, position, old in normalized
                ],
            )

    def update_variable_metadata(
        self, dataset_id, variable_name, label, measure, value_labels
    ):
        if self.get_dataset(dataset_id) is None:
            raise ValueError("Dataset does not exist.")
        if self.connection.execute(
            "SELECT 1 FROM dataset_variables WHERE dataset_id = ? AND name = ?",
            (dataset_id, variable_name),
        ).fetchone() is None:
            raise ValueError("Variable does not exist in the selected dataset.")
        with self.connection:
            self.connection.execute(
                """
                UPDATE dataset_variables
                SET label = ?, measure = ?, value_labels_json = ?
                WHERE dataset_id = ? AND name = ?
                """,
                (
                    str(label or variable_name).strip(),
                    str(measure or "").strip().lower(),
                    json.dumps(value_labels or {}, sort_keys=True),
                    dataset_id,
                    variable_name,
                ),
            )

    def clone_dataset_links(self, source_dataset_id, target_dataset_id):
        """Copy variable metadata and question links to a new revision."""
        variables = self.get_dataset_variables(source_dataset_id)
        self.replace_dataset_variables(
            target_dataset_id,
            [(row["name"], row["data_type"]) for row in variables],
        )
        for row in variables:
            self.update_variable_metadata(
                target_dataset_id,
                row["name"],
                row["label"],
                row["measure"],
                json.loads(row["value_labels_json"] or "{}"),
            )
        links = self.connection.execute(
            """
            SELECT project_id, research_question_id, variable_name, role
            FROM research_question_variables
            WHERE dataset_id = ?
            """,
            (source_dataset_id,),
        ).fetchall()
        with self.connection:
            for link in links:
                self.connection.execute(
                    """
                    INSERT OR REPLACE INTO research_question_variables (
                        project_id, research_question_id, dataset_id,
                        variable_name, role
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        link["project_id"],
                        link["research_question_id"],
                        target_dataset_id,
                        link["variable_name"],
                        link["role"],
                    ),
                )
    def get_dataset_variables(self, dataset_id):
        return self.connection.execute(
            """
            SELECT *
            FROM dataset_variables
            WHERE dataset_id = ?
            ORDER BY position
            """,
            (dataset_id,),
        ).fetchall()

    # =========================================================
    # RESEARCH QUESTIONS
    # =========================================================

    def create_research_question(
        self,
        project_id,
        question,
        code=None,
        position=None,
        design_type="descriptive",
        proposed_test="",
    ):
        question = self._validated_question_text(question)
        design_type = self._validated_design_type(design_type)

        if self.connection.execute(
            "SELECT 1 FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone() is None:
            raise ValueError("Project does not exist.")

        duplicate = self.connection.execute(
            """
            SELECT 1
            FROM research_questions
            WHERE project_id = ? AND lower(trim(question)) = lower(?)
            """,
            (project_id, question),
        ).fetchone()
        if duplicate is not None:
            raise ValueError("A research question with that text already exists.")

        existing = self.get_project_research_questions(project_id)
        next_position = len(existing) + 1
        position = next_position if position is None else int(position)
        position = max(1, min(position, next_position))

        if code is None or not str(code).strip():
            existing_codes = {
                row["code"].strip().casefold()
                for row in existing
            }
            suffix = 1
            while f"rq{suffix}" in existing_codes:
                suffix += 1
            code = f"RQ{suffix}"
        else:
            code = str(code).strip()

        self._validate_question_code(project_id, code)

        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO research_questions (
                    project_id, question, code, position,
                    design_type, proposed_test
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    question,
                    code,
                    next_position,
                    design_type,
                    str(proposed_test or "").strip(),
                ),
            )
            question_id = cursor.lastrowid
            ordered_ids = [row["id"] for row in existing]
            ordered_ids.insert(position - 1, question_id)
            self._write_question_order(project_id, ordered_ids)

        return question_id

    def get_project_research_questions(self, project_id):
        cursor = self.connection.execute(
            """
            SELECT *
            FROM research_questions
            WHERE project_id = ?
            ORDER BY position, id
            """,
            (project_id,),
        )

        return cursor.fetchall()

    def get_research_question(self, project_id, question_id):
        cursor = self.connection.execute(
            """
            SELECT *
            FROM research_questions
            WHERE project_id = ? AND id = ?
            """,
            (project_id, question_id),
        )

        return cursor.fetchone()

    def update_research_question(
        self,
        project_id,
        question_id,
        question,
        code=None,
        position=None,
        design_type=None,
        proposed_test=None,
    ):
        question = self._validated_question_text(question)
        current = self.get_research_question(project_id, question_id)
        if current is None:
            return False

        duplicate = self.connection.execute(
            """
            SELECT 1
            FROM research_questions
            WHERE project_id = ?
                AND id != ?
                AND lower(trim(question)) = lower(?)
            """,
            (project_id, question_id, question),
        ).fetchone()
        if duplicate is not None:
            raise ValueError("A research question with that text already exists.")

        code = current["code"] if code is None else str(code).strip()
        if not code:
            raise ValueError("Question code cannot be empty.")
        self._validate_question_code(project_id, code, question_id)

        design_type = current["design_type"] if design_type is None else (
            self._validated_design_type(design_type)
        )
        proposed_test = (
            current["proposed_test"]
            if proposed_test is None
            else str(proposed_test).strip()
        )

        with self.connection:
            self.connection.execute(
                """
                UPDATE research_questions
                SET question = ?, code = ?, design_type = ?, proposed_test = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE project_id = ? AND id = ?
                """,
                (
                    question,
                    code,
                    design_type,
                    proposed_test,
                    project_id,
                    question_id,
                ),
            )
            if position is not None:
                ordered_ids = [
                    row["id"]
                    for row in self.get_project_research_questions(project_id)
                ]
                ordered_ids.remove(question_id)
                position = max(1, min(int(position), len(ordered_ids) + 1))
                ordered_ids.insert(position - 1, question_id)
                self._write_question_order(project_id, ordered_ids)

        return True

    @staticmethod
    def _validated_question_text(question):
        question = str(question or "").strip()
        if not question:
            raise ValueError("Research question cannot be empty.")
        return question

    @staticmethod
    def _validated_design_type(design_type):
        allowed = {"descriptive", "comparison", "association", "prediction"}
        design_type = str(design_type).strip().lower()
        if design_type not in allowed:
            raise ValueError("Unsupported research design type.")
        return design_type

    def _validate_question_code(self, project_id, code, exclude_id=None):
        query = """
            SELECT 1
            FROM research_questions
            WHERE project_id = ? AND lower(trim(code)) = lower(?)
        """
        parameters = [project_id, code]
        if exclude_id is not None:
            query += " AND id != ?"
            parameters.append(exclude_id)
        if self.connection.execute(query, parameters).fetchone() is not None:
            raise ValueError("Question code already exists in this project.")

    def _write_question_order(self, project_id, ordered_ids):
        current_ids = {
            row["id"]
            for row in self.connection.execute(
                "SELECT id FROM research_questions WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        }
        if len(ordered_ids) != len(current_ids) or set(ordered_ids) != current_ids:
            raise ValueError("Ordering must include each project question once.")

        self.connection.executemany(
            "UPDATE research_questions SET position = ? WHERE project_id = ? AND id = ?",
            [
                (position, project_id, question_id)
                for position, question_id in enumerate(ordered_ids, start=1)
            ],
        )

    def reorder_project_research_questions(self, project_id, ordered_ids):
        with self.connection:
            self._write_question_order(project_id, list(ordered_ids))

    def delete_research_question(self, project_id, question_id):
        cursor = self.connection.execute(
            """
            DELETE FROM research_questions
            WHERE project_id = ? AND id = ?
            """,
            (project_id, question_id),
        )

        self.connection.commit()

        return cursor.rowcount > 0

    # =========================================================
    # HYPOTHESES
    # =========================================================

    def create_hypothesis(
        self,
        project_id,
        question_id,
        hypothesis=None,
        *,
        null_hypothesis=None,
        alternative_hypothesis=None,
        directionality="non-directional",
    ):
        if null_hypothesis is None:
            null_hypothesis = ""
        if alternative_hypothesis is None:
            alternative_hypothesis = hypothesis or ""
        directionality = self._validated_directionality(directionality)
        null_hypothesis = str(null_hypothesis).strip()
        alternative_hypothesis = str(alternative_hypothesis).strip()
        cursor = self.connection.execute(
            """
            INSERT INTO hypotheses (
                research_question_id, hypothesis,
                null_hypothesis, alternative_hypothesis, directionality
            )
            SELECT id, ?, ?, ?, ?
            FROM research_questions
            WHERE project_id = ? AND id = ?
            """,
            (
                alternative_hypothesis,
                null_hypothesis,
                alternative_hypothesis,
                directionality,
                project_id,
                question_id,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError(
                "Research question does not belong to this project."
            )

        self.connection.commit()

        return cursor.lastrowid

    def get_research_question_hypotheses(
        self,
        project_id,
        question_id,
    ):
        cursor = self.connection.execute(
            """
            SELECT hypotheses.*
            FROM hypotheses
            JOIN research_questions
                ON research_questions.id = hypotheses.research_question_id
            WHERE research_questions.project_id = ?
                AND research_questions.id = ?
            ORDER BY hypotheses.created_at, hypotheses.id
            """,
            (project_id, question_id),
        )

        return cursor.fetchall()

    def get_hypothesis(self, project_id, question_id, hypothesis_id):
        cursor = self.connection.execute(
            """
            SELECT hypotheses.*
            FROM hypotheses
            JOIN research_questions
                ON research_questions.id = hypotheses.research_question_id
            WHERE research_questions.project_id = ?
                AND research_questions.id = ?
                AND hypotheses.id = ?
            """,
            (project_id, question_id, hypothesis_id),
        )

        return cursor.fetchone()

    def update_hypothesis(
        self,
        project_id,
        question_id,
        hypothesis_id,
        hypothesis=None,
        *,
        null_hypothesis=None,
        alternative_hypothesis=None,
        directionality=None,
    ):
        current = self.get_hypothesis(project_id, question_id, hypothesis_id)
        if current is None:
            return False

        if alternative_hypothesis is None:
            alternative_hypothesis = (
                hypothesis
                if hypothesis is not None
                else current["alternative_hypothesis"]
            )
        if null_hypothesis is None:
            null_hypothesis = current["null_hypothesis"]
        if directionality is None:
            directionality = current["directionality"]
        directionality = self._validated_directionality(directionality)

        cursor = self.connection.execute(
            """
            UPDATE hypotheses
            SET hypothesis = ?, null_hypothesis = ?,
                alternative_hypothesis = ?, directionality = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
                AND research_question_id = ?
                AND research_question_id IN (
                    SELECT id
                    FROM research_questions
                    WHERE project_id = ?
                )
            """,
            (
                str(alternative_hypothesis).strip(),
                str(null_hypothesis).strip(),
                str(alternative_hypothesis).strip(),
                directionality,
                hypothesis_id,
                question_id,
                project_id,
            ),
        )

        self.connection.commit()

        return cursor.rowcount > 0

    @staticmethod
    def _validated_directionality(directionality):
        allowed = {"directional", "non-directional"}
        directionality = str(directionality).strip().lower()
        if directionality not in allowed:
            raise ValueError("Directionality must be directional or non-directional.")
        return directionality

    def delete_hypothesis(self, project_id, question_id, hypothesis_id):
        cursor = self.connection.execute(
            """
            DELETE FROM hypotheses
            WHERE id = ?
                AND research_question_id = ?
                AND research_question_id IN (
                    SELECT id
                    FROM research_questions
                    WHERE project_id = ?
                )
            """,
            (hypothesis_id, question_id, project_id),
        )

        self.connection.commit()

        return cursor.rowcount > 0

    # =========================================================
    # QUESTION VARIABLES AND ANALYSIS RESULTS
    # =========================================================

    def set_question_variable(
        self,
        project_id,
        question_id,
        dataset_id,
        variable_name,
        role,
    ):
        allowed_roles = {"outcome", "predictor", "grouping"}
        role = str(role).strip().lower()
        variable_name = str(variable_name)
        if role not in allowed_roles:
            raise ValueError("Unsupported variable role.")

        ownership = self.connection.execute(
            """
            SELECT 1
            FROM research_questions
            JOIN datasets ON datasets.project_id = research_questions.project_id
            WHERE research_questions.id = ?
                AND research_questions.project_id = ?
                AND datasets.id = ?
            """,
            (question_id, project_id, dataset_id),
        ).fetchone()
        if ownership is None:
            raise ValueError("Question and dataset must belong to this project.")

        exists = self.connection.execute(
            """
            SELECT 1 FROM dataset_variables
            WHERE dataset_id = ? AND name = ?
            """,
            (dataset_id, variable_name),
        ).fetchone()
        if exists is None:
            raise ValueError("Variable does not exist in the selected dataset.")

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO research_question_variables (
                    project_id, research_question_id, dataset_id,
                    variable_name, role
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (research_question_id, dataset_id, variable_name)
                DO UPDATE SET role = excluded.role
                """,
                (project_id, question_id, dataset_id, variable_name, role),
            )
        return self.connection.execute(
            """
            SELECT id
            FROM research_question_variables
            WHERE research_question_id = ?
                AND dataset_id = ? AND variable_name = ?
            """,
            (question_id, dataset_id, variable_name),
        ).fetchone()[0]

    def get_question_variables(self, project_id, question_id):
        return self.connection.execute(
            """
            SELECT links.*, datasets.filename,
                CASE WHEN variables.name IS NULL THEN 0 ELSE 1 END AS variable_exists
            FROM research_question_variables AS links
            JOIN datasets ON datasets.id = links.dataset_id
            LEFT JOIN dataset_variables AS variables
                ON variables.dataset_id = links.dataset_id
                AND variables.name = links.variable_name
            WHERE links.project_id = ? AND links.research_question_id = ?
            ORDER BY links.id
            """,
            (project_id, question_id),
        ).fetchall()

    def delete_question_variable(self, project_id, question_id, variable_id):
        cursor = self.connection.execute(
            """
            DELETE FROM research_question_variables
            WHERE project_id = ? AND research_question_id = ? AND id = ?
            """,
            (project_id, question_id, variable_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def create_analysis_result(
        self,
        project_id,
        question_id,
        actual_test,
        result_summary="",
    ):
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_results (
                project_id, research_question_id, actual_test, result_summary
            )
            SELECT project_id, id, ?, ?
            FROM research_questions
            WHERE project_id = ? AND id = ?
            """,
            (actual_test, result_summary, project_id, question_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Research question does not belong to this project.")
        self.connection.commit()
        return cursor.lastrowid

    def get_question_analysis_results(self, project_id, question_id):
        return self.connection.execute(
            """
            SELECT * FROM analysis_results
            WHERE project_id = ? AND research_question_id = ?
            ORDER BY created_at, id
            """,
            (project_id, question_id),
        ).fetchall()

    def create_analysis_run(
        self,
        project_id,
        question_id,
        hypothesis_id,
        dataset_id,
        dataset_signature,
        actual_test,
        settings,
        result,
        hypothesis_decision=None,
    ):
        question = self.get_research_question(project_id, question_id)
        dataset = self.get_dataset(dataset_id)
        if question is None:
            raise ValueError("Research question does not belong to this project.")
        if dataset is None or dataset["project_id"] != project_id:
            raise ValueError("Dataset does not belong to this project.")
        if hypothesis_id is not None and self.get_hypothesis(
            project_id,
            question_id,
            hypothesis_id,
        ) is None:
            raise ValueError("Hypothesis does not belong to this question/project.")

        cursor = self.connection.execute(
            """
            INSERT INTO analysis_runs (
                project_id, research_question_id, hypothesis_id, dataset_id,
                dataset_signature, actual_test, settings_json, result_json,
                hypothesis_decision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                question_id,
                hypothesis_id,
                dataset_id,
                dataset_signature,
                actual_test,
                json.dumps(settings, sort_keys=True, allow_nan=False),
                json.dumps(result, sort_keys=True, allow_nan=False),
                hypothesis_decision,
            ),
        )
        self.connection.commit()
        return cursor.lastrowid

    def get_question_analysis_runs(self, project_id, question_id):
        return self.connection.execute(
            """
            SELECT * FROM analysis_runs
            WHERE project_id = ? AND research_question_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (project_id, question_id),
        ).fetchall()

    def get_project_analysis_runs(self, project_id):
        return self.connection.execute(
            """
            SELECT * FROM analysis_runs
            WHERE project_id = ?
            ORDER BY created_at, id
            """,
            (project_id,),
        ).fetchall()

    def update_analysis_run_result(self, run_id, result, hypothesis_decision):
        self.connection.execute(
            """
            UPDATE analysis_runs
            SET result_json = ?, hypothesis_decision = ?
            WHERE id = ?
            """,
            (json.dumps(result, sort_keys=True, allow_nan=False), hypothesis_decision, run_id),
        )
        self.connection.commit()

    def save_time_series_analysis(self, project_id, dataset_id, metadata, result):
        self._require_project(project_id)
        if dataset_id is not None:
            dataset = self.get_dataset(dataset_id)
            if dataset is None or dataset["project_id"] != project_id:
                raise ValueError("The time-series dataset must belong to the selected project.")
        if result.get("analysis_type") in {"exogenous", "multivariate"}:
            stored_result = result
        else:
            stored_result = {
                "date_column": result["date_column"],
                "value_column": result["value_column"],
                "date_range": [result["start_date"], result["end_date"]],
                "frequency": result["frequency_label"],
                "analysis_type": result.get("analysis_type", "univariate"),
                "roles": result.get("roles", {}),
                "recommendations": result.get("recommendations", {}),
                "preprocessing_operations": result.get("preprocessing_operations", []),
                "model_specification": result["model_specification"],
                "stationarity_scope": result["stationarity_scope"],
                "stationarity_tests": result["stationarity_tests"],
                "stationarity_assessment": result["stationarity_assessment"],
                "stationarity_interpretations": result["stationarity_interpretations"],
                "academic_interpretation": result["academic_interpretation"],
                "academic_interpretations": result["academic_interpretations"],
                "model_evaluation_design": result["model_evaluation_design"],
                "time_series_plot": result["time_series_plot"],
                "trend_values": result["trend_values"],
                "fitted_values": result["fitted_values"],
                "fitted_index": result["fitted_index"],
                "correlogram": result["correlogram"],
                "residual_plot": result["residual_plot"],
                "seasonal_components": result["seasonal_components"],
                "decomposition_plot": result.get("decomposition_plot", {}),
                "preprocessing_operations": result.get("preprocessing_operations", []),
                "evaluation": result["evaluation"],
                "model_comparison": result["model_comparison"],
                "prediction_interval": result["prediction_interval"],
                "forecast": [
                    {
                        "period": period,
                        "value": value,
                        "lower": lower,
                        "upper": upper,
                    }
                    for period, value, lower, upper in zip(
                        result["forecast_index"],
                        result["forecast_values"],
                        result["forecast_lower"],
                        result["forecast_upper"],
                    )
                ],
                "diagnostics": result["diagnostics"],
                "diagnostic_warnings": result["diagnostic_warnings"],
                "convergence_status": result["convergence_status"],
                "warnings": result["validation"]["issues"],
            }
        fields = (
            "data_source",
            "indicator_name",
            "methodology",
            "source_url",
            "units",
            "downloaded_date",
        )
        values = [str(metadata.get(field, "") or "").strip() for field in fields]
        result_json = json.dumps(stored_result, sort_keys=True, allow_nan=False)
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO time_series_analyses (
                    project_id, dataset_id, data_source, indicator_name,
                    methodology, source_url, units, downloaded_date, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, dataset_id, *values, result_json),
            )
        return cursor.lastrowid

    def get_project_time_series_analyses(self, project_id):
        rows = self.connection.execute(
            """
            SELECT * FROM time_series_analyses
            WHERE project_id = ?
            ORDER BY created_at, id
            """,
            (project_id,),
        ).fetchall()
        analyses = []
        for row in rows:
            analysis = dict(row)
            try:
                analysis["result"] = json.loads(analysis.pop("result_json"))
            except (TypeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Saved time-series analysis {analysis['id']} is corrupted."
                ) from error
            analyses.append(analysis)
        return analyses

    @staticmethod
    def decode_analysis_run(row):
        if row is None:
            return None
        result = dict(row)
        try:
            result["settings"] = json.loads(result.pop("settings_json"))
            result["result"] = json.loads(result.pop("result_json"))
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(
                "Saved analysis data is corrupted and cannot be displayed."
            ) from error
        return result

    def backup(self, destination=None):
        """Create a consistent SQLite backup and return its path."""
        destination = Path(destination) if destination else self.database_path.with_name(
            f"{self.database_path.stem}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.bak"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup_connection = sqlite3.connect(destination)
        try:
            with backup_connection:
                self.connection.backup(backup_connection)
        finally:
            backup_connection.close()
        return destination

    def integrity_check(self):
        return self.connection.execute("PRAGMA integrity_check").fetchone()[0]

    # =========================================================
    # CLOSE DATABASE
    # =========================================================

    def close(self):
        self.connection.close()
