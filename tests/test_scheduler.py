from datetime import date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Employee, Pod, Brand, Process, Assignment, PublicHoliday, Leave, LeaveRequest, RosterAllocation, OperatingMode
from app.scheduler import generate_roster, apply_leave_and_revalidate

@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    session=Session()
    yield session
    session.close(); engine.dispose()

def setup_entities(db, mode=OperatingMode.FULL_365.value, capacity=3, min_staff=1):
    pod=Pod(name='Alpha'); db.add(pod); db.flush()
    emp=Employee(name='Asha Rao',email='asha@test.local',pod_id=pod.id,preferred_weekly_off='Sunday',daily_capacity=capacity); db.add(emp); db.flush()
    brand=Brand(name='Nova',operating_mode=mode); db.add(brand); db.flush()
    process=Process(name='CS',brand_id=brand.id,min_staffing=min_staff); db.add(process); db.flush()
    db.add(Assignment(employee_id=emp.id,brand_id=brand.id,process_id=process.id)); db.commit()
    return emp,brand,process

def test_365_day_process_is_staffed_on_sunday_and_holiday(db):
    setup_entities(db)
    db.add(PublicHoliday(date=date(2026,11,8),name='Test holiday')); db.commit()
    result=generate_roster(db,2026,11)
    row=next(r for r in result['coverage_report'] if r['date']=='2026-11-08')
    assert row['status']=='ok'
    assert row['available']==1

def test_approved_leave_creates_real_coverage_gap(db):
    emp,brand,process=setup_entities(db)
    db.add(Leave(employee_id=emp.id,start_date=date(2026,11,10),end_date=date(2026,11,10),status='approved')); db.commit()
    result=generate_roster(db,2026,11)
    gap=next(c for c in result['conflicts'] if c['date']=='2026-11-10')
    assert gap['severity']=='critical'
    assert gap['available']==0

def test_employee_can_cover_multiple_processes_within_capacity(db):
    emp,brand,p1=setup_entities(db,capacity=2)
    p2=Process(name='ACC',brand_id=brand.id,min_staffing=1); db.add(p2); db.flush()
    db.add(Assignment(employee_id=emp.id,brand_id=brand.id,process_id=p2.id)); db.commit()
    result=generate_roster(db,2026,11)
    on_day=[a for a in db.query(RosterAllocation).filter(RosterAllocation.date==date(2026,11,2)).all()]
    assert len(on_day)==2
    assert all(r['status']=='ok' for r in result['coverage_report'] if r['date']=='2026-11-02')

def test_daily_capacity_prevents_overallocation(db):
    emp,brand,p1=setup_entities(db,capacity=1)
    p2=Process(name='ACC',brand_id=brand.id,min_staffing=1); db.add(p2); db.flush()
    db.add(Assignment(employee_id=emp.id,brand_id=brand.id,process_id=p2.id)); db.commit()
    result=generate_roster(db,2026,11)
    day_rows=[r for r in result['coverage_report'] if r['date']=='2026-11-02']
    assert sum(r['status']=='gap' for r in day_rows)==1

def test_leave_tool_creates_pending_request_not_approved_leave(db):
    emp,_,_=setup_entities(db)
    result=apply_leave_and_revalidate(db,emp.id,date(2026,11,10),date(2026,11,11))
    assert result['status']=='pending'
    assert db.query(LeaveRequest).count()==1
    assert db.query(Leave).count()==0

def test_pending_leave_approval_revalidates_and_recommends_backup(db):
    from app.scheduler import review_leave_request
    from app.models import AuditEvent
    pod=Pod(name='Ops'); db.add(pod); db.flush()
    owner=Employee(name='Owner',pod_id=pod.id,preferred_weekly_off='Sunday',daily_capacity=2)
    backup=Employee(name='Backup',pod_id=pod.id,preferred_weekly_off='Monday',daily_capacity=2)
    db.add_all([owner,backup]); db.flush()
    brand=Brand(name='SingleOwner',operating_mode=OperatingMode.FULL_365.value); db.add(brand); db.flush()
    process=Process(name='CS',brand_id=brand.id,min_staffing=1); db.add(process); db.flush()
    db.add(Assignment(employee_id=owner.id,brand_id=brand.id,process_id=process.id)); db.commit()
    pending=apply_leave_and_revalidate(db,owner.id,date(2026,11,10),date(2026,11,10))
    assert db.query(Leave).count()==0
    approved=review_leave_request(db,pending['request_id'],True,'test_manager')
    assert approved['status']=='approved'
    assert db.query(Leave).count()==1
    gap=next(c for c in approved['revalidation'][0]['conflicts'] if c['date']=='2026-11-10')
    assert gap['severity']=='critical'
    assert gap['suggested_actions'][0]['employee']=='Backup'
    assert db.query(AuditEvent).count()==1

def test_read_only_validation_preserves_manual_allocation(db):
    emp,brand,process=setup_entities(db)
    manual=RosterAllocation(employee_id=emp.id,brand_id=brand.id,process_id=process.id,
                            date=date(2026,11,10),source='manual')
    db.add(manual); db.commit()
    result=generate_roster(db,2026,11,clear_existing=False)
    row=next(r for r in result['coverage_report'] if r['date']=='2026-11-10')
    assert row['status']=='ok'
    assert row['available_names']==[emp.name]
    assert db.query(RosterAllocation).filter_by(source='manual').count()==1
