# Clarifai

A diagnostic assessment tool and Socratic tutor for grade 8–9 math and science.

Teachers run a short diagnostic test with their class. Every wrong answer maps to a specific misconception. The dashboard shows which students have which gaps — not just scores, but *why* they're struggling. From there, a teacher can launch a one-on-one AI tutor session for any student, pre-loaded with that student's specific misconceptions.

The tutor never gives answers. It asks questions.

---

## What's included

**7 diagnostic tests** across grade 8–9 math and science:

| Subject | Grade | Questions |
|---|---|---|
| Electricity (Ohm's Law, circuits, resistance) | 9 | 15 |
| Linear Equations | 8 | 15 |
| Algebraic Expressions | 8 | 15 |
| Ratios & Proportions | 8 | 15 |
| Simple Interest | 8 | 15 |
| Triangles | 8 | 15 |
| Quadrilaterals | 8 | 15 |

Each test has:
- 15 MCQ questions with shuffled correct answers (not always option A)
- Every wrong answer mapped to a named misconception with severity and root cause
- Pattern detection logic that identifies clusters of related misconceptions

---

## How it works

```
Student takes test → Teacher sees misconception patterns on dashboard
                   → Teacher clicks "Start Tutor" for a struggling student
                   → Tutor session opens pre-loaded with that student's gaps
                   → Tutor probes understanding through Socratic questioning
```

The tutor runs on a local LLM (gemma2:9b via Ollama). No student data leaves your machine.

---

## Running it

### What you need

- Python 3.10+
- PostgreSQL
- [Ollama](https://ollama.com) with gemma2:9b pulled

```bash
ollama pull gemma2:9b
```

### Setup

```bash
# 1. Clone and install dependencies
git clone https://github.com/your-username/clarifai
cd clarifai
pip install -r assessment-tool/requirements.txt

# 2. Create the database
createdb clarifai
psql clarifai -f schema.sql

# 3. Set environment variables
export DATABASE_URL="postgresql://localhost/clarifai"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

# 4. Load the test data
cd assessment-tool
python load_data.py
cd ..
```

### Running

```bash
# Terminal 1 — start the LLM
ollama serve

# Terminal 2 — start the platform
python platform/run_platform.py
```

Open [http://localhost:3000](http://localhost:3000).

For debug mode: `PLATFORM_DEV=1 python platform/run_platform.py`

### Simulating test data (optional)

To populate the dashboard with fake student responses before trying it with a real class:

```bash
python assessment-tool/simulate_session.py --test elec_grade9 --students 30
python assessment-tool/simulate_session.py --test linear_equations_grade8 --students 25
```

Other test IDs: `algebraic_expressions_grade8`, `ratios_proportions_grade8`, `simple_interest_grade8`, `triangles_grade8`, `quadrilaterals_grade8`

---

## For teachers

**Creating a session:**
1. Go to [http://localhost:3000](http://localhost:3000)
2. Click "New Session", pick the test, enter your class details
3. Share the access code with students — they enter it on the same URL
4. Watch responses come in live; the dashboard updates as students submit

**Reading the dashboard:**
- Each card is a detected learning pattern — a cluster of related misconceptions
- Risk levels (Low / Medium / High / Critical) indicate how much this gap will hurt in grade 10 boards
- Click a pattern card to see which students are affected and what specifically they misunderstand
- Click "Start Tutor" next to any student to launch a personalised tutor session for them

**The tutor:**
- Opens pre-loaded with that student's specific misconceptions
- Uses Socratic questioning — it will not give answers, only ask questions that lead the student to the answer themselves
- Responses take 5–15 seconds (local LLM — no internet required)

---

## Project structure

```
clarifai/
  assessment-tool/     # Flask app — diagnostic tests, dashboard, session management
    app.py             # Routes
    database.py        # Postgres queries
    analysis.py        # Pattern detection and session analytics
    load_data.py       # Populate DB from data/ JSON files
    simulate_session.py
    data/              # Questions, misconceptions, patterns per subject
    templates/
    static/
  socratic-tutor/      # Flask app — Socratic chat tutor (local LLM)
    app.py             # Routes, session state, stuck-turn escalation
    logs.py            # Postgres session and message storage
    config.py
    prompts/
      socratic_fractions.py   # System prompt builder
      context_builder.py      # Builds diagnostic context from assessment data
    eval/              # Model eval harness, 13 adversarial scenarios
    templates/
    static/
  platform/            # Single-origin runner and reverse proxy
    run_platform.py    # Starts both apps + proxy, health-checks each
    proxy.py           # Routes /tutor/* → tutor, /* → assessment
    config.py
  schema.sql           # Postgres schema (assessment + tutor schemas)
  db.py                # Shared connection pool
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Required. Postgres connection string |
| `SECRET_KEY` | — | Required. Flask session signing key |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama server URL |
| `MODEL_NAME` | `gemma2:9b` | Ollama model to use for tutor |
| `SECURE_COOKIES` | `0` | Set to `1` when running behind HTTPS |
| `ALLOWED_CB_ORIGINS` | value of `ASSESSMENT_TOOL_BASE_URL` | Comma-separated trusted origins for tutor token handoff |
| `PLATFORM_DEV` | `0` | Set to `1` for debug mode |

---

## Contributing

The most useful contributions right now:

- **New diagnostic tests** — the data format is in `assessment-tool/data/`. Each subject needs a `questions_<subject>.json`, `misconceptions_<subject>.json`, and `patterns_<subject>.json`. Polynomials and chemical reactions are the biggest gaps for the grade 9 syllabus.
- **Subject-specific tutor opening questions** — `socratic-tutor/prompts/context_builder.py` has opening question hooks for electricity and some math subjects. The grade 8 math subjects need better subject-specific openers.
- **Language support** — the tutor prompt and question bank are English-only. Hindi support would significantly expand reach.
- **Eval harness** — `socratic-tutor/eval/` has 13 adversarial scenarios testing Socratic rule adherence. More scenarios, especially subject-specific ones, improve model selection confidence.

---

## Why local LLM

Student diagnostic data — names, wrong answers, learning gaps — is sensitive. Running the tutor model locally means no student data is sent to any external service. It also works on school WiFi that blocks external traffic, and has no per-query cost.

The tradeoff is setup complexity and slower responses. A future version will support API-hosted models behind a teacher-controlled proxy for schools that prefer managed infrastructure.

---

## Motivation

Grade 9 is the last real intervention window before board exams. A student who reaches grade 10 with a foundational misconception in algebra or physics is already behind, and exam pressure leaves no time to go back. Most diagnostic tools tell teachers that students are struggling. This one tells them why — and then does something about it.
