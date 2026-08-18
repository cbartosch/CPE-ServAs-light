"""Predictive modem scanning: a scheduled branch that feeds the main flow.

Design decisions were taken by the operator, not inferred:

1. Two ticket classes. `forecast` claims a modem will breach an alarm threshold
   within the horizon; `proactive` claims it has already breached but nobody has
   called. Different urgency, different SLA.
2. Auto-remediate first, gate second. This activates `PolicyVerdict.ALLOWED`,
   which existed in the domain model and which no code path had ever returned.
   The main engine gates every action; this branch does not, by design.
3. A separate scheduled service, feeding tickets into the existing flow rather
   than running inside `WorkflowEngine`.
4. The forecast class auto-remediates too, including a reboot, even though the
   modem is currently working.
5. On a customer call for a modem with an open predictive ticket, the predictive
   ticket stays parent and the reactive one attaches. The SLA clock runs from when
   the scan opened it, not from the call.
6. Notification is required when a truck roll will be needed, when a hard failure
   is forecast inside the horizon, or when the modem is a repeat offender. A
   service-affecting remediation on its own does **not** require notification.

Decisions 4 and 6 interact and the consequence is worth stating plainly: a working
modem can be rebooted automatically with no customer notification. The control that
keeps that acceptable is the maintenance window, so it is a first-class parameter
in `config.py` rather than a constant buried in the remediation code.

Everything here is standard library only. The main engine needs pydantic and cannot
run in every environment; this branch is independently runnable and testable, which
is the point of it being a separate service.
"""

from __future__ import annotations

__all__ = ["config", "signals", "scanner", "pipeline", "handoff"]
