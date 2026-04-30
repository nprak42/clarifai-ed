"""
Teacher co-pilot: adapter from analyze_session() output → Gemini prompt/chat.
"""
import os

import database as db

from google import genai
from google.genai import types

_client = None

def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get('GOOGLE_API_KEY')
        if not api_key:
            raise RuntimeError('GOOGLE_API_KEY environment variable must be set')
        _client = genai.Client(api_key=api_key)
    return _client


MODEL = 'gemini-2.5-flash'
MAX_HISTORY_TURNS = 10  # max user+model pairs kept from client


def build_copilot_context(data: dict) -> dict:
    """
    Reshape analyze_session() output into the flat dict that build_system_prompt expects.
    """
    test = data['test']
    class_summary = data['class_summary']
    pattern_groups = data['pattern_groups']
    intervention_groups = data['intervention_groups']

    n = class_summary['student_count']
    avg = class_summary['avg_score']

    # Compute score_breakdown from raw responses so the class percentage per
    # question_type is correct/total across every response, not an average of
    # per-student percentages (which skews when students have partial submissions).
    session_id = data['session']['session_id']
    raw_responses = db.get_responses_for_session(session_id)
    type_correct = {}
    type_total = {}
    for r in raw_responses:
        qtype = r.get('question_type')
        if not qtype:
            continue
        type_total[qtype] = type_total.get(qtype, 0) + 1
        if r.get('is_correct'):
            type_correct[qtype] = type_correct.get(qtype, 0) + 1
    score_breakdown = {
        k: round(type_correct.get(k, 0) / type_total[k] * 100, 1)
        for k in type_total
        if type_total[k] > 0
    }

    # Sort patterns by student count (prevalence) for the prompt.
    # analyzer returns risk-first; prompt labels this section "ranked by prevalence".
    patterns = sorted([
        {
            'pattern_id': g['pattern'].get('pattern_id', ''),
            'pattern_name': g['pattern'].get('pattern_name', ''),
            'student_count': g['count'],
            'percent_of_class': round(g['count'] / n * 100) if n else 0,
            'grade8_risk': g['pattern'].get('grade8_risk', ''),
            'diagnosis': g['pattern'].get('diagnosis', ''),
            'intervention_focus': g['pattern'].get('intervention_focus', ''),
            'estimated_intervention_time': g['pattern'].get('estimated_intervention_time', ''),
        }
        for g in pattern_groups
    ], key=lambda p: -p['student_count'])

    # Sort misconceptions by student count (prevalence) for the prompt.
    top_misconceptions = sorted([
        {
            'misconception_id': g['misconception'].get('misconception_id', ''),
            'misconception_name': g['misconception'].get('misconception_name', ''),
            'student_count': g['count'],
            'percent_of_class': round(g['count'] / n * 100) if n else 0,
            'severity': g['misconception'].get('severity', ''),
            'root_cause': g['misconception'].get('root_cause', ''),
            'why_students_think_this': g['misconception'].get('why_students_think_this', ''),
        }
        for g in intervention_groups
    ], key=lambda m: -m['student_count'])[:5]

    return {
        'test': {
            'title': test.get('title', ''),
            'subject': test.get('subject', ''),
            'grade': test.get('grade', ''),
            'total_questions': test.get('total_questions', ''),
        },
        'class_size': n,
        'avg_score_percent': avg,
        'score_breakdown': score_breakdown,
        'patterns': patterns,
        'top_misconceptions': top_misconceptions,
    }


def build_system_prompt(class_data: dict) -> str:
    test = class_data['test']
    patterns = class_data['patterns']
    misconceptions = class_data['top_misconceptions']
    breakdown = class_data['score_breakdown']
    n = class_data['class_size']
    avg = class_data['avg_score_percent']

    lines = []
    lines.append(
        'You are a teaching co-pilot for a secondary school science/maths teacher in India. '
        'Your job is to help the teacher act on diagnostic data about their class — not to give generic teaching advice, '
        'but to generate specific, ready-to-use classroom moves tied directly to the evidence in front of you.'
    )
    lines.append('')
    lines.append(
        'Your outputs must be concrete and specific. Never say "reteach the concept" or "use manipulatives" or '
        '"differentiate instruction". Every suggestion must name the specific misconception it addresses, '
        'the specific question or task to use, and why it targets the root cause — not the symptom.'
    )
    lines.append('')
    lines.append(
        'The teacher is time-constrained. Default to short, prioritised, ready-to-use outputs. '
        'If the teacher asks for a plan, give a plan they can use tomorrow — not a 3-week curriculum. '
        'Use the response template below unless the teacher asks for something different.'
    )
    lines.append('')
    lines.append(
        'Treat the conversation as cumulative planning. Reuse the activity, analogy, and constraint from earlier turns '
        'unless the teacher asks to replace them.'
    )
    lines.append('')
    lines.append(
        'Do not add conversational filler like "Okay, let\'s try something else" or "Here\'s a plan". '
        'Start with the answer itself.'
    )
    lines.append('')

    lines.append('DEFAULT RESPONSE TEMPLATE:')
    lines.append('---')
    lines.append('PRIORITY MISCONCEPTION')
    lines.append('[Name] — [X] of [N] students ([%])')
    lines.append('Root cause: [one sentence, plain language]')
    lines.append('')
    lines.append("TOMORROW'S MOVE")
    lines.append('[One concrete classroom action — specific question to ask or task to set]')
    lines.append('Time: ~[X] minutes')
    lines.append('')
    lines.append('GROUPING SUGGESTION')
    lines.append('[How to split the class for practice — who works with whom and why]')
    lines.append('')
    lines.append('LISTEN FOR (resolution signal)')
    lines.append('[One thing a student says that means the misconception is resolving]')
    lines.append('[One thing that means it isn\'t]')
    lines.append('')
    lines.append('FOLLOW-UP PROBLEMS')
    lines.append('[One problem to expose the gap — one to confirm resolution]')
    lines.append('---')
    lines.append('')
    lines.append(
        'CRITICAL RULES FOR FOLLOW-UP AND REFINEMENT:\n'
        '- If the teacher asks to refine, adjust, or replace ONE thing (an analogy, a grouping, a problem), '
        'change ONLY that thing. Do not regenerate the full plan.\n'
        '- If the teacher asks for a different analogy or a replacement activity, return only the replacement '
        "TOMORROW'S MOVE and any directly dependent FOLLOW-UP PROBLEM if needed. Do not repeat unchanged sections.\n"
        '- If the teacher says an analogy or approach does not work, do not use it again anywhere in the conversation — '
        'not even for a different misconception.\n'
        '- If the teacher asks a direct question, answer it in 2-4 sentences. No template.\n'
        '- Never produce more output than the teacher asked for.\n'
        '- For follow-up questions, start from the previously suggested move unless the teacher asks to switch focus.\n'
        '- Do not invent student-level certainty you do not have. If the data shows class-level counts but not named students, '
        'say how the teacher should identify who goes in which group.\n'
        '- Do not say "pair stronger students with struggling students" unless the context includes evidence for who the stronger students are.\n'
        '- Prefer teacher-feasible grouping instructions such as a quick hinge question, desk-zone grouping, or self-sort by confidence.'
    )
    lines.append('')

    lines.append('=' * 60)
    lines.append('CLASS DIAGNOSTIC CONTEXT')
    lines.append('=' * 60)
    lines.append(f"Test: {test['title']} (Grade {test['grade']})")
    lines.append(f'Class size: {n} students')
    lines.append(f'Average score: {avg}%')

    if breakdown:
        breakdown_str = ' / '.join(f'{k} {v}%' for k, v in breakdown.items())
        lines.append(f'Score breakdown: {breakdown_str}')

    lines.append('')

    if patterns:
        lines.append('DETECTED LEARNING PATTERNS (ranked by number of students affected):')
        for p in patterns:
            lines.append(
                f"  [{p['grade8_risk']}] {p['pattern_name']} — "
                f"{p['student_count']}/{n} students ({p['percent_of_class']}%)"
            )
            lines.append(f"  Diagnosis: {p['diagnosis']}")
            lines.append(f"  Intervention focus: {p['intervention_focus']}")
            if p['estimated_intervention_time']:
                lines.append(f"  Estimated time to address: {p['estimated_intervention_time']}")
            lines.append('')

    if misconceptions:
        lines.append('SPECIFIC MISCONCEPTIONS DETECTED (ranked by number of students affected):')
        for m in misconceptions:
            lines.append(
                f"  [{m['severity']}] {m['misconception_name']} — "
                f"{m['student_count']}/{n} students ({m['percent_of_class']}%)"
            )
            lines.append(f"  What students think: {m['why_students_think_this']}")
            lines.append(f"  Root cause: {m['root_cause']}")
            lines.append('')

    lines.append('=' * 60)
    return '\n'.join(lines)


def get_initial_plan(class_data: dict) -> str:
    system_prompt = build_system_prompt(class_data)
    client = _get_client()
    response = client.models.generate_content(
        model=MODEL,
        contents='What should I do first with this class?',
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
        ),
    )
    return response.text or 'No plan generated. Please try again.'


def get_chat_reply(class_data: dict, history: list, message: str) -> str:
    """
    history: list of {role: 'user'|'model', text: str} from the client.
    Capped and sanitised before sending to Gemini.
    """
    system_prompt = build_system_prompt(class_data)
    client = _get_client()

    # Sanitise: only allow user/model roles, cap turns
    clean = [
        h for h in history
        if isinstance(h, dict) and h.get('role') in ('user', 'model') and isinstance(h.get('text'), str)
    ]
    # Keep last MAX_HISTORY_TURNS pairs (each pair = 2 items)
    clean = clean[-(MAX_HISTORY_TURNS * 2):]

    contents = [
        types.Content(role=h['role'], parts=[types.Part(text=h['text'])])
        for h in clean
    ]
    contents.append(types.Content(role='user', parts=[types.Part(text=message)]))

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
        ),
    )
    return response.text or 'No response generated. Please try again.'
