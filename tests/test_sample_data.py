import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Employee, Brand, Assignment, Pod
from app.sample_data import seed_database
from app.scheduler import generate_roster

@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    session=Session(); yield session; session.close(); engine.dispose()

def test_sample_data_matches_assessment_staffing_pattern(db):
    counts=seed_database(db)
    assert counts['employees']==32
    assert counts['brands']==20
    assert counts['pods']==4
    profiles=[]
    for brand in db.query(Brand).all():
        profiles.append(len({a.employee_id for a in db.query(Assignment).filter_by(brand_id=brand.id).all()}))
    assert sum(n==1 for n in profiles)==16
    assert sum(n in (2,3) for n in profiles)==4
    # Two people are deliberately shared across brands, demonstrating cross-brand assignments.
    per_employee={}
    for a in db.query(Assignment).all(): per_employee.setdefault(a.employee_id,set()).add(a.brand_id)
    assert sum(len(brands)>1 for brands in per_employee.values())>=2

def test_seeded_november_2026_roster_meets_all_configured_coverage(db):
    seed_database(db)
    result=generate_roster(db,2026,11)
    assert result['summary']['coverage_ok_pct']==100.0
    assert result['summary']['conflicts_count']==0
