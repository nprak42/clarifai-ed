"""
Persistent session and message store for the Socratic tutor (Postgres-backed).

Replaces both the old SQLite logs and the in-memory SESSIONS dict.
All active session state (history, stuck_turns, etc.) lives in tutor.sessions.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db import get_conn, put_conn, db_conn


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def create_session(session_id, student_name, subject, assigned_problem,
                   model_name, system_prompt):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tutor.sessions
                    (session_id, student_name, subject, assigned_problem,
                     model_name, system_prompt, history,
                     message_count, stuck_turns, worked_examples_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 0, 0, 0)
                ON CONFLICT (session_id) DO NOTHING
            """, (session_id, student_name, subject, assigned_problem,
                  model_name, system_prompt, json.dumps([])))


def get_session(session_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM tutor.sessions WHERE session_id = %s",
                (session_id,)
            )
            row = cur.fetchone()
        return dict(row) if row else None
    finally:
        put_conn(conn)


def end_session(session_id):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tutor.sessions SET ended_at = NOW() WHERE session_id = %s
            """, (session_id,))


# ---------------------------------------------------------------------------
# Message append — updates history JSONB and counters atomically
# ---------------------------------------------------------------------------

def append_message(session_id, role, content, turn_index):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tutor.sessions SET
                    history       = history || %s::jsonb,
                    message_count = message_count + %s
                WHERE session_id = %s
            """, (
                json.dumps([{'role': role, 'content': content}]),
                1 if role == 'user' else 0,
                session_id,
            ))
            cur.execute("""
                INSERT INTO tutor.messages (session_id, role, content, turn_index)
                VALUES (%s, %s, %s, %s)
            """, (session_id, role, content, turn_index))


# ---------------------------------------------------------------------------
# Stuck-turn state updates
# ---------------------------------------------------------------------------

def update_stuck_state(session_id, stuck_turns, worked_examples_used):
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tutor.sessions
                SET stuck_turns = %s, worked_examples_used = %s
                WHERE session_id = %s
            """, (stuck_turns, worked_examples_used, session_id))


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_history(session_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT history FROM tutor.sessions WHERE session_id = %s",
                (session_id,)
            )
            row = cur.fetchone()
        if not row:
            return []
        h = row['history']
        return h if isinstance(h, list) else json.loads(h)
    finally:
        put_conn(conn)


def get_all_sessions():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT session_id, student_name, subject, message_count, started_at, ended_at
                FROM tutor.sessions ORDER BY started_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)


def get_session_messages(session_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM tutor.messages
                WHERE session_id = %s ORDER BY turn_index, id
            """, (session_id,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)
