"""Track A — frontier-model teacher generator (Anthropic Claude Fable 5), drop-in for the loop.

`TeacherGenerator` satisfies the same `Generator` protocol as `VLLMGenerator`
(`generate(spec, feedback) -> str`), so it plugs into `loop.run()` unchanged: the
existing executor / verifier / retry logic drives it exactly as it drives the local
baseline. The point is an apples-to-apples comparison — same spec JSON, same
`reference_block()` retrieval injected into the user message — with two differences
that make it a *teacher*:

  1. it calls a frontier model (Claude Fable 5) via the Anthropic API, and
  2. it exposes the RAG retrieval as **callable tools** (agentic doc-lookup), instead
     of the baseline's one-shot prompt-injected reference block. Both the injected
     block AND the tools are available; the model can look up more on demand.

Every raw API interaction (model, stop_reason, usage, content blocks incl. summarized
thinking, tool calls) is recorded in `self.trace` so the harness can log chain-of-thought
and tool use.

Fable-5 specifics handled here (they differ from the Opus/Sonnet request surface):
  • Thinking is ALWAYS ON — we don't disable it; we ask for `display: "summarized"` so the
    reasoning is captured in the trace, and control depth with `output_config.effort`.
  • Sampling params (`temperature`/`top_p`/`top_k`) are REMOVED — sending them 400s, so we
    send none and steer purely by prompt + effort.
  • Refusals: safety classifiers can return `stop_reason == "refusal"`. We opt into
    server-side fallbacks by default (Fable 5 → Opus 4.8) so a false positive on benign
    CAD work is re-served inside the same call, and we handle a whole-chain refusal cleanly.
  • Requires 30-day data retention on the org (Fable 5 is not available under ZDR).

Nothing in the existing package is modified — this only imports `.spec` and `.rag`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from anthropic import Anthropic

from .rag import grep, lookup, reference_block
from .spec import Spec

# The exact baseline system prompt (loop.VLLMGenerator.SYSTEM), duplicated here so the
# teacher runs on an identical instruction set by default. Kept as a module constant
# rather than imported so this file has no dependency on loop.py (which we must not touch,
# and which we don't want to import for a mere string).
DEFAULT_SYSTEM = (
    "You are a CAD engineer who writes CadQuery (Python). Think through the 6-stage method "
    "(decompose → workplane/frame → base profile → features → operation order → units) INSIDE a "
    "<think>...</think> block. After </think>, output ONLY the final program as a single ```python "
    "code block — NO prose, NO headings, NO explanation outside the block. The program must "
    "`import cadquery as cq` and assign the final solid to a variable named `result`. "
    "API: `.box(L,W,H)` is centered at the origin; Z-hole via "
    "`.faces('>Z').workplane().center(x,y).hole(d)` (workplane() takes a FLOAT offset, NOT a plane name); "
    "fillet/chamfer vertical edges via `.edges('|Z').fillet(r)` / `.chamfer(d)`; "
    "rectangular pocket via `.faces('>Z').workplane().rect(l,w).cutBlind(-depth)`. "
    "MULTIPLE holes: place them ALL AT ONCE with one "
    "`.faces('>Z').workplane().pushPoints([(x1,y1),(x2,y2),...]).hole(d)` (absolute, origin=part center) "
    "— do NOT chain `.center().hole()` per hole: `.center()` is RELATIVE and accumulates, drifting later holes. "
    "For advanced SHAPES (revolve / sweep / loft), molding (draft / shell), recessed or threaded holes "
    "(counterbore / countersink / thread), mirror symmetry, and variable-radius fillets, FOLLOW THE EXACT "
    "PATTERNS in the retrieved reference below — they encode the required conventions (axes, centering)."
)

# Fable 5's refusal-fallback opt-in: beta header + the model that re-serves a policy decline.
_FALLBACK_BETA = "server-side-fallback-2026-06-01"

# When tools are enabled the model may additionally CALL these to pull more reference on
# demand (beyond the one-shot block already in the prompt). They wrap rag.lookup / rag.grep.
TOOLS: List[Dict[str, Any]] = [
    {
        "name": "cadquery_doc_lookup",
        "description": (
            "TF-IDF search over the CadQuery reference corpus: real Workplane API signatures "
            "(ground truth, version-matched), canonical correct example snippets, and error-fix "
            "hints. Use it to confirm a method's exact signature or find the idiom for a feature "
            "(e.g. 'revolve turned body', 'counterbore hole', 'fillet vertical edges')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language or API-name query.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "cadquery_grep",
        "description": (
            "Regex search over CadQuery symbol NAMES and doc/snippet bodies. Use it for an exact "
            "symbol when you know (or suspect) the method name, e.g. 'cboreHole', r'\\bworkplane\\b', "
            "'pushPoints'. Name matches rank ahead of body matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "A regular expression (falls back to a literal match if invalid).",
                },
            },
            "required": ["pattern"],
        },
    },
]


class TeacherGenerator:
    """Frontier-model (Claude Fable 5) code generator matching the `Generator` protocol.

    Usage mirrors VLLMGenerator:
        gen = TeacherGenerator()
        out = loop.run(spec, gen, max_attempts=3)
        trace = gen.trace   # raw API interactions from the LAST generate() call
    """

    def __init__(
        self,
        model: str = "claude-fable-5",
        system_prompt: Optional[str] = None,
        max_tool_turns: int = 3,
        enable_tools: bool = True,
        verbose: bool = False,
        effort: Optional[str] = "high",          # low|medium|high|xhigh|max — Fable 5's depth knob (replaces temperature)
        max_tokens: int = 16000,                  # headroom for always-on thinking + the program (skill's non-streaming default)
        enable_fallback: bool = True,             # opt into server-side refusal fallbacks (recommended for Fable 5)
        fallback_model: str = "claude-opus-4-8",  # model that re-serves a policy decline
    ) -> None:
        # API key comes from the environment (ANTHROPIC_API_KEY / an `ant auth login` profile).
        self.client = Anthropic()
        self.model = model
        self.system_prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM
        self.max_tool_turns = max_tool_turns
        self.enable_tools = enable_tools
        self.verbose = verbose
        self.effort = effort
        self.max_tokens = max_tokens
        self.enable_fallback = enable_fallback
        self.fallback_model = fallback_model
        # Accumulates one entry per API round-trip within a single generate() call.
        self.trace: List[Dict[str, Any]] = []

    # --------------------------------------------------------------------- helpers
    @staticmethod
    def _extract_code(text: str) -> str:
        """Pull the program out of a possibly-reasoning, possibly-truncated reply.

        Mirrors VLLMGenerator._extract_code so both generators are scored on the same
        extraction rule: strip <think>…</think>, take the LAST fenced ```python block
        (closed or truncated-open), else salvage from `import cadquery`. (Fable 5's real
        reasoning arrives as separate `thinking` content blocks — never as visible text —
        so this only ever sees the final answer text.)
        """
        if "</think>" in text:  # a literal think tag the prompt asks for, if the model emits one
            text = text.rsplit("</think>", 1)[1]
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        closed = re.findall(r"```(?:python)?\s*(.*?)```", text, re.S)
        if closed:
            return closed[-1].strip()
        open_fence = re.search(r"```(?:python)?\s*(.*)$", text, re.S)  # unclosed (truncated) fence
        if open_fence:
            return open_fence.group(1).strip()
        idx = text.find("import cadquery")  # no fence at all — salvage from the import
        return (text[idx:] if idx != -1 else text).strip()

    def _run_tool(self, name: str, tool_input: Dict[str, Any]) -> str:
        """Execute one tool call against rag.py and format the docs as a prompt-ready string."""
        try:
            if name == "cadquery_doc_lookup":
                docs = lookup(str(tool_input.get("query", "")))
            elif name == "cadquery_grep":
                docs = grep(str(tool_input.get("pattern", "")))
            else:
                return f"(unknown tool: {name})"
        except Exception as exc:  # noqa: BLE001 — a bad regex/query must not crash generation
            return f"(tool error: {type(exc).__name__}: {exc})"
        if not docs:
            return "(no matches)"
        return "\n\n".join(d.render for d in docs)

    def _create(self, messages: List[Dict[str, Any]], use_tools: bool) -> Any:
        """One API round-trip, built the Fable-5 way: no temperature, thinking always on
        (summarized so it's captured), effort for depth, and server-side refusal fallbacks."""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system_prompt,
            "messages": messages,
            # Fable 5 thinking is always on; ask for a readable summary so CoT lands in the trace.
            "thinking": {"type": "adaptive", "display": "summarized"},
        }
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if use_tools and self.enable_tools:
            kwargs["tools"] = TOOLS
        if self.enable_fallback:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = [{"model": self.fallback_model}]
        # The beta endpoint is a superset of messages.create and is required for `betas`/`fallbacks`.
        return self.client.beta.messages.create(**kwargs)

    def _log(self, response: Any) -> None:
        """Serialize one API response into self.trace (JSON-safe)."""
        blocks: List[Dict[str, Any]] = []
        for b in response.content:
            if b.type == "text":
                blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
            elif b.type == "thinking":  # Fable 5: summarized reasoning (empty unless display="summarized")
                blocks.append({"type": "thinking", "thinking": getattr(b, "thinking", "")})
            elif b.type == "fallback":  # a refusal switch point (Fable 5 → fallback model)
                blocks.append({"type": "fallback",
                               "from": getattr(getattr(b, "from_", None), "model", None),
                               "to": getattr(getattr(b, "to", None), "model", None)})
            else:
                blocks.append({"type": b.type})
        usage = getattr(response, "usage", None)
        det = getattr(response, "stop_details", None)
        self.trace.append({
            "model": response.model,  # which model actually served (may be the fallback)
            "stop_reason": response.stop_reason,
            "stop_details": {"category": getattr(det, "category", None)} if det else None,
            "usage": {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            } if usage else None,
            "content": blocks,
        })
        if self.verbose:
            kinds = [b["type"] for b in blocks]
            tools = [b["name"] for b in blocks if b["type"] == "tool_use"]
            print(f"    [teacher {response.model}] stop={response.stop_reason} blocks={kinds}"
                  + (f" tools={tools}" if tools else ""))

    def _final_code(self, response: Any) -> str:
        """Extract the program from a final (tool-free) response, handling a whole-chain refusal."""
        if response.stop_reason == "refusal":
            det = getattr(response, "stop_details", None)
            cat = getattr(det, "category", None) if det else None
            # Legible, executable marker: the loop's executor finds no valid `result` and records
            # the attempt as a failure (with the refusal visible in the trace), rather than crashing.
            return (f"# TEACHER_REFUSAL category={cat}\n"
                    "# The safety classifier declined this request (whole fallback chain refused).\n"
                    "result = None")
        text = "".join(b.text for b in response.content if b.type == "text")
        return self._extract_code(text)

    # --------------------------------------------------------------------- protocol
    def generate(self, spec: Spec, feedback: str = "") -> str:
        """spec (+ optional retry feedback) → CadQuery source assigning `result`.

        Builds the identical user message the baseline uses (spec JSON, feedback, then the
        one-shot reference_block), then runs an agentic tool loop up to max_tool_turns.
        """
        self.trace = []  # fresh trace per call — the harness snapshots it after each generate()

        # 1) Identical user message to VLLMGenerator.generate (apples-to-apples).
        user = "Build this part as CadQuery, assigning the solid to `result`:\n" + spec.model_dump_json(indent=2)
        if feedback:
            user += ("\n\nThe previous attempt failed verification — fix ONLY these issues, keep the rest:\n"
                     + feedback)
        ref = reference_block(spec, feedback or None)
        if ref:
            user += f"\n\n{ref}"

        messages: List[Dict[str, Any]] = [{"role": "user", "content": user}]

        # 2) Agentic loop: let the model call the doc tools, feeding results back, until it
        #    emits a final answer (no tool_use) or we run out of tool turns.
        for _turn in range(self.max_tool_turns):
            response = self._create(messages, use_tools=True)
            self._log(response)

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                # Final answer (or a refusal) — extract the program.
                return self._final_code(response)

            # Echo the assistant turn VERBATIM (must include thinking + tool_use blocks — Fable 5
            # requires thinking blocks passed back unchanged on the same model) then answer each tool.
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": tu.id, "content": self._run_tool(tu.name, tu.input)}
                for tu in tool_uses
            ]
            messages.append({"role": "user", "content": tool_results})

        # 3) Tool budget exhausted — force a final answer WITHOUT tools so the model must commit.
        response = self._create(
            messages + [{
                "role": "user",
                "content": "Tool budget exhausted. Output the final CadQuery program now, "
                           "as a single ```python code block assigning `result`, nothing else.",
            }],
            use_tools=False,
        )
        self._log(response)
        return self._final_code(response)


if __name__ == "__main__":  # tiny smoke test (requires ANTHROPIC_API_KEY + a 30-day-retention org)
    import json

    demo = Spec(
        object="filleted bracket with a bolt hole", shape="box",
        envelope={"length": 80, "width": 50, "height": 30},
        features=[{"type": "fillet", "radius": 4, "edges": "all_vertical"},
                  {"type": "through_hole", "diameter": 12, "from_edge": 18}],
        tolerance=0.1,
    )
    g = TeacherGenerator(verbose=True)
    code = g.generate(demo)
    print("\n--- generated code ---\n" + code)
    print("\n--- trace ---\n" + json.dumps(g.trace, indent=2)[:2000])
