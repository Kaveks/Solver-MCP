"""
mcp_server/routes/simulations.py — the Engineering Simulations HTTP API (Layer 2).

These are the routes the web UI's JavaScript calls directly. They wrap the same
``submit_job`` path the MCP tools use, so cache, job store, and worker dispatch behave
identically to an agent-driven call:

    POST /api/submit/cfd    Submit an OpenFOAM (CFD) job          -> JobView
    POST /api/submit/md     Submit a LAMMPS (MD) job              -> JobView
    POST /api/submit/fem    Submit a FreeCAD (FEM) job (stub)     -> NotImplementedView
    POST /api/solver-intro  One-shot solver introduction text     -> SolverIntroResponse
    GET  /api/jobs          List a device's jobs (history)        -> { "jobs": [...] }
    GET  /api/chat          Conversational agent run (SSE stream)

All routes share the ``Engineering Simulations`` OpenAPI tag (set on the router). Heavy
dependencies (the agent/LLM, the solver router, the execution layer) are imported lazily
inside the handlers so importing this module never pulls them in or requires a populated
environment — consistent with the other route modules.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from mcp_server.schemas import FreecadInput, LAMMPSInput, OpenFOAMInput
from mcp_server.schemas.api import (
    JobView,
    NotImplementedView,
    SolverIntroRequest,
    SolverIntroResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Engineering Simulations"])

# Map each simulation tool to the solver it dispatches, so a chat result can be
# tagged with the solver that produced it (used to pick the inline result card).
_SOLVER_BY_TOOL = {
    "run_md_simulation": "lammps",
    "run_cfd_simulation": "openfoam",
    "run_fem_simulation": "freecad",
}

# The validated input model per solver. Used to derive the Layer 2 interpretation cache key
# the SAME way the router derives the Layer 1 solver key: validate the raw tool args through
# this model, then model_dump(). That makes the two keys identical even when the LLM emits
# the args with defaults omitted one time and present the next.
_RUN_MODEL_BY_SOLVER = {
    "openfoam": OpenFOAMInput,
    "lammps": LAMMPSInput,
    "freecad": FreecadInput,
}

# Maximum accepted length of the client-supplied device identifier used to scope history.
# Bounds an untrusted query param so a client cannot write an unbounded owner string.
MAX_DEVICE_ID_LEN = 128


def _interpretation_cache_key(solver: str | None, sim_args: object) -> str | None:
    """SHA-256 key for a run tool's simulation args, identical to the solver cache key.

    Returns None — caching silently skipped — when the solver is unknown or the args fail
    validation (the agent then just interprets fresh; correctness is never affected).
    """
    if not solver or not isinstance(sim_args, dict):
        return None
    model = _RUN_MODEL_BY_SOLVER.get(solver)
    if model is None:
        return None
    try:
        payload = model.model_validate(sim_args).model_dump()
    except Exception as exc:  # malformed args — skip caching, don't fail the request
        logger.debug("interpretation cache: could not validate %s args: %s", solver, exc)
        return None
    from execution.cache import cache_key

    return cache_key(solver, payload)


def _stream_chunks(text: str, size: int = 20):
    """Yield ~size-char slices so a cached interpretation still streams to the UI rather
    than arriving as one sudden dump."""
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _tool_case_name(tool_input: object) -> str | None:
    """Pull the simulation case name out of a run tool's input args, if present.

    Run tools take a single ``simulation`` argument (the validated payload), whose
    ``case_name`` names the simulation. Captured from the on_tool_start event so the UI
    can label the job by name, not just by opaque id.
    """
    if not isinstance(tool_input, dict):
        return None
    sim = tool_input.get("simulation")
    if isinstance(sim, dict) and isinstance(sim.get("case_name"), str):
        return sim["case_name"]
    if isinstance(tool_input.get("case_name"), str):
        return tool_input["case_name"]
    return None


def _message_text(msg: object) -> str:
    """Plain text of a LangChain message whose content may be a list of blocks."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts).strip()
    return ""


def _chunk_text(chunk: object) -> str:
    """Streamed text from a chat-model stream chunk (string or content blocks)."""
    content = getattr(chunk, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _parse_tool_output(output: object) -> dict | None:
    """Coerce a tool result (ToolMessage / dict / JSON string / blocks) to a dict."""
    content = getattr(output, "content", output)
    if isinstance(content, list):
        text = ""
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text += block["text"]
            elif isinstance(block, str):
                text += block
        content = text
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


# ── Submit routes (wrap the same submit_job path the MCP tools use) ──────────


@router.post(
    "/api/submit/cfd",
    response_model=JobView,
    response_model_exclude_none=True,
)
async def api_submit_cfd(simulation: OpenFOAMInput) -> JobView:
    # Validate at the HTTP boundary with the same model the MCP tool uses, then
    # dump to the plain dict submit_job expects — so HTTP and agent paths produce
    # identical payloads (and identical cache keys).
    from mcp_server.router import submit_job

    return JobView(**submit_job("openfoam", simulation.model_dump()))


@router.post(
    "/api/submit/md",
    response_model=JobView,
    response_model_exclude_none=True,
)
async def api_submit_md(simulation: LAMMPSInput) -> JobView:
    from mcp_server.router import submit_job

    return JobView(**submit_job("lammps", simulation.model_dump()))


@router.post("/api/submit/fem", response_model=NotImplementedView)
async def api_submit_fem(simulation: FreecadInput) -> NotImplementedView:
    from connectors.freecad.connector import FreecadConnector

    return NotImplementedView(**FreecadConnector.not_implemented())


@router.post("/api/solver-intro", response_model=SolverIntroResponse)
async def api_solver_intro(body: SolverIntroRequest) -> SolverIntroResponse:
    """Return a solver's introduction message — no tools, no MCP, no simulation.

    The UI calls this once per solver, when the engineer selects it from the
    sidenav, to fetch the connector's "here's what I need from you" text. The
    result is cached in Redis for ~28 days (the intro is not expected to change
    month-to-month), so the LLM is called at most once per TTL window and every
    other selection is served straight from cache. On a miss it runs a single plain
    LLM completion on the supplied prompt and stores it; it never dispatches a job.
    The conversational chat lives at GET /api/chat.
    """
    from execution import cache

    message = body.message.strip()
    if not message:
        return SolverIntroResponse(response="")

    # Cache-first: serve the stored intro as-is when present.
    cached = cache.get_intro(message)
    if cached is not None:
        return SolverIntroResponse(response=cached)

    from agent.agent import build_llm
    from langchain_core.messages import HumanMessage

    llm = build_llm()
    out = await llm.ainvoke([HumanMessage(content=message)])
    text = _message_text(out)
    # Only cache a real answer — never pin an empty/failed response for 28 days.
    if text:
        cache.store_intro(message, text)
    return SolverIntroResponse(response=text)


@router.get("/api/jobs")
async def api_jobs(owner: str = "") -> dict:
    """List a device's jobs from the backend (Redis) — the single source of truth for
    history, scoped to the requesting device via ``owner``. A cleared backend (e.g.
    ``make down-clean``) yields an empty history, never stale client cache."""
    from execution import job_store

    return {"jobs": job_store.list_jobs(owner=owner or None)}


@router.get("/api/chat", response_model=None)
async def api_chat(
    message: str = "", history: str = "", solver: str = "", device: str = ""
) -> StreamingResponse:
    """The conversational chat endpoint — streams an agent run as Server-Sent Events.

    This is the primary chat path the UI uses for every turn. It runs the full
    agent (tools + MCP) and streams progress live. Its request "model" is the query
    params below (a GET, because EventSource only does GET); its response is an SSE
    stream, not a single JSON body, so it has no Pydantic response_model
    (response_model=None). The one-shot solver intro lives at POST /api/solver-intro.

    Query params: ``message``, ``history`` (a JSON-encoded list of
    {"role", "content"} dicts), and ``solver`` (the UI-selected solver, which binds
    the agent deterministically — see build_agent). Emits one event per line-pair:

        {"type": "tool_start", "name": ...}
        {"type": "tool_end",   "name": ...}
        {"type": "token",      "text": ...}
        {"type": "done", "response", "job_id", "result", "solver", "case_name"}
        {"type": "error", "message": ...}

    Mirrors POST /api/chat but live, so the chat page can show tool calls
    and stream the answer. Stateless: history comes from the client.
    """
    from agent.agent import build_agent
    from langchain_core.messages import AIMessage, HumanMessage

    msg = (message or "").strip()
    selected_solver = (solver or "").strip().lower() or None
    # Concern 4 — Prototype assumption: `device` is an unauthenticated, client-supplied
    # identifier used only to scope history. Sanitize it here (strip, bound length, treat
    # blank as unattributed) so a client cannot claim an unbounded owner string. Production
    # must replace this raw device ID with a signed session token or JWT claim rather than
    # trusting the value on the wire. This is sanitization only, not authentication.
    device = (device or "").strip()[:MAX_DEVICE_ID_LEN] or None

    async def event_gen():
        from execution import cache, job_store

        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj)}\n\n"

        if not msg:
            yield sse({"type": "done", "response": "", "job_id": None,
                       "result": None, "solver": None, "case_name": None,
                       "interpretation_cached": False})
            return

        try:
            raw_history = json.loads(history) if history else []
        except (ValueError, TypeError):
            raw_history = []

        hist = []
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            if item.get("role") == "user":
                hist.append(HumanMessage(content=item.get("content", "")))
            elif item.get("role") == "assistant":
                hist.append(AIMessage(content=item.get("content", "")))
        # Concern 3: cap the reconstructed history to the last 20 messages (~10 user/
        # assistant turns) before adding the current message. `history` is an unbounded
        # query-param JSON string; without a cap a long conversation could silently
        # overflow the LLM context window or hit URL-length limits. ~10 turns is enough
        # context for the agent's submit -> poll -> summarise tool-calling pattern.
        hist = hist[-20:]
        hist.append(HumanMessage(content=msg))

        # Seed the solver from the UI selection; the agent is bound to it, so any job
        # it runs is that solver. Inference stays only as a fallback for unbound runs.
        current_solver = {"name": selected_solver}
        found = {"job_id": None, "result": None, "case_name": None}
        # Most recent job_id seen on any tool result, so a Concern 1 timeout can name the
        # job for the engineer even while it is still RUNNING (found["job_id"] is only set
        # once a job COMPLETES).
        last_seen_job_id = {"value": None}
        final_text = {"value": ""}
        # Only the text generated AFTER the last tool result — the final interpretation —
        # is what Layer 2 caches. Reset at each tool_end so it never contains the preamble
        # or the interim "polling…" narration (which must not be replayed on a cache hit).
        segment = {"value": ""}

        try:
            agent = await build_agent(allowed_solver=selected_solver)
            # Concern 1 / Concern 2 clocks: `started_at` bounds the whole run (wall-clock
            # timeout); `last_sent_at` tracks the last byte written so a keepalive can be
            # injected during a long silent poll. Both use time.monotonic() (immune to
            # system-clock changes) and are refreshed after every frame yielded below.
            started_at = time.monotonic()
            last_sent_at = started_at
            async for event in agent.astream_events(
                {"messages": hist}, version="v2", config={"recursion_limit": 60}
            ):
                # Concern 1: wall-clock timeout. A job stuck in RUNNING would otherwise let
                # the agent poll up to recursion_limit steps with no bound on the SSE
                # connection. Track elapsed time here and break cleanly with an error event
                # rather than wrapping the generator in asyncio.wait_for, which would cancel
                # it mid-yield. 120s covers a normal Prototype solver run with headroom.
                if time.monotonic() - started_at > 120:
                    stuck_id = found.get("job_id") or last_seen_job_id["value"]
                    yield sse({
                        "type": "error",
                        "message": (
                            "The simulation is taking longer than expected and is still "
                            "running. "
                            + (
                                f"You can check its status manually using job ID {stuck_id}."
                                if stuck_id
                                else "You can check its status manually from your job history."
                            )
                        ),
                    })
                    return
                kind = event.get("event")
                name = event.get("name", "")
                if kind == "on_tool_start":
                    if name in _SOLVER_BY_TOOL:
                        current_solver["name"] = current_solver["name"] or _SOLVER_BY_TOOL[name]
                        tool_input = event.get("data", {}).get("input")
                        case_name = _tool_case_name(tool_input)
                        if case_name:
                            found["case_name"] = case_name
                        # Capture the raw simulation args so Layer 2 can derive the
                        # interpretation cache key (validated the way the router does).
                        if isinstance(tool_input, dict) and isinstance(
                            tool_input.get("simulation"), dict
                        ):
                            found["sim_args"] = tool_input["simulation"]
                    yield sse({"type": "tool_start", "name": name})
                    last_sent_at = time.monotonic()
                elif kind == "on_tool_end":
                    parsed = _parse_tool_output(event.get("data", {}).get("output"))
                    # Remember the latest job_id seen (a submit result or a status poll) so
                    # the Concern 1 timeout message can name the job even while RUNNING.
                    if parsed and parsed.get("job_id"):
                        last_seen_job_id["value"] = parsed["job_id"]
                    completed = bool(
                        parsed
                        and parsed.get("status") == "COMPLETED"
                        and parsed.get("result")
                    )
                    if completed:
                        found["job_id"] = parsed.get("job_id")
                        found["result"] = parsed.get("result")
                    # Concern 2: SSE keepalive. During a long poll the stream can be silent
                    # long enough for a proxy/browser to drop an idle connection (30-60s).
                    # If >15s have passed since the last frame, emit an SSE comment line (no
                    # `data:` prefix, ignored by the client) before the tool_end frame.
                    if time.monotonic() - last_sent_at > 15:
                        yield ": keepalive\n\n"
                        last_sent_at = time.monotonic()
                    yield sse({"type": "tool_end", "name": name})
                    last_sent_at = time.monotonic()
                    # A new interpretation segment begins after every tool result, so the
                    # cached text is the final answer only — not the interim narration.
                    segment["value"] = ""
                    # Layer 2: the agent's next step after a COMPLETED result is the final
                    # prose interpretation. If that prose is already cached for this exact
                    # simulation, serve it and stop BEFORE the final LLM call is made —
                    # breaking here is clean because on_chat_model_start has not fired yet,
                    # so no in-flight LLM call is aborted. Compute the key once.
                    if completed and "interp_key" not in found:
                        key = _interpretation_cache_key(
                            current_solver["name"], found.get("sim_args")
                        )
                        found["interp_key"] = key
                        if key:
                            cached_interp = cache.get_interpretation(key)
                            if cached_interp:
                                found["interp_cached"] = cached_interp
                                break
                elif kind == "on_chat_model_stream":
                    text = _chunk_text(event.get("data", {}).get("chunk"))
                    if text:
                        final_text["value"] += text
                        segment["value"] += text
                        yield sse({"type": "token", "text": text})
                        last_sent_at = time.monotonic()
                elif kind == "on_chat_model_end":
                    # Fallback when the provider did not stream tokens.
                    if not final_text["value"]:
                        text = _message_text(event.get("data", {}).get("output"))
                        if text:
                            final_text["value"] = text
                            segment["value"] = text
        except Exception as exc:  # surface a clean error event to the client
            yield sse({"type": "error", "message": str(exc)})
            return

        interp_cached = bool(found.get("interp_cached"))
        if interp_cached:
            # Layer 2 hit: the final LLM call was skipped (we broke out above). Stream the
            # cached interpretation as token events so the UI still animates. Append it to
            # the freshly-streamed preamble — the interim polling narration is never
            # replayed, because only the final segment was cached.
            for piece in _stream_chunks(found["interp_cached"]):
                yield sse({"type": "token", "text": piece})
            final_text["value"] += found["interp_cached"]
        elif (
            found.get("result")
            and found.get("interp_key")
            and segment["value"].strip()
        ):
            # Layer 2 miss: cache ONLY the final interpretation segment (text after the
            # last tool result) under the shared key, so the next identical request can
            # skip the final LLM call. A store outage is non-fatal (logged, unaffected).
            #
            # Concern 5 — segment reset assumption: segment["value"] holds only text
            # generated after the last on_tool_end, by design (it is reset to "" on every
            # tool_end above). The assumption here is that NO tool call follows the final
            # prose interpretation. If an unexpected tool call did follow, segment would
            # reset again and the .strip() guard in this elif condition would prevent
            # storing an empty string — so nothing wrong is cached, but the interpretation
            # simply would not be cached for that turn (it is regenerated next time).
            cache.store_interpretation(found["interp_key"], segment["value"].strip())

        # Persist owner + interpretation onto the job record so history is rendered from
        # the backend (Redis), scoped to this device — never from stale client storage.
        if found.get("job_id"):
            # Concern 4: `device` was sanitized to a bounded string or None above; only
            # attribute ownership when a real device ID survived sanitization.
            if device is not None:
                job_store.set_owner(found["job_id"], device)
            interpretation_text = (
                found["interp_cached"] if interp_cached else segment["value"].strip()
            )
            if interpretation_text:
                job_store.set_interpretation(found["job_id"], interpretation_text)

        yield sse({
            "type": "done",
            "response": final_text["value"].strip(),
            "job_id": found["job_id"],
            "result": found["result"],
            "solver": current_solver["name"],
            "case_name": found["case_name"],
            "interpretation_cached": interp_cached,
        })

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
