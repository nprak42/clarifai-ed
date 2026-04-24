import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import uuid
from flask import g
from db import get_conn, put_conn


def get_db():
    if 'db' not in g:
        g.db = get_conn()
    return g.db


def close_db(e=None):
    conn = g.pop('db', None)
    if conn is not None:
        put_conn(conn)


def init_db():
    """Apply schema.sql against the configured database. Safe to re-run."""
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'schema.sql')
    conn = get_conn()
    try:
        with open(schema_path) as f:
            sql = f.read()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cur(conn=None):
    """Return a cursor on the request-scoped connection (or a provided one)."""
    return (conn or get_db()).cursor()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def get_tests():
    with _cur() as cur:
        cur.execute("SELECT * FROM assessment.tests ORDER BY grade, subject")
        return cur.fetchall()


def get_test_by_id(test_id):
    with _cur() as cur:
        cur.execute("SELECT * FROM assessment.tests WHERE test_id = %s", (test_id,))
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Questions & Options
# ---------------------------------------------------------------------------

def get_questions_for_test(test_id):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.questions WHERE test_id = %s ORDER BY question_order",
            (test_id,)
        )
        return cur.fetchall()


def get_options_for_question(question_id):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.options WHERE question_id = %s ORDER BY option_letter",
            (question_id,)
        )
        return cur.fetchall()


def get_all_options_for_test(test_id):
    """Bulk fetch all options for a test to avoid N+1 queries."""
    with _cur() as cur:
        cur.execute("""
            SELECT o.*
            FROM assessment.options o
            JOIN assessment.questions q ON o.question_id = q.question_id
            WHERE q.test_id = %s
            ORDER BY o.question_id, o.option_letter
        """, (test_id,))
        rows = cur.fetchall()

    grouped = {}
    for row in rows:
        qid = row['question_id']
        if qid not in grouped:
            grouped[qid] = []
        grouped[qid].append(dict(row))
    return grouped


def get_option_by_id(option_id):
    with _cur() as cur:
        cur.execute("SELECT * FROM assessment.options WHERE option_id = %s", (option_id,))
        return cur.fetchone()


def get_correct_option_for_question(question_id):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.options WHERE question_id = %s AND is_correct = TRUE LIMIT 1",
            (question_id,)
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(test_id, access_code, teacher_name, school_name, class_section, session_date):
    session_id = str(uuid.uuid4())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO assessment.test_sessions
                (session_id, test_id, access_code, created_by_teacher, school_name, class_section, session_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (session_id, test_id, access_code, teacher_name, school_name, class_section, session_date))
    conn.commit()
    return session_id


def get_session_by_code(access_code):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.test_sessions WHERE access_code = %s",
            (access_code.upper(),)
        )
        return cur.fetchone()


def get_recent_sessions(limit=20):
    with _cur() as cur:
        cur.execute("""
            SELECT ts.*, t.title, t.subject, t.grade
            FROM assessment.test_sessions ts
            JOIN assessment.tests t ON ts.test_id = t.test_id
            ORDER BY ts.created_at DESC
            LIMIT %s
        """, (limit,))
        return cur.fetchall()


def get_session_by_id(session_id):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.test_sessions WHERE session_id = %s",
            (session_id,)
        )
        return cur.fetchone()


def increment_students_completed(session_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE assessment.test_sessions SET students_completed = students_completed + 1 WHERE session_id = %s",
            (session_id,)
        )
    conn.commit()


def close_session(session_id, teacher_notes=None):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE assessment.test_sessions
            SET status = 'closed', closed_at = NOW(), teacher_notes = %s
            WHERE session_id = %s
        """, (teacher_notes, session_id))
    conn.commit()


def save_teacher_notes(session_id, teacher_notes):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE assessment.test_sessions SET teacher_notes = %s WHERE session_id = %s",
            (teacher_notes, session_id)
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Student Responses
# ---------------------------------------------------------------------------

def get_responses_for_student(session_id, student_name):
    with _cur() as cur:
        cur.execute("""
            SELECT sr.*, o.is_correct as opt_correct, o.misconception_id as opt_misconception
            FROM assessment.student_responses sr
            JOIN assessment.options o ON sr.selected_option_id = o.option_id
            WHERE sr.session_id = %s AND sr.student_name = %s
            ORDER BY sr.answered_at
        """, (session_id, student_name))
        return cur.fetchall()


def get_responses_for_session(session_id):
    with _cur() as cur:
        cur.execute("""
            SELECT
                sr.response_id,
                sr.student_name,
                sr.question_id,
                sr.selected_option_id,
                sr.time_spent_seconds,
                sr.is_correct,
                sr.misconception_detected,
                q.concept,
                q.question_type,
                q.tier,
                q.critical_question,
                o.option_letter,
                o.option_text,
                o.misconception_id as option_misconception_id,
                o.severity
            FROM assessment.student_responses sr
            JOIN assessment.questions q ON sr.question_id = q.question_id
            JOIN assessment.options o ON sr.selected_option_id = o.option_id
            WHERE sr.session_id = %s
            ORDER BY sr.student_name, q.question_order
        """, (session_id,))
        return cur.fetchall()


def save_response(session_id, student_name, question_id, option_id, time_spent, is_correct, misconception_id):
    response_id = str(uuid.uuid4())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO assessment.student_responses
                (response_id, session_id, student_name, question_id, selected_option_id,
                 time_spent_seconds, is_correct, misconception_detected)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (response_id) DO UPDATE SET
                selected_option_id  = EXCLUDED.selected_option_id,
                time_spent_seconds  = EXCLUDED.time_spent_seconds,
                is_correct          = EXCLUDED.is_correct,
                misconception_detected = EXCLUDED.misconception_detected
        """, (response_id, session_id, student_name, question_id, option_id,
              time_spent, is_correct, misconception_id))
    conn.commit()
    return response_id


def get_student_results(session_id, student_name):
    with _cur() as cur:
        cur.execute("""
            SELECT
                q.question_id,
                q.question_order,
                q.question_text,
                q.concept,
                sr.is_correct,
                sr.time_spent_seconds,
                sel.option_letter   AS selected_letter,
                sel.option_text     AS selected_text,
                sel.explanation     AS selected_explanation,
                cor.option_letter   AS correct_letter,
                cor.option_text     AS correct_text,
                cor.explanation     AS correct_explanation,
                m.misconception_name,
                m.explanation       AS misconception_explanation
            FROM assessment.student_responses sr
            JOIN assessment.questions q ON sr.question_id = q.question_id
            JOIN assessment.options sel ON sr.selected_option_id = sel.option_id
            JOIN assessment.options cor ON cor.question_id = q.question_id AND cor.is_correct = TRUE
            LEFT JOIN assessment.misconceptions m ON sel.misconception_id = m.misconception_id
            WHERE sr.session_id = %s AND sr.student_name = %s
            ORDER BY q.question_order
        """, (session_id, student_name))
        return cur.fetchall()


def get_answered_question_ids(session_id, student_name):
    with _cur() as cur:
        cur.execute("""
            SELECT question_id FROM assessment.student_responses
            WHERE session_id = %s AND student_name = %s
        """, (session_id, student_name))
        return {r['question_id'] for r in cur.fetchall()}


def get_distinct_students(session_id):
    with _cur() as cur:
        cur.execute("""
            SELECT DISTINCT student_name FROM assessment.student_responses
            WHERE session_id = %s
            ORDER BY student_name
        """, (session_id,))
        return [r['student_name'] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Misconceptions & Interventions
# ---------------------------------------------------------------------------

def get_all_misconceptions():
    with _cur() as cur:
        cur.execute("SELECT * FROM assessment.misconceptions")
        return cur.fetchall()


def get_misconception_by_id(misconception_id):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.misconceptions WHERE misconception_id = %s",
            (misconception_id,)
        )
        return cur.fetchone()


def get_interventions_for_misconception(misconception_id):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.interventions WHERE misconception_id = %s",
            (misconception_id,)
        )
        return cur.fetchall()


def get_all_interventions():
    with _cur() as cur:
        cur.execute("SELECT * FROM assessment.interventions")
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Performance Patterns
# ---------------------------------------------------------------------------

def get_patterns_for_subject(subject):
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM assessment.performance_patterns WHERE subject = %s",
            (subject,)
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Tutor token handoff
# ---------------------------------------------------------------------------

def create_tutor_token(session_id, student_name, subject):
    token = str(uuid.uuid4())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO assessment.tutor_sessions (token, session_id, student_name, subject)
            VALUES (%s, %s, %s, %s)
        """, (token, session_id, student_name, subject))
    conn.commit()
    return token


def get_and_consume_tutor_token(token):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE assessment.tutor_sessions
            SET used = TRUE
            WHERE token = %s AND used = FALSE
            RETURNING *
        """, (token,))
        row = cur.fetchone()
    conn.commit()
    return row


# ---------------------------------------------------------------------------
# Pattern detections
# ---------------------------------------------------------------------------

def save_pattern_detection(session_id, student_name, pattern_id, evidence, t1, t2, t3):
    detection_id = str(uuid.uuid4())
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO assessment.student_pattern_detections
                (detection_id, session_id, student_name, pattern_id,
                 questions_evidence, tier1_score, tier2_score, tier3_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id, student_name, pattern_id) DO UPDATE SET
                questions_evidence  = EXCLUDED.questions_evidence,
                tier1_score         = EXCLUDED.tier1_score,
                tier2_score         = EXCLUDED.tier2_score,
                tier3_score         = EXCLUDED.tier3_score
        """, (detection_id, session_id, student_name, pattern_id,
              evidence, t1, t2, t3))
    conn.commit()
