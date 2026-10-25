"""Safe audit serialization shared by research, shadow and reservation paths."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExecutionDecision:
    candidate_id: str
    strategy_id: str
    account_profile: str
    decision_group: str
    decision_at: str
    eligibility: str
    reasons: tuple
    selected: bool = False
    selected_candidate_id: str | None = None
    conflicts: tuple = ()
    support: tuple = ()
    planned_risk: float | None = None
    available_budget: float | None = None
    quantity: int = 0
    policy_version: str = "manager-shadow-v1"
    mode: str = "conservative"
    execution_status: str = "NOT_SUBMITTED"
    checks_scope: str = "historical_only"

    def to_dict(self):
        return asdict(self)
