from __future__ import annotations

from tistory_growth_os.contracts.json_ast import JsonValue

from .common import (
    Fields,
    array,
    boolean,
    date_value,
    datetime_value,
    enum_value,
    fail,
    identifier,
    strings,
    text,
)
from .evolution import (
    BDWClass,
    ChangeTarget,
    EvolutionDecision,
    EvolutionProposal,
    Experiment,
    ExperimentStatus,
)
from .ids import EvolutionProposalId, ExperimentId, MetricsId, PostId
from .publishing_decode_support import (
    integer,
    number,
    require_version,
    signed_number,
)
from .publishing_future import (
    MetricSource,
    MetricStatus,
    MetricValue,
    PostMetrics,
)


def decode_post_metrics(value: JsonValue) -> PostMetrics:
    fields = Fields.parse(
        value,
        "",
        (
            "schema_version",
            "metrics_id",
            "post_id",
            "source",
            "surface",
            "status",
            "interval_start",
            "interval_end",
            "update_basis_date",
            "ingested_at",
            "retention_days",
            "is_truncated",
            "values",
        ),
    )
    require_version(fields)
    status = enum_value(fields, "status", MetricStatus)
    values = tuple(
        _decode_metric(item, f"/values/{index}")
        for index, item in enumerate(array(fields, "values", False))
    )
    match status:
        case MetricStatus.UNKNOWN | MetricStatus.UNAUTHORIZED:
            observed = False
        case MetricStatus.OBSERVED:
            observed = True
    if not observed and values:
        fail(
            "/values",
            "dependentRequired",
            "unobserved metrics cannot carry numeric values",
        )
    start = date_value(fields, "interval_start")
    end = date_value(fields, "interval_end")
    retention = integer(fields, "retention_days")
    if end < start:
        fail("/interval_end", "range", "interval end cannot precede start")
    return PostMetrics(
        metrics_id=MetricsId(
            identifier(fields, "metrics_id", r"metrics_[a-z0-9_-]{3,64}")
        ),
        post_id=PostId(identifier(fields, "post_id", r"post_[a-z0-9_-]{3,64}")),
        source=enum_value(fields, "source", MetricSource),
        surface=text(fields, "surface"),
        status=status,
        interval_start=start,
        interval_end=end,
        update_basis_date=date_value(fields, "update_basis_date"),
        ingested_at=datetime_value(fields, "ingested_at"),
        retention_days=retention,
        is_truncated=boolean(fields, "is_truncated"),
        values=values,
    )


def decode_experiment(value: JsonValue) -> Experiment:
    fields = Fields.parse(
        value,
        "",
        (
            "schema_version",
            "experiment_id",
            "post_ids",
            "hypothesis",
            "controllable_factor",
            "primary_metric",
            "acceptance_threshold",
            "status",
            "started_at",
            "observation_end",
            "rollback_condition",
        ),
    )
    require_version(fields)
    started = datetime_value(fields, "started_at")
    end = datetime_value(fields, "observation_end")
    if end < started:
        fail("/observation_end", "range", "observation cannot end before start")
    post_ids = tuple(
        PostId(item)
        for item in strings(fields, "post_ids", True, r"post_[a-z0-9_-]{3,64}")
    )
    return Experiment(
        experiment_id=ExperimentId(
            identifier(fields, "experiment_id", r"exp_[a-z0-9_-]{3,64}")
        ),
        post_ids=post_ids,
        hypothesis=text(fields, "hypothesis"),
        controllable_factor=text(fields, "controllable_factor"),
        primary_metric=text(fields, "primary_metric"),
        acceptance_threshold=signed_number(fields, "acceptance_threshold"),
        status=enum_value(fields, "status", ExperimentStatus),
        started_at=started,
        observation_end=end,
        rollback_condition=text(fields, "rollback_condition"),
    )


def decode_evolution_proposal(value: JsonValue) -> EvolutionProposal:
    fields = Fields.parse(
        value,
        "",
        (
            "schema_version",
            "proposal_id",
            "observed_trace_id",
            "bdw_class",
            "root_cause_hypothesis",
            "change_target",
            "expected_effect",
            "regression_risk",
            "eval_ids",
            "acceptance_threshold",
            "cost_budget_krw",
            "latency_budget_seconds",
            "canary_scope",
            "rollback_condition",
            "decision",
            "owner_approval_required",
            "recorded_at",
        ),
    )
    require_version(fields)
    target = enum_value(fields, "change_target", ChangeTarget)
    approval = boolean(fields, "owner_approval_required")
    match target:
        case ChangeTarget.POLICY | ChangeTarget.SCHEMA:
            protected = True
        case (
            ChangeTarget.PROMPT
            | ChangeTarget.MODEL
            | ChangeTarget.REASONING
            | ChangeTarget.TOOL
            | ChangeTarget.HARNESS
            | ChangeTarget.WORKFLOW
        ):
            protected = False
    if protected and not approval:
        fail(
            "/owner_approval_required",
            "policy",
            "protected policy, rights, and threshold changes require owner approval",
        )
    return EvolutionProposal(
        proposal_id=EvolutionProposalId(
            identifier(fields, "proposal_id", r"evo_[a-z0-9_-]{3,64}")
        ),
        observed_trace_id=text(fields, "observed_trace_id"),
        bdw_class=enum_value(fields, "bdw_class", BDWClass),
        root_cause_hypothesis=text(fields, "root_cause_hypothesis"),
        change_target=target,
        expected_effect=text(fields, "expected_effect"),
        regression_risk=text(fields, "regression_risk"),
        eval_ids=strings(fields, "eval_ids", True, r".+"),
        acceptance_threshold=signed_number(fields, "acceptance_threshold"),
        cost_budget_krw=number(fields, "cost_budget_krw"),
        latency_budget_seconds=number(fields, "latency_budget_seconds"),
        canary_scope=text(fields, "canary_scope"),
        rollback_condition=text(fields, "rollback_condition"),
        decision=enum_value(fields, "decision", EvolutionDecision),
        owner_approval_required=approval,
        recorded_at=datetime_value(fields, "recorded_at"),
    )


def _decode_metric(value: JsonValue, pointer: str) -> MetricValue:
    fields = Fields.parse(value, pointer, ("metric", "value", "unit"))
    return MetricValue(
        metric=text(fields, "metric"),
        value=number(fields, "value"),
        unit=text(fields, "unit"),
    )
