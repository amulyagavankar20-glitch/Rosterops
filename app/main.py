"""FastAPI service for the Smart Roster Management System."""
import os
from datetime import date
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import init_db, get_db
from app.models import Employee, Brand, Process, Pod, Assignment, LeaveRequest, RosterAllocation, CoverageRequirement, AuditEvent, PublicHoliday, Leave, RosterEntry
from app.scheduler import generate_roster, analyze_leave_impact, apply_leave_and_revalidate, review_leave_request

app = FastAPI(title="Smart Roster Management API", version="2.0.0", description="Deterministic workforce scheduling with agent-assisted operational recommendations")
origins = os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET","POST","PATCH","PUT","DELETE"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    if os.getenv("APP_ENV", "development") == "production" and not os.getenv("API_ACCESS_KEY"):
        raise RuntimeError("API_ACCESS_KEY must be configured before production startup")
    init_db()
    if os.getenv("SEED_DEMO_DATA", "true").lower() == "true":
        from app.database import SessionLocal
        from app.sample_data import seed_database
        db = SessionLocal()
        try:
            if db.query(Employee).count() == 0:
                seed_database(db)
        finally:
            db.close()


def require_read_access(x_api_key: Optional[str] = Header(default=None)):
    expected = os.getenv("API_ACCESS_KEY")
    if os.getenv("APP_ENV", "development") == "production" and not expected:
        raise HTTPException(503, "API_ACCESS_KEY must be configured in production")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Valid X-API-Key required")

def require_write_access(x_api_key: Optional[str] = Header(default=None)):
    require_read_access(x_api_key)


class EmployeeIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: Optional[str] = None
    pod_id: Optional[int] = None
    preferred_weekly_off: str = "Sunday"
    daily_capacity: int = Field(default=3, ge=1, le=8)
    is_pod_lead: bool = False

class PodIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)

class BrandIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    operating_mode: str = "weekdays_only"
    notes: Optional[str] = None

class ProcessIn(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    brand_id: int
    min_staffing: int = Field(default=1, ge=1, le=50)
    operating_mode: Optional[str] = None

class AssignmentIn(BaseModel):
    employee_id: int
    brand_id: int
    process_id: int
    is_primary: bool = True

class LeaveIn(BaseModel):
    employee_id: int
    start_date: date
    end_date: date
    leave_type: str = "planned"
    reason: Optional[str] = None

class LeaveReviewIn(BaseModel):
    approve: bool
    reviewer: str = "operations_manager"

class GenerateIn(BaseModel):
    year: int = Field(ge=2024, le=2100)
    month: int = Field(ge=1, le=12)

class ImpactIn(BaseModel):
    employee_id: int
    start_date: date
    end_date: date

class CoverageRuleIn(BaseModel):
    brand_id: int
    process_id: Optional[int] = None
    day_of_week: Optional[str] = None
    min_staff: int = Field(ge=0, le=100)

class HolidayIn(BaseModel):
    date: date
    name: str = Field(min_length=2, max_length=100)

class ManualAllocationIn(BaseModel):
    employee_id: int
    brand_id: int
    process_id: int
    date: date

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(__import__('sqlalchemy').text("SELECT 1"))
    return {"status":"ok", "service":"roster-api", "database":"connected"}

@app.get("/api/dashboard", dependencies=[Depends(require_read_access)])
def dashboard(db: Session = Depends(get_db)):
    return {"employees": db.query(Employee).count(), "brands": db.query(Brand).count(),
            "processes": db.query(Process).count(), "pods": db.query(Pod).count(),
            "assignments": db.query(Assignment).count(), "pending_leave_requests": db.query(LeaveRequest).filter(LeaveRequest.status=="pending").count()}

@app.get("/api/employees", dependencies=[Depends(require_read_access)])
def employees(db: Session = Depends(get_db)):
    return [{"id":e.id,"name":e.name,"email":e.email,"pod_id":e.pod_id,"pod":e.pod.name if e.pod else None,
             "weekly_off":e.preferred_weekly_off,"daily_capacity":e.daily_capacity} for e in db.query(Employee).order_by(Employee.name)]

@app.post("/api/employees", dependencies=[Depends(require_write_access)])
def create_employee(payload: EmployeeIn, db: Session = Depends(get_db)):
    e=Employee(name=payload.name,email=payload.email,pod_id=payload.pod_id,preferred_weekly_off=payload.preferred_weekly_off,daily_capacity=payload.daily_capacity,is_pod_lead=payload.is_pod_lead)
    db.add(e); db.commit(); db.refresh(e); return {"id":e.id,"name":e.name}

@app.get("/api/assignments", dependencies=[Depends(require_read_access)])
def assignments(db: Session = Depends(get_db)):
    return [{"id":a.id,"employee_id":a.employee_id,"employee":a.employee.name,"brand_id":a.brand_id,"brand":a.brand.name,"process_id":a.process_id,"process":a.process.name,"is_primary":a.is_primary} for a in db.query(Assignment).order_by(Assignment.id)]

@app.get("/api/processes", dependencies=[Depends(require_read_access)])
def processes(db: Session = Depends(get_db)):
    return [{"id":p.id,"name":p.name,"brand_id":p.brand_id,"brand":p.brand.name,"min_staffing":p.min_staffing,"operating_mode":p.operating_mode} for p in db.query(Process).order_by(Process.brand_id,Process.name)]

@app.get("/api/brands", dependencies=[Depends(require_read_access)])
def brands(db: Session = Depends(get_db)):
    return [{"id":b.id,"name":b.name,"operating_mode":b.operating_mode,"processes":[{"id":p.id,"name":p.name,"min_staffing":p.min_staffing,"operating_mode":p.operating_mode} for p in b.processes],"employees":len({a.employee_id for a in b.assignments})} for b in db.query(Brand).order_by(Brand.name)]

@app.post("/api/brands", dependencies=[Depends(require_write_access)])
def create_brand(payload: BrandIn, db: Session = Depends(get_db)):
    b=Brand(name=payload.name,operating_mode=payload.operating_mode,notes=payload.notes); db.add(b); db.commit(); db.refresh(b); return {"id":b.id,"name":b.name}

@app.post("/api/processes", dependencies=[Depends(require_write_access)])
def create_process(payload: ProcessIn, db: Session = Depends(get_db)):
    if not db.query(Brand).filter(Brand.id==payload.brand_id).first(): raise HTTPException(404,"Brand not found")
    p=Process(name=payload.name,brand_id=payload.brand_id,min_staffing=payload.min_staffing,operating_mode=payload.operating_mode); db.add(p); db.commit(); db.refresh(p); return {"id":p.id,"name":p.name}

@app.post("/api/assignments", dependencies=[Depends(require_write_access)])
def create_assignment(payload: AssignmentIn, db: Session = Depends(get_db)):
    if not db.query(Employee).filter(Employee.id==payload.employee_id).first(): raise HTTPException(404,"Employee not found")
    process=db.query(Process).filter(Process.id==payload.process_id,Process.brand_id==payload.brand_id).first()
    if not process: raise HTTPException(422,"Process does not belong to the selected brand")
    existing=db.query(Assignment).filter_by(employee_id=payload.employee_id,brand_id=payload.brand_id,process_id=payload.process_id).first()
    if existing: raise HTTPException(409,"Assignment already exists")
    a=Assignment(**payload.model_dump()); db.add(a); db.commit(); db.refresh(a); return {"id":a.id,"status":"created"}


@app.get("/api/pods", dependencies=[Depends(require_read_access)])
def pods(db: Session = Depends(get_db)):
    return [{"id":p.id,"name":p.name,"lead_id":p.lead_id,"lead":p.lead.name if p.lead else None,"employees":[e.name for e in p.employees]} for p in db.query(Pod).order_by(Pod.name)]

@app.post("/api/pods", dependencies=[Depends(require_write_access)])
def create_pod(payload: PodIn, db: Session = Depends(get_db)):
    pod=Pod(name=payload.name); db.add(pod); db.commit(); db.refresh(pod); return {"id":pod.id,"name":pod.name}

@app.get("/api/holidays", dependencies=[Depends(require_read_access)])
def holidays(db: Session = Depends(get_db)):
    return [{"id":h.id,"date":h.date.isoformat(),"name":h.name} for h in db.query(PublicHoliday).order_by(PublicHoliday.date)]

@app.post("/api/holidays", dependencies=[Depends(require_write_access)])
def create_holiday(payload: HolidayIn, db: Session = Depends(get_db)):
    if db.query(PublicHoliday).filter(PublicHoliday.date==payload.date).first(): raise HTTPException(409,"Holiday already exists for this date")
    h=PublicHoliday(date=payload.date,name=payload.name); db.add(h); db.commit(); db.refresh(h); return {"id":h.id,"date":h.date.isoformat(),"name":h.name}

@app.post("/api/coverage-rules", dependencies=[Depends(require_write_access)])
def create_coverage_rule(payload: CoverageRuleIn, db: Session = Depends(get_db)):
    if not db.query(Brand).filter(Brand.id==payload.brand_id).first(): raise HTTPException(404,"Brand not found")
    if payload.process_id and not db.query(Process).filter(Process.id==payload.process_id,Process.brand_id==payload.brand_id).first(): raise HTTPException(422,"Process does not belong to brand")
    rule=CoverageRequirement(**payload.model_dump()); db.add(rule); db.commit(); db.refresh(rule); return {"id":rule.id,"status":"created"}

@app.get("/api/rosters/view", dependencies=[Depends(require_read_access)])
def roster_view(year: int, month: int, view_type: str = "company", filter_id: Optional[int] = None, db: Session = Depends(get_db)):
    from calendar import monthrange
    if view_type not in {"company","pod","brand","process","employee"}: raise HTTPException(422,"Unsupported view_type")
    start=date(year,month,1); end=date(year,month,monthrange(year,month)[1])
    q=db.query(RosterAllocation).filter(RosterAllocation.date>=start,RosterAllocation.date<=end)
    if view_type == "employee" and filter_id is not None: q=q.filter(RosterAllocation.employee_id==filter_id)
    elif view_type == "brand" and filter_id is not None: q=q.filter(RosterAllocation.brand_id==filter_id)
    elif view_type == "process" and filter_id is not None: q=q.filter(RosterAllocation.process_id==filter_id)
    elif view_type == "pod" and filter_id is not None: q=q.join(Employee, RosterAllocation.employee_id==Employee.id).filter(Employee.pod_id==filter_id)
    allocations=[{"date":r.date.isoformat(),"employee":r.employee.name,"employee_id":r.employee_id,"brand":r.brand.name,"brand_id":r.brand_id,"process":r.process.name,"process_id":r.process_id} for r in q.order_by(RosterAllocation.date).all()]
    response={"view_type":view_type,"allocations":allocations}
    if view_type == "employee" and filter_id is not None:
        response["daily_status"]=[{"date":r.date.isoformat(),"status":r.status,"notes":r.notes} for r in db.query(RosterEntry).filter(RosterEntry.employee_id==filter_id,RosterEntry.date>=start,RosterEntry.date<=end).order_by(RosterEntry.date)]
    return response

@app.post("/api/rosters/manual-allocation", dependencies=[Depends(require_write_access)])
def manual_allocation(payload: ManualAllocationIn, db: Session = Depends(get_db)):
    """Apply a one-day resource assignment after hard-constraint checks; return coverage impact."""
    from app.scheduler import is_operating_day, _required_staff
    from app.models import OperatingMode
    emp=db.query(Employee).filter(Employee.id==payload.employee_id).first()
    process=db.query(Process).filter(Process.id==payload.process_id,Process.brand_id==payload.brand_id).first()
    brand=db.query(Brand).filter(Brand.id==payload.brand_id).first()
    if not emp or not brand or not process: raise HTTPException(404,"Employee, brand, or process not found")
    if not db.query(Assignment).filter_by(employee_id=emp.id,brand_id=brand.id,process_id=process.id).first(): raise HTTPException(422,"Employee is not assigned to this brand/process")
    if db.query(Leave).filter(Leave.employee_id==emp.id,Leave.status=="approved",Leave.start_date<=payload.date,Leave.end_date>=payload.date).first(): raise HTTPException(409,"Employee has approved leave on this date")
    mode=process.operating_mode or brand.operating_mode
    holidays={h.date for h in db.query(PublicHoliday).filter(PublicHoliday.date==payload.date)}
    if not is_operating_day(payload.date,mode,holidays): raise HTTPException(422,"This process is not operating on the selected date")
    duplicate=db.query(RosterAllocation).filter_by(employee_id=emp.id,process_id=process.id,date=payload.date).first()
    if not duplicate:
        current=db.query(RosterAllocation).filter(RosterAllocation.employee_id==emp.id,RosterAllocation.date==payload.date).all()
        if sum(a.workload_units for a in current)+1 > max(1,emp.daily_capacity or 1): raise HTTPException(409,"Employee daily capacity would be exceeded")
        db.add(RosterAllocation(employee_id=emp.id,brand_id=brand.id,process_id=process.id,date=payload.date,source="manual"))
        status=db.query(RosterEntry).filter_by(employee_id=emp.id,date=payload.date).first()
        if status:
            status.status="working"
            if payload.date.strftime("%A")== (emp.preferred_weekly_off or "Sunday"):
                status.notes="Preferred weekly off overridden by manager-approved manual allocation"
    db.commit()
    required=_required_staff(db,brand.id,process,payload.date)
    assigned=db.query(RosterAllocation).filter_by(brand_id=brand.id,process_id=process.id,date=payload.date).count()
    event=AuditEvent(event_type="manual_allocation",entity_type="roster_allocation",entity_id=emp.id,actor="operations_manager",details=f"{emp.name} -> {brand.name}/{process.name} on {payload.date}; coverage {assigned}/{required}")
    db.add(event); db.commit()
    return {"status":"applied","coverage":{"required":required,"assigned":assigned,"status":"ok" if assigned>=required else "gap"},"warning":None if assigned>=required else "Manual change leaves a coverage gap; manager review required."}

@app.put("/api/assignments/{assignment_id}", dependencies=[Depends(require_write_access)])
def update_assignment(assignment_id: int, payload: AssignmentIn, db: Session = Depends(get_db)):
    row=db.query(Assignment).filter(Assignment.id==assignment_id).first()
    if not row: raise HTTPException(404,"Assignment not found")
    if not db.query(Process).filter(Process.id==payload.process_id,Process.brand_id==payload.brand_id).first(): raise HTTPException(422,"Process does not belong to brand")
    for key,value in payload.model_dump().items(): setattr(row,key,value)
    db.commit(); return {"id":row.id,"status":"updated"}

@app.delete("/api/assignments/{assignment_id}", dependencies=[Depends(require_write_access)])
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    row=db.query(Assignment).filter(Assignment.id==assignment_id).first()
    if not row: raise HTTPException(404,"Assignment not found")
    db.delete(row); db.commit(); return {"status":"deleted"}

@app.post("/api/rosters/generate", dependencies=[Depends(require_write_access)])
def roster_generate(payload: GenerateIn, db: Session = Depends(get_db)):
    return generate_roster(db,payload.year,payload.month,clear_existing=True)

@app.get("/api/rosters/coverage", dependencies=[Depends(require_read_access)])
def roster_coverage(year: int, month: int, db: Session = Depends(get_db)):
    return generate_roster(db,year,month,clear_existing=False)

@app.get("/api/rosters/allocations", dependencies=[Depends(require_read_access)])
def roster_allocations(year: int, month: int, db: Session = Depends(get_db)):
    from calendar import monthrange
    start=date(year,month,1); end=date(year,month,monthrange(year,month)[1])
    rows=db.query(RosterAllocation).filter(RosterAllocation.date>=start,RosterAllocation.date<=end).all()
    return [{"date":r.date.isoformat(),"employee":r.employee.name,"employee_id":r.employee_id,
             "brand":r.brand.name,"brand_id":r.brand_id,"process":r.process.name,"process_id":r.process_id,
             "workload_units":r.workload_units} for r in rows]

@app.post("/api/impact/leave")
def leave_impact(payload: ImpactIn, db: Session = Depends(get_db)):
    if payload.end_date < payload.start_date: raise HTTPException(422,"End date must be on or after start date")
    return analyze_leave_impact(db,payload.employee_id,payload.start_date,payload.end_date)

@app.post("/api/leave-requests", dependencies=[Depends(require_write_access)])
def create_leave_request(payload: LeaveIn, db: Session = Depends(get_db)):
    if payload.end_date < payload.start_date: raise HTTPException(422,"End date must be on or after start date")
    result=apply_leave_and_revalidate(db,payload.employee_id,payload.start_date,payload.end_date,payload.leave_type)
    if "error" in result: raise HTTPException(404,result["error"])
    return result

@app.get("/api/leave-requests", dependencies=[Depends(require_read_access)])
def leave_requests(db: Session = Depends(get_db)):
    return [{"id":r.id,"employee":r.employee.name,"employee_id":r.employee_id,"start_date":r.start_date.isoformat(),"end_date":r.end_date.isoformat(),"leave_type":r.leave_type,"status":r.status,"reason":r.reason} for r in db.query(LeaveRequest).order_by(LeaveRequest.created_at.desc())]

@app.patch("/api/leave-requests/{request_id}/review", dependencies=[Depends(require_write_access)])
def review_leave(request_id: int, payload: LeaveReviewIn, db: Session = Depends(get_db)):
    result=review_leave_request(db,request_id,payload.approve,payload.reviewer)
    if "error" in result: raise HTTPException(404 if "not found" in result["error"] else 409,result["error"])
    return result

@app.get("/api/audit", dependencies=[Depends(require_read_access)])
def audit(db: Session = Depends(get_db)):
    return [{"id":e.id,"event_type":e.event_type,"entity_type":e.entity_type,"entity_id":e.entity_id,"actor":e.actor,"details":e.details,"created_at":e.created_at.isoformat()} for e in db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)]
