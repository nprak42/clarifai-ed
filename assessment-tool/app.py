import os
import random
import string
from datetime import date

from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

import database as db
import analysis
import copilot

app = Flask(__name__)

_secret = os.environ.get('SECRET_KEY', '')
if not _secret:
    raise RuntimeError('SECRET_KEY environment variable must be set')
app.secret_key = _secret

app.config['SESSION_COOKIE_NAME'] = os.environ.get(
    'ASSESSMENT_SESSION_COOKIE_NAME',
    'clarifai_assessment_session',
)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SECURE_COOKIES', '0') == '1'
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

PLATFORM_BASE_URL = os.environ.get('PLATFORM_BASE_URL', '').rstrip('/')

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=os.environ.get('REDIS_URL', 'memory://'),
)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@app.teardown_appcontext
def close_db(e=None):
    db.close_db(e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_access_code():
    """6-char uppercase code, excluding visually ambiguous characters."""
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(chars, k=6))


def build_test_payload(test_id, session_id, student_name, resume_from=0):
    """
    Returns serializable dict with all questions + options for JS consumption.
    Uses bulk fetch to avoid N+1 queries.
    """
    questions = db.get_questions_for_test(test_id)
    all_options = db.get_all_options_for_test(test_id)

    questions_list = []
    for q in questions:
        qid = q['question_id']
        opts = all_options.get(qid, [])
        questions_list.append({
            'question_id': qid,
            'question_order': q['question_order'],
            'question_text': q['question_text'],
            'image_path': q['image_path'],
            'image_description': q['image_description'],
            'concept': q['concept'],
            'tier': q['tier'],
            'options': [
                {
                    'option_id': o['option_id'],
                    'option_letter': o['option_letter'],
                    'option_text': o['option_text'],
                    # Never send is_correct to the client
                }
                for o in opts
            ],
        })

    return {
        'session_id': session_id,
        'student_name': student_name,
        'questions': questions_list,
        'resume_from': resume_from,
    }


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    recent = db.get_recent_sessions()
    return render_template('home.html', recent_sessions=recent)


# ---------------------------------------------------------------------------
# Teacher: Create Session
# ---------------------------------------------------------------------------

@app.route('/create', methods=['GET', 'POST'])
def create_session():
    if request.method == 'GET':
        tests = db.get_tests()
        return render_template('session_create.html', tests=tests, today=date.today().isoformat())

    # POST
    test_id = request.form.get('test_id', '').strip()
    teacher_name = request.form.get('teacher_name', '').strip()
    school_name = request.form.get('school_name', '').strip()
    class_section = request.form.get('class_section', '').strip()
    session_date = request.form.get('session_date', date.today().isoformat()).strip()

    if not test_id:
        tests = db.get_tests()
        return render_template('session_create.html', tests=tests,
                               error="Please select a test.", today=date.today().isoformat())

    test = db.get_test_by_id(test_id)
    if not test:
        abort(400)

    # Generate unique access code
    for _ in range(10):
        code = generate_access_code()
        if not db.get_session_by_code(code):
            break

    session_id = db.create_session(
        test_id=test_id,
        access_code=code,
        teacher_name=teacher_name or None,
        school_name=school_name or None,
        class_section=class_section or None,
        session_date=session_date or None,
    )

    return redirect(url_for('dashboard', access_code=code))


# ---------------------------------------------------------------------------
# Student: Enter Test
# ---------------------------------------------------------------------------

@app.route('/test/<access_code>', methods=['GET', 'POST'])
def enter_test(access_code):
    session = db.get_session_by_code(access_code)
    if not session:
        return render_template('error.html',
                               message=f"No test found for code '{access_code.upper()}'. Please check the code with your teacher."), 404
    if session['status'] != 'active':
        return render_template('error.html', message="This test session is no longer active."), 410

    test = db.get_test_by_id(session['test_id'])

    if request.method == 'GET':
        return render_template('student_entry.html', session=dict(session), test=dict(test))

    # POST: student submits their name
    student_name = request.form.get('student_name', '').strip()
    if not student_name:
        return render_template('student_entry.html', session=dict(session), test=dict(test),
                               error="Please enter your name.")

    # Check if already started (allow resume) or already finished (block)
    answered_ids = db.get_answered_question_ids(session['session_id'], student_name)
    questions = db.get_questions_for_test(session['test_id'])
    resume_from = 0
    if answered_ids:
        # Find the first unanswered question index
        for i, q in enumerate(questions):
            if q['question_id'] not in answered_ids:
                resume_from = i
                break
        else:
            resume_from = len(questions)  # all answered

    if resume_from >= len(questions) and answered_ids:
        # Already completed — block re-entry to avoid duplicate data
        return render_template('student_entry.html', session=dict(session), test=dict(test),
                               error=f"'{student_name}' has already completed this test. "
                                     f"If that's not you, add your initial to make your name unique "
                                     f"(e.g. '{student_name} K').")

    payload = build_test_payload(
        test_id=session['test_id'],
        session_id=session['session_id'],
        student_name=student_name,
        resume_from=resume_from,
    )

    return render_template('test.html',
                           test=dict(test),
                           session=dict(session),
                           test_data=payload)


# ---------------------------------------------------------------------------
# Student: Submit a single answer (AJAX)
# ---------------------------------------------------------------------------

@app.route('/api/submit_response', methods=['POST'])
def submit_response():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON body'}), 400

    session_id = data.get('session_id')
    student_name = data.get('student_name', '').strip()
    question_id = data.get('question_id')
    option_id = data.get('option_id')
    time_spent = data.get('time_spent_seconds', 0)

    if not all([session_id, student_name, question_id, option_id]):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    # Look up the option to determine correctness and misconception
    option = db.get_option_by_id(option_id)
    if not option:
        return jsonify({'success': False, 'error': 'Invalid option_id'}), 400

    is_correct = bool(option['is_correct'])
    misconception_id = option['misconception_id'] if not is_correct else None

    db.save_response(
        session_id=session_id,
        student_name=student_name,
        question_id=question_id,
        option_id=option_id,
        time_spent=time_spent,
        is_correct=is_correct,
        misconception_id=misconception_id,
    )

    # Fetch the correct option so the client can build the review screen
    correct_option = db.get_correct_option_for_question(question_id)

    misconception_name = None
    misconception_explanation = None
    if misconception_id:
        m = db.get_misconception_by_id(misconception_id)
        if m:
            misconception_name = m['misconception_name']
            misconception_explanation = m['explanation']

    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'correct_letter': correct_option['option_letter'] if correct_option else None,
        'correct_text': correct_option['option_text'] if correct_option else None,
        'correct_explanation': correct_option['explanation'] if correct_option else None,
        'selected_letter': option['option_letter'],
        'selected_text': option['option_text'],
        'misconception_name': misconception_name,
        'misconception_explanation': misconception_explanation,
    })


# ---------------------------------------------------------------------------
# Student: Mark test complete
# ---------------------------------------------------------------------------

@app.route('/api/complete_test', methods=['POST'])
def complete_test():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON body'}), 400

    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'error': 'Missing session_id'}), 400

    db.increment_students_completed(session_id)
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Teacher: Close session + save notes
# ---------------------------------------------------------------------------

@app.route('/api/close_session', methods=['POST'])
def close_session():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON body'}), 400

    access_code = data.get('access_code', '').strip().upper()
    teacher_notes = data.get('teacher_notes', '').strip() or None

    session = db.get_session_by_code(access_code)
    if not session:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    db.close_session(session['session_id'], teacher_notes)
    return jsonify({'success': True})


@app.route('/api/create_tutor_session', methods=['POST'])
def create_tutor_session():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON body'}), 400

    session_id = data.get('session_id', '').strip()
    student_name = data.get('student_name', '').strip()
    if not session_id or not student_name:
        return jsonify({'success': False, 'error': 'Missing fields'}), 400

    sess = db.get_session_by_id(session_id)
    if not sess:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    test = db.get_test_by_id(sess['test_id'])
    token = db.create_tutor_token(session_id, student_name, test['subject'])
    public_base = request.host_url.rstrip('/') or PLATFORM_BASE_URL
    tutor_base = f"{public_base}/tutor"
    # Build tutor handoff URLs from the actual public origin so reverse proxies
    # and ngrok links keep working when the app is opened off-device.
    from urllib.parse import urlencode
    tutor_url = f"{tutor_base}/start/{token}?{urlencode({'cb': public_base})}"
    return jsonify({'success': True, 'token': token, 'tutor_url': tutor_url})


@app.route('/api/student_context/<token>')
@limiter.limit("10 per minute")
def student_context(token):
    token_row = db.get_and_consume_tutor_token(token)
    if not token_row:
        return jsonify({'error': 'Invalid or expired token'}), 404

    session_id = token_row['session_id']
    student_name = token_row['student_name']
    subject = token_row['subject']

    data = analysis.analyze_session(session_id)
    student = next((s for s in data['students'] if s['name'] == student_name), None)

    all_misconceptions = data['all_misconceptions']
    all_patterns = data['all_patterns']

    if not student:
        return jsonify({
            'student_name': student_name,
            'subject': subject,
            'score_percent': None,
            'misconceptions': [],
            'misconception_details': {},
            'misconception_counts': {},
            'patterns': [],
            'pattern_details': {},
            'tier_scores': {},
            'type_scores': {},
            'test': dict(data['test']),
        })

    return jsonify({
        'student_name': student_name,
        'subject': subject,
        'score_percent': student['score_percent'],
        'total_correct': student['total_correct'],
        'total_questions': student['total_questions'],
        'misconceptions': student['misconceptions'],
        'misconception_details': {
            mid: all_misconceptions[mid]
            for mid in student['misconceptions']
            if mid in all_misconceptions
        },
        'misconception_counts': student['misconception_counts'],
        'patterns': student['patterns'],
        'pattern_details': {
            pid: dict(all_patterns[pid])
            for pid in student['patterns']
            if pid in all_patterns
        },
        'tier_scores': student['tier_scores'],
        'type_scores': student['type_scores'],
        'test': dict(data['test']),
    })


@app.route('/api/save_notes', methods=['POST'])
def save_notes():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON body'}), 400

    access_code = data.get('access_code', '').strip().upper()
    teacher_notes = data.get('teacher_notes', '').strip() or None

    session = db.get_session_by_code(access_code)
    if not session:
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    db.save_teacher_notes(session['session_id'], teacher_notes)
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Student: Results
# ---------------------------------------------------------------------------

@app.route('/api/student_results', methods=['POST'])
def student_results():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON body'}), 400

    session_id = data.get('session_id')
    student_name = data.get('student_name', '').strip()
    if not session_id or not student_name:
        return jsonify({'success': False, 'error': 'Missing fields'}), 400

    rows = db.get_student_results(session_id, student_name)
    results = []
    for r in rows:
        results.append({
            'question_id': r['question_id'],
            'question_order': r['question_order'],
            'question_text': r['question_text'],
            'concept': r['concept'],
            'is_correct': bool(r['is_correct']),
            'selected_letter': r['selected_letter'],
            'selected_text': r['selected_text'],
            'correct_letter': r['correct_letter'],
            'correct_text': r['correct_text'],
            'correct_explanation': r['correct_explanation'],
            'misconception_name': r['misconception_name'],
            'misconception_explanation': r['misconception_explanation'],
        })

    total = len(results)
    correct = sum(1 for r in results if r['is_correct'])
    return jsonify({
        'success': True,
        'results': results,
        'total': total,
        'correct': correct,
        'score_percent': round(correct / total * 100, 1) if total else 0,
    })


# ---------------------------------------------------------------------------
# Teacher: Dashboard
# ---------------------------------------------------------------------------

@app.route('/dashboard/<access_code>')
def dashboard(access_code):
    session = db.get_session_by_code(access_code)
    if not session:
        return render_template('error.html',
                               message=f"No session found for code '{access_code.upper()}'."), 404

    data = analysis.analyze_session(session['session_id'])
    return render_template('dashboard.html', data=data, access_code=access_code.upper())


@app.route('/dashboard/<access_code>/data')
def dashboard_data(access_code):
    """JSON endpoint for dashboard auto-refresh."""
    session = db.get_session_by_code(access_code)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    data = analysis.analyze_session(session['session_id'])

    # Serialize - convert sqlite Row objects
    return jsonify({
        'session': dict(data['session']),
        'class_summary': data['class_summary'],
        'students': data['students'],
        'intervention_groups': [
            {
                'misconception': g['misconception'],
                'students': g['students'],
                'count': g['count'],
                'interventions': g['interventions'],
            }
            for g in data['intervention_groups']
        ],
        'pattern_groups': [
            {
                'pattern': g['pattern'],
                'students': g['students'],
                'count': g['count'],
                'misconception_evidence': g['misconception_evidence'],
            }
            for g in data['pattern_groups']
        ],
    })


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


# ---------------------------------------------------------------------------
# Teacher co-pilot
# ---------------------------------------------------------------------------

@app.route('/api/copilot/plan', methods=['POST'])
@limiter.limit('20 per hour')
def copilot_plan():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON body'}), 400

    access_code = data.get('access_code', '').strip().upper()
    if not access_code:
        return jsonify({'error': 'access_code required'}), 400

    session = db.get_session_by_code(access_code)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    try:
        session_data = analysis.analyze_session(session['session_id'])
        class_data = copilot.build_copilot_context(session_data)
        plan = copilot.get_initial_plan(class_data)
        return jsonify({'plan': plan, 'context': class_data})
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503
    except Exception as e:
        app.logger.exception('copilot_plan failed')
        return jsonify({'error': 'Failed to generate plan'}), 500


@app.route('/api/copilot/chat', methods=['POST'])
@limiter.limit('60 per hour')
def copilot_chat():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON body'}), 400

    access_code = data.get('access_code', '').strip().upper()
    message = (data.get('message') or '').strip()
    history = data.get('history') or []

    if not access_code or not message:
        return jsonify({'error': 'access_code and message required'}), 400

    if not isinstance(history, list):
        return jsonify({'error': 'history must be an array'}), 400

    if len(message) > 2000:
        return jsonify({'error': 'Message too long'}), 400

    session = db.get_session_by_code(access_code)
    if not session:
        return jsonify({'error': 'Session not found'}), 404

    try:
        session_data = analysis.analyze_session(session['session_id'])
        class_data = copilot.build_copilot_context(session_data)
        reply = copilot.get_chat_reply(class_data, history, message)
        return jsonify({'reply': reply})
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 503
    except Exception as e:
        app.logger.exception('copilot_chat failed')
        return jsonify({'error': 'Failed to generate reply'}), 500


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', message="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', message="Something went wrong. Please try again."), 500


# ---------------------------------------------------------------------------
# Dev: seed test data
# ---------------------------------------------------------------------------

@app.route('/dev/seed_test_session')
def dev_seed():
    """Quick helper to create a test session for development."""
    if not app.debug:
        abort(404)

    import uuid
    # Create a fractions session
    code = 'FRAC4A'
    existing = db.get_session_by_code(code)
    if not existing:
        sid = db.create_session(
            test_id='frac_grade4',
            access_code=code,
            teacher_name='Demo Teacher',
            school_name='Demo School',
            class_section='Grade 4-A',
            session_date=date.today().isoformat(),
        )
    else:
        sid = existing['session_id']

    # Create an electricity session
    code2 = 'ELEC9B'
    existing2 = db.get_session_by_code(code2)
    if not existing2:
        db.create_session(
            test_id='elec_grade9',
            access_code=code2,
            teacher_name='Demo Teacher',
            school_name='Demo School',
            class_section='Grade 9-B',
            session_date=date.today().isoformat(),
        )

    return f"""
    <h2>Test sessions created!</h2>
    <p>Fractions: <a href="/test/FRAC4A">/test/FRAC4A</a>
       &nbsp;|&nbsp; <a href="/dashboard/FRAC4A">Dashboard</a></p>
    <p>Electricity: <a href="/test/ELEC9B">/test/ELEC9B</a>
       &nbsp;|&nbsp; <a href="/dashboard/ELEC9B">Dashboard</a></p>
    <p><a href="/">← Home</a></p>
    """


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--dev', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    app.run(debug=args.dev, host='0.0.0.0', port=args.port)
