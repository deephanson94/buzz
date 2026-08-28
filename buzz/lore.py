"""`buzz analyze --lore`: the semantic layer, automated.

An LLM reads the map plus the head of each source file and produces three
things in one pass:
  1. lore quests  - "where does behavior X live?" - validated by
     author.apply_authored (answer must resolve, never leak, etc.)
  2. district briefs - a one-line "what this cluster is for" per zone
  3. module glosses  - a one-line purpose for modules with NO docstring

Design rule #14 holds: LLM prose is never XP ground truth. Quest answers
stay mechanically checkable; briefs and glosses are flavor, displayed as
clearly-marked "scout's impressions", and worth 0 XP.

Transports, in order: BUZZ_LORE_CMD (any command: brief on stdin, JSON on
stdout), BUZZ_LORE_URL (any OpenAI-compatible /v1 endpoint, stdlib only),
the `anthropic` Python SDK (any credentials the SDK resolves), then the
`claude` CLI in non-interactive mode. All failures degrade to a plain
world plus a printed hint - --lore must never break analyze.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .model import World
from . import author

MODEL = "claude-opus-5"
HEAD_LINES = 30           # per-file source glimpse in the brief
MAX_BRIEF_CHARS = 180_000  # keep the request sane on big repos


class LoreUnavailable(Exception):
    """No usable LLM transport; carries user-facing guidance."""


def build_brief(world: World) -> str:
    """The authoring request: map facts + source heads + the contract."""
    base = author.export_brief(world)
    heads = {}
    budget = MAX_BRIEF_CHARS
    for m in sorted(world.modules,
                    key=lambda m: -world.modules[m].pagerank):
        try:
            text = (Path(world.repo) / world.modules[m].path).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[:HEAD_LINES])[:4000]
        if budget - len(head) < 0:
            break
        budget -= len(head)
        heads[m] = head
    no_doc = sorted(m for m in world.modules if not world.modules[m].doc)
    payload = {
        "map": base,
        "source_heads": heads,
        "modules_missing_docstrings": no_doc,
    }
    return (
        "You are the lore author for buzz, a game that teaches how a repo "
        "works. Below is the analyzed map of a repository and the head of "
        "each source file.\n\n"
        "Return ONE JSON object (no markdown fences, no prose) with keys:\n"
        '  "quests": a JSON list following map.contract exactly - about '
        "questions_per_zone per district, asking WHERE a behavior or "
        "responsibility lives, written in the game's voice per "
        "map.contract.voice;\n"
        '  "zone_briefs": {zone-id: one-sentence description of what that '
        "district collectively does};\n"
        '  "glosses": {module-name: one-line purpose} for every module in '
        "modules_missing_docstrings (from its source head; write nothing "
        "you cannot see evidence for).\n\n"
        + json.dumps(payload)
    )


def _call_sdk(prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise LoreUnavailable("anthropic SDK not installed")
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL, max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise LoreUnavailable("anthropic SDK found no working credentials")
    return "".join(b.text for b in response.content if b.type == "text")


def _call_cli(prompt: str) -> str:
    exe = shutil.which("claude")
    if not exe:
        raise LoreUnavailable("no `claude` CLI on PATH")
    r = subprocess.run([exe, "-p", "--output-format", "text"],
                       input=prompt, capture_output=True, text=True,
                       timeout=600)
    if r.returncode != 0:
        raise LoreUnavailable(f"claude CLI failed: {r.stderr.strip()[:200]}")
    return r.stdout


def _call_openai_compat(prompt: str) -> str:
    """Any OpenAI-compatible chat endpoint (a company gateway, Ollama,
    vLLM, ...) via BUZZ_LORE_URL + BUZZ_LORE_MODEL (+ optional
    BUZZ_LORE_KEY). Stdlib only - no new dependency."""
    import urllib.error
    import urllib.request
    url = os.environ["BUZZ_LORE_URL"]
    model = os.environ.get("BUZZ_LORE_MODEL")
    if not model:
        raise LoreUnavailable("BUZZ_LORE_URL is set but BUZZ_LORE_MODEL "
                              "is not - the gateway needs a model id")
    endpoint = url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("BUZZ_LORE_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(endpoint, headers=headers, data=json.dumps({
        "model": model, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }).encode())
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:200]
        except Exception:
            detail = ""
        raise LoreUnavailable(f"{endpoint} returned HTTP {e.code}: {detail}")
    except Exception as e:
        raise LoreUnavailable(f"could not reach {endpoint}: {e}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        content = None
    if not isinstance(content, str) or not content.strip():
        raise LoreUnavailable(f"unexpected response shape from {endpoint} "
                              f"(no choices[0].message.content text)")
    return content


def _call_custom(cmd: str, prompt: str) -> str:
    r = subprocess.run(cmd, shell=True, input=prompt,
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise LoreUnavailable(
            f"BUZZ_LORE_CMD failed: {r.stderr.strip()[:200]}")
    return r.stdout


def _transport(prompt: str) -> str:
    cmd = os.environ.get("BUZZ_LORE_CMD")
    if cmd:
        return _call_custom(cmd, prompt)
    if os.environ.get("BUZZ_LORE_URL"):
        # an explicitly configured gateway never falls back to the SDK -
        # failing loudly beats silently talking to a different provider
        return _call_openai_compat(prompt)
    errors = []
    for fn in (_call_sdk, _call_cli):
        try:
            return fn(prompt)
        except LoreUnavailable as e:
            errors.append(str(e))
    raise LoreUnavailable(
        "; ".join(errors)
        + ". Fix: `pip install anthropic` + credentials, install the "
        "`claude` CLI, set BUZZ_LORE_URL/BUZZ_LORE_MODEL[/BUZZ_LORE_KEY] "
        "to an OpenAI-compatible endpoint, or set BUZZ_LORE_CMD to any "
        "command that reads the brief on stdin and prints the JSON. "
        "Manual path: buzz author export / apply.")


def _parse(raw: str) -> dict:
    """Tolerate markdown fences and leading prose around the JSON object."""
    text = raw.strip()
    if "```" in text:
        for chunk in text.split("```"):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                text = chunk
                break
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the response")
    return json.loads(text[start:text.rfind("}") + 1])


def run_lore(world: World) -> dict:
    """Author quests + briefs + glosses into the world. Returns a summary."""
    data = _parse(_transport(build_brief(world)))
    result = author.apply_authored(world, data.get("quests") or [])
    briefs = 0
    for zid, brief in (data.get("zone_briefs") or {}).items():
        if zid in world.zones and isinstance(brief, str) and brief.strip():
            world.zones[zid].brief = brief.strip()[:160]
            briefs += 1
    glosses = 0
    for m, gloss in (data.get("glosses") or {}).items():
        # flavor only, and only where the repo itself is silent
        if (m in world.modules and not world.modules[m].doc
                and isinstance(gloss, str) and gloss.strip()):
            world.modules[m].gloss = gloss.strip()[:120]
            glosses += 1
    result["zone_briefs"] = briefs
    result["glosses"] = glosses
    return result
