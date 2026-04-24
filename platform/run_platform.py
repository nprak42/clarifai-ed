import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import requests

import config

ROOT = Path(__file__).resolve().parent.parent


def wait_for_http(url, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=1.5)
            return resp.status_code
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"{url} did not become ready: {last_error}")


def check_http(url, timeout_seconds=2):
    try:
        resp = requests.get(url, timeout=timeout_seconds)
        return True, resp.status_code, None
    except requests.RequestException as exc:
        return False, None, str(exc)


def start_process(name, cmd, workdir, env):
    process = subprocess.Popen(
        cmd,
        cwd=workdir,
        env=env,
    )
    return {"name": name, "process": process}


def stop_processes(processes):
    for entry in reversed(processes):
        process = entry["process"]
        if process.poll() is None:
            process.terminate()

    deadline = time.time() + 5
    while time.time() < deadline:
        if all(entry["process"].poll() is not None for entry in processes):
            return
        time.sleep(0.1)

    for entry in reversed(processes):
        process = entry["process"]
        if process.poll() is None:
            process.kill()


def build_common_env():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PLATFORM_BASE_URL"] = config.PLATFORM_BASE_URL
    env["OLLAMA_BASE_URL"] = config.OLLAMA_BASE_URL
    return env


def print_preflight():
    ollama_url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    ok, status, error = check_http(ollama_url)
    if ok:
        print(f"Ollama check: OK ({ollama_url}, status {status})")
        return True

    print(f"Ollama check: unavailable at {ollama_url}")
    print("The platform will still start, but tutor replies will fail until Ollama is running.")
    print("Start it with `ollama serve` in another terminal.\n")
    if error:
        print(f"Details: {error}\n")
    return False


def maybe_open_browser():
    should_open = os.environ.get("PLATFORM_OPEN_BROWSER", "0") == "1"
    if not should_open:
        return

    try:
        webbrowser.open(config.PLATFORM_BASE_URL)
        print(f"Opened browser at {config.PLATFORM_BASE_URL}")
    except Exception as exc:
        print(f"Could not open browser automatically: {exc}")


def main():
    common_env = build_common_env()
    processes = []
    dev_mode = os.environ.get("PLATFORM_DEV") == "1"
    print_preflight()

    assessment_env = common_env.copy()
    assessment_env["TUTOR_BASE_URL"] = config.TUTOR_PUBLIC_BASE_URL
    assessment_env["ASSESSMENT_SESSION_COOKIE_NAME"] = "clarifai_assessment_session"

    tutor_env = common_env.copy()
    tutor_env["ASSESSMENT_TOOL_BASE_URL"] = config.ASSESSMENT_INTERNAL_URL
    tutor_env["TUTOR_SESSION_COOKIE_NAME"] = "clarifai_tutor_session"

    proxy_env = common_env.copy()
    proxy_env["ASSESSMENT_INTERNAL_URL"] = config.ASSESSMENT_INTERNAL_URL
    proxy_env["TUTOR_INTERNAL_URL"] = config.TUTOR_INTERNAL_URL
    proxy_env["PLATFORM_PROXY_HOST"] = config.PLATFORM_HOST
    proxy_env["PLATFORM_PROXY_PORT"] = str(config.PLATFORM_PORT)
    if dev_mode:
        proxy_env["PLATFORM_PROXY_DEBUG"] = "1"

    try:
        processes.append(start_process(
            "assessment-tool",
            [sys.executable, "-u", "app.py", "--port", str(config.ASSESSMENT_PORT)]
            + (["--dev"] if dev_mode else []),
            ROOT / "assessment-tool",
            assessment_env,
        ))
        wait_for_http(config.ASSESSMENT_INTERNAL_URL, config.STARTUP_TIMEOUT_SECONDS)

        processes.append(start_process(
            "socratic-tutor",
            [sys.executable, "-u", "app.py", "--port", str(config.TUTOR_PORT)]
            + (["--dev"] if dev_mode else []),
            ROOT / "socratic-tutor",
            tutor_env,
        ))
        wait_for_http(config.TUTOR_INTERNAL_URL, config.STARTUP_TIMEOUT_SECONDS)

        processes.append(start_process(
            "platform-proxy",
            [sys.executable, "-u", "proxy.py"],
            ROOT / "platform",
            proxy_env,
        ))
        wait_for_http(config.PLATFORM_BASE_URL, config.STARTUP_TIMEOUT_SECONDS)
    except Exception:
        stop_processes(processes)
        raise

    print("\nClarifai platform is ready")
    print(f"Open:        {config.PLATFORM_BASE_URL}")
    print(f"Assessment:  {config.ASSESSMENT_INTERNAL_URL}")
    print(f"Tutor:       {config.TUTOR_INTERNAL_URL}")
    print(f"Ollama:      {config.OLLAMA_BASE_URL}")
    if dev_mode:
        print("Mode:        dev")
    print("Stop:        Ctrl+C\n")
    maybe_open_browser()

    def handle_shutdown(signum, frame):
        stop_processes(processes)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    while True:
        for entry in processes:
            code = entry["process"].poll()
            if code is not None:
                stop_processes(processes)
                raise SystemExit(f"{entry['name']} exited unexpectedly with code {code}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
