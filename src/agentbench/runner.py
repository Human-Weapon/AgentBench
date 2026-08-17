"""Sequential experiment runner with hard budgets and incremental persistence."""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .aggregation import aggregate_experiment
from .comparison import compare
from .errors import (
    BudgetExceededError,
    CostBoundViolationError,
    SourceMutationError,
    TargetExecutionError,
    ValidationError,
)
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
from .numbers import money
from .persistence import ResultStore, assert_unused_output
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
    _open_reservation: float = 0.0
    cost_bound_violated: bool = False
    reserved_cost: float = 0.0
    unknown_reserved_cost: float = 0.0
    _committed: Decimal = field(default_factory=lambda: Decimal("0"))
    _reserved: Decimal = field(default_factory=lambda: Decimal("0"))

    def check_can_start(
        self, *, elapsed_seconds: float, remaining_timeout: float | None = None
    ) -> None:
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
            if remaining_timeout is not None and remaining_timeout <= 0:
                raise BudgetExceededError(
                    f"max_total_duration_seconds={budget.max_total_duration_seconds} exhausted"
                )
        if budget.max_failures is not None and self.failures >= budget.max_failures:
            raise BudgetExceededError(
                f"max_failures={budget.max_failures} reached ({self.failures})"
            )

    def reserve_cost(self) -> None:
        budget = self.budget
        if self.cost_bound_violated:
            raise CostBoundViolationError(
                "cost bound already violated; further runs are not scheduled",
                reserved=self.reserved_cost,
                measured=self.committed_cost,
            )
        if budget.max_total_cost is None:
            self._reserved = Decimal("0")
            self._open_reservation = 0.0
            return
        bound = money(budget.per_run_max_cost, name="per_run_max_cost")
        cap = money(budget.max_total_cost, name="max_total_cost")
        if self._committed + bound > cap:
            raise BudgetExceededError(
                f"max_total_cost={budget.max_total_cost} exhausted "
                f"(committed={self.committed_cost}, reservation={budget.per_run_max_cost})"
            )
        self._committed += bound
        self._reserved = bound
        self.committed_cost = float(self._committed)
        self._open_reservation = float(bound)
        self.reserved_cost = float(bound)

    def reconcile_cost(self, measured: float | None) -> None:
        reserved = self._reserved
        self._reserved = Decimal("0")
        self._open_reservation = 0.0
        if reserved == 0 and measured is None:
            return
        if measured is None:
            self.cost_known = False
            self.unknown_reserved_cost += float(reserved)
            return
        measured_d = money(measured, name="cost")
        if reserved > 0:
            next_committed = self._committed - reserved + measured_d
        else:
            next_committed = self._committed + measured_d
        if next_committed < 0:
            next_committed = Decimal("0")
        self._committed = next_committed
        self.committed_cost = float(self._committed)
        if reserved > 0 and measured_d > reserved:
            self.cost_bound_violated = True

    def mark_started(self) -> None:
        self.started += 1

    def mark_finished(self, result: RunResult) -> None:
        self.completed += 1
        if result.target.status is RunStatus.FAILURE:
            self.failures += 1
        self.reconcile_cost(result.target.telemetry.cost)


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
    planned_runs: int = 0
    executed_runs: int = 0
    not_scheduled: int = 0
    committed_cost: float = 0.0
    cost_known: bool = True
    cost_bound_violated: bool = False
    budget_guarantee_breached: bool = False
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
            "planned_runs": self.planned_runs,
            "executed_runs": self.executed_runs,
            "not_scheduled": self.not_scheduled,
            "committed_cost": self.committed_cost,
            "cost_known": self.cost_known,
            "cost_bound_violated": self.cost_bound_violated,
            "budget_guarantee_breached": self.budget_guarantee_breached,
        }


class ExperimentRunner:
    """Expand case × variant × repetition and execute sequentially."""

    def run(self, spec: ExperimentSpec) -> ExperimentOutcome:
        suite = spec.suite
        if not isinstance(suite, BenchmarkSuite):
            raise ValidationError("spec.suite must be a BenchmarkSuite")
        budget = spec.budget or suite.budget
        seed = suite.seed if spec.seed is None else spec.seed
        assert_unused_output(spec.output_root)
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
            remaining = None
            if budget.max_total_duration_seconds is not None:
                remaining = budget.max_total_duration_seconds - elapsed
            try:
                ledger.check_can_start(elapsed_seconds=elapsed, remaining_timeout=remaining)
                ledger.reserve_cost()
            except BudgetExceededError as exc:
                budget_exhausted = True
                stopped_reason = str(exc)
                break

            case_timeout = (
                case.timeout_seconds
                if case.timeout_seconds is not None
                else budget.per_run_timeout_seconds
            )
            if remaining is not None:
                case_timeout = min(case_timeout, remaining)

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
                    timeout_seconds=case_timeout,
                )
            except SourceMutationError:
                ledger.reconcile_cost(None)
                raise
            except TargetExecutionError:
                ledger.reconcile_cost(None)
                raise
            ledger.mark_finished(result)
            runs.append(result)
            if ledger.cost_bound_violated:
                reserved = ledger.reserved_cost
                measured = result.target.telemetry.cost
                stopped_reason = (
                    f"cost bound contract violated: per_run_max_cost={reserved} "
                    f"but measured={measured}; hard cost cap is no longer enforceable"
                )
                break
            if result.target.infrastructure_error:
                stopped_reason = result.target.error_message or "infrastructure error"
                break

        not_scheduled = len(planned) - len(runs)

        summary = aggregate_experiment(runs)
        store.write_json("summary.json", summary)
        comparison = None
        baseline = suite.baseline_variant_id
        if spec.policy is not None:
            baseline = spec.policy.baseline_variant_id
        if baseline:
            if any(r.variant_id == baseline for r in runs):
                metrics = [m.name for m in suite.metrics] or None
                comparison = compare(
                    runs,
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
            planned_runs=len(planned),
            executed_runs=len(runs),
            not_scheduled=not_scheduled,
            committed_cost=ledger.committed_cost,
            cost_known=ledger.cost_known,
            cost_bound_violated=ledger.cost_bound_violated,
            budget_guarantee_breached=ledger.cost_bound_violated,
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
                    "per_run_max_cost": budget.per_run_max_cost,
                },
                "committed_cost": ledger.committed_cost,
                "cost_known": ledger.cost_known,
                "unknown_reserved_cost": ledger.unknown_reserved_cost,
                "cost_bound_violated": ledger.cost_bound_violated,
                "budget_guarantee_breached": ledger.cost_bound_violated,
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
        timeout_seconds: float,
    ) -> RunResult:
        run_id = make_run_id(suite.id, case.id, variant.id, repetition, seed)
        timeout = timeout_seconds
        started_at = _iso()
        work_dir: Path | None = None
        tmp_holder = None
        active_provider = workspace_provider
        before = {}
        try:
            if case.workspace_template:
                active_provider = DirectoryCopyWorkspace(case.workspace_template)
            if active_provider is not None:
                tmp_holder = tempfile.TemporaryDirectory(prefix="agentbench-ws-")
                work_dir = active_provider.create(Path(tmp_holder.name) / run_id)
                write_case_files(
                    work_dir,
                    {"id": case.id, "payload": case.payload, "expected": case.expected},
                    {"id": variant.id, "config": dict(variant.config)},
                )
                before = snapshot_tree(work_dir)
                active_provider.assert_source_unchanged()

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
            if not isinstance(target_result, TargetResult):
                raise TargetExecutionError(
                    f"target returned {type(target_result).__name__}, expected TargetResult"
                )
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

            if active_provider is not None:
                active_provider.assert_source_unchanged()

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
