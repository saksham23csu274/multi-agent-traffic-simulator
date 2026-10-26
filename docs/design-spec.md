# Multi-Agent Traffic Management and Emergency Routing Simulator

## 1. Project Overview

The **Multi-Agent Traffic Management and Emergency Routing Simulator** is a software system for modeling, observing, and improving urban traffic operations in a simulated city. It combines a microscopic or mesoscopic traffic simulation with a set of autonomous software agents that coordinate traffic signals, monitor congestion, and support emergency vehicle routing.

The project will provide a controlled environment in which to compare a baseline traffic system with multi-agent strategies under normal and disrupted conditions. The simulator is intended for experimentation, demonstrations, and evaluation—not direct control of real traffic infrastructure.

### Problem statement

Fixed traffic signal plans and isolated routing decisions can perform poorly when traffic demand changes quickly, incidents block road segments, or emergency vehicles need a reliable path through congested streets. A coordinated system could use current simulated conditions to adapt signal timing and route choices, but its behavior and trade-offs need to be tested safely before any real-world deployment is considered.

### Proposed solution

Build a configurable, repeatable simulation in which:

1. A road network and time-varying traffic demand generate vehicle movement.
2. Local traffic-signal agents observe their intersections and choose signal actions.
3. A traffic coordination agent or coordination protocol helps local agents avoid harmful interactions and manage network-level goals.
4. Emergency dispatch and routing agents identify feasible paths for emergency vehicles.
5. Signal agents can provide conditional priority to an approaching emergency vehicle while retaining safety constraints.
6. A monitoring and evaluation layer measures performance and presents runs for comparison.

## 2. Vision, Goals, and Non-Goals

### Vision

Demonstrate how cooperating autonomous agents can improve traffic flow and emergency response in a realistic, configurable city simulation, while making the agents' decisions measurable and explainable.

### Goals

- Represent roads, intersections, traffic signals, vehicles, and incidents in a simulation.
- Support multiple independent agents operating at different intersections.
- Adapt signal decisions to local traffic conditions and, where enabled, network-level information.
- Detect emergency requests and plan routes using current network conditions.
- Coordinate emergency vehicle passage through intersections using safe, bounded signal-priority actions.
- Compare agent strategies against transparent baseline controllers using repeatable scenarios and random seeds.
- Expose useful metrics, logs, and visualizations for analysis.
- Keep simulation time, agent decisions, and experiment configuration reproducible.

### Non-goals for the initial version

- Controlling real traffic lights, roadside units, or emergency fleets.
- Replacing certified traffic-engineering analysis or operational dispatch systems.
- Claiming real-world safety, legal compliance, or guaranteed response-time improvements.
- Modeling every human, weather, vehicle, communications, and infrastructure behavior in full fidelity.
- Using live personally identifiable location data.

## 3. Users and Use Cases

### Intended users

- Students and researchers studying intelligent transportation systems and multi-agent coordination.
- Developers implementing or comparing traffic-management policies.
- Instructors demonstrating agent behavior, routing, and simulation evaluation.
- Reviewers who need a visual explanation of system behavior and experiment outcomes.

### Core use cases

1. **Run a baseline scenario:** Load a road network and demand profile, then run fixed-time or conventional traffic control.
2. **Run adaptive control:** Enable signal agents and compare traffic metrics with the baseline.
3. **Introduce an incident:** Close or slow a road segment and observe rerouting and congestion response.
4. **Dispatch an emergency vehicle:** Create an emergency request, calculate a route, and measure simulated response time.
5. **Coordinate signal priority:** Allow approaching intersections to grant bounded priority to an emergency vehicle, subject to conflict and safety rules.
6. **Compare experiments:** Repeat scenarios with the same random seed and compare strategies, metrics, and event histories.
7. **Inspect agent decisions:** Review observations, selected actions, constraints, and outcomes for a chosen time interval.

## 4. System Scope and Assumptions

The simulator should be designed around a pluggable traffic-simulation engine. A suitable initial implementation can use **SUMO (Simulation of Urban MObility)** with its TraCI interface, because it supports road-network simulation and programmatic control. The architecture should avoid coupling core policy logic to SUMO-specific APIs so that a different engine can be substituted later.

Initial assumptions:

- The road graph is supplied as a prepared network or generated from a small sample map.
- Demand is synthetic or derived from openly licensed aggregate data.
- Vehicles follow the simulator's supported movement and safety rules.
- Simulation time advances in discrete steps; agent actions occur at configured decision intervals.
- Emergency priority is simulated and constrained by the traffic engine and configured right-of-way rules.
- Results are evaluated in simulation only and do not constitute operational guidance.

## 5. High-Level Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                     User / Experiment Operator                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ configure, run, inspect
┌────────────────────────────▼────────────────────────────────────┐
│                    User Interface / Dashboard                    │
│  Map view | controls | metrics | event timeline | comparisons    │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST/WebSocket or local API
┌────────────────────────────▼────────────────────────────────────┐
│                  Simulation Orchestrator                         │
│  run lifecycle | clock | scenario config | seed | event handling │
└──────────────┬─────────────────────┬────────────────────────────┘
               │                     │
┌──────────────▼─────────────┐  ┌────▼────────────────────────────┐
│ Traffic Engine Adapter      │  │ Agent Runtime / Coordinator     │
│ SUMO/TraCI or other engine  │  │ scheduling | state | messaging  │
│ network | vehicles | signals│  │ constraints | decision logs     │
└──────────────┬─────────────┘  └────┬────────────────────────────┘
               │ observations/actions  │
               └──────────────┬────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                         Agent Services                           │
│ Signal agents | traffic monitor | incident agent | dispatch and  │
│ emergency-routing agent | optional network coordinator          │
└─────────────────────────────┬───────────────────────────────────┘
                              │ events and measurements
┌─────────────────────────────▼───────────────────────────────────┐
│                    Data and Evaluation Layer                     │
│ scenario store | event log | metrics | run results | exports     │
└─────────────────────────────────────────────────────────────────┘
```

### Architectural principles

- **Separation of concerns:** Simulation mechanics, decision policies, UI, and evaluation are separate modules.
- **Replaceable policies:** Controllers implement a common interface and can be swapped without changing the simulator.
- **Reproducibility:** Every run records its scenario, parameters, policy versions, and random seed.
- **Safety constraints first:** Agent actions are checked against allowed signal phases, minimum green/yellow/all-red timing, and configured priority rules before application.
- **Observable behavior:** Decisions and relevant observations are logged with timestamps and reasons.
- **Progressive fidelity:** Begin with a small network and simple demand; increase complexity only when the end-to-end loop works.
- **Simulation-time determinism:** Agent scheduling and event ordering are tied to simulation time rather than arbitrary wall-clock timing where feasible.

## 6. Major Components

### 6.1 Scenario and Network Manager

Responsible for loading, validating, and describing the simulated world.

Responsibilities:
- Load road-network files, junctions, lanes, permitted movements, and signal programs.
- Load or generate traffic demand, vehicle types, and route definitions.
- Define incident locations, start/end times, severity, and affected edges.
- Define emergency requests, vehicle classes, origin/destination, and release time.
- Validate that routes and signal plans are compatible with the network.
- Store a scenario manifest with all inputs and configuration values.

### 6.2 Traffic Simulation Engine Adapter

Provides a stable interface between project modules and the chosen simulator.

Example responsibilities:
- Start, stop, pause, and advance simulation time.
- Read vehicle positions, speeds, queues, lane occupancy, travel times, and signal states.
- Apply permitted traffic-signal phase changes or priority requests.
- Add or remove vehicles and apply configured edge closures or slowdowns.
- Translate engine-specific identifiers and units into project-level models.

Example interface (conceptual):

```text
start(run_config)
step() -> SimulationSnapshot
get_intersection_state(intersection_id) -> IntersectionObservation
set_signal_action(intersection_id, action) -> ActionResult
get_network_graph() -> RoadGraphSnapshot
apply_incident(incident) -> IncidentResult
close()
```

The adapter should surface invalid actions and engine errors explicitly rather than silently ignoring them.

### 6.3 Simulation Orchestrator

Coordinates one simulation run from initialization to result export.

Responsibilities:
- Validate the run configuration and create a unique run ID.
- Initialize the engine, agents, event schedule, and metric collectors.
- Advance the simulation in discrete steps and invoke agents at configured intervals.
- Deliver observations and events to the appropriate agents.
- Apply validated agent actions in deterministic order.
- Handle pause, resume, cancellation, timeout, and failure states.
- Persist run metadata, events, metrics, and final status.

### 6.4 Agent Runtime and Messaging

Hosts agents and standardizes how they receive observations and return actions.

Responsibilities:
- Register agent instances and their controlled entities.
- Schedule agent decisions according to the configured cadence.
- Provide typed observations and event messages.
- Validate action schemas and apply action constraints.
- Support local in-process message passing for the first version; allow a message-bus adapter later if needed.
- Record agent identity, input timestamp, action, and outcome.

Messages should be versioned and timestamped in simulation time. Agents must be able to handle stale or missing information safely.

### 6.5 Intersection Signal Agent

Each signal agent controls one intersection or one signal group.

**Observations may include:**
- Queue length and waiting time by incoming lane or movement.
- Vehicle count, average speed, occupancy, and approaching flow.
- Current phase, phase elapsed time, and valid next phases.
- Downstream congestion or blocked exits, if available.
- Incident status and emergency-vehicle ETA or priority request.

**Actions may include:**
- Keep the current phase for a bounded duration.
- Request a valid next phase.
- Extend or shorten a phase within configured limits.
- Enter a priority mode for a specified movement, subject to safety constraints.

**Policy progression:**
1. Fixed-time baseline.
2. Rule-based adaptive policy (e.g., queue-weighted phase selection).
3. Optional optimization or learning policy after baselines, metrics, and safety validation exist.

Each agent should have a safe fallback (e.g., revert to a legal configured phase plan) when observations are invalid, an action is rejected, or the agent fails.

### 6.6 Traffic Monitoring Agent / Service

Aggregates traffic state and detects conditions that may require attention.

Responsibilities:
- Estimate congestion using queues, speeds, density, and delay thresholds.
- Identify blocked or unusually slow segments.
- Publish incident and congestion events to routing and coordination components.
- Track network-level indicators such as throughput and travel-time trends.

For the initial release, detection can be based on simulator-known events and explicit thresholds. More advanced anomaly detection is optional future work.

### 6.7 Incident Agent / Event Manager

Applies scheduled or interactive disruptions.

Responsibilities:
- Activate and resolve road closures, lane reductions, or speed restrictions.
- Emit event notifications to route planners and nearby signal agents.
- Track incident lifecycle and affected network elements.
- Ensure scenario changes are logged and reversible where the engine permits.

### 6.8 Emergency Dispatch and Routing Agent

Manages simulated emergency requests and computes routes.

Responsibilities:
- Receive an emergency request containing origin, destination, release time, and vehicle class.
- Compute a feasible route over the road graph.
- Recompute or adjust the route when incidents, closures, or congestion materially change.
- Estimate route cost using configurable travel time, expected delay, and risk/uncertainty penalties.
- Notify relevant intersection agents of the vehicle's approach and estimated arrival.
- Track dispatch time, route changes, arrival, and completion status.

The initial router can use Dijkstra's algorithm or A* with edge costs based on estimated travel time. Dynamic costs should be updated at controlled intervals to avoid unstable route oscillations. A route must respect vehicle access restrictions and network connectivity.

### 6.9 Emergency Signal-Priority Coordinator

Coordinates signal support for an approaching emergency vehicle without violating configured intersection safety constraints.

Responsibilities:
- Identify intersections along the active emergency route.
- Estimate arrival time and issue time-bounded priority requests.
- Avoid conflicting green indications and enforce minimum change intervals.
- Clear or expire requests when the emergency vehicle passes, reroutes, or completes its trip.
- Provide a fair-use policy so ordinary traffic is not indefinitely starved.
- Log requested, approved, denied, and expired priority actions with reasons.

Priority behavior is a simulation policy only. The simulator should not imply that emergency vehicles may disregard actual traffic laws or operational procedures.

### 6.10 Metrics and Evaluation Service

Collects raw measurements and derives run-level and interval-level performance indicators.

**Traffic metrics:**
- Mean and median trip travel time.
- Mean waiting time and delay relative to a reference/free-flow estimate.
- Average and maximum queue length.
- Network throughput (vehicles completed per unit time).
- Time-loss or stop counts, if provided by the engine.
- Congestion duration and recovery time after an incident.

**Emergency metrics:**
- Dispatch-to-arrival time.
- Route length and number of route changes.
- Emergency vehicle stopped time and delay.
- Number and duration of signal-priority actions.
- Priority request success/denial counts.

**System metrics:**
- Simulation steps per second or wall-clock run duration.
- Agent decision latency and failure count.
- Rejected or invalid actions.
- Missing/stale observation count.

Metrics should be defined precisely, including units, aggregation window, and handling of unfinished trips. Avoid comparing runs with materially different demand or scenario settings unless the difference is intentional.

### 6.11 Dashboard and Visualization

A web-based or desktop dashboard should enable users to configure and inspect experiments.

Core views:
- **Map view:** road network, vehicles, signal states, incidents, and emergency route.
- **Run controls:** scenario selection, seed, strategy selection, simulation speed, pause/resume, and stop.
- **Live metrics:** traffic volume, completed trips, congestion, average delay, and emergency status.
- **Event timeline:** incidents, dispatches, route changes, signal-priority requests, and agent faults.
- **Comparison view:** baseline versus agent strategies across one or multiple repeated runs.
- **Decision inspector:** selected agent, observation summary, action, constraints, and result.

The dashboard is for analysis and demonstration. It is not an operational traffic-control console.

### 6.12 Persistence and Export

Store enough information to reproduce and interpret each run.

Suggested records:
- Scenario manifest and network/demand references.
- Run configuration, software version, policy names/versions, and random seed.
- Timestamped event and action logs.
- Time-series metrics and final aggregates.
- Run status, warnings, and errors.

Initial storage may use JSON/CSV files or SQLite. A server deployment can later use PostgreSQL for structured run data and object storage for larger artifacts. Provide CSV/JSON export for analysis.

## 7. Data Flow and Decision Loop

A typical simulation step follows this sequence:

1. The orchestrator advances the traffic engine by one or more simulation ticks.
2. The adapter reads a snapshot of vehicles, signals, queues, and network state.
3. The event manager applies scheduled scenario events and publishes any changes.
4. The monitoring service updates congestion estimates and incident state.
5. The emergency router updates active route plans if triggered by a material event or configured refresh interval.
6. Signal agents receive local observations and relevant messages, including emergency-priority requests.
7. Agents propose actions through the common action interface.
8. The action validator checks phase legality, minimum/maximum timing, conflict rules, request expiry, and other configured limits.
9. The adapter applies accepted actions to the engine and reports results.
10. Metrics and structured decision/event logs are updated.
11. The dashboard receives live updates and the loop continues until the run ends.

### Example signal-agent observation

```json
{
  "simulation_time_s": 420,
  "intersection_id": "J_12",
  "current_phase": "north_south_through",
  "phase_elapsed_s": 24,
  "movements": [
    {"id": "north_in_through", "queue_vehicles": 8, "mean_wait_s": 31},
    {"id": "east_in_through", "queue_vehicles": 3, "mean_wait_s": 12}
  ],
  "emergency_requests": [
    {"vehicle_id": "EMS_3", "movement_id": "west_in_through", "eta_s": 18}
  ]
}
```

### Example action

```json
{
  "agent_id": "signal-agent-J_12",
  "intersection_id": "J_12",
  "action": "request_phase",
  "phase_id": "west_through_priority",
  "requested_duration_s": 15,
  "reason_code": "emergency_vehicle_approaching"
}
```

These examples are conceptual; the final schema should be defined and versioned in code.

## 8. Agent Coordination Model

The first implementation should favor a transparent hybrid model over a complex distributed-learning system:

- **Local autonomy:** Each intersection agent acts using its local observations.
- **Shared event channel:** Incidents and emergency-route information are published to affected agents.
- **Central orchestration:** The simulation orchestrator controls time and enforces action constraints, but does not need to choose every signal phase.
- **Optional coordinator:** A network-level service can publish congestion costs, corridor priorities, or recommendations without directly overriding every local decision.

This structure provides a useful multi-agent setting while keeping the initial system tractable. Central coordination can be ablated in experiments to quantify its value.

## 9. Technology and Implementation Options

A practical initial stack could be:

- **Traffic simulation:** SUMO with TraCI, behind a project-owned adapter.
- **Backend and agent logic:** Python, chosen for simulator integration and algorithm prototyping.
- **API:** FastAPI for run management and configuration; WebSocket or server-sent events for live updates.
- **Frontend:** React with a map/graph visualization layer, or a lightweight visualization built around the engine's existing network/map exports.
- **Persistence:** SQLite and JSON/CSV for a single-user prototype; PostgreSQL for multi-user or hosted use.
- **Testing:** pytest for unit/integration tests; scenario-based regression tests for reproducible runs.
- **Packaging:** Docker Compose may be used for local reproducibility if the simulator and UI are run as separate services.

These are recommended options, not fixed requirements. Keep interfaces and deployment decisions documented so components can be replaced.

## 10. Configuration Model

A run configuration should include:

```yaml
scenario_id: sample_grid
random_seed: 42
simulation:
  engine: sumo
  step_length_s: 1
  duration_s: 1800
  decision_interval_s: 5
traffic_control:
  strategy: adaptive_queue
  min_green_s: 8
  max_green_s: 45
  yellow_s: 3
  all_red_s: 1
emergency:
  enabled: true
  routing_strategy: dynamic_shortest_path
  priority_enabled: true
  reroute_threshold_percent: 15
metrics:
  sample_interval_s: 5
outputs:
  save_events: true
  export_csv: true
```

Validation should reject invalid values, unknown strategies, missing network files, impossible routes, and unsafe signal-timing configurations before a run starts.

## 11. Safety, Reliability, and Ethics

Although the project is a simulator, it must be explicit about the limits of its results.

- Never connect the prototype to live traffic infrastructure.
- Apply a policy/action validation layer before any signal command reaches the simulator.
- Preserve legal phase transitions and configured yellow/all-red clearance intervals.
- Ensure emergency priority expires and cannot persist indefinitely.
- Provide safe fallback behavior when an agent crashes or returns malformed data.
- Make emergency and ordinary-traffic trade-offs visible in reports.
- Avoid using personal or identifiable movement data; use synthetic or properly aggregated data.
- Document simulator fidelity, assumptions, calibration gaps, and known limitations.
- Do not describe simulation results as proof of real-world safety or guaranteed performance.

## 12. Non-Functional Requirements

### Performance

The target is to run the chosen sample network in real time or faster on a typical development machine, subject to network size and engine configuration. Performance should be measured rather than assumed.

### Reliability

- A failed agent should not terminate the whole run unless configured to do so.
- Run metadata and partial logs should be preserved after a failure.
- Invalid configurations should fail early with actionable error messages.

### Usability

- Users can launch a documented sample scenario without manually editing engine internals.
- Live visualization makes agent and emergency behavior interpretable.
- Results can be exported and compared.

### Maintainability

- Policies, adapters, metrics, and UI are independently testable.
- Configuration and message schemas are documented and versioned.
- Core algorithms have unit tests and scenario regression coverage.

### Reproducibility

- Fixed seeds and immutable scenario manifests reproduce comparable runs.
- Experiment outputs record code and policy versions.
- Baseline and candidate runs use matched demand and incident conditions where possible.

## 13. Testing and Validation Strategy

### Unit tests

- Route-cost calculation and shortest-path behavior.
- Signal action validation and phase transition constraints.
- Metric aggregation and units.
- Event scheduling, request expiry, and reroute thresholds.
- Schema validation and configuration errors.

### Integration tests

- Adapter starts and advances a small network.
- Agent observations match the expected schema.
- Accepted actions reach the engine and rejected actions are safely handled.
- Emergency dispatch, routing, signal requests, and arrival are logged end to end.
- Incident activation updates routes and metrics.

### Scenario tests

- Low-demand baseline with no incidents.
- Peak demand with multiple congested intersections.
- Emergency request on an uncongested route.
- Emergency request during congestion.
- Road closure on the shortest route.
- Agent failure or malformed action.
- Multiple emergency requests to test priority fairness.

### Evaluation design

For each policy, run multiple seeds or matched scenarios and report distributions (mean/median and variation), not only a single best run. Compare against at least one fixed-time baseline and, if available, a conventional actuated baseline. Include both network-wide and emergency-specific outcomes so improvements in one objective do not conceal degradation in another.

## 14. Success Criteria and Expected Outcomes

The project is successful when it delivers a functioning and understandable simulation prototype, not merely an algorithm in isolation.

### Expected deliverables

- A documented sample road network and traffic-demand scenario.
- A runnable simulation orchestrator and traffic-engine adapter.
- At least one baseline signal controller and one adaptive multi-agent controller.
- Emergency request generation, route planning, and route-change handling.
- Safe, bounded signal-priority request flow in the simulation.
- A dashboard or visualization for live state and post-run comparison.
- Reproducible experiment configuration and exported metrics.
- Automated tests and project documentation.

### Expected measurable outcomes

The experiment framework should make it possible to determine whether the candidate policies, under defined scenarios:

- Reduce average delay, waiting time, or queues relative to the selected baseline.
- Maintain or improve network throughput under variable demand.
- Reduce emergency dispatch-to-arrival time and emergency vehicle stopped time.
- Recover more quickly after specified incidents.
- Keep ordinary-traffic impacts and signal-priority side effects within explicitly reported bounds.
- Operate reliably, with low rates of invalid actions and recoverable agent failures.

No numerical improvement is guaranteed in advance. Results will depend on network design, demand, policy, simulator fidelity, and evaluation setup. The project should publish measured results with scenario details and limitations.

## 15. Phased Implementation Plan

### Phase 1 — Requirements and baseline scenario

- Choose simulator and define adapter boundary.
- Prepare a small grid or corridor network.
- Define demand, vehicle types, and a run configuration format.
- Implement a baseline fixed-time run and verify basic metrics.

**Exit condition:** A deterministic sample run completes and produces valid outputs.

### Phase 2 — Orchestration and observability

- Implement run lifecycle, simulation clock, event logging, and configuration validation.
- Add common observation/action schemas and action validator.
- Add run summaries and CSV/JSON exports.

**Exit condition:** Runs are reproducible and invalid actions are rejected safely.

### Phase 3 — Multi-agent adaptive signals

- Implement one agent per controlled intersection.
- Add a transparent rule-based queue-responsive controller.
- Add safe fallback behavior and decision logs.
- Compare with fixed-time control on matched scenarios.

**Exit condition:** Multiple agents control the network and results can be compared.

### Phase 4 — Emergency routing and incidents

- Add emergency request lifecycle and route planner.
- Add incident scheduling and dynamic route-cost updates.
- Notify intersections along the route and implement bounded signal priority.
- Measure response time and traffic side effects.

**Exit condition:** Emergency vehicles can be dispatched, rerouted, and tracked end to end.

### Phase 5 — Dashboard and experiment comparison

- Add live map, run controls, metrics, event timeline, and result comparison.
- Add decision inspection for selected agents.
- Improve error messages and user documentation.

**Exit condition:** A user can configure, run, inspect, and compare scenarios through the interface.

### Phase 6 — Evaluation and extension

- Run repeated experiments across demand levels and incident types.
- Add sensitivity analysis and optional coordination strategies.
- Consider optimization or learning-based policies only after the benchmark and safety layer are stable.
- Document limitations and publish a reproducible evaluation report.

## 16. Key Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Simulator setup or network complexity delays development | High | Start with a small known-good network; keep a smoke test and adapter boundary. |
| Adaptive policy improves one metric while worsening another | High | Use multi-metric evaluation and report traffic-wide and emergency outcomes together. |
| Emergency priority causes cross-traffic starvation | High | Bound priority duration, add expiry/fairness rules, and measure impacts. |
| Agents oscillate between phases or reroute too often | Medium | Add minimum dwell times, hysteresis, event thresholds, and route-change penalties. |
| Results are not reproducible | Medium | Record seeds, configuration, versions, and scenario manifests. |
| Simulator results are mistaken for real-world validation | High | Clearly label the tool as simulation-only and document model limitations. |
| Dashboard distracts from validating the core loop | Medium | Build the backend and repeatable experiments first; add UI incrementally. |

## 17. Open Decisions

The following decisions should be finalized during project kickoff:

1. Which traffic engine and version will be used?
2. Is the first delivery a command-line prototype, a web dashboard, or both?
3. What sample network and demand profile are appropriate for the target users?
4. Which baseline controllers will be included?
5. What is the initial definition of emergency-priority behavior and fairness?
6. Which metrics are required for acceptance, and how are unfinished trips treated?
7. Is the prototype single-user/local or intended for a hosted multi-user deployment?
8. Are learning-based agents in scope, or reserved for a later research phase?

## 18. Recommended Initial Milestone

The first milestone should be a small, end-to-end proof of concept: one sample network, fixed-time baseline, rule-based intersection agents, one emergency request, one road-closure event, route planning, bounded simulated signal priority, and a concise metric report. This validates the architecture's critical interfaces before investing in advanced algorithms or extensive UI work.

## 19. Summary

This project will build a modular traffic simulation in which local signal agents, emergency-routing logic, incident handling, and a central orchestration layer operate together. The system will provide reproducible baseline comparisons, interpretable agent decisions, and measurable traffic and emergency outcomes. Its value is a safe experimental platform for testing coordination strategies and understanding trade-offs; real-world deployment, operational certification, and guaranteed improvements are explicitly outside the initial scope.
