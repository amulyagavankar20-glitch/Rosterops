# DataStraw Assessment — Approach Note

## Problem framing
The scheduling unit is a **brand + process + operating date**, not merely an employee calendar cell. Different processes under the same brand may follow different operating calendars and minimum staffing requirements. Employees may own multiple processes or brands, so the system must track daily workload capacity as well as availability.

## Data model
Employees belong to pods. Pods identify their lead. Brands own processes. Assignments form the many-to-many relationship between employees and brand/process pairs. Operating modes can be configured at brand or process level. Public holidays, approved leaves, employee weekly-off preferences, daily capacity, and process-level coverage rules are stored separately.

## Scheduling and validation
For a selected month, the deterministic allocator expands each active brand/process into daily staffing demands. It filters employees with approved leave, applies process operating calendars, and allocates staff without exceeding each employee's daily workload capacity. Preferred weekly offs are soft preferences and are overridden only if needed to meet coverage. A separate coverage pass reports every process/day requirement, actual allocation, shortage severity, candidate diagnostics, and backup suggestions. The allocator is deterministic and explainable; it is greedy rather than globally optimal.

## Handling single- and multi-resource brands
Single-resource brands have one employee assigned across their processes, so that employee's daily capacity and absence are high-risk factors. Multi-resource brands have two or three assigned employees; process-level assignments determine whether they cover separate processes or overlap on one process. The same process/day coverage rule is applied to both patterns.

## Agentic layer
The LangGraph agent uses application tools to retrieve workforce data, simulate an absence, inspect coverage, recommend backup resources, and explain operational trade-offs. When leave is requested, the tool creates a pending request and simulates impact; it does not approve leave. A human manager approves or rejects the request. Approval triggers deterministic revalidation for all affected months. When roster generation detects gaps, the UI can trigger an agent investigation and present proactive recommendations. The LLM does not allocate employees, bypass capacity constraints, approve leave, or publish rosters.

## Trade-offs and next improvements
The deterministic allocator favors predictable behavior and clear diagnostics over a black-box model. It is not a global optimization solver; CP-SAT would be the next improvement for fairness and complex multi-objective scheduling. Other next steps are shift start/end-time modelling, comp-off balance tracking, durable Postgres-backed LangGraph checkpoints, individual authentication/RBAC, scenario draft/publish lifecycle, and container/browser integration testing before production use with real employee data.
