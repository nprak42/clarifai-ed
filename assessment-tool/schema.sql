-- Clarifai — Postgres schema
-- Two schemas: assessment (assessment tool) and tutor (socratic tutor)
-- Run once against the clarifai database:
--   psql $DATABASE_URL -f schema.sql

CREATE SCHEMA IF NOT EXISTS assessment;
CREATE SCHEMA IF NOT EXISTS tutor;

-- ===========================================================================
-- ASSESSMENT SCHEMA
-- ===========================================================================

CREATE TABLE IF NOT EXISTS assessment.tests (
    test_id             TEXT PRIMARY KEY,
    subject             TEXT NOT NULL,
    grade               INTEGER NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT,
    total_questions     INTEGER NOT NULL,
    estimated_time_minutes INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assessment.misconceptions (
    misconception_id        TEXT PRIMARY KEY,
    concept                 TEXT NOT NULL,
    subject                 TEXT NOT NULL,
    misconception_name      TEXT NOT NULL,
    explanation             TEXT NOT NULL,
    why_students_think_this TEXT,
    severity                TEXT NOT NULL,
    intervention_priority   TEXT NOT NULL,
    grade8_impact           TEXT,
    root_cause              TEXT
);

CREATE TABLE IF NOT EXISTS assessment.questions (
    question_id             TEXT PRIMARY KEY,
    test_id                 TEXT NOT NULL REFERENCES assessment.tests(test_id),
    question_order          INTEGER NOT NULL,
    question_text           TEXT NOT NULL,
    image_path              TEXT,
    image_description       TEXT,
    concept                 TEXT NOT NULL,
    question_type           TEXT NOT NULL,
    tier                    TEXT,
    difficulty              TEXT NOT NULL,
    requires_multiple_steps BOOLEAN DEFAULT FALSE,
    critical_question       BOOLEAN DEFAULT FALSE,
    teaching_note           TEXT
);

CREATE TABLE IF NOT EXISTS assessment.options (
    option_id           TEXT PRIMARY KEY,
    question_id         TEXT NOT NULL REFERENCES assessment.questions(question_id),
    option_letter       TEXT NOT NULL,
    option_text         TEXT NOT NULL,
    is_correct          BOOLEAN NOT NULL,
    explanation         TEXT,
    misconception_id    TEXT REFERENCES assessment.misconceptions(misconception_id),
    diagnostic_note     TEXT,
    severity            TEXT
);

CREATE TABLE IF NOT EXISTS assessment.interventions (
    intervention_id         TEXT PRIMARY KEY,
    misconception_id        TEXT NOT NULL REFERENCES assessment.misconceptions(misconception_id),
    intervention_type       TEXT NOT NULL,
    intervention_focus      TEXT NOT NULL,
    estimated_time_minutes  INTEGER,
    materials_needed        TEXT,
    activity_outline        TEXT,
    llm_generated           BOOLEAN DEFAULT FALSE,
    human_reviewed          BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS assessment.performance_patterns (
    pattern_id                      TEXT PRIMARY KEY,
    pattern_name                    TEXT NOT NULL,
    description                     TEXT NOT NULL,
    subject                         TEXT NOT NULL,
    detection_logic                 TEXT NOT NULL,
    diagnosis                       TEXT NOT NULL,
    grade8_risk                     TEXT NOT NULL,
    recommended_intervention_type   TEXT,
    symptoms                        TEXT,
    intervention_focus              TEXT,
    estimated_intervention_time     TEXT
);

CREATE TABLE IF NOT EXISTS assessment.test_sessions (
    session_id          TEXT PRIMARY KEY,
    test_id             TEXT NOT NULL REFERENCES assessment.tests(test_id),
    access_code         TEXT NOT NULL UNIQUE,
    created_by_teacher  TEXT,
    school_id           TEXT,
    school_name         TEXT,
    class_section       TEXT,
    session_date        DATE,
    status              TEXT DEFAULT 'active',
    students_completed  INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    teacher_notes       TEXT,
    closed_at           TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS assessment.student_responses (
    response_id             TEXT PRIMARY KEY,
    session_id              TEXT NOT NULL REFERENCES assessment.test_sessions(session_id),
    student_name            TEXT NOT NULL,
    question_id             TEXT NOT NULL REFERENCES assessment.questions(question_id),
    selected_option_id      TEXT NOT NULL REFERENCES assessment.options(option_id),
    time_spent_seconds      INTEGER,
    answered_at             TIMESTAMPTZ DEFAULT NOW(),
    is_correct              BOOLEAN,
    misconception_detected  TEXT
);

CREATE TABLE IF NOT EXISTS assessment.student_pattern_detections (
    detection_id        TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES assessment.test_sessions(session_id),
    student_name        TEXT NOT NULL,
    pattern_id          TEXT NOT NULL REFERENCES assessment.performance_patterns(pattern_id),
    questions_evidence  TEXT,
    tier1_score         REAL,
    tier2_score         REAL,
    tier3_score         REAL,
    detected_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (session_id, student_name, pattern_id)
);

-- One-time token minted by assessment, consumed by tutor on /start/<token>
CREATE TABLE IF NOT EXISTS assessment.tutor_sessions (
    token           TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES assessment.test_sessions(session_id),
    student_name    TEXT NOT NULL,
    subject         TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    used            BOOLEAN DEFAULT FALSE
);

-- INDEXES
CREATE INDEX IF NOT EXISTS idx_questions_test       ON assessment.questions(test_id);
CREATE INDEX IF NOT EXISTS idx_options_question     ON assessment.options(question_id);
CREATE INDEX IF NOT EXISTS idx_responses_session    ON assessment.student_responses(session_id);
CREATE INDEX IF NOT EXISTS idx_responses_student    ON assessment.student_responses(session_id, student_name);
CREATE INDEX IF NOT EXISTS idx_sessions_code        ON assessment.test_sessions(access_code);
CREATE INDEX IF NOT EXISTS idx_tutor_tokens_unused  ON assessment.tutor_sessions(token) WHERE used = FALSE;
CREATE INDEX IF NOT EXISTS idx_sessions_school      ON assessment.test_sessions(school_id);

-- ===========================================================================
-- TUTOR SCHEMA
-- ===========================================================================

-- Active + historical tutor chat sessions
CREATE TABLE IF NOT EXISTS tutor.sessions (
    session_id          TEXT PRIMARY KEY,
    student_name        TEXT,
    subject             TEXT,
    assigned_problem    TEXT,
    model_name          TEXT,
    system_prompt       TEXT,
    history             JSONB NOT NULL DEFAULT '[]',
    message_count       INTEGER DEFAULT 0,
    stuck_turns         INTEGER DEFAULT 0,
    worked_examples_used INTEGER DEFAULT 0,
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    -- links back to the assessment session that spawned this (nullable for standalone)
    assessment_session_id TEXT,
    school_id           TEXT
);

CREATE TABLE IF NOT EXISTS tutor.messages (
    id          SERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES tutor.sessions(session_id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    turn_index  INTEGER NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tutor_messages_session ON tutor.messages(session_id);
CREATE INDEX IF NOT EXISTS idx_tutor_sessions_school  ON tutor.sessions(school_id);
