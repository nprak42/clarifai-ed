"""
Builds the dynamic student context section of the Socratic tutor's system prompt
from diagnostic assessment data.

Two entry points:

  1. build_from_diagnostic(student_data, all_misconceptions, all_patterns, test)
     — takes data already in memory (from analysis.analyze_session output)

  2. build_from_session(session_id, student_name)
     — pulls everything from the assessment DB directly (for API use)

Output is a plain string that gets appended to the static system prompt.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../assessment-tool'))


# ---------------------------------------------------------------------------
# Severity priority for sorting misconceptions
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
RISK_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM-HIGH': 2, 'MEDIUM': 3, 'LOW': 4}


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def build_from_diagnostic(student_data: dict, all_misconceptions: dict,
                           all_patterns: dict, test: dict) -> str:
    """
    student_data: one entry from analysis.analyze_session()['students']
      {
        'name': str,
        'score_percent': float,
        'misconceptions': [misconception_id, ...],   # sorted by severity
        'misconception_counts': {mid: count},
        'patterns': [pattern_id, ...],
        'tier_scores': {...},
        'type_scores': {...},
      }
    all_misconceptions: {misconception_id: {...}} from analysis output
    all_patterns: {pattern_id: {...}} from analysis output
    test: test row dict (title, subject, grade)
    """
    name = student_data.get('name', 'Student')
    score = student_data.get('score_percent', 0)
    misconception_ids = student_data.get('misconceptions', [])
    misconception_counts = student_data.get('misconception_counts', {})
    pattern_ids = student_data.get('patterns', [])
    type_scores = student_data.get('type_scores', {})
    tier_scores = student_data.get('tier_scores', {})
    subject = test.get('subject', '')
    grade = test.get('grade', '')

    lines = []
    lines.append("---")
    lines.append("STUDENT DIAGNOSTIC CONTEXT")
    lines.append(f"Name: {name}")
    lines.append(f"Test: {test.get('title', subject)} (Grade {grade})")
    lines.append(f"Score: {score}% ({student_data.get('total_correct', '?')}/{student_data.get('total_questions', '?')} correct)")

    # Score breakdown by type if available
    if type_scores:
        breakdown = ", ".join(
            f"{t}: {round(s)}%" for t, s in sorted(type_scores.items())
        )
        lines.append(f"Score breakdown: {breakdown}")
    if tier_scores:
        breakdown = ", ".join(
            f"{t}: {round(s)}%" for t, s in sorted(tier_scores.items())
        )
        lines.append(f"Tier breakdown: {breakdown}")

    lines.append("")

    # Detected patterns (big picture diagnosis)
    if pattern_ids:
        lines.append("DETECTED LEARNING PATTERNS:")
        for pid in pattern_ids:
            p = all_patterns.get(pid)
            if not p:
                continue
            risk = p.get('grade8_risk', '')
            lines.append(f"  [{risk}] {p['pattern_name']}")
            lines.append(f"  Diagnosis: {p['diagnosis']}")
            if p.get('intervention_focus'):
                lines.append(f"  What to address: {p['intervention_focus']}")
        lines.append("")

    # Specific misconceptions (fine-grained evidence)
    if misconception_ids:
        # Top 4 by severity, then count
        top = sorted(
            misconception_ids,
            key=lambda m: (
                SEVERITY_ORDER.get(all_misconceptions.get(m, {}).get('severity', 'LOW'), 3),
                -misconception_counts.get(m, 0)
            )
        )[:4]

        lines.append("SPECIFIC MISCONCEPTIONS DETECTED:")
        for mid in top:
            m = all_misconceptions.get(mid)
            if not m:
                continue
            count = misconception_counts.get(mid, 1)
            times = f"{count}x" if count > 1 else "once"
            lines.append(f"  [{m['severity']}] {m['misconception_name']} (triggered {times})")
            lines.append(f"  What the student thinks: {m.get('why_students_think_this') or m['explanation']}")
            if m.get('root_cause'):
                lines.append(f"  Root cause: {m['root_cause']}")
        lines.append("")

    # Opening question guidance
    opening = _suggest_opening(misconception_ids, pattern_ids, all_misconceptions, all_patterns, subject)
    if opening:
        lines.append("SUGGESTED OPENING:")
        lines.append(f"  {opening}")
        lines.append("")

    # Assigned problem
    problem = _suggest_problem(misconception_ids, pattern_ids, all_misconceptions, subject)
    lines.append(f"ASSIGNED PROBLEM: {problem}")
    lines.append("---")

    return "\n".join(lines)


def _suggest_opening(misconception_ids, pattern_ids, all_misconceptions, all_patterns, subject):
    """
    Pick the most pointed opening question based on the student's top misconception.
    This gives the tutor a concrete first move rather than a generic greeting.
    """
    if not misconception_ids:
        return None

    # Get the top (most severe) misconception
    top_mid = misconception_ids[0]
    m = all_misconceptions.get(top_mid, {})
    name = m.get('misconception_name', '')

    # Subject-specific opening hooks
    if subject == 'fractions':
        openings = {
            'adding_numerators_and_denominators':
                "Ask: 'If you eat 1/3 of a pizza and then 1/4 of the same pizza, how much have you eaten — more or less than half?'",
            'larger_denominator_larger_fraction':
                "Ask: 'If I cut a roti into 8 pieces and give you 1, vs cutting it into 3 pieces and giving you 1 — which piece is bigger?'",
            'compares_numerators_only':
                "Ask: 'Which is bigger — 3/4 or 3/8? How do you know?'",
            'whole_number_thinking':
                "Ask: 'What does the bottom number of a fraction actually tell you?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid or key in name.lower():
                return suggestion

    elif subject in ('lines_angles', 'geometry'):
        openings = {
            'supp_vs_comp':
                "Ask: 'If two angles together make a straight line, what must they add up to?'",
            'all_parallel_angles_equal':
                "Ask: 'When two parallel lines are cut by a transversal, do you think ALL the angle pairs formed are equal?'",
            'vertical_angles_supplementary':
                "Ask: 'When two lines cross, what do you notice about the angles directly across from each other?'",
            'triangle_sum_360':
                "Ask: 'How many degrees are in a triangle altogether? How did you arrive at that?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject == 'circles':
        openings = {
            'formula_swap':
                "Ask: 'If I asked you to find how much space a circle takes up versus how far it is around the edge — are those the same thing?'",
            'radius_diameter':
                "Ask: 'If the diameter of a circle is 10cm, how long is the radius? How do you know?'",
            'area_scales_linearly':
                "Ask: 'If you double the radius of a circle, what do you think happens to its area?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject == 'motion':
        openings = {
            'aristotelian':
                "Ask: 'If you slide a book across a smooth table and let go, what happens — and why?'",
            'third_law':
                "Ask: 'When you push a wall, does the wall push back on you? How would you know?'",
            'weight_is_mass':
                "Ask: 'Is weight the same thing as mass? What's the difference?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    # Generic fallback based on what they got wrong
    why = m.get('why_students_think_this') or m.get('explanation', '')
    if why:
        return f"The student likely believes: '{why[:100]}'. Start by probing this belief with a concrete example before introducing any formulas or rules."

    return None


def _suggest_problem(misconception_ids, pattern_ids, all_misconceptions, subject):
    """
    Pick the most targeted problem to assign based on misconceptions.
    Falls back to a standard problem for the subject.
    """
    if not misconception_ids:
        return _default_problem(subject)

    top_mid = misconception_ids[0]

    problems = {
        # Fractions
        'adding_numerators_and_denominators': "What is 1/3 + 1/4? (Do not simplify — just find the sum.)",
        'larger_denominator_larger_fraction': "Which fraction is larger: 1/4 or 1/6? Explain your reasoning.",
        'compares_numerators_only': "Which is bigger: 3/8 or 3/5? Explain.",
        'whole_number_thinking': "What does the fraction 3/4 actually mean? Can you describe it in words?",
        # Lines & Angles
        'la_supp_vs_comp': "Two angles are supplementary. One is 65°. What is the other?",
        'la_all_parallel_angles_equal': "Two parallel lines are cut by a transversal at 70°. Find the co-interior angle.",
        'la_vertical_angles_supplementary': "Two lines intersect. One angle is 42°. What are the other three angles?",
        'la_triangle_sum_360': "A triangle has angles 48° and 75°. What is the third angle?",
        # Circles
        'circ_formula_swap': "Find the area of a circle with radius 5cm.",
        'circ_radius_equals_diameter': "A circle has diameter 12cm. What is its radius? What is its circumference?",
        'circ_area_scales_linearly': "Circle A has radius 3cm. Circle B has radius 6cm. How many times bigger is Circle B's area?",
        # Motion
        'motion_aristotelian_rest': "A hockey puck slides on frictionless ice. Will it keep moving or slow down? Why?",
        'motion_third_law_cancel': "A horse pulls a cart forward. The cart pulls the horse backward equally. Why does anything move at all?",
        'motion_weight_is_mass': "An astronaut has a mass of 70kg on Earth. What is their mass on the Moon?",
    }

    for key, problem in problems.items():
        if key in top_mid:
            return problem

    return _default_problem(subject)


def _default_problem(subject):
    defaults = {
        'fractions': "What is 1/3 + 1/4?",
        'lines_angles': "Two parallel lines are cut by a transversal. One angle is 55°. Find the alternate interior angle and the co-interior angle.",
        'circles': "Find the area and circumference of a circle with radius 7cm.",
        'motion': "A 5kg object is pushed with a force of 20N. What is its acceleration?",
        'electricity': "A resistor has a resistance of 10Ω. A current of 2A flows through it. What is the voltage across it?",
    }
    return defaults.get(subject, "Work through the problem your teacher has assigned.")


# ---------------------------------------------------------------------------
# DB entry point (for use from the tutor app)
# ---------------------------------------------------------------------------

def build_from_session(session_id: str, student_name: str) -> str:
    """
    Pull diagnostic data from the assessment DB and build the context string.
    Use this from the Socratic tutor app once Pass 2 connects the two systems.
    """
    import database as db
    import analysis

    data = analysis.analyze_session(session_id)
    if not data:
        return _fallback_context(student_name)

    student = next((s for s in data['students'] if s['name'] == student_name), None)
    if not student:
        return _fallback_context(student_name)

    return build_from_diagnostic(
        student_data=student,
        all_misconceptions=data['all_misconceptions'],
        all_patterns=data['all_patterns'],
        test=dict(data['test']),
    )


def _fallback_context(student_name: str) -> str:
    return f"""---
STUDENT DIAGNOSTIC CONTEXT
Name: {student_name}
No diagnostic data available. Use a general fractions starting point.
ASSIGNED PROBLEM: What is 1/3 + 1/4?
---"""


# ---------------------------------------------------------------------------
# Preview (run directly to see output)
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Simulate what the tutor would receive for a typical student
    sample_student = {
        'name': 'Rahul',
        'score_percent': 47.0,
        'total_correct': 7,
        'total_questions': 15,
        'misconceptions': [
            'adding_numerators_and_denominators',
            'larger_denominator_larger_fraction',
            'whole_number_thinking',
        ],
        'misconception_counts': {
            'adding_numerators_and_denominators': 3,
            'larger_denominator_larger_fraction': 2,
            'whole_number_thinking': 1,
        },
        'patterns': ['procedural_without_understanding'],
        'type_scores': {'mechanical': 60.0, 'understanding': 33.0, 'application': 25.0},
        'tier_scores': {'concrete': 80.0, 'semi_abstract': 40.0, 'abstract': 20.0},
    }

    sample_misconceptions = {
        'adding_numerators_and_denominators': {
            'misconception_name': 'Adds numerators and denominators separately',
            'severity': 'CRITICAL',
            'explanation': 'Student adds 1/3 + 1/4 = 2/7 by adding tops and bottoms separately.',
            'why_students_think_this': 'Fractions look like two separate numbers, so adding them feels like adding two numbers each.',
            'root_cause': 'No understanding of what the denominator represents as a unit size.',
        },
        'larger_denominator_larger_fraction': {
            'misconception_name': 'Larger denominator = larger fraction',
            'severity': 'HIGH',
            'explanation': 'Student thinks 1/8 > 1/3 because 8 > 3.',
            'why_students_think_this': 'Transfers whole number reasoning — bigger number means bigger quantity.',
            'root_cause': 'Denominator understood as count, not as size of each part.',
        },
        'whole_number_thinking': {
            'misconception_name': 'Applies whole number rules to fractions',
            'severity': 'HIGH',
            'explanation': 'Student treats fraction operations like whole number operations.',
            'why_students_think_this': 'All prior math experience has been with whole numbers.',
            'root_cause': 'Incomplete conceptual shift from discrete to part-whole reasoning.',
        },
    }

    sample_patterns = {
        'procedural_without_understanding': {
            'pattern_name': 'Procedural Without Understanding',
            'grade8_risk': 'HIGH',
            'diagnosis': 'Can follow fraction procedures in familiar formats but breaks down on novel problems or conceptual questions.',
            'intervention_focus': 'Build part-whole understanding using area models and number lines before returning to procedures.',
        },
    }

    sample_test = {
        'title': 'Fractions Diagnostic Assessment',
        'subject': 'fractions',
        'grade': 4,
    }

    context = build_from_diagnostic(sample_student, sample_misconceptions, sample_patterns, sample_test)
    print(context)
