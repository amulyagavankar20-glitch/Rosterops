"""Deterministic, explainable roster allocator and independent coverage validator.

Coverage requirements and approved leave are hard constraints. Preferred weekly offs
are soft preferences and may be overridden when coverage otherwise cannot be met.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional
import calendar
from sqlalchemy.orm import Session, joinedload
from app.models import (Employee, Brand, Process, Assignment, PublicHoliday, Leave,
                        RosterEntry, RosterAllocation, CoverageRequirement, OperatingMode)


def get_month_dates(year: int, month: int):
    return [date(year, month, day) for day in range(1, calendar.monthrange(year, month)[1] + 1)]


def is_operating_day(d: date, mode: str, holidays: set[date]) -> bool:
    if mode == OperatingMode.FULL_365.value:
        return True
    if mode == OperatingMode.DAILY_EXCEPT_HOLIDAYS.value:
        return d not in holidays
    return d.weekday() != 6 and d not in holidays


def _approved_leave_map(db: Session, start: date, end: date):
    result = defaultdict(list)
    for leave in db.query(Leave).filter(Leave.status == "approved", Leave.start_date <= end, Leave.end_date >= start):
        result[leave.employee_id].append((leave.start_date, leave.end_date))
    return result


def _required_staff(db: Session, brand_id: int, process: Process, d: date) -> int:
    rules = db.query(CoverageRequirement).filter(
        CoverageRequirement.brand_id == brand_id,
        (CoverageRequirement.process_id == process.id) | (CoverageRequirement.process_id.is_(None)),
        (CoverageRequirement.day_of_week == d.strftime("%A")) | (CoverageRequirement.day_of_week.is_(None)),
    ).all()
    # Most-specific rule wins: process+weekday > process > brand+weekday > brand.
    if rules:
        rules.sort(key=lambda r: (r.process_id is not None, r.day_of_week is not None), reverse=True)
        return max(0, int(rules[0].min_staff))
    return max(0, int(process.min_staffing or 1))


def generate_roster(db: Session, year: int, month: int, clear_existing: bool = True) -> dict:
    dates = get_month_dates(year, month)
    start, end = dates[0], dates[-1]
    employees = db.query(Employee).order_by(Employee.id).all()
    brands = {b.id: b for b in db.query(Brand).all()}
    processes = {p.id: p for p in db.query(Process).all()}
    assignments = db.query(Assignment).all()
    holidays = {h.date for h in db.query(PublicHoliday).filter(PublicHoliday.date >= start, PublicHoliday.date <= end)}
    leave_map = _approved_leave_map(db, start, end)

    eligible = defaultdict(list)
    for a in assignments:
        if a.employee_id in {e.id for e in employees} and a.brand_id in brands and a.process_id in processes:
            eligible[(a.brand_id, a.process_id)].append((a.employee_id, bool(a.is_primary)))

    # Build daily demand in priority order: larger minimums and 365-day services first.
    demands = []
    for (brand_id, process_id), employee_links in eligible.items():
        brand, process = brands[brand_id], processes[process_id]
        mode = process.operating_mode or brand.operating_mode or OperatingMode.WEEKDAYS_ONLY.value
        for d in dates:
            if is_operating_day(d, mode, holidays):
                required = _required_staff(db, brand_id, process, d)
                if required:
                    demands.append((d, brand_id, process_id, required, mode, employee_links))
    demands.sort(key=lambda x: (x[0], x[4] != OperatingMode.FULL_365.value, -x[3], x[1], x[2]))

    employee_by_id = {e.id: e for e in employees}
    daily_load = defaultdict(int)
    daily_allocations = defaultdict(list)
    allocations = []
    coverage = []
    conflicts = []
    manual_pins = defaultdict(list)
    # In read-only validation mode, preserve manager-entered allocations as pinned
    # decisions and validate the rest of the roster around them.
    if not clear_existing:
        for pinned in db.query(RosterAllocation).filter(RosterAllocation.date >= start, RosterAllocation.date <= end, RosterAllocation.source == "manual").all():
            manual_pins[(pinned.date, pinned.brand_id, pinned.process_id)].append(pinned.employee_id)
            daily_load[(pinned.employee_id, pinned.date)] += pinned.workload_units

    for d, brand_id, process_id, required, mode, employee_links in demands:
        brand, process = brands[brand_id], processes[process_id]
        selected = []
        # Preserve explicit manager allocations during validation; the generated
        # remainder is still deterministic and capacity-aware.
        for pinned_id in manual_pins.get((d, brand_id, process_id), []):
            if not any(a <= d <= b for a, b in leave_map.get(pinned_id, [])):
                selected.append(pinned_id)
        # Avoid counting one employee twice for the same process/day.
        unique_links = {emp_id: primary for emp_id, primary in employee_links}
        candidates = []
        for emp_id, primary in unique_links.items():
            if emp_id in selected:
                continue
            emp = employee_by_id[emp_id]
            on_leave = any(a <= d <= b for a, b in leave_map.get(emp_id, []))
            if on_leave:
                continue
            # Employees are allowed to work public holidays/Sundays when the client process operates.
            if daily_load[(emp_id, d)] + 1 > max(1, emp.daily_capacity or 1):
                continue
            is_weekly_off = d.strftime("%A") == (emp.preferred_weekly_off or "Sunday")
            # Prefer primary assignees, avoid overriding weekly offs, then balance workload.
            score = (1 if is_weekly_off else 0, daily_load[(emp_id, d)], 0 if primary else 1, emp_id)
            candidates.append((score, emp_id, is_weekly_off))
        candidates.sort(key=lambda x: x[0])
        for _, emp_id, weekly_off_override in candidates[:max(0, required - len(selected))]:
            selected.append(emp_id)
            daily_load[(emp_id, d)] += 1
            daily_allocations[(emp_id, d)].append((brand_id, process_id))
            allocations.append(RosterAllocation(employee_id=emp_id, brand_id=brand_id,
                process_id=process_id, date=d, workload_units=1, source="deterministic"))
        row = {"date": d.isoformat(), "brand": brand.name, "brand_id": brand_id,
               "process": process.name, "process_id": process_id, "required": required,
               "available": len(selected), "available_names": [employee_by_id[i].name for i in selected],
               "status": "ok" if len(selected) >= required else "gap"}
        coverage.append(row)
        if len(selected) < required:
            unavailable = []
            for emp_id, _ in unique_links.items():
                emp = employee_by_id[emp_id]
                if any(a <= d <= b for a, b in leave_map.get(emp_id, [])):
                    reason = "approved leave"
                elif daily_load[(emp_id, d)] >= max(1, emp.daily_capacity or 1):
                    reason = "daily capacity already allocated"
                elif d.strftime("%A") == (emp.preferred_weekly_off or "Sunday"):
                    reason = "preferred weekly off (soft constraint)"
                else:
                    reason = "not selected by allocation priority"
                unavailable.append({"employee": emp.name, "reason": reason})
            conflicts.append({"type": "coverage_gap", "severity": "critical" if not selected else "warning",
                "date": d.isoformat(), "brand": brand.name, "brand_id": brand_id,
                "process": process.name, "process_id": process_id, "required": required,
                "available": len(selected), "available_names": row["available_names"],
                "message": f"{brand.name} / {process.name} requires {required} on {d.isoformat()}, allocated {len(selected)}.",
                "candidate_diagnostics": unavailable,
                "suggested_actions": _backup_recommendations(db, brand_id, process_id, d, required-len(selected), employee_by_id, daily_load, leave_map)})

    # Persist as one transaction after calculation. No partial delete/commit.
    if clear_existing:
        db.query(RosterAllocation).filter(RosterAllocation.date >= start, RosterAllocation.date <= end).delete(synchronize_session=False)
        db.query(RosterEntry).filter(RosterEntry.date >= start, RosterEntry.date <= end).delete(synchronize_session=False)
        db.add_all(allocations)
        allocation_keys = {(a.employee_id, a.date) for a in allocations}
        for emp in employees:
            for d in dates:
                if any(a <= d <= b for a, b in leave_map.get(emp.id, [])):
                    status = "leave"
                elif (emp.id, d) in allocation_keys:
                    status = "working"
                elif d in holidays:
                    status = "holiday"
                elif d.strftime("%A") == (emp.preferred_weekly_off or "Sunday"):
                    status = "weekly_off"
                else:
                    status = "off"
                note = "Preferred weekly off overridden to protect client coverage" if status == "working" and d.strftime("%A") == (emp.preferred_weekly_off or "Sunday") else None
                db.add(RosterEntry(employee_id=emp.id, date=d, status=status, notes=note))
        db.commit()

    total = len(coverage)
    ok = sum(1 for r in coverage if r["status"] == "ok")
    summary = {"year": year, "month": month, "total_days": len(dates), "employees": len(employees),
        "brands": len(brands), "processes": len(processes), "allocation_count": len(allocations),
        "conflicts_count": len(conflicts), "critical_conflicts": sum(c["severity"] == "critical" for c in conflicts),
        "coverage_ok_pct": round(100 * ok / total, 1) if total else 100.0}
    return {"summary": summary, "conflicts": conflicts, "coverage_report": coverage}


def _backup_recommendations(db, brand_id, process_id, d, shortage, employee_by_id, daily_load, leave_map):
    # Recommend employees in the same pod/brand ecosystem who are not already assigned that day.
    assigned_ids = {a.employee_id for a in db.query(Assignment).filter(Assignment.brand_id == brand_id).all()}
    assigned_pods = {employee_by_id[i].pod_id for i in assigned_ids if i in employee_by_id}
    recs = []
    for emp in employee_by_id.values():
        if emp.id in assigned_ids or emp.pod_id not in assigned_pods:
            continue
        if any(a <= d <= b for a, b in leave_map.get(emp.id, [])):
            continue
        if daily_load[(emp.id, d)] >= max(1, emp.daily_capacity or 1):
            continue
        recs.append({"employee_id": emp.id, "employee": emp.name, "pod_id": emp.pod_id,
                     "current_load": daily_load[(emp.id, d)], "reason": "Same pod; no approved leave; capacity available",
                     "requires_temporary_assignment": True})
    return recs[:max(3, shortage)]


def analyze_leave_impact(db: Session, employee_id: int, start_date: date, end_date: date) -> dict:
    """Simulate a leave without persisting it and report impacted services and backups."""
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return {"error": "Employee not found"}
    original = _approved_leave_map(db, start_date, end_date)
    original[employee_id].append((start_date, end_date))
    assignments = db.query(Assignment).filter(Assignment.employee_id == employee_id).all()
    impacts = []
    holidays = {h.date for h in db.query(PublicHoliday).filter(PublicHoliday.date >= start_date, PublicHoliday.date <= end_date)}
    for a in assignments:
        brand = db.query(Brand).filter(Brand.id == a.brand_id).first()
        process = db.query(Process).filter(Process.id == a.process_id).first()
        if not brand or not process: continue
        mode = process.operating_mode or brand.operating_mode
        d = start_date
        while d <= end_date:
            if is_operating_day(d, mode, holidays):
                impacts.append({"date": d.isoformat(), "brand": brand.name, "process": process.name,
                                "employee": emp.name, "risk": "coverage review required"})
            d += timedelta(days=1)
    return {"employee": emp.name, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
            "affected_assignments": len(assignments), "impacted_service_days": impacts,
            "requires_revalidation": bool(impacts), "approval_required": True}


def apply_leave_and_revalidate(db: Session, employee_id: int, start_date: date, end_date: date,
                               leave_type: str = "planned", year: int = None, month: int = None) -> dict:
    """Compatibility function: create a pending request, never auto-approve it."""
    from app.models import LeaveRequest
    if end_date < start_date: return {"error": "End date must be on or after start date"}
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp: return {"error": "Employee not found"}
    impact = analyze_leave_impact(db, employee_id, start_date, end_date)
    request = LeaveRequest(employee_id=employee_id, start_date=start_date, end_date=end_date,
                           leave_type=leave_type, status="pending", impact_json=str(impact))
    db.add(request); db.commit()
    return {"request_id": request.id, "status": "pending", "impact": impact,
            "message": "Leave request recorded as pending. An authorized manager must approve it."}


def review_leave_request(db: Session, request_id: int, approve: bool, reviewer: str = "manager") -> dict:
    from app.models import LeaveRequest, AuditEvent
    request = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not request: return {"error": "Leave request not found"}
    if request.status != "pending": return {"error": f"Request is already {request.status}"}
    request.status = "approved" if approve else "rejected"
    request.reviewed_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc); request.reviewer = reviewer
    if approve:
        db.add(Leave(employee_id=request.employee_id, start_date=request.start_date, end_date=request.end_date,
                     leave_type=request.leave_type, status="approved", notes=f"Approved request #{request.id}"))
    db.add(AuditEvent(event_type="leave_approved" if approve else "leave_rejected", entity_type="leave_request",
                      entity_id=request.id, actor=reviewer, details=request.status))
    db.commit()
    impacts = []
    if approve:
        cursor = date(request.start_date.year, request.start_date.month, 1)
        last = date(request.end_date.year, request.end_date.month, 1)
        while cursor <= last:
            impacts.append(generate_roster(db, cursor.year, cursor.month, clear_existing=True))
            cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return {"request_id": request.id, "status": request.status, "revalidation": impacts}


def get_roster_view(db: Session, year: int, month: int, view_type: str = "company", filter_id: Optional[int] = None) -> dict:
    dates = get_month_dates(year, month)
    entries = db.query(RosterEntry).filter(RosterEntry.date >= dates[0], RosterEntry.date <= dates[-1]).all()
    emp_map = {e.id: e for e in db.query(Employee).all()}
    if view_type == "employee" and filter_id:
        emp = emp_map.get(filter_id)
        selected = [e for e in entries if e.employee_id == filter_id]
        return {"view": "employee", "employee": emp.name if emp else None,
                "entries": [{"date": e.date.isoformat(), "status": e.status} for e in sorted(selected, key=lambda x:x.date)]}
    if view_type == "pod" and filter_id:
        selected_ids = {e.id for e in emp_map.values() if e.pod_id == filter_id}
        entries = [e for e in entries if e.employee_id in selected_ids]
    grouped = defaultdict(list)
    for e in entries:
        name = emp_map[e.employee_id].name if e.employee_id in emp_map else str(e.employee_id)
        grouped[name].append({"date": e.date.isoformat(), "status": e.status})
    return {"view": view_type, "entries_by_employee": dict(grouped)}
