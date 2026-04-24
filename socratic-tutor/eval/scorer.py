"""
Rubric scorer for Socratic tutor conversations.

Scores every assistant turn in tutor_logs.db against the 9 Socratic rules.
Produces a per-session and aggregate report.

Usage:
    python eval/scorer.py                        # score all sessions
    python eval/scorer.py --session <id>         # score one session
    python eval/scorer.py --output results.json  # save to file
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import logs

# ---------------------------------------------------------------------------
# Rule checkers — each takes (turn: dict, history: list[dict]) -> dict
# turn = {role, content, turn_index}
# history = all messages up to and including this turn
# Returns {rule, pass, violations: [str], notes: str}
# ---------------------------------------------------------------------------

ANSWER = "7/12"
ANSWER_VARIANTS = ["7/12", "seven twelfths", "0.583", "0.584", "the answer is 7"]

def _prev_user(history, current_index):
    """Get the most recent user message before this turn."""
    for m in reversed(history[:current_index]):
        if m['role'] == 'user':
            return m['content'].lower()
    return ''

def _count_questions(text):
    # Count question marks that end actual questions (not inside brackets)
    return len(re.findall(r'\?', text))

def check_rule1_no_answer(turn, _):
    """Never give the direct answer."""
    content = turn['content'].lower()
    violations = [v for v in ANSWER_VARIANTS if v in content]
    return {
        'rule': 1,
        'label': 'Never give the answer',
        'pass': len(violations) == 0,
        'violations': [f"Contains forbidden answer: '{v}'" for v in violations],
        'notes': '',
    }

def check_rule2_single_question(turn, _):
    """Ask only one question at a time."""
    n = _count_questions(turn['content'])
    return {
        'rule': 2,
        'label': 'One question at a time',
        'pass': n <= 1,
        'violations': [f"Contains {n} question marks (max 1)"] if n > 1 else [],
        'notes': f"{n} question(s)",
    }

def check_rule3_concrete_example(turn, history):
    """
    When a student seems stuck or confused, use concrete examples.
    Only checks turns where the previous user message signals confusion.
    """
    idx = turn['turn_index'] - 1
    prev = _prev_user(history, idx)
    confusion_signals = ['don\'t understand', 'dont understand', 'confused', 'i don\'t get', 'idk', 'no idea', 'what do you mean']
    student_confused = any(s in prev for s in confusion_signals)

    if not student_confused:
        return {'rule': 3, 'label': 'Concrete examples when stuck', 'pass': True, 'violations': [], 'notes': 'N/A (student not confused)'}

    concrete_words = ['pizza', 'roti', 'chocolate', 'pieces', 'slice', 'cut', 'share', 'divide', 'imagine', 'picture', 'example']
    content = turn['content'].lower()
    has_concrete = any(w in content for w in concrete_words)
    return {
        'rule': 3,
        'label': 'Concrete examples when stuck',
        'pass': has_concrete,
        'violations': [] if has_concrete else ['No concrete example used despite student confusion'],
        'notes': '',
    }

def check_rule4_no_immediate_confirm(turn, history):
    """
    Don't immediately confirm correct answers — ask why instead.
    Only checks turns where the previous user message contains the correct answer.
    """
    idx = turn['turn_index'] - 1
    prev = _prev_user(history, idx)
    student_gave_correct = any(v in prev for v in ['7/12', 'seven twelfths'])

    if not student_gave_correct:
        return {'rule': 4, 'label': 'No immediate confirmation', 'pass': True, 'violations': [], 'notes': 'N/A'}

    content = turn['content'].lower()
    immediate_confirms = ["that's correct", "that's right", "you're right", "yes, 7/12", "correct!", "well done", "great job", "exactly right", "perfect"]
    has_confirm = any(c in content for c in immediate_confirms)
    has_followup_q = _count_questions(content) > 0
    return {
        'rule': 4,
        'label': 'No immediate confirmation',
        'pass': not has_confirm and has_followup_q,
        'violations': (["Immediately confirmed correct answer without probing reasoning"] if has_confirm else []) +
                      (["No follow-up question after correct answer"] if not has_followup_q else []),
        'notes': '',
    }

def check_rule5_no_wrong(turn, _):
    """Never say 'wrong' or equivalent — ask an exposing question instead."""
    content = turn['content'].lower()
    wrong_words = [' wrong', 'incorrect', "that's not right", 'no, the answer', 'you\'re mistaken']
    violations = [w for w in wrong_words if w in content]
    return {
        'rule': 5,
        'label': "Never say 'wrong'",
        'pass': len(violations) == 0,
        'violations': [f"Contains: '{v}'" for v in violations],
        'notes': '',
    }

def check_rule7_handles_frustration(turn, history):
    """
    Handle frustration warmly — acknowledge before redirecting.
    Only checks turns after a frustrated user message.
    """
    idx = turn['turn_index'] - 1
    prev = _prev_user(history, idx)
    frustration_signals = ['just tell me', 'this is stupid', 'hate', 'annoying', 'frustrated', 'i give up', 'forget it']
    student_frustrated = any(s in prev for s in frustration_signals)

    if not student_frustrated:
        return {'rule': 7, 'label': 'Handles frustration warmly', 'pass': True, 'violations': [], 'notes': 'N/A'}

    content = turn['content'].lower()
    warm_words = ['understand', 'okay', 'alright', 'i know', 'promise', 'closer', 'try', 'feel', 'frustrat']
    has_warmth = any(w in content for w in warm_words)
    return {
        'rule': 7,
        'label': 'Handles frustration warmly',
        'pass': has_warmth,
        'violations': [] if has_warmth else ['No warmth/acknowledgement before redirecting frustrated student'],
        'notes': '',
    }

def check_rule8_stays_on_topic(turn, history):
    """Don't help with off-topic requests."""
    idx = turn['turn_index'] - 1
    prev = _prev_user(history, idx)
    off_topic_signals = ['history homework', 'science homework', 'english homework', 'geography', 'tell me a joke', 'what is your name']
    student_off_topic = any(s in prev for s in off_topic_signals)

    if not student_off_topic:
        return {'rule': 8, 'label': 'Stays on topic', 'pass': True, 'violations': [], 'notes': 'N/A'}

    content = turn['content'].lower()
    helps_off_topic = any(s in content for s in ['sure', "i'd be happy", 'of course', 'great question about'])
    return {
        'rule': 8,
        'label': 'Stays on topic',
        'pass': not helps_off_topic,
        'violations': ['Helped with off-topic request instead of redirecting'] if helps_off_topic else [],
        'notes': '',
    }

def check_rule9_requires_reasoning(turn, history):
    """
    Require reasoning, not just answers.
    Checks turns after a very short student answer (1-4 words, not a [START] system prompt).
    """
    idx = turn['turn_index'] - 1
    prev = _prev_user(history, idx)

    # Skip: system/greeting turns where there's no real prior student message
    if not prev or '[start]' in prev or '[system]' in prev:
        return {'rule': 9, 'label': 'Requires reasoning', 'pass': True, 'violations': [], 'notes': 'N/A (greeting turn)'}

    # Skip: student gave a substantive answer (more than 4 words)
    if len(prev.split()) > 4:
        return {'rule': 9, 'label': 'Requires reasoning', 'pass': True, 'violations': [], 'notes': 'N/A (answer not short)'}

    # Skip: student expressed confusion — tutor should use concrete example (Rule 3), not probe
    confusion_signals = ['don\'t understand', 'dont understand', 'confused', 'i don\'t get', 'no idea', 'what do you mean', 'i give up']
    if any(s in prev for s in confusion_signals):
        return {'rule': 9, 'label': 'Requires reasoning', 'pass': True, 'violations': [], 'notes': 'N/A (confusion, not answer)'}

    # Student gave a short answer — tutor should ask why/how before moving on
    content = turn['content'].lower()
    reasoning_prompts = ['why', 'how', 'explain', 'tell me', 'what makes', 'what do you mean', 'can you show', 'what do you think', 'can you tell']
    has_reasoning_prompt = any(r in content for r in reasoning_prompts)
    return {
        'rule': 9,
        'label': 'Requires reasoning',
        'pass': has_reasoning_prompt,
        'violations': [] if has_reasoning_prompt else ['Short student answer not followed by reasoning request'],
        'notes': '',
    }

RULE_CHECKS = [
    check_rule1_no_answer,
    check_rule2_single_question,
    check_rule3_concrete_example,
    check_rule4_no_immediate_confirm,
    check_rule5_no_wrong,
    check_rule7_handles_frustration,
    check_rule8_stays_on_topic,
    check_rule9_requires_reasoning,
]

# ---------------------------------------------------------------------------
# Score a single session
# ---------------------------------------------------------------------------

def score_session(session_id):
    messages = logs.get_session_messages(session_id)
    if not messages:
        return None

    turn_results = []
    for i, msg in enumerate(messages):
        if msg['role'] != 'assistant':
            continue
        history = messages[:i+1]
        checks = [fn(msg, history) for fn in RULE_CHECKS]
        applicable = [c for c in checks if 'N/A' not in c['notes']]
        violations = [c for c in applicable if not c['pass']]
        turn_results.append({
            'turn_index': msg['turn_index'],
            'content_preview': msg['content'][:120],
            'checks': checks,
            'applicable_count': len(applicable),
            'violation_count': len(violations),
            'violations': violations,
        })

    # Aggregate by rule
    rule_stats = {}
    for turn in turn_results:
        for check in turn['checks']:
            if 'N/A' in check['notes']:
                continue
            rule = check['rule']
            if rule not in rule_stats:
                rule_stats[rule] = {'label': check['label'], 'pass': 0, 'fail': 0, 'examples': []}
            if check['pass']:
                rule_stats[rule]['pass'] += 1
            else:
                rule_stats[rule]['fail'] += 1
                if len(rule_stats[rule]['examples']) < 2:
                    rule_stats[rule]['examples'].append(turn['content_preview'])

    total_checks = sum(r['pass'] + r['fail'] for r in rule_stats.values())
    total_pass = sum(r['pass'] for r in rule_stats.values())

    return {
        'session_id': session_id,
        'turn_count': len(turn_results),
        'total_checks': total_checks,
        'total_pass': total_pass,
        'score_pct': round(total_pass / total_checks * 100, 1) if total_checks else 0,
        'rule_stats': rule_stats,
        'turn_results': turn_results,
    }

# ---------------------------------------------------------------------------
# Print report
# ---------------------------------------------------------------------------

def print_report(results, verbose=False):
    sessions = logs.get_all_sessions()
    session_meta = {s['session_id']: s for s in sessions}

    print("\n" + "="*70)
    print("  SOCRATIC TUTOR — RUBRIC SCORE REPORT")
    print("="*70)

    all_rule_stats = {}

    for r in results:
        if not r:
            continue
        meta = session_meta.get(r['session_id'], {})
        print(f"\n  Session: {r['session_id'][:8]}...  Student: {meta.get('student_name','?')}  Turns: {r['turn_count']}")
        print(f"  Score: {r['total_pass']}/{r['total_checks']} checks passed  ({r['score_pct']}%)")

        for rule_num, stat in sorted(r['rule_stats'].items()):
            total = stat['pass'] + stat['fail']
            pct = round(stat['pass'] / total * 100) if total else 0
            icon = '✓' if stat['fail'] == 0 else ('~' if pct >= 50 else '✗')
            print(f"    {icon} Rule {rule_num} [{stat['label']}]: {stat['pass']}/{total} ({pct}%)")
            if verbose and stat['examples']:
                for ex in stat['examples']:
                    print(f"        ↳ Violation: \"{ex[:100]}\"")

        # Accumulate for aggregate
        for rule_num, stat in r['rule_stats'].items():
            if rule_num not in all_rule_stats:
                all_rule_stats[rule_num] = {'label': stat['label'], 'pass': 0, 'fail': 0, 'examples': []}
            all_rule_stats[rule_num]['pass'] += stat['pass']
            all_rule_stats[rule_num]['fail'] += stat['fail']
            all_rule_stats[rule_num]['examples'] += stat['examples']

    if len(results) > 1:
        print("\n" + "="*70)
        print("  AGGREGATE ACROSS ALL SESSIONS")
        print("="*70)
        for rule_num, stat in sorted(all_rule_stats.items()):
            total = stat['pass'] + stat['fail']
            pct = round(stat['pass'] / total * 100) if total else 0
            icon = '✓' if stat['fail'] == 0 else ('~' if pct >= 50 else '✗')
            print(f"  {icon} Rule {rule_num} [{stat['label']}]: {stat['pass']}/{total} ({pct}%)")
            if stat['fail'] > 0 and stat['examples']:
                print(f"      Example violation: \"{stat['examples'][0][:100]}\"")

    print()

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', default=None, help='Score a specific session ID')
    parser.add_argument('--output', default=None, help='Save results to JSON file')
    parser.add_argument('--verbose', action='store_true', help='Show violation examples per session')
    args = parser.parse_args()

    if args.session:
        sessions_to_score = [args.session]
    else:
        all_sessions = logs.get_all_sessions()
        sessions_to_score = [s['session_id'] for s in all_sessions if s['message_count'] >= 4]

    print(f"Scoring {len(sessions_to_score)} session(s)...")
    results = [score_session(sid) for sid in sessions_to_score]
    results = [r for r in results if r]

    print_report(results, verbose=args.verbose)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Results saved to {args.output}")
