"""
Populate the assessment database from JSON data files.
Run once (or re-run safely - uses INSERT ... ON CONFLICT DO NOTHING).

Usage:
    DATABASE_URL=postgres://... python load_data.py
"""
import json
import os

from db import get_conn, put_conn

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


def load_json(filename):
    with open(os.path.join(DATA_DIR, filename)) as f:
        return json.load(f)


def load_misconceptions(cur, filename):
    data = load_json(filename)
    for m in data:
        cur.execute("""
            INSERT INTO assessment.misconceptions
                (misconception_id, concept, subject, misconception_name,
                 explanation, why_students_think_this, severity,
                 intervention_priority, grade8_impact, root_cause)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (misconception_id) DO NOTHING
        """, (
            m['misconception_id'], m['concept'], m['subject'],
            m['misconception_name'], m['explanation'],
            m.get('why_students_think_this'), m['severity'],
            m['intervention_priority'], m.get('grade8_impact'), m.get('root_cause'),
        ))
    print(f"  Loaded {len(data)} misconceptions from {filename}.")


def load_interventions(cur):
    data = load_json('interventions.json')
    for i in data:
        cur.execute("""
            INSERT INTO assessment.interventions
                (intervention_id, misconception_id, intervention_type,
                 intervention_focus, estimated_time_minutes, materials_needed,
                 activity_outline, llm_generated, human_reviewed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (intervention_id) DO NOTHING
        """, (
            i['intervention_id'], i['misconception_id'], i['intervention_type'],
            i['intervention_focus'], i.get('estimated_time_minutes'),
            i.get('materials_needed'), i.get('activity_outline'), False, False,
        ))
    print(f"  Loaded {len(data)} interventions.")


def load_patterns(cur, filename):
    data = load_json(filename)
    for p in data:
        cur.execute("""
            INSERT INTO assessment.performance_patterns
                (pattern_id, pattern_name, description, subject,
                 detection_logic, diagnosis, grade8_risk,
                 recommended_intervention_type, symptoms,
                 intervention_focus, estimated_intervention_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (pattern_id) DO NOTHING
        """, (
            p['pattern_id'], p['pattern_name'], p['description'], p['subject'],
            json.dumps(p['detection_logic']), p['diagnosis'], p['grade8_risk'],
            p.get('recommended_intervention_type'), json.dumps(p.get('symptoms', [])),
            p.get('intervention_focus'), p.get('estimated_intervention_time'),
        ))
    print(f"  Loaded {len(data)} patterns from {filename}.")


def load_tests(cur, filename):
    data = load_json(filename)
    for t in data:
        cur.execute("""
            INSERT INTO assessment.tests
                (test_id, subject, grade, title, description,
                 total_questions, estimated_time_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (test_id) DO NOTHING
        """, (
            t['test_id'], t['subject'], t['grade'], t['title'],
            t.get('description'), t['total_questions'], t.get('estimated_time_minutes'),
        ))
    print(f"  Loaded {len(data)} tests from {filename}.")


def load_questions_and_options(cur, filename):
    questions = load_json(filename)
    q_count = 0
    o_count = 0

    for q in questions:
        options = q.pop('options', [])
        cur.execute("""
            INSERT INTO assessment.questions
                (question_id, test_id, question_order, question_text,
                 image_path, image_description, concept, question_type,
                 tier, difficulty, requires_multiple_steps, critical_question,
                 teaching_note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (question_id) DO NOTHING
        """, (
            q['question_id'], q['test_id'], q['question_order'], q['question_text'],
            q.get('image_path'), q.get('image_description'), q['concept'],
            q['question_type'], q.get('tier'), q['difficulty'],
            bool(q.get('requires_multiple_steps')), bool(q.get('critical_question')),
            q.get('teaching_note'),
        ))
        q_count += 1

        for opt in options:
            cur.execute("""
                INSERT INTO assessment.options
                    (option_id, question_id, option_letter, option_text,
                     is_correct, explanation, misconception_id, diagnostic_note, severity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (option_id) DO NOTHING
            """, (
                opt['option_id'], q['question_id'], opt['option_letter'],
                opt['option_text'], bool(opt.get('is_correct')),
                opt.get('explanation'), opt.get('misconception_id'),
                opt.get('diagnostic_note'), opt.get('severity'),
            ))
            o_count += 1

    print(f"  Loaded {q_count} questions and {o_count} options from {filename}.")


def verify(cur):
    tables = [
        'assessment.tests', 'assessment.questions', 'assessment.options',
        'assessment.misconceptions', 'assessment.interventions',
        'assessment.performance_patterns',
    ]
    print("\nVerification:")
    for table in tables:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()['count']
        print(f"  {table}: {count} rows")

    cur.execute("""
        SELECT COUNT(*) FROM assessment.options
        WHERE misconception_id IS NOT NULL
          AND misconception_id NOT IN (SELECT misconception_id FROM assessment.misconceptions)
    """)
    orphan = cur.fetchone()['count']
    if orphan > 0:
        print(f"\n  WARNING: {orphan} options reference misconception_ids not in misconceptions table!")
        cur.execute("""
            SELECT DISTINCT misconception_id FROM assessment.options
            WHERE misconception_id IS NOT NULL
              AND misconception_id NOT IN (SELECT misconception_id FROM assessment.misconceptions)
        """)
        for r in cur.fetchall():
            print(f"    Missing: {r['misconception_id']}")
    else:
        print("  All option misconception references are valid.")


def main():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Disable FK checks during bulk load to avoid ordering issues
            cur.execute("SET session_replication_role = replica")

            print("Loading misconceptions:")
            load_misconceptions(cur, 'misconceptions_electricity_grade9.json')
            for subject in ('algebraic_expressions', 'linear_equations', 'quadrilaterals',
                            'ratios_proportions', 'simple_interest', 'triangles'):
                load_misconceptions(cur, f'misconceptions_{subject}_grade8.json')
            load_misconceptions(cur, 'misconceptions_trig_prerequisites_grade10.json')

            print("Loading interventions:")
            load_interventions(cur)

            print("Loading patterns:")
            load_patterns(cur, 'patterns_electricity_grade9.json')
            for subject in ('algebraic_expressions', 'linear_equations', 'quadrilaterals',
                            'ratios_proportions', 'simple_interest', 'triangles'):
                load_patterns(cur, f'patterns_{subject}_grade8.json')
            load_patterns(cur, 'patterns_trig_prerequisites_grade10.json')

            print("Loading tests:")
            load_tests(cur, 'tests.json')
            load_tests(cur, 'tests_new.json')

            print("Loading questions and options:")
            for fname in [
                'questions_electricity.json',
                'questions_ratios_proportions_grade8.json',
                'questions_simple_interest_grade8.json',
                'questions_quadrilaterals_grade8.json',
                'questions_triangles_grade8.json',
                'questions_linear_equations_grade8.json',
                'questions_algebraic_expressions_grade8.json',
                'questions_trig_prerequisites_grade10.json',
            ]:
                load_questions_and_options(cur, fname)

            cur.execute("SET session_replication_role = DEFAULT")
            verify(cur)

        conn.commit()
        print("\nDone! Database ready.")
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        put_conn(conn)


if __name__ == '__main__':
    main()
