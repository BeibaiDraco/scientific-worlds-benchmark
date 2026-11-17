# Run a model on Linux

Use an unprivileged account on a clean x86-64 Linux host with bubblewrap, libseccomp, unprivileged user namespaces, Python 3.11 and the scientific packages below. The reference CI uses Ubuntu 22.04. The host runs the judge and model provider. Each participant program runs as a single, restricted process, with its work directory and read-only prior history. Keep the benchmark, the run directory, private files and keys outside the Python installation and the worker's system-library mounts. Use a clean runtime.

The first three commands install dependencies. The final two run one free engineering interaction and physically replay it.

```bash
sudo apt-get update && sudo apt-get install -y bubblewrap libseccomp2
python3.11 -m venv /tmp/sw-python
/tmp/sw-python/bin/pip install -r host/requirements.txt
/tmp/sw-python/bin/python host/run.py qualify runs/check
/tmp/sw-python/bin/python host/run.py replay runs/check
```

## Test your model

Start a local server that implements the chat completions endpoint, or use an HTTPS provider with that API. Use the exact model ID the endpoint returns. The adapter accepts a single user message, max_tokens and a non-streaming response with the model name, assistant text and integer usage.completion_tokens. Set SW_API_KEY only for endpoints that require authentication, in the operator's environment. A local Ollama example follows.

```bash
ollama pull qwen2.5-coder:1.5b
/tmp/sw-python/bin/python host/run.py run runs/my-first-session \
  --base-url http://localhost:11434/v1 --model qwen2.5-coder:1.5b \
  --family B --condition M --seed 101 --turns 2 --seconds 600 --reply-tokens 512
/tmp/sw-python/bin/python host/run.py replay runs/my-first-session
```

This example uses a public seed and a shortened development budget. Supply a new output directory for every attempt. Omit the seed to sample a new operator-private instance. Choose S (uniform modules), B (mixed module sizes), or C (coupled modules); choose N0, M, or F independently. For a full-budget self-test omit the development time and turn overrides. Configure and report the per-response cap supported by your model.

The full envelope is 12 active hours, 1.2 million returned generated tokens, 256 turns, 4,800 single-core worker CPU seconds, 2 GiB worker RSS, and 5,200 simulated capital. Provider costs depend on the chosen service. A run records one physical instance, prompt and config, model replies and usage, worker receipts, physical actions, result and independent replay in the new directory. The physical scorer accepts any legal controller. A technical error produces an unresolved result with a null delivery and exits nonzero. The model connection is never silently retried. A normal participant finish or exhausted turn budget with incomplete devices earns zero.

A full-budget run here is a self-hosted result. The November 2026 Astra series used its historical provider and host. To compare models directly, register a common panel and protocol before sampling outcomes. [Reporting guide](method.md)

## Connecting a different provider

[The adapter](../host/provider.py) makes one request per turn. Translate request and response fields there if your service uses a different schema. Retain returned identity, usage (including provider-counted reasoning tokens), timeout outcomes, and failure evidence. [Ollama API](https://docs.ollama.com/api/openai-compatibility)
