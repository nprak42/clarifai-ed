import os


PLATFORM_HOST = os.environ.get("PLATFORM_HOST", "127.0.0.1")
PLATFORM_PORT = int(os.environ.get("PLATFORM_PORT", "3000"))

ASSESSMENT_HOST = os.environ.get("ASSESSMENT_HOST", "127.0.0.1")
ASSESSMENT_PORT = int(os.environ.get("ASSESSMENT_PORT", "18080"))

TUTOR_HOST = os.environ.get("TUTOR_HOST", "127.0.0.1")
TUTOR_PORT = int(os.environ.get("TUTOR_PORT", "15001"))

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

REQUEST_TIMEOUT_SECONDS = float(os.environ.get("PLATFORM_REQUEST_TIMEOUT_SECONDS", "10"))
STARTUP_TIMEOUT_SECONDS = float(os.environ.get("PLATFORM_STARTUP_TIMEOUT_SECONDS", "20"))


def make_url(host, port):
    return f"http://{host}:{port}"


PLATFORM_BASE_URL = os.environ.get(
    "PLATFORM_BASE_URL",
    make_url(PLATFORM_HOST, PLATFORM_PORT),
)
ASSESSMENT_INTERNAL_URL = os.environ.get(
    "ASSESSMENT_INTERNAL_URL",
    make_url(ASSESSMENT_HOST, ASSESSMENT_PORT),
)
TUTOR_INTERNAL_URL = os.environ.get(
    "TUTOR_INTERNAL_URL",
    make_url(TUTOR_HOST, TUTOR_PORT),
)
TUTOR_PUBLIC_BASE_URL = os.environ.get(
    "TUTOR_PUBLIC_BASE_URL",
    f"{PLATFORM_BASE_URL.rstrip('/')}/tutor",
)
