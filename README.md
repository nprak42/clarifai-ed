# Clarifai

A teacher co-pilot for acting on student misconceptions at classroom scale.

Teachers run a short diagnostic test with their class. Every wrong answer maps to a named misconception. The dashboard shows which students have which gaps and why — not just scores. From there, a teacher gets a specific, ready-to-use intervention plan from an AI co-pilot, and can refine it through a follow-up chat.

---

## What's included

**8 diagnostic tests** across grade 8–10 math and science:

| Subject | Grade | Questions |
|---|---|---|
| Electricity (Ohm's Law, circuits, resistance) | 9 | 15 |
| Trig Prerequisites (ratios, similarity, Pythagoras) | 10 | 15 |
| Linear Equations | 8 | 15 |
| Algebraic Expressions | 8 | 15 |
| Ratios & Proportions | 8 | 15 |
| Simple Interest | 8 | 15 |
| Triangles | 8 | 15 |
| Quadrilaterals | 8 | 15 |

Each test has:
- 15 MCQ questions with shuffled correct answers
- Every wrong answer mapped to a named misconception with severity and root cause
- Pattern detection that identifies clusters of related misconceptions

---

## How it works

```
Student takes test → Teacher sees misconception patterns on dashboard
                   → Teacher clicks "Get Intervention Plan"
                   → Co-pilot generates a specific, ready-to-use classroom plan
                   → Teacher refines it through follow-up chat
```

The co-pilot is backed by Gemini. It is given the class's actual diagnostic data — which patterns were detected, how many students, what the root causes are — and generates plans tied directly to that evidence, not generic teaching advice.

---

## Running it

### What you need

- Python 3.10+
- PostgreSQL
- A [Google AI Studio](https://aistudio.google.com) API key (free tier works)

### Setup

```bash
git clone https://github.com/your-username/clarifai
cd clarifai

pip install -r assessment-tool/requirements.txt

# Create the database schema
createdb clarifai
psql clarifai -f schema.sql

# Set environment variables
export DATABASE_URL="postgresql://localhost/clarifai"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export GOOGLE_API_KEY="your-api-key-here"

# Load test data
cd assessment-tool
python load_data.py
```

### Running

```bash
cd assessment-tool
python app.py
```

Open [http://localhost:8080](http://localhost:8080).

### Simulating test data (optional)

To populate the dashboard with fake student responses before trying it with a real class:

```bash
python simulate_session.py --test elec_grade9 --students 30
python simulate_session.py --test linear_equations_grade8 --students 25
```

Other test IDs: `algebraic_expressions_grade8`, `ratios_proportions_grade8`, `simple_interest_grade8`, `triangles_grade8`, `quadrilaterals_grade8`, `trig_prerequisites_grade10`

---

## For teachers

**Running a diagnostic:**
1. Go to the home page and click "New Session"
2. Pick a test and enter your class details
3. Share the access code with students — they enter it at the same URL
4. Watch responses come in live; the dashboard updates as students submit

**Reading the dashboard:**
- Each card is a detected learning pattern — a cluster of related misconceptions
- Risk levels (CRITICAL / HIGH / MEDIUM) indicate impact on grade 10 boards
- Click a pattern card to see which students are affected and what they specifically misunderstand

**Getting an intervention plan:**
- Click "Get Intervention Plan" on any session dashboard
- The co-pilot reads the actual diagnostic data and returns a structured plan:
  - Priority misconception with root cause
  - A concrete classroom move for tomorrow
  - A grouping suggestion based on the data
  - What to listen for (resolution signals)
  - Follow-up problems to expose the gap and confirm resolution
- Use the chat input to refine: "I only have 15 minutes", "change the grouping", "suggest a different analogy"

---

## Deploying (Railway)

The app deploys as a single service from `assessment-tool/`.

1. Push the repo to GitHub
2. New Railway project → Deploy from GitHub → set root directory to `assessment-tool/`
3. Add a Postgres plugin (Railway sets `DATABASE_URL` automatically)
4. Set environment variables: `SECRET_KEY`, `GOOGLE_API_KEY`, `SECURE_COOKIES=1`
5. Open a Railway shell and run `python load_data.py` once to seed the database

---

## Project structure

```
clarifai/
  assessment-tool/       # The deployable app
    app.py               # Flask routes
    database.py          # Postgres queries
    analysis.py          # Pattern detection and session analytics
    copilot.py           # Adapter + Gemini calls for teacher co-pilot
    load_data.py         # Populate DB from data/ JSON files
    simulate_session.py  # Generate fake student responses for testing
    data/                # Questions, misconceptions, patterns per subject
    templates/
    static/
    Dockerfile
    railway.json
  teacher-copilot/
    prompt_test.py       # Offline prompt iteration against simulated class data
  schema.sql             # Postgres schema
  db.py                  # Shared connection pool
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Required. Postgres connection string |
| `SECRET_KEY` | — | Required. Flask session signing key |
| `GOOGLE_API_KEY` | — | Required. Gemini API key for the co-pilot |
| `SECURE_COOKIES` | `0` | Set to `1` when running behind HTTPS |

---

## Contributing

Most useful right now:

- **New diagnostic tests** — data format is in `assessment-tool/data/`. Each subject needs `questions_<subject>.json`, `misconceptions_<subject>.json`, and `patterns_<subject>.json`. Polynomials and quadratic equations are the biggest gaps for the grade 10 syllabus.
- **Pedagogical review of co-pilot strategies** — the quality of the intervention plans depends on the quality of the `intervention_focus` and `diagnosis` fields in the patterns data. Subject-matter feedback on whether the suggested approaches are actually sound is the most valuable contribution.
- **Language support** — the question bank and co-pilot prompts are English-only. Hindi support would significantly expand reach.

---

## Motivation

Grade 9 is the last real intervention window before board exams. A student who reaches grade 10 with a foundational misconception in algebra or physics is already behind, and exam pressure leaves no time to go back. Most diagnostic tools tell teachers that students are struggling. This one tells them why — and then helps the teacher do something about it.
