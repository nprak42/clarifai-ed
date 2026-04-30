"""
Analysis engine for the diagnostic assessment tool.

Main entry point: analyze_session(session_id)

Pattern detection logic handles both fractions (tier-based) and
electricity (question_type-based) assessments.
"""
import json
import database as db


# Maps keys used in detection_logic JSON to the score dict keys
TIER_KEY_MAP = {
    'tier1_score_min': 'concrete',
    'tier1_score_max': 'concrete',
    'tier2_score_min': 'semi_abstract',
    'tier2_score_max': 'semi_abstract',
    'tier3_score_min': 'abstract',
    'tier3_score_max': 'abstract',
    'mechanical_score_min': 'mechanical',
    'mechanical_score_max': 'mechanical',
    'conceptual_score_min': 'understanding',
    'conceptual_score_max': 'understanding',
    'understanding_score_min': 'understanding',
    'understanding_score_max': 'understanding',
    'application_score_min': 'application',
    'application_score_max': 'application',
}

SEVERITY_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}


def _compute_scores(responses):
    """
    Given a list of response dicts for ONE student, compute:
      - tier_scores: {tier_name: percent_correct}
      - type_scores: {question_type: percent_correct}
      - overall: percent correct overall
    """
    tier_totals = {}   # tier -> [correct, total]
    type_totals = {}   # question_type -> [correct, total]
    total_correct = 0
    total = len(responses)

    for r in responses:
        correct = bool(r['is_correct'])
        if correct:
            total_correct += 1

        tier = r['tier']
        if tier:
            if tier not in tier_totals:
                tier_totals[tier] = [0, 0]
            tier_totals[tier][1] += 1
            if correct:
                tier_totals[tier][0] += 1

        qtype = r['question_type']
        if qtype:
            if qtype not in type_totals:
                type_totals[qtype] = [0, 0]
            type_totals[qtype][1] += 1
            if correct:
                type_totals[qtype][0] += 1

    tier_scores = {
        t: (v[0] / v[1] * 100) if v[1] > 0 else 0
        for t, v in tier_totals.items()
    }
    type_scores = {
        t: (v[0] / v[1] * 100) if v[1] > 0 else 0
        for t, v in type_totals.items()
    }
    overall = (total_correct / total * 100) if total > 0 else 0

    return tier_scores, type_scores, overall, total_correct, total


def _get_score_for_key(key, tier_scores, type_scores):
    """
    Map a detection_logic key to the correct score dict.
    Returns None if the score category isn't available for this test.
    """
    mapped = TIER_KEY_MAP.get(key)
    if mapped is None:
        return None
    # Check tier_scores first, then type_scores
    if mapped in tier_scores:
        return tier_scores[mapped]
    if mapped in type_scores:
        return type_scores[mapped]
    return None  # this score category doesn't exist for this test


def _evaluate_pattern(detection_logic_str, tier_scores, type_scores,
                       student_misconception_counts=None):
    """
    Parse detection_logic JSON and evaluate against computed scores.
    Returns True if all rules match, False if any rule fails,
    None if the pattern can't be evaluated for this test (missing score categories).

    Supports two styles of detection_logic:
      Score-threshold style (fractions/electricity):
        {"tier1_score_min": 75, "mechanical_score_max": 50, ...}
      Misconception-count style (motion):
        {"misconception_ids": ["mid1", "mid2"], "min_count": 2}
    """
    try:
        rules = json.loads(detection_logic_str)
    except (json.JSONDecodeError, TypeError):
        return None

    # --- Misconception-count style ---
    if 'misconception_ids' in rules:
        if student_misconception_counts is None:
            return None
        target_ids = rules['misconception_ids']
        min_count = rules.get('min_count', 1)
        # Count how many of the target misconceptions the student has triggered
        matched = sum(1 for mid in target_ids if student_misconception_counts.get(mid, 0) > 0)
        return matched >= min_count

    # --- Score-threshold style ---
    skip_keys = {'requires_both', 'requires_all', 'indicates_critical_gap', 'critical_question_ids'}

    evaluable_rules = 0
    for key, threshold in rules.items():
        if key in skip_keys:
            continue
        if not isinstance(threshold, (int, float)):
            continue

        actual = _get_score_for_key(key, tier_scores, type_scores)
        if actual is None:
            # Rule references a score category that doesn't exist for this test.
            # Treat the whole pattern as unevaluable rather than silently ignoring
            # the rule — otherwise a _max guard that would exclude a high scorer
            # gets skipped and the pattern fires incorrectly.
            return None

        evaluable_rules += 1
        if key.endswith('_min') and actual < threshold:
            return False
        if key.endswith('_max') and actual >= threshold:
            return False

    if evaluable_rules == 0:
        return None

    return True


def _detect_patterns(student_name, responses, subject, session_id, student_misconception_counts=None):
    """
    Run all patterns for a subject against a student's responses.
    Returns list of matched pattern_ids.
    """
    tier_scores, type_scores, overall, _, _ = _compute_scores(responses)
    patterns = db.get_patterns_for_subject(subject)

    matched = []
    for p in patterns:
        result = _evaluate_pattern(
            p['detection_logic'], tier_scores, type_scores,
            student_misconception_counts=student_misconception_counts
        )
        if result is True:
            # Save detection to DB
            evidence = json.dumps([r['question_id'] for r in responses if not r['is_correct']])
            t1 = tier_scores.get('concrete')
            t2 = tier_scores.get('semi_abstract')
            t3 = tier_scores.get('abstract')
            db.save_pattern_detection(
                session_id, student_name, p['pattern_id'],
                evidence, t1, t2, t3
            )
            matched.append(p['pattern_id'])

    return matched


def analyze_session(session_id):
    """
    Full analysis of a test session.

    Returns:
    {
        'session': {...},
        'test': {...},
        'students': [
            {
                'name': str,
                'total_correct': int,
                'total_questions': int,
                'score_percent': float,
                'misconceptions': [misconception_id, ...],  # deduplicated
                'misconception_counts': {misconception_id: count},
                'patterns': [pattern_id, ...],
                'tier_scores': {tier: percent},
                'type_scores': {type: percent},
            }
        ],
        'class_summary': {
            'student_count': int,
            'avg_score': float,
            'misconception_counts': {misconception_id: count},  # across all students
            'pattern_counts': {pattern_id: count},
        },
        'intervention_groups': [
            {
                'misconception': {...},
                'students': [name, ...],
                'count': int,
                'interventions': [{...}],
            }
        ],
        'all_misconceptions': {misconception_id: {...}},
        'all_patterns': {pattern_id: {...}},
    }
    """
    session = db.get_session_by_id(session_id)
    if not session:
        return None

    test = db.get_test_by_id(session['test_id'])
    subject = test['subject']

    # Load all responses for session
    all_responses = db.get_responses_for_session(session_id)

    # Pre-load all misconceptions and patterns into dicts for fast lookup
    all_misconceptions = {m['misconception_id']: dict(m) for m in db.get_all_misconceptions()}
    all_patterns_list = db.get_patterns_for_subject(subject)
    all_patterns = {p['pattern_id']: dict(p) for p in all_patterns_list}

    # Group responses by student
    students_responses = {}
    for r in all_responses:
        name = r['student_name']
        if name not in students_responses:
            students_responses[name] = []
        students_responses[name].append(dict(r))

    # Per-student analysis
    students = []
    class_misconception_counts = {}
    class_pattern_counts = {}

    for student_name, responses in sorted(students_responses.items()):
        tier_scores, type_scores, overall, total_correct, total = _compute_scores(responses)

        # Collect misconceptions (from wrong answers that map to a misconception_id)
        student_misconception_counts = {}
        for r in responses:
            if not r['is_correct']:
                mid = r.get('misconception_detected') or r.get('option_misconception_id')
                if mid:
                    student_misconception_counts[mid] = student_misconception_counts.get(mid, 0) + 1
                    class_misconception_counts[mid] = class_misconception_counts.get(mid, 0) + 1

        # Detect patterns
        patterns = _detect_patterns(student_name, responses, subject, session_id,
                                    student_misconception_counts=student_misconception_counts)
        for pid in patterns:
            class_pattern_counts[pid] = class_pattern_counts.get(pid, 0) + 1

        students.append({
            'name': student_name,
            'total_correct': total_correct,
            'total_questions': total,
            'score_percent': round(overall, 1),
            'misconceptions': sorted(
                student_misconception_counts.keys(),
                key=lambda m: SEVERITY_ORDER.get(
                    all_misconceptions.get(m, {}).get('severity', 'LOW'), 3
                )
            ),
            'misconception_counts': student_misconception_counts,
            'patterns': patterns,
            'tier_scores': {k: round(v, 1) for k, v in tier_scores.items()},
            'type_scores': {k: round(v, 1) for k, v in type_scores.items()},
        })

    # Class summary
    scores = [s['score_percent'] for s in students]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    top_misconceptions = sorted(
        class_misconception_counts.items(), key=lambda x: -x[1]
    )[:3]

    class_summary = {
        'student_count': len(students),
        'avg_score': avg_score,
        'misconception_counts': class_misconception_counts,
        'pattern_counts': class_pattern_counts,
        'top_misconceptions': top_misconceptions,
    }

    # Build intervention groups: one per misconception, sorted by severity
    intervention_groups = _build_intervention_groups(
        students, class_misconception_counts, all_misconceptions
    )

    # Build pattern groups: one per detected pattern, patterns as primary unit
    pattern_groups = _build_pattern_groups(
        students, class_pattern_counts, all_patterns, all_misconceptions
    )

    return {
        'session': dict(session),
        'test': dict(test),
        'students': students,
        'class_summary': class_summary,
        'intervention_groups': intervention_groups,
        'pattern_groups': pattern_groups,
        'all_misconceptions': all_misconceptions,
        'all_patterns': all_patterns,
    }


def _build_intervention_groups(students, class_misconception_counts, all_misconceptions):
    """
    For each misconception seen in the class, build a group showing:
    - Which students have it
    - Intervention plan
    Sorted CRITICAL > HIGH > MEDIUM > LOW, then by count descending.
    """
    groups = []

    for mid, count in class_misconception_counts.items():
        misconception = all_misconceptions.get(mid)
        if not misconception:
            continue

        # Which students have this misconception
        affected_students = [
            s['name'] for s in students
            if mid in s['misconceptions']
        ]

        # Get interventions
        interventions = [dict(i) for i in db.get_interventions_for_misconception(mid)]

        groups.append({
            'misconception': misconception,
            'students': affected_students,
            'count': count,
            'interventions': interventions,
        })

    # Sort: CRITICAL first, then by count
    groups.sort(key=lambda g: (
        SEVERITY_ORDER.get(g['misconception'].get('severity', 'LOW'), 3),
        -g['count']
    ))

    return groups


RISK_ORDER = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM-HIGH': 2, 'MEDIUM': 3, 'LOW': 4}


def _build_pattern_groups(students, class_pattern_counts, all_patterns, all_misconceptions):
    """
    For each pattern detected in the class, build a group showing:
    - Which students match the pattern
    - The misconceptions those students share (as evidence)
    - The pattern's diagnosis, symptoms, intervention focus
    Sorted by grade8_risk then by student count.
    """
    groups = []

    for pid, count in class_pattern_counts.items():
        pattern = all_patterns.get(pid)
        if not pattern:
            continue

        affected_students = [s for s in students if pid in s['patterns']]

        # Collect misconceptions seen across affected students, ranked by frequency
        miscon_counts = {}
        for s in affected_students:
            for mid, c in s['misconception_counts'].items():
                miscon_counts[mid] = miscon_counts.get(mid, 0) + c

        # Top misconceptions as evidence (up to 5, with full detail)
        top_misconceptions = sorted(miscon_counts.items(), key=lambda x: -x[1])[:5]
        misconception_evidence = [
            {**all_misconceptions[mid], 'count': c}
            for mid, c in top_misconceptions
            if mid in all_misconceptions
        ]

        groups.append({
            'pattern': pattern,
            'students': [s['name'] for s in affected_students],
            'student_details': affected_students,
            'count': count,
            'misconception_evidence': misconception_evidence,
        })

    # Sort by risk then count
    groups.sort(key=lambda g: (
        RISK_ORDER.get(g['pattern'].get('grade8_risk', 'LOW'), 4),
        -g['count']
    ))

    return groups
