"""Streamlit frontend for the FastAPI-backed Smart Roster Management System."""
import os, uuid, hmac
from datetime import date
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from app.frontend_helpers import build_brand_map, build_process_options
load_dotenv()

st.set_page_config(page_title="RosterOps | Workforce Control", page_icon="🗓️", layout="wide")
API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("API_ACCESS_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

# Shared access gate for the public demo deployment. This is not a substitute
# for individual user identities/RBAC, which should be added before real HR use.
if os.getenv("APP_ENV", "development") == "production":
    login_password = os.getenv("APP_LOGIN_PASSWORD", "")
    if not login_password:
        st.error("APP_LOGIN_PASSWORD is not configured. Set it before exposing the application.")
        st.stop()
    if not st.session_state.get("authenticated", False):
        st.title("RosterOps secure access")
        with st.form("login"):
            entered = st.text_input("Access password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted and hmac.compare_digest(entered, login_password):
            st.session_state["authenticated"] = True
            st.rerun()
        elif submitted:
            st.error("Incorrect access password.")
        st.stop()

def api(method, path, **kwargs):
    try:
        response = requests.request(method, f"{API}{path}", headers={**HEADERS, **kwargs.pop("headers", {})}, timeout=25, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}
    except requests.RequestException as exc:
        detail = getattr(getattr(exc, "response", None), "text", str(exc))
        st.error(f"Backend request failed: {detail[:500]}")
        return None

st.markdown("""<style>
:root{
  --ro-bg:#0B1120;--ro-surface:#111827;--ro-sidebar:#0F172A;
  --ro-card:#172033;--ro-elevated:#1E293B;--ro-hover:#263449;
  --ro-text:#F1F5F9;--ro-secondary:#CBD5E1;--ro-muted:#94A3B8;
  --ro-disabled:#64748B;--ro-border:#263449;--ro-strong:#334155;
  --ro-blue:#3B82F6;--ro-blue-hover:#2563EB;--ro-violet:#A78BFA;
  --ro-green:#22C55E;--ro-amber:#F59E0B;--ro-red:#F87171;--ro-cyan:#22D3EE;
}
.stApp{background:var(--ro-bg);color:var(--ro-text)}
.block-container{max-width:1500px;padding:1rem 1.5rem 1.5rem}
h1,h2,h3,h4,h5,h6{color:var(--ro-text)!important}
h1{font-size:26px!important;line-height:1.2!important}
h2,h3{font-size:19px!important;line-height:1.3!important}
h4,h5,h6{font-size:15px!important}
p,li,label{color:var(--ro-secondary)}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:var(--ro-muted)!important}

.hero{padding:12px 16px 14px;margin:0 0 16px;background:var(--ro-surface);
  border:1px solid var(--ro-border);border-radius:8px;border-top:2px solid var(--ro-blue)}
.hero h1{color:var(--ro-text);font-size:25px;margin:0}
.hero p{color:var(--ro-muted);font-size:13px;margin:4px 0 0}

[data-testid="stMetric"]{min-height:74px;padding:10px 12px;background:var(--ro-card);
  border:1px solid var(--ro-border);border-radius:7px}
[data-testid="stMetricLabel"]{color:var(--ro-muted)!important;font-size:12px!important;font-weight:600}
[data-testid="stMetricValue"]{color:var(--ro-text)!important;font-size:27px!important;font-weight:700}
[data-testid="stMetricDelta"]{color:var(--ro-secondary)!important;font-size:12px!important}

.stTabs [data-baseweb="tab-list"]{gap:0;border-bottom:1px solid var(--ro-border)}
.stTabs [data-baseweb="tab"]{color:var(--ro-muted)!important;font-size:13px;font-weight:600;padding:8px 12px}
.stTabs [data-baseweb="tab"]:hover{color:var(--ro-text)!important;background:var(--ro-hover)}
.stTabs [aria-selected="true"]{color:var(--ro-text)!important;border-bottom:2px solid var(--ro-blue)}

.stButton>button{min-height:34px;background:var(--ro-elevated);border:1px solid var(--ro-strong);
  color:var(--ro-secondary);font-size:13px;font-weight:600;border-radius:6px}
.stButton>button:hover{background:var(--ro-hover);border-color:var(--ro-blue);color:var(--ro-text)}
.stButton>button[kind="primary"]{background:var(--ro-blue);border-color:var(--ro-blue);color:#fff}
.stButton>button[kind="primary"]:hover{background:var(--ro-blue-hover);border-color:var(--ro-blue-hover)}

[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,[data-testid="stDateInput"] input,
[data-baseweb="select"]>div{
  background:var(--ro-surface)!important;color:var(--ro-text)!important;
  border:1px solid var(--ro-strong)!important;border-radius:6px!important}
input::placeholder,textarea::placeholder{color:var(--ro-disabled)!important;opacity:1!important}
[data-baseweb="select"] svg{fill:var(--ro-muted)!important}
[data-testid="stNumberInput"] button{background:var(--ro-elevated)!important;color:var(--ro-secondary)!important;border-color:var(--ro-strong)!important}

[data-testid="stDataFrame"]{border:1px solid var(--ro-border);border-radius:6px;overflow:hidden}
[data-testid="stDataFrame"] th{background:var(--ro-elevated)!important;color:var(--ro-secondary)!important;font-size:12px!important;font-weight:700!important}
[data-testid="stDataFrame"] td{background:var(--ro-surface)!important;color:#E2E8F0!important;font-size:13px!important}
[data-testid="stDataFrame"] tr:hover td{background:var(--ro-card)!important}

[data-testid="stAlert"]{background:var(--ro-card);border:1px solid var(--ro-border);color:var(--ro-secondary)}
[data-testid="stAlert"] p{color:var(--ro-secondary)!important}
[data-testid="stExpander"]{background:var(--ro-surface);border:1px solid var(--ro-border);border-radius:6px}
[data-testid="stExpander"] summary{color:var(--ro-secondary)!important}
[data-testid="stChatMessage"]{background:var(--ro-card);border:1px solid var(--ro-border);border-radius:7px;margin:6px 0;padding:8px 10px}
[data-testid="stChatMessage"][data-testid*="assistant"]{border-color:#493d68}
[data-testid="stChatInput"] textarea{background:var(--ro-surface)!important;color:var(--ro-text)!important;border-color:var(--ro-strong)!important}

[data-testid="stSidebar"]{background:var(--ro-sidebar);border-right:1px solid var(--ro-border)}
[data-testid="stSidebar"] *{color:var(--ro-secondary)}
[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3{color:var(--ro-text)!important}
[data-testid="stSidebar"] input,[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] [data-baseweb="select"]>div{
  background:var(--ro-surface)!important;color:var(--ro-text)!important;border:1px solid var(--ro-strong)!important}
[data-testid="stSidebar"] [data-testid="stNumberInput"] button{background:var(--ro-elevated)!important;border-color:var(--ro-strong)!important}

button:focus,input:focus,select:focus,textarea:focus{outline:2px solid var(--ro-blue)!important;outline-offset:2px}
hr{border-color:var(--ro-border)!important}
</style><div class='hero'><h1>RosterOps Control Center</h1><p>Deterministic workforce scheduling · Live coverage intelligence · Human-governed AI recommendations</p></div>""", unsafe_allow_html=True)

health = api("GET", "/health")
if health:
    st.caption(f"Backend: {health.get('status')} · Database: {health.get('database')} · API v2.0")
else:
    st.stop()

now = date.today()
if "agent_thread" not in st.session_state:
    st.session_state.agent_thread = str(uuid.uuid4())
if "event_thread" not in st.session_state:
    st.session_state.event_thread = str(uuid.uuid4())
with st.sidebar:
    st.subheader("Planning period")
    year = st.number_input("Year", 2024, 2100, now.year)
    month = st.selectbox("Month", list(range(1,13)), index=now.month-1, format_func=lambda x: date(2000,x,1).strftime("%B"))
    st.divider()
    st.caption("Write actions require API_ACCESS_KEY when deployed in production.")

tabs = st.tabs(["Overview", "Roster & Coverage", "Live Change Impact", "People & Assignments", "Agent Workspace", "Approvals & Audit"])

with tabs[0]:
    stats = api("GET", "/api/dashboard") or {}
    cols = st.columns(5)
    for col, label, key in zip(cols, ["Employees","Brands","Processes","Pods","Assignments"], ["employees","brands","processes","pods","assignments"]): col.metric(label, stats.get(key,0))
    st.subheader("Operational design")
    st.markdown("- **Hard constraints:** approved leave, client operating calendars, minimum coverage, daily capacity.\n- **Soft constraints:** preferred weekly offs; these may be overridden only when coverage needs it, and the override is visible.\n- **AI role:** investigate impact, retrieve operational context, recommend backups and explain trade-offs. It cannot approve leave or silently change assignments.")
    brands = api("GET", "/api/brands") or []
    if brands:
        st.subheader("Brand staffing profile")
        df = pd.DataFrame([{"Brand":b["name"],"Operating mode":b["operating_mode"],"Employees":b["employees"],"Processes":", ".join(p["name"] for p in b["processes"])} for b in brands])
        st.dataframe(df, use_container_width=True, hide_index=True)

with tabs[1]:
    st.subheader(f"Monthly roster · {year}-{month:02d}")
    c1,c2 = st.columns([1,3])
    if c1.button("Generate / Rebuild roster", type="primary", use_container_width=True):
        result = api("POST","/api/rosters/generate",json={"year":int(year),"month":int(month)})
        if result:
            st.session_state["roster_result"] = result
            st.success("Roster generated and validated.")
            if result.get("conflicts") and os.getenv("GOOGLE_API_KEY"):
                try:
                    with st.spinner("Agent is investigating staffing gaps and backup options..."):
                        from app.agent import run_agent
                        insight=run_agent(f"A roster was just generated for {year}-{month:02d} and {len(result.get('conflicts', []))} coverage conflicts were found. Proactively investigate the most serious gaps, use the coverage and backup tools, and recommend practical actions. Do not change assignments or approve anything.",thread_id=st.session_state.event_thread)
                    st.session_state["event_agent_insight"]=insight
                except Exception: st.warning("Automatic agent insight is unavailable. The roster result is still available.")
    result = st.session_state.get("roster_result")
    if not result: result = api("GET",f"/api/rosters/coverage?year={year}&month={month}")
    if result:
        summary = result.get("summary",{})
        a,b,c,d = st.columns(4); a.metric("Allocations",summary.get("allocation_count",0)); b.metric("Coverage satisfied",f"{summary.get('coverage_ok_pct',0)}%"); c.metric("Coverage gaps",summary.get("conflicts_count",0)); d.metric("Critical gaps",summary.get("critical_conflicts",0))
        cov = result.get("coverage_report",[])
        st.subheader("Brand / process / day coverage")
        if cov: st.dataframe(pd.DataFrame(cov),use_container_width=True,hide_index=True)
        alloc = api("GET",f"/api/rosters/allocations?year={year}&month={month}") or []
        st.subheader("Concrete employee allocations")
        if alloc: st.dataframe(pd.DataFrame(alloc),use_container_width=True,hide_index=True)
        else: st.info("No persisted allocations yet. Generate the roster to create allocations.")
        conflicts=result.get("conflicts",[])
        if conflicts:
            st.subheader("Issues requiring attention")
            for issue in conflicts:
                with st.expander(f"{issue.get('severity', 'warning').upper()} · {issue.get('date', 'Unknown date')} · {issue.get('brand', 'Unknown brand')} / {issue.get('process', 'Unknown process')}"):
                    st.write(issue.get("message", "The backend returned a coverage issue without a message."))
                    st.write("Candidate diagnostics", issue.get("candidate_diagnostics",[]))
                    st.write("Backup recommendations", issue.get("suggested_actions",[]))
        if st.session_state.get("event_agent_insight"):
            st.subheader("Agent's proactive staffing recommendations")
            st.info(st.session_state["event_agent_insight"])

    st.markdown("#### Roster views")
    view_types=["company","pod","brand","process","employee"]
    view_type=st.selectbox("View level",view_types)
    filter_options=[]
    if view_type=="pod": filter_options=api("GET","/api/pods") or []
    elif view_type in {"brand","process"}: filter_options=api("GET","/api/brands") or []
    elif view_type=="employee": filter_options=api("GET","/api/employees") or []
    if view_type=="company": filter_id=None
    elif view_type=="pod": filter_id=st.selectbox("Pod",filter_options,format_func=lambda x:x["name"],key="pod_view")["id"] if filter_options else None
    elif view_type=="brand": filter_id=st.selectbox("Brand",filter_options,format_func=lambda x:x["name"],key="brand_view")["id"] if filter_options else None
    elif view_type=="employee": filter_id=st.selectbox("Employee",filter_options,format_func=lambda x:x["name"],key="employee_view")["id"] if filter_options else None
    else:
        all_procs=[{"id":p["id"],"name":f"{b['name']} / {p['name']}"} for b in (filter_options or []) for p in b["processes"]]
        filter_id=st.selectbox("Process",all_procs,format_func=lambda x:x["name"],key="process_view")["id"] if all_procs else None
    if view_type=="company" or filter_id:
        view=api("GET",f"/api/rosters/view?year={year}&month={month}&view_type={view_type}"+(f"&filter_id={filter_id}" if filter_id else ""))
        if view and view.get("allocations"): st.dataframe(pd.DataFrame(view["allocations"]),use_container_width=True,hide_index=True)
        if view and view.get("daily_status"):
            st.caption("Employee daily status (working / weekly off / holiday / leave)")
            st.dataframe(pd.DataFrame(view["daily_status"]),use_container_width=True,hide_index=True)

with tabs[2]:
    st.subheader("Absence / leave impact simulation")
    employees = api("GET","/api/employees") or []
    if employees:
        by_name={f"{e['name']} · #{e['id']}":e["id"] for e in employees}
        with st.form("impact_form"):
            selected=st.selectbox("Employee",list(by_name))
            c1,c2=st.columns(2); start=c1.date_input("Start date",now); end=c2.date_input("End date",now)
            submitted=st.form_submit_button("Analyze operational impact",type="primary")
        if submitted:
            if end < start: st.error("End date must not precede start date.")
            else:
                impact=api("POST","/api/impact/leave",json={"employee_id":by_name[selected],"start_date":start.isoformat(),"end_date":end.isoformat()})
                if impact:
                    st.session_state["latest_impact"]=impact
                    st.write(f"**Affected assignments:** {impact.get('affected_assignments',0)} · **Impacted service-days:** {len(impact.get('impacted_service_days',[]))}")
                    st.dataframe(pd.DataFrame(impact.get("impacted_service_days",[])),use_container_width=True,hide_index=True)
                    st.warning("This is a simulation only. No leave has been approved and no roster has been changed.")
                    if os.getenv("GOOGLE_API_KEY"):
                        try:
                            from app.agent import run_agent
                            with st.spinner("Agent is checking live backup options..."):
                                insight=run_agent(f"Simulate {selected.split(' · #')[0]} being unavailable from {start} through {end}. Investigate every affected brand/process, recommend backup employees using tools, and explain risks. Do not create leave or change the roster.",thread_id=st.session_state.event_thread)
                            st.subheader("Agent recommendation"); st.info(insight)
                        except Exception: st.warning("Agent recommendation is unavailable. The simulation results are still shown.")
        st.divider(); st.markdown("#### Submit leave request for human review")
        with st.form("leave_request"):
            employee=st.selectbox("Requesting employee",list(by_name),key="leave_employee")
            c1,c2=st.columns(2); ls=c1.date_input("Leave starts",now,key="leave_start"); le=c2.date_input("Leave ends",now,key="leave_end")
            kind=st.selectbox("Leave type",["planned","sick","comp_off"])
            request=st.form_submit_button("Submit pending request")
        if request:
            response=api("POST","/api/leave-requests",json={"employee_id":by_name[employee],"start_date":ls.isoformat(),"end_date":le.isoformat(),"leave_type":kind})
            if response:
                st.success(f"Request #{response.get('request_id')} submitted as PENDING. Manager approval is required.")
                if os.getenv("GOOGLE_API_KEY"):
                    try:
                        from app.agent import run_agent
                        with st.spinner("Agent is proactively assessing the pending absence..."):
                            insight=run_agent(f"A pending leave request #{response.get('request_id')} was submitted for {employee.split(' · #')[0]} from {ls} through {le}. Analyze affected services, identify coverage risks and backup options using live tools. Do not approve the request or change assignments.",thread_id=st.session_state.event_thread)
                        st.subheader("Real-time agent impact recommendation"); st.info(insight)
                    except Exception: st.warning("Agent impact analysis is unavailable. The pending request was still submitted.")

with tabs[3]:
    st.subheader("Workforce and resource management")
    people=api("GET","/api/employees") or []; brands=api("GET","/api/brands") or []
    left,right=st.columns(2)
    with left:
        st.markdown("#### Employees")
        if people: st.dataframe(pd.DataFrame(people),use_container_width=True,hide_index=True)
        else: st.info("No employees are available yet.")
        with st.expander("Add employee"):
            with st.form("add_employee"):
                name=st.text_input("Name"); email=st.text_input("Email")
                pod_rows=api("GET","/api/pods") or []; pod_options={"Unassigned":None,**{p["name"]:p["id"] for p in pod_rows}}
                selected_pod=st.selectbox("Pod",list(pod_options)); off=st.selectbox("Preferred weekly off",["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]); cap=st.number_input("Daily workload capacity",1,8,3); lead=st.checkbox("Pod lead")
                if st.form_submit_button("Create employee"):
                    r=api("POST","/api/employees",json={"name":name,"email":email or None,"pod_id":pod_options[selected_pod],"preferred_weekly_off":off,"daily_capacity":cap,"is_pod_lead":lead})
                    if r: st.success(f"Created {r['name']}"); st.rerun()
    with right:
        st.markdown("#### Brands and processes")
        if brands: st.dataframe(pd.DataFrame([{"Brand":b["name"],"Mode":b["operating_mode"],"Employees":b["employees"],"Processes":", ".join(p["name"] for p in b["processes"])} for b in brands]),use_container_width=True,hide_index=True)
        else: st.info("No brands are available yet.")
        with st.expander("Add brand"):
            with st.form("add_brand"):
                bn=st.text_input("Brand name"); mode=st.selectbox("Operating mode",["365_days","daily_except_holidays","weekdays_only"])
                if st.form_submit_button("Create brand"):
                    r=api("POST","/api/brands",json={"name":bn,"operating_mode":mode})
                    if r: st.success(f"Created {r['name']}"); st.rerun()
        with st.expander("Add process"):
            brand_map={b["name"]:b["id"] for b in brands}
            if brand_map:
                with st.form("add_process"):
                    chosen=st.selectbox("Brand",list(brand_map)); pn=st.text_input("Process name"); minimum=st.number_input("Minimum staff",1,20,1); pmode=st.selectbox("Operating mode override",["Inherit brand","365_days","daily_except_holidays","weekdays_only"])
                    if st.form_submit_button("Create process"):
                        r=api("POST","/api/processes",json={"name":pn,"brand_id":brand_map[chosen],"min_staffing":minimum,"operating_mode":None if pmode=="Inherit brand" else pmode})
                        if r: st.success(f"Created {r['name']}"); st.rerun()
    st.markdown("#### Create employee-to-process assignment")
    processes=[(b,p) for b in brands for p in b["processes"]]
    if people and processes:
        with st.form("assign"):
            empmap={f"{e['name']} · #{e['id']}":e["id"] for e in people}; selected_emp=st.selectbox("Employee",list(empmap))
            pmap={f"{b['name']} / {p['name']}":(b["id"],p["id"]) for b,p in processes}; selected_proc=st.selectbox("Brand / process",list(pmap)); primary=st.checkbox("Primary assignment",True)
            if st.form_submit_button("Add assignment"):
                bid,pid=pmap[selected_proc]; r=api("POST","/api/assignments",json={"employee_id":empmap[selected_emp],"brand_id":bid,"process_id":pid,"is_primary":primary})
                if r: st.success("Assignment created."); st.rerun()
    with st.expander("Create a pod"):
        with st.form("create_pod"):
            pod_name=st.text_input("Pod name")
            if st.form_submit_button("Create pod"):
                r=api("POST","/api/pods",json={"name":pod_name})
                if r: st.success(f"Created {r['name']}"); st.rerun()
    with st.expander("Configure process coverage requirement"):
        rule_brand_map = build_brand_map(brands)
        if rule_brand_map:
            with st.form("coverage_rule"):
                rule_brand=st.selectbox("Brand for rule",list(rule_brand_map),key="rule_brand")
                rule_processes=rule_brand_map[rule_brand].get("processes", [])
                rule_process_options={"All processes in brand":None, **{p["name"]:p["id"] for p in rule_processes}}
                rule_process=st.selectbox("Process scope",list(rule_process_options),key="rule_process")
                rule_day=st.selectbox("Day of week",["All days","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"])
                rule_min=st.number_input("Minimum staff required",0,50,1)
                if st.form_submit_button("Save coverage rule"):
                    r=api("POST","/api/coverage-rules",json={"brand_id":rule_brand_map[rule_brand]["id"],"process_id":rule_process_options[rule_process],"day_of_week":None if rule_day=="All days" else rule_day,"min_staff":rule_min})
                    if r: st.success("Coverage rule saved."); st.rerun()
        else:
            st.info("Create a brand before configuring coverage rules.")
    with st.expander("Add public holiday"):
        with st.form("add_holiday"):
            hd=st.date_input("Holiday date",now); hn=st.text_input("Holiday name")
            if st.form_submit_button("Add holiday"):
                r=api("POST","/api/holidays",json={"date":hd.isoformat(),"name":hn})
                if r: st.success("Holiday added."); st.rerun()
    st.markdown("#### Manual daily allocation")
    allocation_brand_map = build_brand_map(brands)
    if people and allocation_brand_map:
        with st.form("manual_daily_allocation"):
            amap={f"{e['name']} · #{e['id']}":e["id"] for e in people}
            selected_brand=st.selectbox("Brand",list(allocation_brand_map),key="manual_brand")
            process_map=build_process_options(allocation_brand_map[selected_brand])
            if process_map:
                selected_process=st.selectbox("Process",list(process_map),key="manual_process")
                selected_employee=st.selectbox("Assigned employee",list(amap),key="manual_employee")
                allocation_date=st.date_input("Allocation date",now,key="manual_date")
                if st.form_submit_button("Apply and validate allocation"):
                    r=api("POST","/api/rosters/manual-allocation",json={"employee_id":amap[selected_employee],"brand_id":allocation_brand_map[selected_brand]["id"],"process_id":process_map[selected_process],"date":allocation_date.isoformat()})
                    if r:
                        if r.get("warning"): st.warning(r["warning"])
                        else: st.success("Manual allocation saved and coverage validated.")
                        st.json(r)
            else:
                st.info("The selected brand has no processes to allocate.")
    else:
        st.info("Add at least one employee and one brand with a process before creating a manual allocation.")

with tabs[4]:
    st.subheader("Agentic Operations Assistant")
    st.caption("The agent can investigate operational changes, retrieve workforce records, recommend backups, and explain trade-offs. It cannot approve leave or publish a roster.")
    if "agent_history" not in st.session_state: st.session_state.agent_history=[]
    for m in st.session_state.agent_history:
        with st.chat_message(m["role"]): st.markdown(m["content"])
    prompt=st.chat_input("Example: If Riya takes leave tomorrow, which brands are at risk and who can cover?")
    if prompt:
        st.session_state.agent_history.append({"role":"user","content":prompt})
        with st.chat_message("user"): st.markdown(prompt)
        with st.chat_message("assistant"):
            try:
                from app.agent import run_agent
                answer=run_agent(prompt,thread_id=st.session_state.agent_thread)
                st.markdown(answer)
                st.session_state.agent_history.append({"role":"assistant","content":answer})
            except Exception:
                st.error("Agent unavailable. Check the LLM provider configuration and try again.")
    if st.button("Start new agent conversation"):
        st.session_state.agent_thread=str(uuid.uuid4()); st.session_state.agent_history=[]; st.rerun()

with tabs[5]:
    st.subheader("Human approvals")
    if st.session_state.get("approval_agent_insight"):
        st.info(st.session_state["approval_agent_insight"])
    requests_list=api("GET","/api/leave-requests") or []
    pending=[r for r in requests_list if r["status"]=="pending"]
    if not pending: st.success("No pending leave requests.")
    for req in pending:
        with st.container(border=True):
            st.write(f"**#{req['id']} · {req['employee']}** · {req['start_date']} → {req['end_date']} · {req['leave_type']}")
            c1,c2=st.columns(2)
            if c1.button("Approve and revalidate",key=f"approve_{req['id']}"):
                r=api("PATCH",f"/api/leave-requests/{req['id']}/review",json={"approve":True,"reviewer":"operations_manager"})
                if r:
                    st.success("Approved; affected roster month(s) revalidated.")
                    if os.getenv("GOOGLE_API_KEY"):
                        try:
                            from app.agent import run_agent
                            insight=run_agent(f"Leave request #{req['id']} for {req['employee']} from {req['start_date']} to {req['end_date']} was just approved. Inspect the resulting roster gaps for {date.fromisoformat(req['start_date']).year}-{date.fromisoformat(req['start_date']).month:02d} and recommend practical backup options using get_staffing_alerts and backup tools. Do not make further changes.",thread_id=st.session_state.event_thread)
                            st.session_state["approval_agent_insight"]=insight
                            st.info(insight)
                        except Exception: st.warning("Agent follow-up is unavailable. The approval was still recorded.")
                    st.rerun()
            if c2.button("Reject",key=f"reject_{req['id']}"):
                r=api("PATCH",f"/api/leave-requests/{req['id']}/review",json={"approve":False,"reviewer":"operations_manager"})
                if r: st.info("Request rejected."); st.rerun()
    st.divider(); st.subheader("Recent audit events")
    audit=api("GET","/api/audit") or []
    if audit: st.dataframe(pd.DataFrame(audit),use_container_width=True,hide_index=True)

st.divider()
st.caption("RosterOps · FastAPI · SQLAlchemy · PostgreSQL / SQLite · LangGraph · Gemini · Deterministic capacity-aware allocation")
