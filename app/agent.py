"""
LangGraph-based agent for roster management.
Uses Gemini for reasoning and tool calling.
"""
import os
from typing import TypedDict, Annotated, Sequence, List, Dict, Any, Optional
from datetime import date, datetime
import operator

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.scheduler import generate_roster, apply_leave_and_revalidate, get_roster_view, analyze_leave_impact
from app.models import Employee, Brand, Process, Assignment, Pod, Leave, LeaveRequest, RosterAllocation


# ---------------------------------------------------------------------------
# Tools (these will be called by the agent)
# ---------------------------------------------------------------------------

@tool
def list_employees(limit: int = 50) -> str:
    """List all employees with their pod and preferred weekly off."""
    db = SessionLocal()
    try:
        emps = db.query(Employee).limit(limit).all()
        lines = []
        for e in emps:
            pod_name = e.pod.name if e.pod else "None"
            lines.append(f"ID:{e.id} | {e.name} | Pod:{pod_name} | WeeklyOff:{e.preferred_weekly_off} | Lead:{e.is_pod_lead}")
        return "\n".join(lines) if lines else "No employees found."
    finally:
        db.close()


@tool
def list_brands() -> str:
    """List all brands with their operating mode and assigned processes."""
    db = SessionLocal()
    try:
        brands = db.query(Brand).all()
        lines = []
        for b in brands:
            procs = [p.name for p in b.processes]
            asg_count = len(b.assignments)
            lines.append(f"ID:{b.id} | {b.name} | Mode:{b.operating_mode} | Processes:{procs} | Assignments:{asg_count}")
        return "\n".join(lines)
    finally:
        db.close()


@tool
def get_brand_coverage(brand_name: str, year: int = date.today().year, month: int = date.today().month) -> str:
    """Get coverage status and any gaps for a specific brand in a month."""
    db = SessionLocal()
    try:
        result = generate_roster(db, year, month, clear_existing=False)
        relevant = [
            c for c in result["conflicts"]
            if c["brand"].lower() == brand_name.lower()
        ]
        coverage = [
            r for r in result["coverage_report"]
            if r["brand"].lower() == brand_name.lower()
        ]
        summary = result["summary"]
        text = f"Overall summary: {summary}\n\n"
        if relevant:
            text += "Conflicts for this brand:\n"
            for c in relevant:
                text += f"- {c['message']}\n  Suggestions: {c.get('suggested_actions', [])}\n"
        else:
            text += "No conflicts found for this brand.\n"
        gaps = [r for r in coverage if r["status"] == "gap"]
        text += f"\nTotal gap days for brand: {len(gaps)}"
        return text
    finally:
        db.close()


@tool
def get_staffing_alerts(year: int = date.today().year, month: int = date.today().month) -> str:
    """Retrieve all live coverage shortages for a month with root-cause diagnostics and backup recommendations. Read-only."""
    db = SessionLocal()
    try:
        result = generate_roster(db, year, month, clear_existing=False)
        return str({"summary": result["summary"], "coverage_gaps": result["conflicts"][:100]})
    finally:
        db.close()


@tool
def generate_monthly_roster(year: int = date.today().year, month: int = date.today().month) -> str:
    """Generate (or regenerate) the full monthly roster and return summary + top conflicts."""
    db = SessionLocal()
    try:
        result = generate_roster(db, year, month, clear_existing=True)
        s = result["summary"]
        text = (
            f"Roster generated for {year}-{month:02d}\n"
            f"Employees: {s['employees']} | Conflicts: {s['conflicts_count']} "
            f"(Critical: {s['critical_conflicts']}) | Coverage OK: {s['coverage_ok_pct']}%\n\n"
        )
        if result["conflicts"]:
            text += "Top conflicts:\n"
            for c in result["conflicts"][:8]:
                text += f"- [{c['severity'].upper()}] {c['message']}\n"
        else:
            text += "No conflicts detected. Roster looks healthy."
        return text
    finally:
        db.close()


@tool
def add_employee_leave(
    employee_name: str, start_date: str, end_date: str, leave_type: str = "planned"
) -> str:
    """Create a PENDING leave request, simulate impact, and return risks. Never auto-approve leave."""
    db = SessionLocal()
    try:
        emp = db.query(Employee).filter(Employee.name.ilike(f"%{employee_name}%")).first()
        if not emp:
            return f"Employee matching '{employee_name}' not found."
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if end < start:
            return "Invalid date range: end_date must be on or after start_date."
        impact = analyze_leave_impact(db, emp.id, start, end)
        result = apply_leave_and_revalidate(db, emp.id, start, end, leave_type, start.year, start.month)
        return (f"Leave request #{result.get('request_id')} created with status PENDING for {emp.name}. "
                f"Affected assignments: {impact.get('affected_assignments', 0)}. "
                f"Potentially impacted service-days: {len(impact.get('impacted_service_days', []))}. "
                "A manager must approve or reject this request. No roster was changed.")
    except ValueError:
        return "Dates must use YYYY-MM-DD format."
    finally:
        db.close()


@tool
def analyze_employee_absence(employee_name: str, start_date: str, end_date: str) -> str:
    """Simulate an employee absence and explain which brands/processes may be affected, without changing data."""
    db = SessionLocal()
    try:
        emp = db.query(Employee).filter(Employee.name.ilike(f"%{employee_name}%")).first()
        if not emp: return f"Employee matching '{employee_name}' not found."
        impact = analyze_leave_impact(db, emp.id, date.fromisoformat(start_date), date.fromisoformat(end_date))
        return str(impact)
    except ValueError:
        return "Dates must use YYYY-MM-DD format."
    finally:
        db.close()


@tool
def recommend_backup_resources(brand_name: str, process_name: str, date_str: str) -> str:
    """Find possible backup employees in the same pod who have capacity and no approved leave on the requested day."""
    db = SessionLocal()
    try:
        brand = db.query(Brand).filter(Brand.name.ilike(f"%{brand_name}%")).first()
        if not brand: return f"Brand '{brand_name}' not found."
        process = db.query(Process).filter(Process.brand_id == brand.id, Process.name.ilike(f"%{process_name}%")).first()
        if not process: return f"Process '{process_name}' not found for {brand.name}."
        day = date.fromisoformat(date_str)
        assigned_ids = {a.employee_id for a in db.query(Assignment).filter(Assignment.brand_id == brand.id).all()}
        pods = {e.pod_id for e in db.query(Employee).filter(Employee.id.in_(assigned_ids)).all()}
        from collections import defaultdict
        existing_load = defaultdict(int)
        for allocation in db.query(RosterAllocation).filter(RosterAllocation.date == day).all():
            existing_load[allocation.employee_id] += allocation.workload_units
        leave_ids = {l.employee_id for l in db.query(Leave).filter(Leave.status == "approved", Leave.start_date <= day, Leave.end_date >= day).all()}
        candidates = []
        for emp in db.query(Employee).filter(Employee.pod_id.in_(pods)).all():
            if emp.id in assigned_ids or emp.id in leave_ids: continue
            load = existing_load[emp.id]
            if load < max(1, emp.daily_capacity or 1):
                candidates.append({"employee": emp.name, "employee_id": emp.id, "pod_id": emp.pod_id, "current_load": load, "capacity": emp.daily_capacity})
        return str({"brand": brand.name, "process": process.name, "date": date_str, "backup_candidates": candidates[:5],
                     "warning": "Recommendations only. A manager must confirm eligibility and approve any assignment change."})
    finally:
        db.close()


@tool
def list_pending_leave_requests() -> str:
    """List leave requests awaiting a human manager decision."""
    db = SessionLocal()
    try:
        rows = db.query(LeaveRequest).filter(LeaveRequest.status == "pending").order_by(LeaveRequest.created_at.desc()).all()
        return str([{"request_id": r.id, "employee": r.employee.name, "start": r.start_date.isoformat(),
                     "end": r.end_date.isoformat(), "type": r.leave_type} for r in rows])
    finally:
        db.close()


@tool
def explain_conflict(brand_name: str, process_name: str, date_str: str) -> str:
    """Explain why a particular brand/process has a coverage problem on a date and suggest fixes."""
    db = SessionLocal()
    try:
        d = date.fromisoformat(date_str)
        result = generate_roster(db, d.year, d.month, clear_existing=False)
        matches = [
            c for c in result["conflicts"]
            if c["brand"].lower() == brand_name.lower()
            and c["process"].lower() == process_name.lower()
            and c["date"] == date_str
        ]
        if not matches:
            return f"No conflict found for {brand_name}/{process_name} on {date_str}."
        c = matches[0]
        explanation = (
            f"Conflict details\n"
            f"Brand: {c['brand']} | Process: {c['process']} | Date: {c['date']}\n"
            f"Severity: {c['severity']}\n"
            f"Required staff: {c['required']} | Allocated: {c['available']} ({', '.join(c['available_names']) or 'none'})\n\n"
            f"Candidate diagnostics: {c.get('candidate_diagnostics', [])}\n\n"
            f"Suggested backup resources / actions:\n"
        )
        for s in c.get("suggested_actions", []):
            explanation += f"- {s}\n"
        return explanation
    finally:
        db.close()


@tool
def get_employee_schedule(employee_name: str, year: int = date.today().year, month: int = date.today().month) -> str:
    """Get the personal schedule (working / off / leave) for an employee in a month."""
    db = SessionLocal()
    try:
        emp = db.query(Employee).filter(Employee.name.ilike(f"%{employee_name}%")).first()
        if not emp:
            return f"No employee matching '{employee_name}'."
        view = get_roster_view(db, year, month, view_type="employee", filter_id=emp.id)
        entries = view.get("entries", [])
        text = f"Schedule for {emp.name} ({year}-{month:02d}):\n"
        for e in entries:
            text += f"  {e['date']}: {e['status']}\n"
        return text
    finally:
        db.close()


# ---------------------------------------------------------------------------
# LangGraph Agent
# ---------------------------------------------------------------------------

MEMORY_CHECKPOINTER = MemorySaver()

tools = [
    list_employees,
    list_brands,
    get_brand_coverage,
    get_staffing_alerts,
    generate_monthly_roster,
    add_employee_leave,
    analyze_employee_absence,
    recommend_backup_resources,
    list_pending_leave_requests,
    explain_conflict,
    get_employee_schedule,
]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


def create_roster_agent(api_key: Optional[str] = None):
    """Create and compile the LangGraph agent."""
    key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "GOOGLE_API_KEY or GEMINI_API_KEY environment variable is required. "
            "Get a free key at https://aistudio.google.com/apikey"
        )

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=key,
        temperature=0.2,
    )
    llm_with_tools = llm.bind_tools(tools)

    system_prompt = """You are an expert Roster Management Assistant for a CX/operations company.
You help operations managers plan, generate, validate and adjust monthly employee rosters across multiple D2C brands and processes.

Key domain knowledge:
- ~80% of brands are managed by a single dedicated employee (high risk if that person is unavailable).
- Brands have different operating modes: 365_days, daily_except_holidays, weekdays_only.
- Processes include CS, ACC, NDR, Retention, Returns.
- Employees have preferred weekly offs, planned leaves, and belong to pods.

Your responsibilities:
0. Proactively analyze operational impact whenever a leave/absence, staffing shortage, or coverage risk is mentioned. Use get_staffing_alerts for low staffing and use analyze_employee_absence plus recommend_backup_resources for a named absence; do not wait for the user to ask only for QA.
1. Generate and summarize monthly rosters.
2. Detect and clearly explain coverage gaps and conflicts.
3. Distinguish hard constraints (client coverage) from soft preferences (preferred offs).
4. When a change happens (e.g. leave), re-validate and propose practical resolutions.
5. Always be concise, actionable, and transparent about what is automated vs what needs human decision.

When you use tools, synthesize the evidence and explain affected dates, brands, processes, shortage size, viable backups, and trade-offs. Never claim a backup is assigned unless a manager-approved assignment change was actually saved. Never approve leave or publish a roster. When a leave is requested, create a pending request and clearly say that no schedule change occurs until approval.
If a conflict cannot be auto-resolved, clearly flag it for the operations manager.
"""

    def chatbot(state: AgentState):
        messages = state["messages"]
        # Prepend system message if not present
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=system_prompt)] + list(messages)
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", chatbot)
    graph.add_node("tools", ToolNode(tools))

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=MEMORY_CHECKPOINTER)


def run_agent(query: str, api_key: Optional[str] = None, chat_history: List = None, thread_id: str = "default") -> str:
    """Run a stateful conversation. A stable thread_id preserves LangGraph checkpoint state."""
    agent = create_roster_agent(api_key)
    messages = list(chat_history or [])
    if messages:
        # Compatibility path for clients that explicitly pass a full history.
        result = agent.invoke({"messages": messages + [HumanMessage(content=query)]}, config={"configurable": {"thread_id": thread_id}})
    else:
        result = agent.invoke({"messages": [HumanMessage(content=query)]}, config={"configurable": {"thread_id": thread_id}})
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return "No response generated."
