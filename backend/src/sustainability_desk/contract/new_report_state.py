# ABOUTME(en): The initial StoredReportState of a freshly created report, derived from its knowledge package.
# ABOUTME(en): Field set and defaults both come from the package contract, so a report never carries another
# ABOUTME(en): package's fields. Owned server-side: the client has no authoritative view of a package's contract.
from __future__ import annotations

from datetime import date

from sustainability_desk.contract.knowledge_packages import KnowledgePackage
from sustainability_desk.contract.loader import load_package_contract
from sustainability_desk.contract.stored_report_state import (
    StoredReportStateV4,
    empty_stored_report_state,
)

#: Default rules a package may declare on `inputGuidance`. The contract validator
#: (`models.Report._validate_input_guidance`) already pins each rule to one field path,
#: so the rule name alone determines what is derived.
_REPORTING_YEAR_RULE = "previous_calendar_year"
_PERIOD_START_RULE = "reporting_year_start"
_PERIOD_END_RULE = "reporting_year_end"


def _reporting_year(today: date) -> str:
    """A report covers the completed calendar year, so the default is last year."""

    return str(today.year - 1)


def new_report_state(package: KnowledgePackage, *, today: date | None = None) -> StoredReportStateV4:
    """Initial persisted state for a new report on `package`.

    The field set is the package's own: seeding from a client-side template would carry
    fields another package never declares (an HKEX report would ask about the Mainland-only
    technology-ethics scope), and `plan_report` merges client fields over package fields,
    so such extras survive every later reload.

    Defaults come from the package's `inputGuidance.defaultRule`; a package that declares
    none simply gets empty values. Only the reporting year and period are derivable —
    everything else is a user fact.
    """

    contract = load_package_contract(package)
    resolved = today or date.today()
    values: dict[str, str | int | float | None] = {key: None for key in contract.fields}

    rules = {
        path: guidance.defaultRule
        for path, guidance in (contract.inputGuidance or {}).items()
        if guidance.defaultRule
    }
    year: str | None = None
    for path, rule in rules.items():
        field_key = path.removeprefix("fields.").removesuffix(".value")
        if field_key not in values:
            continue
        if rule == _REPORTING_YEAR_RULE:
            year = _reporting_year(resolved)
            values[field_key] = year

    # Period bounds derive from the reporting year, so they are resolved after it.
    if year is not None:
        for path, rule in rules.items():
            field_key = path.removeprefix("fields.").removesuffix(".value")
            if field_key not in values:
                continue
            if rule == _PERIOD_START_RULE:
                values[field_key] = f"{year}-01-01"
            elif rule == _PERIOD_END_RULE:
                values[field_key] = f"{year}-12-31"

    state = empty_stored_report_state()
    state.fields = values
    return state
