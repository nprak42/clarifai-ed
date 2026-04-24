"""
Configuration for the Socratic tutor app.
Swap these values to test different models or student profiles.
"""
import os

# Model
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemma2:9b")

# Student profile (hardcoded for Pass 1)
STUDENT_NAME = os.environ.get("STUDENT_NAME", "Student")
TARGET_MISCONCEPTION = os.environ.get(
    "TARGET_MISCONCEPTION",
    "Adding numerators and denominators directly when adding fractions",
)
DIAGNOSTIC_NOTES = (
    os.environ.get(
        "DIAGNOSTIC_NOTES",
        "Student understands basic fraction notation but struggles with fraction operations. "
        "Tends to add numerators and denominators separately (e.g. 1/3 + 1/4 = 2/7). "
        "Performs better on concrete/visual problems than abstract ones.",
    )
)
# Set to None to let the student bring their own question
ASSIGNED_PROBLEM = os.environ.get("ASSIGNED_PROBLEM", "What is 1/3 + 1/4?")
if ASSIGNED_PROBLEM == "":
    ASSIGNED_PROBLEM = None

# Session settings
MAX_CONVERSATION_LENGTH = int(os.environ.get("MAX_CONVERSATION_LENGTH", "50"))

# Assessment tool base URL (for fetching student diagnostic context)
ASSESSMENT_TOOL_BASE_URL = os.environ.get(
    "ASSESSMENT_TOOL_BASE_URL",
    "http://localhost:8080",
)

# Allowlist of trusted origins for the ?cb= callback parameter on /start/<token>.
# The tutor makes a server-side request to cb/api/student_context/<token>, so only
# known assessment tool origins should be accepted.
# Comma-separated, e.g. "http://localhost:8080,https://clarifai.example.com"
_cb_raw = os.environ.get("ALLOWED_CB_ORIGINS", ASSESSMENT_TOOL_BASE_URL)
ALLOWED_CB_ORIGINS = {o.rstrip('/') for o in _cb_raw.split(',') if o.strip()}
