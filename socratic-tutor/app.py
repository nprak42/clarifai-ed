"""
Socratic Tutor — Flask app with Postgres-backed session state.
"""
import json
import os
import re
import uuid

import requests
from flask import (Flask, Response, render_template, request,
                   jsonify, session, stream_with_context, redirect, url_for)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import logs
from prompts.socratic_fractions import build_system_prompt
from prompts.context_builder import build_from_diagnostic

app = Flask(__name__)

_secret = os.environ.get('SECRET_KEY', '')
if not _secret:
    raise RuntimeError('SECRET_KEY environment variable must be set')
app.secret_key = _secret

app.config['SESSION_COOKIE_NAME'] = os.environ.get(
    'TUTOR_SESSION_COOKIE_NAME', 'clarifai_tutor_session'
)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SECURE_COOKIES', '0') == '1'

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=os.environ.get('REDIS_URL', 'memory://'),
)

STUCK_THRESHOLD = 3
MAX_WORKED_EXAMPLES = 2

DEFAULT_SYSTEM_PROMPT = build_system_prompt(
    student_name=config.STUDENT_NAME,
    target_misconception=config.TARGET_MISCONCEPTION,
    diagnostic_notes=config.DIAGNOSTIC_NOTES,
    assigned_problem=config.ASSIGNED_PROBLEM,
)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _create_session(student_name, assigned_problem, system_prompt, subject):
    sid = str(uuid.uuid4())
    session['sid'] = sid
    logs.create_session(
        session_id=sid,
        student_name=student_name,
        subject=subject,
        assigned_problem=assigned_problem,
        model_name=config.MODEL_NAME,
        system_prompt=system_prompt,
    )
    return sid


def _get_sid():
    """Return the session id from the signed cookie if it exists in the DB."""
    sid = session.get('sid')
    if sid and logs.get_session(sid):
        return sid
    return None


def get_or_create_session(student_name=None, assigned_problem=None,
                          system_prompt=None, subject=None):
    sid = _get_sid()
    if sid:
        return sid
    return _create_session(
        student_name=student_name or config.STUDENT_NAME,
        assigned_problem=assigned_problem or config.ASSIGNED_PROBLEM,
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        subject=subject or 'fractions',
    )


def _session_data(sid):
    """Return the full session row or raise."""
    data = logs.get_session(sid)
    if not data:
        raise KeyError(f'Session {sid} not found')
    return data


def _build_greeting_instruction(sess):
    subject = sess.get('subject') or 'fractions'
    assigned_problem = sess.get('assigned_problem')

    lines = [
        "[START] Greet the student warmly by name.",
        "Use exactly one short greeting sentence.",
        "Then ask exactly one opening question.",
        f"Stay strictly within the subject '{subject}'.",
    ]

    if assigned_problem:
        lines.append(f"The assigned problem is: {assigned_problem}")
        lines.append(
            "Base the question on this assigned problem or the student's misconception in this same subject."
        )
    else:
        lines.append(
            "There is no assigned problem, so ask one question about the student's diagnosed misunderstanding in this same subject."
        )

    lines.extend([
        "Do not switch to another chapter or topic.",
        "Do not mention circles, angles, geometry, motion, or science unless that is the student's actual subject.",
        "Do not reveal any answer, formula, or worked solution.",
    ])

    return " ".join(lines)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def render_handoff_error(title, message, status_code=502, details=None):
    return render_template(
        'handoff_error.html',
        title=title,
        message=message,
        details=details,
    ), status_code


@app.route('/start/<token>')
@limiter.limit("10 per minute")
def start_with_token(token):
    old_sid = session.get('sid')
    if old_sid and logs.get_session(old_sid):
        logs.end_session(old_sid)
    session.clear()

    cb_base = request.args.get('cb', '').rstrip('/')
    request_origin = request.host_url.rstrip('/')
    allowed_cb_origins = set(config.ALLOWED_CB_ORIGINS)
    if request_origin:
        allowed_cb_origins.add(request_origin)

    if cb_base and allowed_cb_origins:
        if cb_base not in allowed_cb_origins:
            return render_handoff_error(
                title="Invalid callback origin",
                message="The tutor received a request from an untrusted source.",
                status_code=400,
                details=f"Origin '{cb_base}' is not in the allowed callback list.",
            )
    if not cb_base:
        cb_base = config.ASSESSMENT_TOOL_BASE_URL.rstrip('/')

    try:
        resp = requests.get(
            f"{cb_base}/api/student_context/{token}",
            timeout=5,
        )
        if resp.status_code != 200:
            return render_handoff_error(
                title="Couldn't start this tutor session",
                message="The tutor could not load this student's diagnostic context.",
                status_code=502,
                details=f"Assessment service returned status {resp.status_code} for token {token}.",
            )
        ctx = resp.json()
    except requests.exceptions.RequestException as exc:
        return render_handoff_error(
            title="Assessment service unreachable",
            message="The tutor could not reach the diagnostic app to load this student's context.",
            status_code=502,
            details=str(exc),
        )
    except Exception as exc:
        return render_handoff_error(
            title="Tutor launch failed",
            message="Something went wrong while preparing this tutor session.",
            status_code=500,
            details=str(exc),
        )

    student_data = {
        'name': ctx['student_name'],
        'score_percent': ctx.get('score_percent', 0),
        'total_correct': ctx.get('total_correct'),
        'total_questions': ctx.get('total_questions'),
        'misconceptions': ctx.get('misconceptions', []),
        'misconception_counts': ctx.get('misconception_counts', {}),
        'patterns': ctx.get('patterns', []),
        'tier_scores': ctx.get('tier_scores', {}),
        'type_scores': ctx.get('type_scores', {}),
    }
    diagnostic_context = build_from_diagnostic(
        student_data=student_data,
        all_misconceptions=ctx.get('misconception_details', {}),
        all_patterns=ctx.get('pattern_details', {}),
        test=ctx.get('test', {}),
    )
    system_prompt = build_system_prompt(
        student_name=ctx['student_name'],
        diagnostic_context=diagnostic_context,
    )

    _create_session(
        student_name=ctx['student_name'],
        assigned_problem=ctx.get('test', {}).get('title', ''),
        system_prompt=system_prompt,
        subject=ctx.get('subject', 'fractions'),
    )
    return redirect(url_for('index'))


@app.route('/')
def index():
    sid = get_or_create_session()
    sess = _session_data(sid)
    return render_template('chat.html',
                           student_name=sess.get('student_name', config.STUDENT_NAME),
                           assigned_problem=sess.get('assigned_problem', config.ASSIGNED_PROBLEM))


@app.route('/api/chat', methods=['POST'])
@limiter.limit("30 per minute")
def chat():
    data = request.get_json()
    if not data or not data.get('message', '').strip():
        return jsonify({'error': 'Empty message'}), 400

    sid = _get_sid()
    if not sid:
        return jsonify({'error': 'No active session'}), 401

    sess = _session_data(sid)
    user_message = data['message'].strip()

    if sess['message_count'] >= config.MAX_CONVERSATION_LENGTH:
        return jsonify({
            'reply': "We've covered a lot of ground! I think it would really help to talk through the rest with your teacher.",
            'done': True,
        })

    history = logs.get_history(sid)
    turn_index = len(history) + 1
    logs.append_message(sid, 'user', user_message, turn_index)

    student_reply = user_message.lower().strip()
    understanding_signals = [
        'because', 'since', 'i see', 'oh', 'so if', 'that means',
        '7/12', 'twelve', 'common', 'denominator', 'numerator',
        'multiply', 'divide', 'equal', 'same', 'half', 'fraction',
    ]
    has_number = bool(re.search(r'\d', student_reply))
    off_task_signals = [
        'i like', "i don't know", 'idk', 'no idea', 'i dunno',
        'because i', 'just because', "i don't care", 'whatever',
        'by eating', 'by giving', 'by sharing', 'everyone',
    ]
    is_off_task = any(s in student_reply for s in off_task_signals) and not has_number
    shows_understanding = any(s in student_reply for s in understanding_signals) or (has_number and not is_off_task)

    stuck_turns = sess['stuck_turns']
    worked_examples_used = sess['worked_examples_used']

    if is_off_task or (not shows_understanding and len(student_reply.split()) < 8):
        stuck_turns += 1
    else:
        stuck_turns = 0

    system_content = sess['system_prompt']
    if stuck_turns >= STUCK_THRESHOLD:
        if worked_examples_used < MAX_WORKED_EXAMPLES:
            system_content += (
                "\n\n[TUTOR INSTRUCTION — this turn only]: The student has been stuck for several turns. "
                "Say something like 'Let me try a different angle' and use a new concrete example or analogy "
                "from the same subject area to illuminate the concept. Stay within the topic from the student's "
                "diagnostic — do not switch to a different subject or introduce unrelated problems. "
                "Then ask them to try again."
            )
            worked_examples_used += 1
            stuck_turns = 0
        else:
            system_content += (
                "\n\n[TUTOR INSTRUCTION — this turn only]: The student has been stuck for a long time and you've "
                "already used your worked examples. Warmly tell them: 'I think it would really help to talk "
                "through this with your teacher — I've made a note of where we got to so they can pick up "
                "right where we left off.' Then summarise the misconception clearly in one sentence."
            )

    logs.update_stuck_state(sid, stuck_turns, worked_examples_used)

    fresh_history = logs.get_history(sid)
    messages = [{'role': 'system', 'content': system_content}] + fresh_history

    def generate():
        full_response = []
        try:
            resp = requests.post(
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json={
                    'model': config.MODEL_NAME,
                    'messages': messages,
                    'stream': True,
                    'options': {'temperature': 0.7, 'num_predict': 300},
                },
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                token = chunk.get('message', {}).get('content', '')
                if token:
                    full_response.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"

                if chunk.get('done'):
                    break

        except requests.exceptions.ConnectionError:
            yield f"data: {json.dumps({'error': 'Cannot connect to Ollama. Is it running?'})}\n\n"
            return
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        full_text = ''.join(full_response)
        reply_index = len(fresh_history) + 2
        logs.append_message(sid, 'assistant', full_text, reply_index)
        yield f"data: {json.dumps({'done': True, 'stuck_turns': stuck_turns, 'worked_examples_used': worked_examples_used})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/reset', methods=['POST'])
def reset():
    sid = _get_sid()
    if sid:
        logs.end_session(sid)
        session.pop('sid', None)
    return jsonify({'success': True})


@app.route('/api/greeting', methods=['GET'])
def greeting():
    sid = _get_sid() or get_or_create_session()
    history = logs.get_history(sid)

    if history:
        return jsonify({'reply': None})

    sess = _session_data(sid)
    student_name = sess.get('student_name', config.STUDENT_NAME)
    assigned_problem = sess.get('assigned_problem')
    messages = [
        {'role': 'system', 'content': sess['system_prompt']},
        {'role': 'user', 'content': _build_greeting_instruction(sess)},
    ]

    try:
        resp = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                'model': config.MODEL_NAME,
                'messages': messages,
                'stream': False,
                'options': {'temperature': 0.7, 'num_predict': 150},
            },
            timeout=60,
        )
        resp.raise_for_status()
        reply = resp.json()['message']['content'].strip()
        logs.append_message(sid, 'assistant', reply, 1)
        return jsonify({'reply': reply})
    except Exception:
        if assigned_problem:
            fallback = f"Hi {student_name}! Let's look at {assigned_problem}. What do you notice first?"
        else:
            fallback = f"Hi {student_name}! What part of this topic has been feeling the most confusing?"
        logs.append_message(sid, 'assistant', fallback, 1)
        return jsonify({'reply': fallback})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--dev', action='store_true')
    args = parser.parse_args()
    app.run(debug=args.dev, host='0.0.0.0', port=args.port)
