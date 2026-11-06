"""
Generate realistic sample data for the roster system.
~32 employees, ~20 brands, mixed single/multi-resource patterns.
"""
from datetime import date, timedelta
from sqlalchemy.orm import Session
from app.models import (
    Employee, Pod, Brand, Process, Assignment, PublicHoliday, Leave, OperatingMode
)
import random


FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan",
    "Krishna", "Ishaan", "Shaurya", "Atharv", "Advik", "Pranav", "Dhruv",
    "Ananya", "Aadhya", "Saanvi", "Aarohi", "Anika", "Myra", "Diya", "Pari",
    "Anvi", "Kiara", "Navya", "Riya", "Ira", "Sara", "Meera", "Priya", "Neha"
]

LAST_NAMES = [
    "Sharma", "Patel", "Singh", "Kumar", "Gupta", "Reddy", "Nair", "Iyer",
    "Joshi", "Mehta", "Chopra", "Malhotra", "Banerjee", "Desai", "Kapoor"
]

BRAND_NAMES = [
    "NovaWear", "LuminaSkin", "FreshCart", "UrbanNest", "PureGlow",
    "FitPulse", "EcoSip", "StyleHive", "BloomBox", "TechNest",
    "VitaBrew", "HomeHaven", "PetPals", "SnackSphere", "YogaRoots",
    "GlowLab", "BookNook", "TrailBlaze", "MintyFresh", "CraftCircle",
    "ZenDesk", "AromaLeaf", "PixelPlay", "GreenSprout"
]

PROCESSES = ["CS", "ACC", "NDR", "Retention", "Returns"]


def seed_database(db: Session):
    from app.models import RosterEntry  # local import to avoid circularity issues

    # Clear existing (for re-seeding)
    for table in [Assignment, Leave, RosterEntry, Process, Brand, Employee, Pod, PublicHoliday]:
        db.query(table).delete()
    db.commit()

    # --- Pods ---
    pods = []
    for i, name in enumerate(["Alpha Pod", "Beta Pod", "Gamma Pod", "Delta Pod"]):
        pod = Pod(name=name)
        db.add(pod)
        pods.append(pod)
    db.flush()

    # --- Employees (32) ---
    employees = []
    random.seed(42)
    for i in range(32):
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        email = f"emp{i+1}@datastraw.ops"
        pod = pods[i % 4]
        preferred_off = random.choice(["Sunday", "Monday", "Saturday", "Wednesday"])
        emp = Employee(
            name=name,
            email=email,
            pod_id=pod.id,
            is_pod_lead=(i % 8 == 0),  # roughly one lead per pod + extras
            preferred_weekly_off=preferred_off
        )
        db.add(emp)
        employees.append(emp)
    db.flush()

    # Assign pod leads
    for idx, pod in enumerate(pods):
        lead = next((e for e in employees if e.pod_id == pod.id and e.is_pod_lead), employees[idx*8])
        pod.lead_id = lead.id
    db.flush()

    # --- Brands & Processes ---
    brands = []
    for i, bname in enumerate(BRAND_NAMES[:20]):
        mode = random.choice([
            OperatingMode.WEEKDAYS_ONLY.value,
            OperatingMode.DAILY_EXCEPT_HOLIDAYS.value,
            OperatingMode.FULL_365.value,
            OperatingMode.WEEKDAYS_ONLY.value,  # bias toward weekdays
        ])
        brand = Brand(name=bname, operating_mode=mode)
        db.add(brand)
        brands.append(brand)
    db.flush()

    processes = []
    for brand in brands:
        # Each brand gets 1-3 processes
        n_proc = random.choices([1, 2, 3], weights=[0.5, 0.35, 0.15])[0]
        chosen = random.sample(PROCESSES, n_proc)
        for p in chosen:
            min_staff = 1
            proc = Process(
                name=p,
                brand_id=brand.id,
                min_staffing=min_staff,
                operating_mode=None  # inherit from brand mostly
            )
            db.add(proc)
            processes.append(proc)
    db.flush()

    # --- Assignments ---
    # 80% single-resource brands: first 16 employees each own one brand.
    # Remaining employees are distributed across the four multi-resource brands,
    # leaving a small cross-pod backup pool for recommendations.
    for brand_index, brand in enumerate(brands[:16]):
        emp = employees[brand_index]
        for proc in [p for p in processes if p.brand_id == brand.id]:
            db.add(Assignment(employee_id=emp.id, brand_id=brand.id, process_id=proc.id, is_primary=True))

    pool = employees[16:]
    # Two shared resources intentionally span brands; each multi-resource brand
    # still has only two or three distinct people.
    team_patterns = [[0, 1], [1, 2, 3], [4, 5], [5, 6, 7]]
    for brand, pattern in zip(brands[16:], team_patterns):
        brand_procs = [p for p in processes if p.brand_id == brand.id]
        chosen_emps = [pool[i] for i in pattern]
        process_assigned_counts = {p.id: 0 for p in brand_procs}
        for i, emp in enumerate(chosen_emps):
            proc = brand_procs[i] if i < len(brand_procs) else brand_procs[0]
            db.add(Assignment(employee_id=emp.id, brand_id=brand.id, process_id=proc.id, is_primary=True))
            process_assigned_counts[proc.id] += 1
        for proc in brand_procs:
            proc.min_staffing = 2 if process_assigned_counts[proc.id] >= 2 else 1

    # --- Public Holidays (sample for 2025-2026) ---
    holidays = [
        (date(2025, 1, 26), "Republic Day"),
        (date(2025, 3, 14), "Holi"),
        (date(2025, 8, 15), "Independence Day"),
        (date(2025, 10, 2), "Gandhi Jayanti"),
        (date(2025, 11, 1), "Diwali"),
        (date(2025, 12, 25), "Christmas"),
        (date(2026, 1, 26), "Republic Day"),
        (date(2026, 3, 3), "Holi"),
        (date(2026, 8, 15), "Independence Day"),
        (date(2026, 10, 2), "Gandhi Jayanti"),
        (date(2026, 11, 8), "Diwali"),
        (date(2026, 12, 25), "Christmas"),
    ]
    for d, name in holidays:
        db.add(PublicHoliday(date=d, name=name))

    # --- Some planned leaves ---
    for _ in range(12):
        emp = random.choice(employees)
        start = date(2025, 11, 1) + timedelta(days=random.randint(0, 25))
        end = start + timedelta(days=random.randint(0, 2))
        db.add(Leave(
            employee_id=emp.id,
            start_date=start,
            end_date=end,
            leave_type=random.choice(["planned", "comp_off"]),
            status="approved"
        ))

    db.commit()
    print(f"Seeded: {len(employees)} employees, {len(brands)} brands, {len(processes)} processes")
    return {
        "employees": len(employees),
        "brands": len(brands),
        "processes": len(processes),
        "pods": len(pods)
    }