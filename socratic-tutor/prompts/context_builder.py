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

# Resolution points per misconception — what "understood" looks like.
# The tutor uses these to recognize when the session is complete.
RESOLUTION_POINTS = {
    # Fractions
    'adding_numerators_and_denominators':
        "Student explains that the denominators represent the size of each part, so you can only add "
        "fractions when the parts are the same size (same denominator). They find a common denominator "
        "without being told to. Correct transfer: solves 1/2 + 1/3 = 5/6 and explains why.",
    'larger_denominator_larger_fraction':
        "Student explains that a larger denominator means each piece is smaller, so 1/8 < 1/3. "
        "They can compare two unit fractions without calculating. Correct transfer: correctly orders 1/5, 1/3, 1/9.",
    'compares_numerators_only':
        "Student explains that you can only compare numerators when the denominators are the same. "
        "Correct transfer: correctly identifies 3/5 > 3/8 and explains the piece-size reasoning.",
    'whole_number_thinking':
        "Student explains that fraction operations require thinking about part-size, not just counting. "
        "Correct transfer: correctly adds or compares two fractions without reverting to whole-number logic.",

    # Electricity (Grade 9)
    'elec_series_current_splits':
        "Student explains that current is the same everywhere in a series circuit because charge is not "
        "created or destroyed — it flows like water through a single pipe. Correct transfer: states the "
        "current through each component in a simple series circuit without calculating.",
    'elec_voltage_is_current':
        "Student distinguishes voltage (pressure, energy per charge) from current (flow, charge per second) "
        "using their own words or a water-pipe analogy. Correct transfer: identifies which quantity changes "
        "when a battery is replaced vs when a bulb is added.",
    'elec_ohm_inverted':
        "Student correctly states I = V/R and explains the direction: more voltage → more current, more "
        "resistance → less current. Correct transfer: calculates current given V=12V, R=4Ω without inverting.",
    'elec_parallel_voltage_differs':
        "Student explains that in a parallel circuit, each branch has the same voltage as the source. "
        "Correct transfer: states the voltage across each branch in a simple parallel circuit.",

    # Linear Equations (Grade 8)
    'lin_eq_balance_misunderstood':
        "Student explains that both sides of an equation must stay equal — any operation on one side must "
        "be done to the other. Correct transfer: solves 2x + 5 = 13 with correct balance steps.",
    'lin_eq_sign_error_transposing':
        "Student explains that moving a term to the other side changes its sign because you are doing the "
        "inverse operation to both sides. Correct transfer: solves x - 7 = 3 without sign error.",
    'lin_eq_variable_both_sides':
        "Student collects like terms correctly and explains why. Correct transfer: solves 3x + 4 = x + 10.",

    # Algebraic Expressions (Grade 8)
    'alg_like_terms_confusion':
        "Student explains that only terms with the same variable and power can be combined. "
        "Correct transfer: correctly simplifies 3x + 2y + x - y.",
    'alg_distributive_error':
        "Student applies the distributive law correctly and explains that the factor outside multiplies "
        "every term inside. Correct transfer: correctly expands 3(2x - 4).",

    # Ratios & Proportions (Grade 8)
    'ratio_part_whole_confusion':
        "Student distinguishes part:part ratios from part:whole fractions. Correct transfer: given "
        "ratio 2:3, correctly identifies each part and the whole.",
    'ratio_not_scale_invariant':
        "Student explains that equivalent ratios represent the same relationship at different scales. "
        "Correct transfer: correctly identifies 4:6 as equivalent to 2:3.",

    # Triangles (Grade 8)
    'tri_angle_sum_wrong':
        "Student explains that angles in a triangle always sum to 180° and can demonstrate why with "
        "a straight line argument. Correct transfer: finds missing angle in a triangle.",
    'tri_congruence_confusion':
        "Student distinguishes the congruence conditions (SSS, SAS, ASA, RHS) and explains what each "
        "guarantees. Correct transfer: identifies which condition applies to a given pair of triangles.",

    # Quadrilaterals (Grade 8)
    'quad_all_same':
        "Student correctly identifies at least two properties that distinguish a rectangle from a "
        "parallelogram. Correct transfer: classifies a given quadrilateral by its properties.",

    # Simple Interest (Grade 8)
    'si_formula_confusion':
        "Student correctly recalls SI = (P × R × T) / 100 and explains what each variable means. "
        "Correct transfer: calculates SI for P=1000, R=5%, T=2 years.",
    'si_adds_principal':
        "Student distinguishes Simple Interest from Amount (A = P + SI). Correct transfer: correctly "
        "calculates the total amount due after interest.",

    # Lines & Angles (Grade 7)
    'la_all_parallel_angles_equal':
        "Student correctly distinguishes the three angle pair types (alternate, corresponding, co-interior) "
        "and states the correct relationship for each. Correct transfer: finds co-interior angle given one angle.",
    'la_supp_vs_comp_confusion':
        "Student anchors 90° to complementary and 180° to supplementary without confusion. "
        "Correct transfer: finds the supplement of 65° and the complement of 40°.",
    'la_vertical_angles_supplementary':
        "Student explains that vertically opposite angles are equal because they are both supplementary "
        "to the same angle. Correct transfer: finds all four angles at an intersection given one.",

    # Circles (Grade 7)
    'circ_formula_swap':
        "Student correctly associates πr² with area (2D, space inside) and 2πr with circumference "
        "(1D, distance around). Correct transfer: correctly identifies which formula to use given a context.",
    'circ_area_scales_linearly':
        "Student explains that area involves r², so doubling the radius quadruples the area. "
        "Correct transfer: calculates the area ratio when radius doubles.",
    'circ_radius_equals_diameter':
        "Student explains that radius is half the diameter and can move between the two fluently. "
        "Correct transfer: given diameter 10cm, correctly uses r=5cm in the area formula.",

    # Motion (Grade 8)
    'motion_aristotelian_rest':
        "Student explains that objects keep moving at constant velocity unless a net force acts on them "
        "(Newton's First Law). Correct transfer: predicts motion of a puck on frictionless ice.",
    'motion_force_needed_for_motion':
        "Student distinguishes net force from individual forces and explains that constant velocity "
        "requires zero net force, not zero force. Correct transfer: explains why a car at constant speed "
        "still needs the engine running.",
    'motion_third_law_cancel':
        "Student explains that action-reaction pairs act on *different* objects, so they cannot cancel. "
        "Correct transfer: explains why a horse-cart system accelerates despite Newton's Third Law.",
}


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

    # Resolution points — what "understood" looks like for this student's misconceptions
    resolution_lines = []
    for mid in (misconception_ids or [])[:3]:
        rp = RESOLUTION_POINTS.get(mid)
        if rp:
            m = all_misconceptions.get(mid, {})
            label = m.get('misconception_name', mid)
            resolution_lines.append(f"  [{label}]: {rp}")
    if resolution_lines:
        lines.append("RESOLUTION POINTS (session is complete when the student demonstrates these):")
        lines.extend(resolution_lines)
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

    elif subject == 'electricity':
        openings = {
            'elec_series_current_splits':
                "Ask: 'In a series circuit with two bulbs, do you think the current through the first bulb "
                "is more, less, or the same as the current through the second bulb? Why?'",
            'elec_voltage_is_current':
                "Ask: 'When you say a battery is 9 volts — what does that actually mean? What is voltage?'",
            'elec_ohm_inverted':
                "Ask: 'If you increase the resistance in a circuit but keep the battery the same, what "
                "do you think happens to the current? Why?'",
            'elec_parallel_voltage_differs':
                "Ask: 'In a parallel circuit, does each branch get the full battery voltage or do they share it?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject in ('linear_equations', 'linear_eq'):
        openings = {
            'lin_eq_balance':
                "Ask: 'If both sides of a scale are equal and you add something to one side, what do you "
                "have to do to keep it balanced?'",
            'lin_eq_sign_error':
                "Ask: 'If x - 7 = 3, what is x? Walk me through how you got there.'",
            'lin_eq_variable_both_sides':
                "Ask: 'If you have 3 apples on one side and x apples on the other side and they balance, "
                "what is x — and does it matter which side the variable is on?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject in ('algebraic_expressions', 'algebra'):
        openings = {
            'alg_like_terms':
                "Ask: 'Can you add 3 apples and 2 oranges and call the result 5 apples? Why or why not?'",
            'alg_distributive':
                "Ask: 'If I give 3 bags to each of 5 people, and each bag has 2 pens and a notebook, "
                "how many pens do I need altogether — and how did you work that out?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject in ('ratios_proportions', 'ratios'):
        openings = {
            'ratio_part_whole':
                "Ask: 'If a class has 2 boys for every 3 girls, what fraction of the class is girls?'",
            'ratio_not_scale':
                "Ask: 'Are the ratios 2:3 and 4:6 the same or different? How do you know?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject == 'simple_interest':
        openings = {
            'si_formula':
                "Ask: 'If you borrow ₹1000 for 1 year at 10% interest, how much extra do you pay back? "
                "How did you figure that out?'",
            'si_adds_principal':
                "Ask: 'What is the difference between the interest on a loan and the total amount you owe?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject == 'triangles':
        openings = {
            'tri_angle_sum':
                "Ask: 'If you tear off the three corners of any triangle and place them side by side, "
                "what angle do they always make together?'",
            'tri_congruence':
                "Ask: 'If two triangles have the same three side lengths, must they be identical? "
                "Could they be different shapes?'",
        }
        for key, suggestion in openings.items():
            if key in top_mid:
                return suggestion

    elif subject == 'quadrilaterals':
        openings = {
            'quad_all_same':
                "Ask: 'What is the difference between a rectangle and a parallelogram? Are all rectangles "
                "parallelograms, or are all parallelograms rectangles?'",
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
        # Electricity
        'elec_series_current_splits': "A series circuit has a 6V battery and two identical bulbs. What is the current through the second bulb if the current through the first is 0.5A?",
        'elec_voltage_is_current': "A bulb has a resistance of 6Ω and a current of 0.5A flows through it. What is the voltage across the bulb?",
        'elec_ohm_inverted': "A resistor of 4Ω is connected to a 12V battery. What current flows through it?",
        'elec_parallel_voltage_differs': "Two bulbs are connected in parallel to a 9V battery. What is the voltage across each bulb?",
        # Linear Equations
        'lin_eq_balance': "Solve: 2x + 5 = 13",
        'lin_eq_sign_error': "Solve: x - 7 = 3",
        'lin_eq_variable_both_sides': "Solve: 3x + 4 = x + 10",
        # Algebraic Expressions
        'alg_like_terms': "Simplify: 3x + 2y + x - y",
        'alg_distributive': "Expand and simplify: 3(2x - 4) + x",
        # Ratios & Proportions
        'ratio_part_whole': "A bag has red and blue marbles in the ratio 3:5. If there are 24 marbles in total, how many are red?",
        'ratio_not_scale': "A recipe uses 2 cups of flour for every 3 cups of milk. How much milk is needed for 8 cups of flour?",
        # Simple Interest
        'si_formula': "Find the simple interest on ₹2000 at 5% per year for 3 years.",
        'si_adds_principal': "₹1500 is invested at 8% simple interest for 2 years. What is the total amount at the end?",
        # Triangles
        'tri_angle_sum': "A triangle has angles 48° and 75°. What is the third angle?",
        'tri_congruence': "Two triangles have sides 5cm, 7cm, 9cm each. Are they congruent? Which condition applies?",
        # Quadrilaterals
        'quad_all_same': "A quadrilateral has all sides equal but its angles are not 90°. What type of quadrilateral is it?",
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
        'electricity': "A series circuit has a 9V battery and a 3Ω resistor. What current flows through it?",
        'linear_equations': "Solve: 3x - 4 = 11",
        'algebraic_expressions': "Simplify: 4x + 3y - x + 2y",
        'ratios_proportions': "A map uses a scale of 1:50000. Two towns are 4cm apart on the map. What is the actual distance?",
        'simple_interest': "Find the simple interest on ₹5000 at 6% per year for 2 years.",
        'triangles': "In triangle ABC, angle A = 50° and angle B = 70°. Find angle C.",
        'quadrilaterals': "The angles of a quadrilateral are 90°, 85°, 95°, and x°. Find x.",
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
