"""
Simulate a class of students taking a test and populate the database.

Usage:
    python simulate_session.py --test lines_angles_grade7 --students 30
    python simulate_session.py --test circles_grade7 --students 25

Each student is assigned a profile that biases their wrong-answer choices,
producing realistic misconception patterns the dashboard can detect.
"""
import argparse
import random
import sqlite3
import uuid
import os
from datetime import date

DATABASE = os.path.join(os.path.dirname(__file__), 'assessment.db')

# ---------------------------------------------------------------------------
# Student profiles — each profile has a set of misconception_ids it's likely
# to exhibit, and a base accuracy. The simulation biases wrong answers toward
# those misconceptions when available.
# ---------------------------------------------------------------------------

PROFILES = {
    # Lines & Angles profiles
    'lines_angles_grade7': [
        {
            'name': 'supp_comp_confuser',
            'description': 'Mixes up supplementary and complementary',
            'target_misconceptions': ['la_supp_vs_comp_confusion', 'la_comp_means_equal'],
            'base_accuracy': 0.45,
            'count': 5,
        },
        {
            'name': 'parallel_overgeneraliser',
            'description': 'Thinks all parallel-line angle pairs are equal',
            'target_misconceptions': ['la_all_parallel_angles_equal', 'la_parallel_means_all_same', 'la_alternate_supplementary'],
            'base_accuracy': 0.40,
            'count': 6,
        },
        {
            'name': 'vertical_angle_confused',
            'description': 'Misunderstands vertical angles — thinks they are supplementary or up/down',
            'target_misconceptions': ['la_vertical_angles_supplementary', 'la_vertical_means_up_down', 'la_vertical_not_recognised'],
            'base_accuracy': 0.50,
            'count': 5,
        },
        {
            'name': 'triangle_sum_procedural',
            'description': 'Applies triangle sum mechanically but not conceptually',
            'target_misconceptions': ['la_triangle_sum_360', 'la_triangle_sum_arithmetic', 'la_triangle_sum_without_reasoning'],
            'base_accuracy': 0.55,
            'count': 5,
        },
        {
            'name': 'strong_student',
            'description': 'Mostly correct, minor errors only',
            'target_misconceptions': [],
            'base_accuracy': 0.85,
            'count': 5,
        },
        {
            'name': 'struggling_all_around',
            'description': 'Low accuracy across the board',
            'target_misconceptions': ['la_supp_means_360', 'la_linear_pair_equal', 'la_visual_justification_sufficient'],
            'base_accuracy': 0.25,
            'count': 4,
        },
    ],

    # Circles profiles
    'circles_grade7': [
        {
            'name': 'formula_confuser',
            'description': 'Mixes up area and circumference formulas',
            'target_misconceptions': ['circ_area_uses_diameter', 'circ_circumference_uses_radius_not_diameter', 'circ_formula_swap'],
            'base_accuracy': 0.40,
            'count': 6,
        },
        {
            'name': 'radius_diameter_flipper',
            'description': 'Inverts radius and diameter',
            'target_misconceptions': ['circ_radius_equals_diameter', 'circ_diameter_half_radius'],
            'base_accuracy': 0.50,
            'count': 5,
        },
        {
            'name': 'linear_scaler',
            'description': 'Scales area linearly with radius instead of quadratically',
            'target_misconceptions': ['circ_area_scales_linearly', 'circ_doubling_r_doubles_area'],
            'base_accuracy': 0.45,
            'count': 5,
        },
        {
            'name': 'composite_confused',
            'description': 'Cannot handle composite circle shapes',
            'target_misconceptions': ['circ_annulus_adds_not_subtracts', 'circ_semicircle_forgets_diameter'],
            'base_accuracy': 0.55,
            'count': 5,
        },
        {
            'name': 'strong_student',
            'description': 'Mostly correct, minor errors only',
            'target_misconceptions': [],
            'base_accuracy': 0.88,
            'count': 5,
        },
        {
            'name': 'struggling_all_around',
            'description': 'Low accuracy, scattered errors',
            'target_misconceptions': ['circ_pi_is_integer', 'circ_radius_equals_diameter'],
            'base_accuracy': 0.28,
            'count': 4,
        },
    ],

    # Motion profiles (for completeness)
    'motion_grade8': [
        {
            'name': 'aristotelian',
            'target_misconceptions': ['motion_aristotelian_rest', 'motion_force_needed_for_motion'],
            'base_accuracy': 0.38, 'count': 6,
        },
        {
            'name': 'impetus_theorist',
            'target_misconceptions': ['motion_impetus_stored', 'motion_heavier_falls_faster'],
            'base_accuracy': 0.42, 'count': 5,
        },
        {
            'name': 'third_law_confused',
            'target_misconceptions': ['motion_third_law_cancel', 'motion_bigger_force_wins'],
            'base_accuracy': 0.55, 'count': 5,
        },
        {
            'name': 'strong_student',
            'target_misconceptions': [],
            'base_accuracy': 0.87, 'count': 8,
        },
        {
            'name': 'struggling',
            'target_misconceptions': ['motion_weight_is_mass', 'motion_acceleration_is_velocity'],
            'base_accuracy': 0.25, 'count': 6,
        },
    ],

    # Electricity profiles
    'elec_grade9': [
        {
            'name': 'formula_memoriser',
            'target_misconceptions': ['elec_ohm_inverted', 'elec_power_formula_confused'],
            'base_accuracy': 0.45, 'count': 7,
        },
        {
            'name': 'circuit_conceptual',
            'target_misconceptions': ['elec_series_current_splits', 'elec_parallel_same_resistance'],
            'base_accuracy': 0.40, 'count': 6,
        },
        {
            'name': 'strong_student',
            'target_misconceptions': [],
            'base_accuracy': 0.85, 'count': 10,
        },
        {
            'name': 'struggling',
            'target_misconceptions': ['elec_voltage_is_current', 'elec_resistance_additive_parallel'],
            'base_accuracy': 0.30, 'count': 7,
        },
    ],

    # Fractions profiles
    'frac_grade4': [
        {
            'name': 'numerator_focuser',
            'target_misconceptions': ['compares_numerators_only', 'larger_denominator_larger_fraction'],
            'base_accuracy': 0.42, 'count': 6,
        },
        {
            'name': 'procedural_without_understanding',
            'target_misconceptions': ['whole_number_thinking', 'adding_numerators_and_denominators'],
            'base_accuracy': 0.50, 'count': 7,
        },
        {
            'name': 'strong_student',
            'target_misconceptions': [],
            'base_accuracy': 0.88, 'count': 8,
        },
        {
            'name': 'struggling',
            'target_misconceptions': ['fraction_means_any_two_numbers', 'unit_fraction_misconception'],
            'base_accuracy': 0.28, 'count': 4,
        },
        {
            'name': 'visual_dependent',
            'target_misconceptions': ['area_model_only', 'number_line_confusion'],
            'base_accuracy': 0.58, 'count': 5,
        },
    ],
}

FIRST_NAMES = [
    'Aarav', 'Aisha', 'Arjun', 'Bhavna', 'Chirag', 'Deepika', 'Dev', 'Divya',
    'Farhan', 'Geeta', 'Harini', 'Ishan', 'Jaya', 'Kabir', 'Kavya', 'Keerthana',
    'Lakshmi', 'Manish', 'Meera', 'Mihir', 'Naina', 'Nikhil', 'Nitya', 'Pooja',
    'Priya', 'Rahul', 'Riya', 'Rohan', 'Sakshi', 'Sanvi', 'Siddharth', 'Sneha',
    'Tanvi', 'Tarun', 'Uma', 'Varun', 'Vidya', 'Vikram', 'Yamini', 'Zara',
    'Aditi', 'Akash', 'Ananya', 'Ankit', 'Bharat', 'Chandan', 'Diya', 'Gaurav',
]


def get_conn():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def generate_access_code():
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(chars, k=6))


def pick_option(options, profile_misconceptions, accuracy):
    """
    Pick an option for a question given a student profile.
    - With probability `accuracy`, pick the correct answer.
    - Otherwise, prefer options whose misconception_id is in profile_misconceptions.
    - Fall back to random wrong option.
    """
    correct = next((o for o in options if o['is_correct']), None)
    wrong = [o for o in options if not o['is_correct']]

    if random.random() < accuracy:
        return correct

    # Try to pick a wrong answer matching this profile's misconceptions
    targeted = [o for o in wrong if o['misconception_id'] in profile_misconceptions]
    if targeted:
        return random.choice(targeted)
    return random.choice(wrong) if wrong else correct


def simulate(test_id, n_students, access_code=None, teacher='Ms. Demo', school='Demo School', section='Class A'):
    conn = get_conn()

    # Validate test exists
    test = conn.execute("SELECT * FROM tests WHERE test_id = ?", (test_id,)).fetchone()
    if not test:
        print(f"ERROR: test_id '{test_id}' not found.")
        conn.close()
        return None

    # Create session
    if not access_code:
        access_code = generate_access_code()
        # Ensure unique
        while conn.execute("SELECT 1 FROM test_sessions WHERE access_code = ?", (access_code,)).fetchone():
            access_code = generate_access_code()

    session_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO test_sessions
            (session_id, test_id, access_code, created_by_teacher, school_name, class_section, session_date, students_completed)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """, (session_id, test_id, access_code, teacher, school, section, date.today().isoformat()))
    conn.commit()

    # Load questions and options
    questions = conn.execute(
        "SELECT * FROM questions WHERE test_id = ? ORDER BY question_order", (test_id,)
    ).fetchall()

    options_by_q = {}
    for row in conn.execute("""
        SELECT o.* FROM options o
        JOIN questions q ON o.question_id = q.question_id
        WHERE q.test_id = ?
    """, (test_id,)):
        qid = row['question_id']
        options_by_q.setdefault(qid, []).append(dict(row))

    # Expand profiles into individual student slots
    profiles = PROFILES.get(test_id, [])
    if not profiles:
        # Generic fallback
        profiles = [{'name': 'student', 'target_misconceptions': [], 'base_accuracy': 0.60, 'count': n_students}]

    student_slots = []
    for p in profiles:
        for _ in range(p['count']):
            student_slots.append(p)
    random.shuffle(student_slots)

    # Trim or extend to n_students
    while len(student_slots) < n_students:
        student_slots.extend(student_slots)
    student_slots = student_slots[:n_students]

    # Generate unique names
    names_pool = FIRST_NAMES.copy()
    random.shuffle(names_pool)
    while len(names_pool) < n_students:
        names_pool += [f"{n}{i}" for i, n in enumerate(FIRST_NAMES)]
    student_names = names_pool[:n_students]

    completed = 0
    for student_name, profile in zip(student_names, student_slots):
        target_misconceptions = set(profile.get('target_misconceptions', []))
        # Add slight per-student noise to accuracy
        accuracy = min(0.97, max(0.05, profile['base_accuracy'] + random.gauss(0, 0.08)))

        for q in questions:
            qid = q['question_id']
            opts = options_by_q.get(qid, [])
            if not opts:
                continue

            chosen = pick_option(opts, target_misconceptions, accuracy)
            if not chosen:
                continue

            is_correct = bool(chosen['is_correct'])
            misconception_id = chosen['misconception_id'] if not is_correct else None
            time_spent = int(random.gauss(45, 20))
            time_spent = max(5, min(180, time_spent))

            conn.execute("""
                INSERT INTO student_responses
                    (response_id, session_id, student_name, question_id, selected_option_id,
                     time_spent_seconds, is_correct, misconception_detected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), session_id, student_name, qid,
                  chosen['option_id'], time_spent, is_correct, misconception_id))

        completed += 1

    conn.execute(
        "UPDATE test_sessions SET students_completed = ? WHERE session_id = ?",
        (completed, session_id)
    )
    conn.commit()
    conn.close()

    print(f"Created session {access_code} for '{test['title']}'")
    print(f"  {completed} students simulated")
    print(f"  Dashboard: http://localhost:8080/dashboard/{access_code}")
    return access_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', default='lines_angles_grade7',
                        choices=['lines_angles_grade7', 'circles_grade7', 'motion_grade8', 'elec_grade9', 'frac_grade4'])
    parser.add_argument('--students', type=int, default=30)
    parser.add_argument('--code', default=None, help='Override access code (optional)')
    parser.add_argument('--section', default='Grade 7-A')
    parser.add_argument('--teacher', default='Ms. Sharma')
    parser.add_argument('--school', default='Greenfield Middle School')
    args = parser.parse_args()

    simulate(
        test_id=args.test,
        n_students=args.students,
        access_code=args.code,
        teacher=args.teacher,
        school=args.school,
        section=args.section,
    )
