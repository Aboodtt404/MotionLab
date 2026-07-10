"""Benchmark scoring — fable_run/out/02_benchmark.md §Scoring rubric, verbatim.

capability_score = 100 · Σ(weight_i · passed_i) / Σ(weight_i)     over the FULL 100-task set (Σw = 263),
computed separately for pass@1 and pass@3. Category sub-scores use the same formula over each
category's tasks. Bands are evaluated on the pass@3 score with category + L1 floors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

WEIGHT = {1: 1, 2: 2, 3: 3, 4: 4}   # L1=1 … L4=4
TOTAL_WEIGHT = 263                    # 13·1 + 32·2 + 34·3 + 21·4  (asserted by the registry test)

CATEGORY_NAME = {
    "C": "Parametric CAD", "M": "Mesh modeling", "B": "Blender", "W": "Three.js / web GLB",
    "G": "Game assets", "P": "Product models", "D": "Drones / robotics", "A": "Assemblies",
}


@dataclass
class TaskResult:
    task_id: str
    category: str
    level: int
    passed_at1: bool = False
    passed_at3: bool = False
    attempts_used: int = 0
    runnable: bool = True          # False = no verifier yet (blocked); counts as not-passed in the denominator
    blocked_on: Optional[str] = None
    failure_category: Optional[str] = None


@dataclass
class Scorecard:
    results: List[TaskResult] = field(default_factory=list)

    def _score(self, tasks: List[TaskResult], at3: bool) -> float:
        denom = sum(WEIGHT[t.level] for t in tasks)
        if not denom:
            return 0.0
        num = sum(WEIGHT[t.level] for t in tasks if (t.passed_at3 if at3 else t.passed_at1))
        return round(100.0 * num / denom, 2)

    def capability_score(self, at3: bool = True) -> float:
        return self._score(self.results, at3)

    def category_scores(self, at3: bool = True) -> Dict[str, float]:
        out = {}
        for c in CATEGORY_NAME:
            ts = [t for t in self.results if t.category == c]
            if ts:
                out[c] = self._score(ts, at3)
        return out

    def band(self) -> str:
        """Capability band on the pass@3 score (02_benchmark §Capability bands)."""
        s = self.capability_score(at3=True)
        cats = self.category_scores(at3=True)
        l1 = [t for t in self.results if t.level == 1]
        l1_rate = (sum(1 for t in l1 if t.passed_at3) / len(l1)) if l1 else 0.0
        if s >= 85 and cats and min(cats.values()) >= 70:
            return "Expert"
        if s >= 75 and cats and min(cats.values()) >= 60 and l1_rate >= 0.90:
            return "Strong"
        if s >= 60:
            return "Competent"
        if s >= 40:
            return "Basic"
        return "Weak"

    def diagnostics(self) -> Dict[str, object]:
        runnable = [t for t in self.results if t.runnable]
        blocked = [t for t in self.results if not t.runnable]
        gap = round(self.capability_score(True) - self.capability_score(False), 2)   # repair skill
        hist: Dict[str, int] = {}
        for t in self.results:
            if not t.passed_at3 and t.failure_category:
                hist[t.failure_category] = hist.get(t.failure_category, 0) + 1
        by_cat_blocked: Dict[str, int] = {}
        for t in blocked:
            by_cat_blocked[t.category] = by_cat_blocked.get(t.category, 0) + 1
        return {
            "encoded_runnable": len(runnable),
            "blocked": len(blocked),
            "blocked_by_category": by_cat_blocked,
            "encodable_weight": sum(WEIGHT[t.level] for t in runnable),
            "encodable_weight_pct": round(100.0 * sum(WEIGHT[t.level] for t in runnable) / TOTAL_WEIGHT, 1),
            "pass1_to_pass3_gap": gap,
            "failure_histogram": hist,
        }

    def render(self) -> str:
        d = self.diagnostics()
        lines = [
            "═" * 62,
            "CAPABILITY SCORECARD (02_benchmark §Scoring rubric)",
            "═" * 62,
            f"capability_score  pass@1 = {self.capability_score(False):5.2f}   "
            f"pass@3 = {self.capability_score(True):5.2f}   /263",
            f"band              {self.band()}",
            "",
            "category sub-scores (pass@3):",
        ]
        cs1, cs3 = self.category_scores(False), self.category_scores(True)
        for c, name in CATEGORY_NAME.items():
            if c in cs3:
                lines.append(f"  {c} {name:<22} pass@1 {cs1[c]:5.1f}  pass@3 {cs3[c]:5.1f}")
        lines += [
            "",
            f"encoded+runnable  {d['encoded_runnable']}/100 tasks "
            f"({d['encodable_weight']}/263 weight = {d['encodable_weight_pct']}%)",
            f"blocked (no verifier yet)  {d['blocked']}  by category: {d['blocked_by_category']}",
            f"pass@1→pass@3 gap (repair skill)  {d['pass1_to_pass3_gap']}",
            f"failure histogram  {d['failure_histogram']}",
            "═" * 62,
        ]
        return "\n".join(lines)
