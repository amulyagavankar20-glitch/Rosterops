from sqlalchemy import (
    Column, Integer, String, Boolean, Date, ForeignKey, Text, Enum, UniqueConstraint, DateTime, Float
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base
import enum


class OperatingMode(str, enum.Enum):
    FULL_365 = "365_days"           # including Sundays + public holidays
    DAILY_EXCEPT_HOLIDAYS = "daily_except_holidays"
    WEEKDAYS_ONLY = "weekdays_only" # Sundays + public holidays off


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True)
    pod_id = Column(Integer, ForeignKey("pods.id"))
    is_pod_lead = Column(Boolean, default=False)
    preferred_weekly_off = Column(String(20), default="Sunday")  # day name
    max_brands = Column(Integer, default=3)
    daily_capacity = Column(Integer, default=3)

    pod = relationship("Pod", back_populates="employees", foreign_keys=[pod_id])
    assignments = relationship("Assignment", back_populates="employee")
    leaves = relationship("Leave", back_populates="employee")
    roster_entries = relationship("RosterEntry", back_populates="employee")
    allocations = relationship("RosterAllocation", back_populates="employee")


class Pod(Base):
    __tablename__ = "pods"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    lead_id = Column(Integer, ForeignKey("employees.id"), nullable=True)

    employees = relationship(
        "Employee",
        back_populates="pod",
        foreign_keys="Employee.pod_id"
    )
    lead = relationship(
        "Employee",
        foreign_keys=[lead_id],
        post_update=True
    )


class Brand(Base):
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    operating_mode = Column(String(50), default=OperatingMode.WEEKDAYS_ONLY.value)
    notes = Column(Text, nullable=True)

    processes = relationship("Process", back_populates="brand")
    assignments = relationship("Assignment", back_populates="brand")


class Process(Base):
    __tablename__ = "processes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)  # CS, ACC, NDR, Retention, etc.
    brand_id = Column(Integer, ForeignKey("brands.id"))
    min_staffing = Column(Integer, default=1)
    operating_mode = Column(String(50), nullable=True)  # override brand if set

    brand = relationship("Brand", back_populates="processes")
    assignments = relationship("Assignment", back_populates="process")


class Assignment(Base):
    """Employee assigned to a brand-process pair."""
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("employee_id", "brand_id", "process_id"),)

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    brand_id = Column(Integer, ForeignKey("brands.id"))
    process_id = Column(Integer, ForeignKey("processes.id"))
    is_primary = Column(Boolean, default=True)

    employee = relationship("Employee", back_populates="assignments")
    brand = relationship("Brand", back_populates="assignments")
    process = relationship("Process", back_populates="assignments")


class PublicHoliday(Base):
    __tablename__ = "public_holidays"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, unique=True)
    name = Column(String(100), nullable=False)


class Leave(Base):
    __tablename__ = "leaves"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    leave_type = Column(String(30), default="planned")  # planned, sick, comp_off
    status = Column(String(20), default="approved")
    notes = Column(Text, nullable=True)

    employee = relationship("Employee", back_populates="leaves")


class RosterEntry(Base):
    __tablename__ = "roster_entries"
    __table_args__ = (UniqueConstraint("employee_id", "date"),)

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    date = Column(Date, nullable=False)
    status = Column(String(30), default="working")  # working, weekly_off, holiday, leave, comp_off
    notes = Column(Text, nullable=True)

    employee = relationship("Employee", back_populates="roster_entries")


class CoverageRequirement(Base):
    """Optional extra coverage rules."""
    __tablename__ = "coverage_requirements"

    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"))
    process_id = Column(Integer, ForeignKey("processes.id"), nullable=True)
    day_of_week = Column(String(15), nullable=True)  # specific day or null for all
    min_staff = Column(Integer, default=1)

class RosterAllocation(Base):
    """A concrete employee-to-process assignment for one roster day."""
    __tablename__ = "roster_allocations"
    __table_args__ = (UniqueConstraint("employee_id", "process_id", "date", name="uq_employee_process_day"),)
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True)
    process_id = Column(Integer, ForeignKey("processes.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    workload_units = Column(Integer, nullable=False, default=1)
    source = Column(String(20), nullable=False, default="solver")
    employee = relationship("Employee", back_populates="allocations")
    brand = relationship("Brand")
    process = relationship("Process")


class LeaveRequest(Base):
    """Leave requests are pending until a human approver acts."""
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    leave_type = Column(String(30), nullable=False, default="planned")
    status = Column(String(20), nullable=False, default="pending", index=True)
    reason = Column(Text)
    impact_json = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    reviewed_at = Column(DateTime)
    reviewer = Column(String(120))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(80), nullable=False, index=True)
    entity_type = Column(String(80), nullable=False)
    entity_id = Column(Integer)
    actor = Column(String(120), nullable=False, default="system")
    details = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
