"""Sequential experiment runner with hard budgets and incremental persistence."""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .aggregation import aggregate_experiment
from .comparison import compare
from .errors import BudgetExceededError, SourceMutationError, TargetExecutionError, ValidationError
from .evaluators import Evaluator, ValidationCommandEvaluator
from .fingerprint import collect_fingerprint
from .models import (
    SCHEMA_VERSION,
    BenchmarkCase,
    BenchmarkSuite,
    EvaluationResult,
    ExecutionBudget,
    PricingConfig,
    RunResult,
    RunStatus,
    TargetResult,
    Variant,
    make_run_id,
)
from .persistence import ResultStore
from .regression import RegressionPolicy
from .targets import BenchmarkTarget
from .workspace import DirectoryCopyWorkspace, diff_snapshots, snapshot_tree, write_case_files


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BudgetLedger:
    budget: ExecutionBudget
    started: int = 0
    completed: int = 0
    failures: int = 0
    committed_cost: float = 0.0
    cost_known: bool = True
    experiment_started_at: float = 0.0

    def check_can_start(self, *, elapsed_seconds: float) -> None:
        budget = self.budget
        if budget.max_runs is not None and self.started >= budget.max_runs:
            raise BudgetExceededError(
                f"max_runs={budget.max_runs} already reached ({self.started} started)"
            )
        if budget.max_total_duration_seconds is not None:
            if elapsed_seconds >= budget.max_total_duration_seconds:
                raise BudgetExceededError(
                    f"max_total_duration_seconds={budget.max_total_duration_seconds} exhausted"
                )
        if budget.max_total_cost is not None:
            if self.committed_cost >= budget.max_total_cost:
                raise BudgetExceededError(
                    f"max_total_cost={budget.max_total_cost} exhausted "
                    f"(committed={self.committed_cost})"
                )
        if budget.max_failures is not None and self.failures >= budget.max_failures:
            raise BudgetExceededError(
                f"max_failures={budget.max_failures} reached ({self.failures})"
            )

    def mark_started(self) -> None:
        self.started += 1

    def mark_finished(self, result: RunResult) -> None:
        self.completed += 1
        if result.target.status is RunStatus.FAILURE:
            self.failures += 1
        cost = result.target.telemetry.cost
        if cost is None:
            self.cost_known = False
        else:
            self.committed_cost += cost


@dataclass
class ExperimentSpec:
    suite: BenchmarkSuite
    target: BenchmarkTarget
    output_root: str | Path
    evaluators: Sequence[Evaluator] = ()
    budget: ExecutionBudget | None = None
    seed: int | None = None
    pricing: PricingConfig | None = None
    policy: RegressionPolicy | None = None
    workspace_template: str | Path | None = None


@dataclass
class ExperimentOutcome:
    suite_id: str
    seed: int
    fingerprint: Any
    runs: list[RunResult]
    summary: dict[str, Any]
    comparison: dict[str, Any] | None
    budget_exhausted: bool
    stopped_reason: str | None
    output_root: str
    schema_version: int = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "suite_id": self.suite_id,
            "seed": self.seed,
            "fingerprint": self.fingerprint.as_dict(),
            "run_ids": [r.run_id for r in self.runs],
            "budget_exhausted": self.budget_exhausted,
            "stopped_reason": self.stopped_reason,
            "output_root": self.output_root,
        }


class ExperimentRunner:
    """Expand case × variant × repetition and execute sequentially."""

    def run(self, spec: ExperimentSpec) -> ExperimentOutcome:
        suite = spec.suite
        if not isinstance(suite, BenchmarkSuite):
            raise ValidationError("spec.suite must be a BenchmarkSuite")
        budget = spec.budget or suite.budget
        seed = suite.seed if spec.seed is None else spec.seed
        store = ResultStore(spec.output_root)
        template = spec.workspace_template or suite.workspace_template
        workspace_provider = None
        if template:
            workspace_provider = DirectoryCopyWorkspace(template)

        fingerprint = collect_fingerprint(
            seed=seed,
            cwd=str(Path(template).resolve()) if template else None,
            target_metadata=spec.target.describe(),
        )
        store.write_json(
            "experiment.json",
            {
                "schema_version": SCHEMA_VERSION,
                "suite_id": suite.id,
                "suite_name": suite.name,
                "seed": seed,
                "fingerprint": fingerprint.as_dict(),
                "budget": {
                    "max_runs": budget.max_runs,
                    "per_run_timeout_seconds": budget.per_run_timeout_seconds,
                    "max_total_duration_seconds": budget.max_total_duration_seconds,
                    "max_total_cost": budget.max_total_cost,
                    "max_failures": budget.max_failures,
                },
                "variants": [v.id for v in suite.variants],
                "cases": [c.id for c in suite.cases],
                "repetitions": suite.repetitions,
            },
        )

        planned: list[tuple[BenchmarkCase, Variant, int]] = []
        for case in suite.cases:
            for variant in suite.variants:
                for rep in range(suite.repetitions):
                    planned.append((case, variant, rep))

        import time

        ledger = BudgetLedger(budget=budget, experiment_started_at=time.perf_counter())
        runs: list[RunResult] = []
        stopped_reason: str | None = None
        budget_exhausted = False

        for case, variant, rep in planned:
            elapsed = time.perf_counter() - ledger.experiment_started_at
            try:
                ledger.check_can_start(elapsed_seconds=elapsed)
            except BudgetExceededError as exc:
                budget_exhausted = True
                stopped_reason = str(exc)
                skip = self._skipped_result(suite.id, case, variant, rep, seed, str(exc))
                store.write_run(skip)
                runs.append(skip)
                # Remaining planned runs also skipped without starting.
                idx = planned.index((case, variant, rep))
                for later_case, later_var, later_rep in planned[idx + 1 :]:
                    later = self._skipped_result(
                        suite.id, later_case, later_var, later_rep, seed, str(exc)
                    )
                    store.write_run(later)
                    runs.append(later)
                break

            ledger.mark_started()
            try:
                result = self._execute_one(
                    suite=suite,
                    case=case,
                    variant=variant,
                    repetition=rep,
                    seed=seed,
                    spec=spec,
                    budget=budget,
                    store=store,
                    workspace_provider=workspace_provider,
                )
            except SourceMutationError:
                raise
            except TargetExecutionError:
                raise
            ledger.mark_finished(result)
            runs.append(result)
            if result.target.infrastructure_error:
                stopped_reason = result.target.error_message or "infrastructure error"
                # Do not continue after infrastructure corruption.
                idx = planned.index((case, variant, rep))
                for later_case, later_var, later_rep in planned[idx + 1 :]:
                    later = self._skipped_result(
                        suite.id,
                        later_case,
                        later_var,
                        later_rep,
                        seed,
                        "aborted after infrastructure error",
                    )
                    store.write_run(later)
                    runs.append(later)
                break

        summary = aggregate_experiment(runs)
        store.write_json("summary.json", summary)
        comparison = None
        baseline = suite.baseline_variant_id
        if spec.policy is not None:
            baseline = spec.policy.baseline_variant_id
        if baseline:
            executed = [r for r in runs if r.target.status is not RunStatus.SKIPPED]
            if any(r.variant_id == baseline for r in executed):
                metrics = [m.name for m in suite.metrics] or None
                comparison = compare(
                    executed,
                    baseline=baseline,
                    policy=spec.policy,
                    metrics=metrics,
                )
                store.write_json("comparison.json", comparison)

        outcome = ExperimentOutcome(
            suite_id=suite.id,
            seed=seed,
            fingerprint=fingerprint,
            runs=runs,
            summary=summary,
            comparison=comparison,
            budget_exhausted=budget_exhausted,
            stopped_reason=stopped_reason,
            output_root=str(store.root),
        )
        store.write_json(
            "experiment.json",
            {
                **outcome.as_dict(),
                "suite_name": suite.name,
                "budget": {
                    "max_runs": budget.max_runs,
                    "per_run_timeout_seconds": budget.per_run_timeout_seconds,
                    "max_total_duration_seconds": budget.max_total_duration_seconds,
                    "max_total_cost": budget.max_total_cost,
                    "max_failures": budget.max_failures,
                },
                "committed_cost": ledger.committed_cost,
                "cost_known": ledger.cost_known,
            },
        )
        return outcome

    def _skipped_result(
        self,
        suite_id: str,
        case: BenchmarkCase,
        variant: Variant,
        repetition: int,
        seed: int,
        reason: str,
    ) -> RunResult:
        run_id = make_run_id(suite_id, case.id, variant.id, repetition, seed)
        now = _iso()
        return RunResult(
            run_id=run_id,
            case_id=case.id,
            variant_id=variant.id,
            repetition=repetition,
            seed=seed,
            target=TargetResult(
                status=RunStatus.SKIPPED,
                error_message=reason,
            ),
            started_at=now,
            finished_at=now,
        )

    def _execute_one(
        self,
        *,
        suite: BenchmarkSuite,
        case: BenchmarkCase,
        variant: Variant,
        repetition: int,
        seed: int,
        spec: ExperimentSpec,
        budget: ExecutionBudget,
        store: ResultStore,
        workspace_provider: DirectoryCopyWorkspace | None,
    ) -> RunResult:
        run_id = make_run_id(suite.id, case.id, variant.id, repetition, seed)
        timeout = (
            case.timeout_seconds
            if case.timeout_seconds is not None
            else budget.per_run_timeout_seconds
        )
        started_at = _iso()
        work_dir: Path | None = None
        tmp_holder = None
        before = {}
        try:
            if workspace_provider is not None:
                tmp_holder = tempfile.TemporaryDirectory(prefix="agentbench-ws-")
                work_dir = workspace_provider.create(Path(tmp_holder.name) / run_id)
                write_case_files(
                    work_dir,
                    {"id": case.id, "payload": case.payload, "expected": case.expected},
                    {"id": variant.id, "config": dict(variant.config)},
                )
                before = snapshot_tree(work_dir)
                workspace_provider.assert_source_unchanged()
            elif case.workspace_template:
                provider = DirectoryCopyWorkspace(case.workspace_template)
                tmp_holder = tempfile.TemporaryDirectory(prefix="agentbench-ws-")
                work_dir = provider.create(Path(tmp_holder.name) / run_id)
                write_case_files(
                    work_dir,
                    {"id": case.id, "payload": case.payload, "expected": case.expected},
                    {"id": variant.id, "config": dict(variant.config)},
                )
                before = snapshot_tree(work_dir)
                provider.assert_source_unchanged()

            context = {
                "run_id": run_id,
                "seed": seed,
                "repetition": repetition,
                "timeout_seconds": timeout,
                "cwd": str(work_dir) if work_dir else None,
                "output_root": str(store.root),
                "variant_config": dict(variant.config),
            }
            target_result = spec.target.run(case, variant, context)
            if spec.pricing is not None and target_result.telemetry.cost is None:
                estimate = spec.pricing.estimate(
                    target_result.telemetry.input_tokens,
                    target_result.telemetry.output_tokens,
                )
                if estimate is not None:
                    target_result = TargetResult(
                        status=target_result.status,
                        stdout=target_result.stdout,
                        stderr=target_result.stderr,
                        exit_code=target_result.exit_code,
                        duration_seconds=target_result.duration_seconds,
                        structured_output=target_result.structured_output,
                        telemetry=target_result.telemetry.merge(cost=estimate),
                        artifacts=target_result.artifacts,
                        error_message=target_result.error_message,
                        timed_out=target_result.timed_out,
                        infrastructure_error=target_result.infrastructure_error,
                    )

            diff = None
            if work_dir is not None:
                after = snapshot_tree(work_dir)
                diff = diff_snapshots(before, after)
                tel = target_result.telemetry
                updates = {}
                if tel.files_created is None:
                    updates["files_created"] = diff.files_created
                if tel.files_modified is None:
                    updates["files_modified"] = diff.files_modified
                if tel.files_deleted is None:
                    updates["files_deleted"] = diff.files_deleted
                if updates:
                    target_result = TargetResult(
                        status=target_result.status,
                        stdout=target_result.stdout,
                        stderr=target_result.stderr,
                        exit_code=target_result.exit_code,
                        duration_seconds=target_result.duration_seconds,
                        structured_output=target_result.structured_output,
                        telemetry=tel.merge(**updates),
                        artifacts=target_result.artifacts,
                        error_message=target_result.error_message,
                        timed_out=target_result.timed_out,
                        infrastructure_error=target_result.infrastructure_error,
                    )

            eval_context = {
                "target": target_result,
                "case": case,
                "variant": variant,
                "cwd": str(work_dir) if work_dir else None,
                "workspace_diff": diff,
            }
            evaluations: list[EvaluationResult] = []
            for evaluator in spec.evaluators:
                try:
                    evaluations.append(evaluator.evaluate(eval_context))
                except Exception as exc:  # noqa: BLE001 - evaluator failure is data
                    evaluations.append(
                        EvaluationResult(
                            evaluator=getattr(evaluator, "name", type(evaluator).__name__),
                            passed=None,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
            if case.validation_command:
                v_eval = ValidationCommandEvaluator(case.validation_command)
                try:
                    evaluations.append(v_eval.evaluate(eval_context))
                except Exception as exc:  # noqa: BLE001
                    evaluations.append(
                        EvaluationResult(
                            evaluator="validation_command",
                            passed=None,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )

            if workspace_provider is not None:
                workspace_provider.assert_source_unchanged()

            result = RunResult(
                run_id=run_id,
                case_id=case.id,
                variant_id=variant.id,
                repetition=repetition,
                seed=seed,
                target=target_result,
                evaluations=tuple(evaluations),
                workspace_diff=diff,
                started_at=started_at,
                finished_at=_iso(),
            )
            store.write_run(result)
            return result
        finally:
            if tmp_holder is not None:
                tmp_holder.cleanup()
