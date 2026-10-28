# MotionLab — session pointers

## Second brain (read this first)
Current project state (three-layer truth: pushed / 37 unpushed commits / uncommitted worktree),
architecture, adapter scores, and the GPU/serving runbook live in the Mercatura brain — call
`brain_context(project: "motion-lab")` at session start (MCP server `brain`, configured in this
repo's `.mcp.json`; export `BRAIN_MCP_TOKEN`). Scope with `topic:` (track-a, track-b, engine,
training, studio, serving…). If your session changed project reality, push it back via
`brain_update_state` / `brain_write_note` / `brain_log` before ending.

## Hard rules (from the brain's sharp findings)
- ~/MotionLab is an ACTIVE worktree with unpushed+uncommitted work — never run mutating git without its owner.
- GPU: read `nvidia-smi` first; kill by exact PID only; never point serving at `training/<run>/final` (rotation-managed) — serve from `adapters/`.
- CAD API launches from `~/MotionLab` with `PLAN_MODEL` exported, or the planner silently degrades to the untuned base.
- Working memory `task.md`, `fable_run/`, `docs/research/` are gitignored and box-only — treat as irreplaceable.
