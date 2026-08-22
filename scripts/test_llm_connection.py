"""Standalone, secret-safe connectivity diagnostics for the configured LLM gateway."""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comic_agent.config import get_settings  # noqa: E402

SEPARATOR = "=" * 60
NOT_RUN = "NOT RUN"
CHAT_MAX_ATTEMPTS = 3
CHAT_CONNECT_TIMEOUT_SECONDS = 10.0
CHAT_READ_TIMEOUT_SECONDS = 45.0
CHAT_RETRY_DELAYS_SECONDS = (2.0, 4.0)
TRANSIENT_CHAT_CATEGORIES = {
    "TIMEOUT",
    "CONNECTION_RESET",
    "TCP_ERROR",
    "TLS_ERROR",
    "RATE_LIMIT",
    "PROVIDER_5XX",
}


@dataclass
class CheckResult:
    status: str
    category: str | None = None
    message: str | None = None


def _redact(value: str, api_key: str) -> str:
    return value.replace(api_key, "[REDACTED]") if api_key else value


def _safe_body(response: httpx.Response, api_key: str, limit: int = 500) -> str:
    text = _redact(response.text.replace("\r", " ").replace("\n", " "), api_key)
    return text[:limit] + ("..." if len(text) > limit else "")


def _endpoint(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def _classify_exception(exc: Exception) -> str:
    if isinstance(exc, (TimeoutError, socket.timeout, httpx.TimeoutException)):
        return "TIMEOUT"
    if isinstance(exc, (ssl.SSLError, httpx.ConnectError)) and "SSL" in str(exc).upper():
        return "TLS_ERROR"
    if isinstance(exc, ConnectionResetError) or "10054" in str(exc):
        return "CONNECTION_RESET"
    if isinstance(exc, socket.gaierror):
        return "DNS_ERROR"
    if isinstance(exc, (ConnectionError, httpx.NetworkError, OSError)):
        return "TCP_ERROR"
    return "UNKNOWN_ERROR"


def _http_category(status_code: int) -> str:
    if status_code in {401, 403}:
        return "AUTH_ERROR"
    if status_code == 404:
        return "MODEL_NOT_FOUND"
    if status_code == 429:
        return "RATE_LIMIT"
    if status_code >= 500:
        return "PROVIDER_5XX"
    return "HTTP_ERROR"


def _print_failure(label: str, category: str, exc: Exception, api_key: str) -> None:
    print(f"[FAIL] {label}")
    print(f"Error type: {type(exc).__name__}")
    print(f"Error: {_redact(str(exc), api_key)}")
    print(f"Category: {category}")


def check_dns(host: str, port: int, api_key: str, verbose: bool) -> CheckResult:
    print("\n[1/5] DNS")
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, port)})
    except Exception as exc:
        category = _classify_exception(exc)
        _print_failure("DNS", category, exc, api_key)
        return CheckResult("FAIL", category, str(exc))
    print("[PASS] DNS")
    print(f"Host: {host}")
    if verbose:
        print("Resolved IPs:")
        for address in addresses:
            print(f"  {address}")
    else:
        print(f"Resolved addresses: {len(addresses)}")
    return CheckResult("PASS")


def check_tcp(host: str, port: int, api_key: str, timeout: float) -> CheckResult:
    print(f"\n[2/5] TCP {port}")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except Exception as exc:
        category = _classify_exception(exc)
        _print_failure(f"TCP {port}", category, exc, api_key)
        return CheckResult("FAIL", category, str(exc))
    print(f"[PASS] TCP {port}")
    print("Connection established")
    return CheckResult("PASS")


def check_https(
    client: httpx.Client, base_url: str, api_key: str, verbose: bool
) -> CheckResult:
    print("\n[3/5] HTTPS")
    started = perf_counter()
    try:
        response = client.get(base_url)
    except Exception as exc:
        category = _classify_exception(exc)
        _print_failure("HTTPS transport", category, exc, api_key)
        return CheckResult("FAIL", category, str(exc))
    print("[PASS] HTTPS transport")
    print(f"HTTP status: {response.status_code}")
    print("TLS/HTTP connection successfully reached server")
    if verbose:
        print(f"Elapsed: {(perf_counter() - started) * 1000:.0f} ms")
    return CheckResult("PASS")


def check_models(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    models: list[str],
    api_key: str,
    verbose: bool,
) -> CheckResult:
    print("\n[4/5] Models API")
    url = _endpoint(base_url, "models")
    started = perf_counter()
    try:
        response = client.get(url, headers=headers)
    except Exception as exc:
        category = _classify_exception(exc)
        _print_failure("Models API", category, exc, api_key)
        return CheckResult("FAIL", category, str(exc))
    print(f"HTTP status: {response.status_code}")
    if response.status_code in {404, 405}:
        print("[UNSUPPORTED] Models API")
        print("HTTP transport works, but the /models endpoint is unsupported.")
        return CheckResult("UNSUPPORTED", "HTTP_ERROR")
    if response.status_code != 200:
        category = _http_category(response.status_code)
        print("[FAIL] Models API")
        print(f"Category: {category}")
        if verbose:
            print(f"Response: {_safe_body(response, api_key)}")
        return CheckResult("FAIL", category)
    try:
        payload = response.json()
        items = payload.get("data", []) if isinstance(payload, dict) else []
        returned = [str(item["id"]) for item in items if isinstance(item, dict) and "id" in item]
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        _print_failure("Models API", "INVALID_JSON_RESPONSE", exc, api_key)
        return CheckResult("FAIL", "INVALID_JSON_RESPONSE", str(exc))
    print("[PASS] Models API")
    print(f"Models returned: {len(returned)}")
    for model in dict.fromkeys(models):
        print(f"Configured model {model!r} found: {'yes' if model in returned else 'no'}")
    if verbose and returned:
        print(f"Model summary: {', '.join(returned[:10])}")
        print(f"Elapsed: {(perf_counter() - started) * 1000:.0f} ms")
    return CheckResult("PASS")


def check_chat(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    model: str,
    api_key: str,
    verbose: bool,
) -> CheckResult:
    print("\n[5/5] Chat Completions")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复：USTC LLM connection OK"}],
        "max_tokens": 32,
        "stream": False,
    }
    chat_timeout = httpx.Timeout(
        CHAT_READ_TIMEOUT_SECONDS,
        connect=CHAT_CONNECT_TIMEOUT_SECONDS,
    )
    last_result = CheckResult("FAIL", "UNKNOWN_ERROR")
    for attempt in range(1, CHAT_MAX_ATTEMPTS + 1):
        started = perf_counter()
        try:
            response = client.post(
                _endpoint(base_url, "chat/completions"),
                headers=headers,
                json=payload,
                timeout=chat_timeout,
            )
        except Exception as exc:
            category = _classify_exception(exc)
            last_result = CheckResult("FAIL", category, str(exc))
            print(
                f"[WARN] Chat Completions attempt {attempt}/{CHAT_MAX_ATTEMPTS}: "
                f"{category}"
            )
            if category not in TRANSIENT_CHAT_CATEGORIES or attempt == CHAT_MAX_ATTEMPTS:
                _print_failure("Chat Completions", category, exc, api_key)
                return last_result
            time.sleep(CHAT_RETRY_DELAYS_SECONDS[attempt - 1])
            continue

        print(f"HTTP status: {response.status_code}")
        if response.status_code != 200:
            category = _http_category(response.status_code)
            last_result = CheckResult("FAIL", category)
            if category in TRANSIENT_CHAT_CATEGORIES and attempt < CHAT_MAX_ATTEMPTS:
                print(
                    f"[WARN] Chat Completions attempt {attempt}/{CHAT_MAX_ATTEMPTS}: "
                    f"{category}"
                )
                if verbose:
                    print(f"Response: {_safe_body(response, api_key)}")
                time.sleep(CHAT_RETRY_DELAYS_SECONDS[attempt - 1])
                continue
            print("[FAIL] Chat Completions")
            print(f"Category: {category}")
            print(f"Response: {_safe_body(response, api_key)}")
            return last_result

        try:
            data = response.json()
            choices = data.get("choices", []) if isinstance(data, dict) else []
            content = choices[0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("choices[0].message.content is not a string")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            _print_failure("Chat Completions", "INVALID_JSON_RESPONSE", exc, api_key)
            return CheckResult("FAIL", "INVALID_JSON_RESPONSE", str(exc))
        print(f"[PASS] Chat Completions attempt {attempt}/{CHAT_MAX_ATTEMPTS}")
        print(f"Model: {model}")
        print(f"Response: {content.strip()}")
        if verbose:
            print(f"Elapsed: {(perf_counter() - started) * 1000:.0f} ms")
        return CheckResult("PASS")
    return last_result


def _summary(
    results: dict[str, CheckResult], override_category: str | None = None
) -> str:
    print(f"\n{SEPARATOR}")
    print("FINAL RESULT")
    print(SEPARATOR)
    labels = {
        "dns": "DNS",
        "tcp": "TCP 443",
        "https": "HTTPS",
        "models": "Models API",
        "chat": "Chat Completions",
    }
    for key, label in labels.items():
        print(f"{label + ':':18} {results[key].status}")
    if override_category is not None:
        category = override_category
        cause = "Required LLM configuration is missing or invalid."
    elif results["chat"].status == "PASS":
        category = "SUCCESS"
        cause = "LLM gateway is ready for project E2E testing."
    else:
        failed = next(
            (result for result in results.values() if result.status == "FAIL"),
            CheckResult("FAIL", "UNKNOWN_ERROR"),
        )
        category = failed.category or "UNKNOWN_ERROR"
        cause = {
            "CONFIG_ERROR": "Required LLM configuration is missing or invalid.",
            "DNS_ERROR": "The configured gateway hostname could not be resolved.",
            "TCP_ERROR": "School VPN or routing is not reaching the gateway TCP port.",
            "CONNECTION_RESET": "The connection was reset; check VPN and gateway routing.",
            "TIMEOUT": "The gateway or network route timed out.",
            "TLS_ERROR": "TLS negotiation with the gateway failed.",
            "AUTH_ERROR": "The configured API key was rejected.",
            "MODEL_NOT_FOUND": "The configured model or endpoint was not found.",
            "RATE_LIMIT": "The gateway rate limit was reached.",
            "PROVIDER_5XX": "The provider returned a server-side failure.",
            "INVALID_JSON_RESPONSE": "The provider response did not match the expected JSON shape.",
        }.get(category, "Review the failed stage above for the provider error.")
    print(f"\nResult: {category}")
    print(f"\nLikely cause:\n{cause}")
    return category


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Temporarily override LLM_MODEL for this test.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print(SEPARATOR)
    print("LLM Connectivity Test")
    print(SEPARATOR)
    settings = get_settings()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    model = args.model or settings.llm_model
    base_url = settings.llm_base_url.strip()
    timeline_model = settings.timeline_model or model
    print("\n[CONFIG]")
    print(f"ENABLE_REAL_LLM: {str(settings.enable_real_llm).lower()}")
    print(f"LLM_BASE_URL: {base_url or 'missing'}")
    print(f"LLM_MODEL: {model or 'missing'}")
    print(f"TIMELINE_MODEL: {timeline_model or 'missing'}")
    print(f"LLM_API_KEY: {'configured' if api_key else 'missing'}")

    results = {key: CheckResult(NOT_RUN) for key in ("dns", "tcp", "https", "models", "chat")}
    missing = [
        name
        for name, value in {
            "LLM_BASE_URL": base_url,
            "LLM_MODEL": model,
            "LLM_API_KEY": api_key,
        }.items()
        if not value
    ]
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        missing.append("valid LLM_BASE_URL")
    if missing:
        print("\n[FAIL] CONFIG")
        print(f"Missing/invalid: {', '.join(missing)}")
        category = _summary(results, "CONFIG_ERROR")
        return 1 if category != "SUCCESS" else 0

    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    results["dns"] = check_dns(host, port, api_key, args.verbose)
    if results["dns"].status == "PASS":
        results["tcp"] = check_tcp(host, port, api_key, args.timeout)
    if results["tcp"].status == "PASS":
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
            results["https"] = check_https(client, base_url, api_key, args.verbose)
            if results["https"].status == "PASS":
                results["models"] = check_models(
                    client,
                    base_url,
                    headers,
                    [model, timeline_model],
                    api_key,
                    args.verbose,
                )
                results["chat"] = check_chat(
                    client, base_url, headers, model, api_key, args.verbose
                )
    return 0 if _summary(results) == "SUCCESS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        raise SystemExit(130) from None
