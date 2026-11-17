"""One chat-completions request to the operator's selected endpoint."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def completion(base, model, prompt, limit, timeout):
    url = urllib.parse.urlsplit(base)
    loopback = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if (url.scheme != "https" and not (url.scheme == "http" and loopback)) or not url.hostname:
        raise ValueError("Use an HTTPS endpoint or a local HTTP server.")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Supply endpoint credentials via SW_API_KEY only.")
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("SW_API_KEY"):
        headers["Authorization"] = "Bearer " + key
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": limit, "stream": False}
    request = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                     json.dumps(payload).encode(), headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Provider response exceeds 8 MiB.")
    return json.loads(raw)


def parse_reply(raw, model):
    if raw.get("model") != model:
        raise ValueError("Returned model ID differs from the requested ID.")
    usage = raw.get("usage", {}).get("completion_tokens")
    if type(usage) is not int or usage < 0:
        raise ValueError("Missing provider-reported completion-token count.")
    message = raw["choices"][0]["message"]["content"]
    if not isinstance(message, str):
        raise ValueError("Missing assistant text.")
    return message, usage
