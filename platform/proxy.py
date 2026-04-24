import os

import requests
from flask import Flask, Response, jsonify, request, stream_with_context

import config

app = Flask(__name__, static_folder=None)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


def split_target(path):
    if path == "tutor" or path.startswith("tutor/"):
        suffix = path[len("tutor"):].lstrip("/")
        return config.TUTOR_INTERNAL_URL.rstrip("/"), suffix
    return config.ASSESSMENT_INTERNAL_URL.rstrip("/"), path


def build_target_url(base_url, path):
    url = f"{base_url}/{path}" if path else base_url
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8')}"
    return url


def forwarded_headers():
    headers = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS or lower == "host":
            continue
        headers[key] = value

    headers["X-Forwarded-For"] = request.remote_addr or ""
    headers["X-Forwarded-Proto"] = request.scheme
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Prefix"] = "/tutor" if request.path.startswith("/tutor") else ""
    return headers


def rewrite_location(value):
    if not value:
        return value

    if value.startswith("/"):
        if value == "/tutor" or value.startswith("/tutor/"):
            return value
        return f"/tutor{value}" if request.path.startswith("/tutor") else value

    mappings = (
        (config.TUTOR_INTERNAL_URL.rstrip("/"), f"{config.PLATFORM_BASE_URL.rstrip('/')}/tutor"),
        (config.ASSESSMENT_INTERNAL_URL.rstrip("/"), config.PLATFORM_BASE_URL.rstrip("/")),
    )
    for internal_base, public_base in mappings:
        if value.startswith(internal_base):
            return public_base + value[len(internal_base):]
    return value


def response_headers(upstream):
    headers = []
    for key, value in upstream.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in {"content-length", "set-cookie"}:
            continue
        if lower == "location":
            value = rewrite_location(value)
        headers.append((key, value))

    raw_headers = getattr(upstream.raw, "headers", None)
    if raw_headers and hasattr(raw_headers, "getlist"):
        for cookie in raw_headers.getlist("Set-Cookie"):
            headers.append(("Set-Cookie", cookie))
    return headers


def proxy_request(path):
    base_url, upstream_path = split_target(path)
    target_url = build_target_url(base_url, upstream_path)

    try:
        upstream = requests.request(
            method=request.method,
            url=target_url,
            headers=forwarded_headers(),
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True,
            timeout=(config.REQUEST_TIMEOUT_SECONDS, None),
        )
    except requests.RequestException as exc:
        return jsonify({
            "error": "Upstream service unavailable",
            "detail": str(exc),
            "target": target_url,
        }), 502

    headers = response_headers(upstream)

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(
        stream_with_context(generate()),
        status=upstream.status_code,
        headers=headers,
    )


@app.route("/health", methods=["GET"])
def health():
    checks = {
        "assessment": config.ASSESSMENT_INTERNAL_URL,
        "tutor": config.TUTOR_INTERNAL_URL,
        "ollama": f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/tags",
    }
    results = {}
    overall_ok = True

    for name, url in checks.items():
        try:
            resp = requests.get(url, timeout=3)
            results[name] = {"ok": resp.ok, "status_code": resp.status_code}
            overall_ok = overall_ok and resp.ok
        except requests.RequestException as exc:
            results[name] = {"ok": False, "error": str(exc)}
            overall_ok = False

    status = 200 if overall_ok else 503
    return jsonify({"ok": overall_ok, "checks": results}), status


@app.route("/tutor", defaults={"path": ""}, methods=ALL_METHODS)
@app.route("/tutor/", defaults={"path": ""}, methods=ALL_METHODS)
@app.route("/tutor/<path:path>", methods=ALL_METHODS)
def tutor_proxy(path):
    tutor_path = "tutor"
    if path:
        tutor_path = f"tutor/{path}"
    return proxy_request(tutor_path)


@app.route("/", defaults={"path": ""}, methods=ALL_METHODS)
@app.route("/<path:path>", methods=ALL_METHODS)
def assessment_proxy(path):
    return proxy_request(path)


if __name__ == "__main__":
    app.run(
        host=os.environ.get("PLATFORM_PROXY_HOST", config.PLATFORM_HOST),
        port=int(os.environ.get("PLATFORM_PROXY_PORT", str(config.PLATFORM_PORT))),
        debug=os.environ.get("PLATFORM_PROXY_DEBUG") == "1",
        threaded=True,
    )
