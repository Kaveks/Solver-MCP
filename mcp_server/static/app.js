/* =============================================================
 *Solver-MCP — single-page UI controller.
 *
 * Vanilla JS, no libraries. Drives three views inside .right-panel:
 *   "faq"    — static overview (default)
 *   "chat"   — conversational simulation per solver
 *   "result" — full job result panel
 *
 * The agent is reached through:
 *   POST /api/solver-intro    (one-shot solver intro text — no tools)
 *   GET  /api/chat            (SSE: tool calls + streamed tokens + result)
 *   GET  /jobs/{id}           (poll job status/result)
 * ============================================================= */

// =============================================================
// CONSTANTS
// =============================================================

const SOLVER_META = {
  openfoam: {
    name: "OpenFOAM",
    subtitle: "Computational Fluid Dynamics",
    icon: "⚡",
    color: "#4f8ef7",
    bgColor: "rgba(79,142,247,0.15)",
  },
  lammps: {
    name: "LAMMPS",
    subtitle: "Molecular Dynamics",
    icon: "⚛",
    color: "#2dd4a0",
    bgColor: "rgba(45,212,160,0.15)",
  },
  freecad: {
    name: "FreeCAD",
    subtitle: "Structural FEM",
    icon: "📐",
    color: "#8b8fa8",
    bgColor: "rgba(139,143,168,0.15)",
  },
};

const SOLVER_INTRO_PROMPTS = {
  openfoam: `You are starting a CFD simulation session. Introduce yourself as the OpenFOAM connector in one sentence. Then list exactly what you need from the engineer as 4-6 short bullet points: case name, inlet velocity vector, kinematic viscosity, turbulence model (kEpsilon or kOmegaSST), iteration count, and write interval. State valid ranges where relevant. End with one sentence inviting them to describe their case. No markdown headers. Under 120 words total.`,
  lammps: `You are starting an MD simulation session. Introduce yourself as the LAMMPS connector in one sentence. Then list exactly what you need as 4-6 short bullet points: case name, FCC lattice density (reduced units, typical 0.8442), box replication (NxNxN, typical 10), NVT temperature, timestep (typical 0.005), number of steps, output frequency. State valid ranges. End with one sentence inviting them to describe their simulation. No markdown headers. Under 120 words total.`,
};

const FREECAD_STATIC_INTRO = `I'm the FreeCAD connector for structural finite-element analysis. In the Prototype, this connector is registered and input is validated against the schema, but execution returns a structured NOT_IMPLEMENTED response. Full headless FEM — geometry import, Gmsh/Netgen meshing, and solve — is planned for the Production track. You can submit a FreeCAD job to see the validated response structure, or select OpenFOAM or LAMMPS to run a live simulation.`;

// =============================================================
// STATE
// =============================================================

const state = {
  activeSolver: null,
  currentView: "faq", // "faq" | "chat" | "result"
  chatHistory: [],
  solverIntros: {}, // cached LLM intros per solver
  jobs: [],
  selectedJobId: null,
};

// =============================================================
// VIEW TRANSITIONS
// =============================================================

function showView(view) {
  document.getElementById("state-faq").style.display =
    view === "faq" ? "block" : "none";
  document.getElementById("state-chat").style.display =
    view === "chat" ? "flex" : "none";
  document.getElementById("state-result").style.display =
    view === "result" ? "flex" : "none";
  state.currentView = view;
}

function showFAQ() {
  showView("faq");
  state.activeSolver = null;
  state.chatHistory = [];
  document
    .querySelectorAll(".solver-row")
    .forEach((r) => r.classList.remove("active"));
}

// Remove conversation nodes but keep the persistent #thinking indicator.
function clearMessages() {
  document
    .getElementById("chat-messages")
    .querySelectorAll(".msg-agent, .msg-user, .msg-tool")
    .forEach((n) => n.remove());
}

async function showChat(solver) {
  const meta = SOLVER_META[solver];
  const iconEl = document.getElementById("chat-solver-icon");
  iconEl.textContent = meta.icon;
  iconEl.style.background = meta.bgColor;
  iconEl.style.color = meta.color;
  document.getElementById("chat-solver-name").textContent = meta.name;
  document.getElementById("chat-solver-subtitle").textContent = meta.subtitle;

  clearMessages();
  hideThinking();

  showView("chat");
  state.activeSolver = solver;
  state.chatHistory = [];

  // Get or generate intro (cached per solver per session).
  if (state.solverIntros[solver]) {
    appendAgentBubble(state.solverIntros[solver]);
    state.chatHistory.push({
      role: "assistant",
      content: state.solverIntros[solver],
    });
  } else {
    showThinking();
    const intro = await getSolverIntro(solver);
    hideThinking();
    // Guard: the user may have navigated away while the intro was generating.
    if (state.activeSolver !== solver || state.currentView !== "chat") return;
    state.solverIntros[solver] = intro;
    appendAgentBubble(intro);
    state.chatHistory.push({ role: "assistant", content: intro });
  }

  document.getElementById("chat-input").focus();
}

async function showResult(jobId) {
  state.selectedJobId = jobId;
  showView("result");
  // Render immediately from whatever we hold so the panel opens without a blank flash...
  renderJobResult(jobId);
  renderJobHistory();
  // ...then reconcile against the backend (the single source of truth) so a job opened later
  // in the session reflects its authoritative status + clean interpretation, not a stale live
  // entry. Guard against the user navigating away while the fetch is in flight.
  await loadJobsFromBackend();
  if (state.selectedJobId === jobId && state.currentView === "result") {
    renderJobResult(jobId);
    renderJobHistory();
  }
}

// =============================================================
// SOLVER INTRO (LLM called once per solver per session)
// =============================================================

async function getSolverIntro(solver) {
  if (solver === "freecad") return FREECAD_STATIC_INTRO;
  if (state.solverIntros[solver]) return state.solverIntros[solver];

  try {
    const res = await fetch("/api/solver-intro", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: SOLVER_INTRO_PROMPTS[solver],
      }),
    });
    const data = await res.json();
    return data.response || "Ready. Describe your simulation.";
  } catch {
    return "Ready. Describe your simulation.";
  }
}

// =============================================================
// CHAT — MESSAGE RENDERING
// =============================================================

// Sender shown above a bubble: the engineer is "You"; the assistant is named after
// the active solver (e.g. "OpenFOAM"), falling back to "Assistant".
function senderLabel(role) {
  if (role === "user") return "You";
  const meta = SOLVER_META[state.activeSolver];
  return meta ? meta.name : "Assistant";
}

// Build an agent message row: avatar + a column of [sender label, bubble].
// Returns the bubble so callers can fill it (and streaming can append to it).
function createAgentRow() {
  const row = document.createElement("div");
  row.className = "msg-agent";

  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.textContent = "⚗";

  const col = document.createElement("div");
  col.className = "msg-col";

  const label = document.createElement("div");
  label.className = "msg-sender";
  label.textContent = senderLabel("agent");

  const bubble = document.createElement("div");
  bubble.className = "bubble-agent";

  col.appendChild(label);
  col.appendChild(bubble);
  row.appendChild(avatar);
  row.appendChild(col);
  return { row, bubble };
}

function appendAgentBubble(text, jobResult, jobId, solver) {
  const messagesEl = document.getElementById("chat-messages");
  const { row, bubble } = createAgentRow();
  bubble.innerHTML = renderMarkdown(text); // safe: renderMarkdown escapes first

  if (jobResult && jobId && solver) {
    bubble.appendChild(buildResultCard(jobResult, jobId, solver));
  }

  messagesEl.appendChild(row);
  scrollMessages();

  return bubble; // returned so streaming can append to it
}

function appendUserBubble(text) {
  const messagesEl = document.getElementById("chat-messages");
  const row = document.createElement("div");
  row.className = "msg-user";

  const col = document.createElement("div");
  col.className = "msg-col";

  const label = document.createElement("div");
  label.className = "msg-sender";
  label.textContent = senderLabel("user");

  const bubble = document.createElement("div");
  bubble.className = "bubble-user";
  bubble.textContent = text;

  col.appendChild(label);
  col.appendChild(bubble);
  row.appendChild(col);
  messagesEl.appendChild(row);
  scrollMessages();
}

function appendToolIndicator(type, name) {
  const messagesEl = document.getElementById("chat-messages");
  const row = document.createElement("div");
  row.className = "msg-tool " + (type === "start" ? "tool-start" : "tool-end");
  row.dataset.tool = name;
  row.dataset.type = type;
  row.textContent = type === "start" ? `→ ${name}` : `✓ ${name}`;
  messagesEl.appendChild(row);
  scrollMessages();
  return row;
}

function scrollMessages() {
  // The conversation AND the composer share one scroll container, so scrolling it
  // to the bottom keeps the input (which flows under the last message) in view.
  const el = document.getElementById("chat-scroll");
  el.scrollTop = el.scrollHeight;
}

function showThinking() {
  const el = document.getElementById("chat-messages");
  const thinking = document.getElementById("thinking");
  el.appendChild(thinking); // move to end so dots follow the last message
  thinking.style.display = "flex";
  scrollMessages();
}

function hideThinking() {
  document.getElementById("thinking").style.display = "none";
}

// =============================================================
// CHAT — INLINE RESULT CARDS
// =============================================================

function buildResultCard(result, jobId, solver) {
  const card = document.createElement("div");
  card.className = "result-card";

  if (solver === "lammps") {
    card.classList.add("result-card-lammps");
    const eq = result.equilibrium || {};
    const traj = result.trajectory || [];

    const header = document.createElement("div");
    header.className = "card-header";
    header.textContent = "⚛ MD Simulation Complete";
    card.appendChild(header);

    const metrics = document.createElement("div");
    metrics.className = "card-metrics";
    [
      ["T*", fmt(eq.temperature, 3)],
      ["P*", fmt(eq.pressure, 3)],
      ["E_tot", fmt(eq.total_energy, 3)],
      ["E_pot", fmt(eq.potential_energy, 3)],
    ].forEach(([label, value]) =>
      metrics.appendChild(metricInline(label, value)),
    );
    card.appendChild(metrics);

    const sparkContainer = document.createElement("div");
    sparkContainer.className = "sparkline-container";
    const temps = traj.map((r) => r.temp);
    if (temps.length > 1) {
      sparkContainer.appendChild(renderSparkline(temps, "#4f8ef7"));
    }
    card.appendChild(sparkContainer);

    const footer = document.createElement("div");
    footer.className = "card-footer";
    footer.innerHTML =
      `${esc(result.steps ?? "?")} steps · ${esc(traj.length)} atoms · ` +
      `<a href="/dashboard#${esc(jobId)}" class="artifact-link">View details →</a>`;
    card.appendChild(footer);
  } else if (solver === "openfoam") {
    card.classList.add("result-card-openfoam");
    const pressure = result.pressure || {};
    const velocity = (result.velocity && result.velocity.magnitude) || {};

    const header = document.createElement("div");
    header.className = "card-header card-header-cfd";
    header.textContent = "⚡ CFD Simulation Complete";
    card.appendChild(header);

    const metrics = document.createElement("div");
    metrics.className = "card-metrics";
    [
      ["P_min", fmt(pressure.min, 4)],
      ["P_mean", fmt(pressure.mean, 4)],
      ["P_max", fmt(pressure.max, 4)],
      ["V_mean", fmt(velocity.mean, 3)],
    ].forEach(([label, value]) =>
      metrics.appendChild(metricInline(label, value)),
    );
    card.appendChild(metrics);

    const barContainer = document.createElement("div");
    barContainer.className = "mini-bar-container";
    if (velocity.min != null) {
      barContainer.appendChild(
        renderMiniBar(velocity.min, velocity.mean, velocity.max),
      );
    }
    card.appendChild(barContainer);

    const footer = document.createElement("div");
    footer.className = "card-footer";
    footer.innerHTML =
      `${esc(result.cells ?? "?")} cells · ` +
      `<a href="/dashboard#${esc(jobId)}" class="artifact-link">View details →</a>`;
    card.appendChild(footer);
  } else {
    // freecad — static content only (no API-derived HTML)
    card.classList.add("result-card-freecad");
    card.innerHTML = `
      <div class="card-header card-header-freecad">📐 FEM — Not Implemented</div>
      <p class="card-body-dim">
        FreeCAD returns NOT_IMPLEMENTED in the Prototype.
        Full structural FEM is on the Production roadmap.
      </p>`;
  }

  return card;
}

function metricInline(label, value) {
  const item = document.createElement("div");
  item.className = "metric-inline";
  const l = document.createElement("span");
  l.className = "mi-label";
  l.textContent = label;
  const v = document.createElement("span");
  v.className = "mi-value";
  v.textContent = value;
  item.appendChild(l);
  item.appendChild(v);
  return item;
}

function fmt(value, digits) {
  return typeof value === "number" ? value.toFixed(digits) : "—";
}

// =============================================================
// CHAT — SEND (SSE streaming)
// =============================================================

async function sendChat() {
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;

  input.value = "";
  input.style.height = "auto";
  document.getElementById("btn-send").disabled = true;

  appendUserBubble(message);
  state.chatHistory.push({ role: "user", content: message });
  showThinking();

  const messagesEl = document.getElementById("chat-messages");
  let agentBubble = null;
  let agentText = "";
  let receivedResult = null;
  let receivedJobId = null;
  let receivedSolver = null;

  const finish = () => {
    document.getElementById("btn-send").disabled = false;
    input.focus();
  };

  try {
    const params = new URLSearchParams({
      message,
      history: JSON.stringify(state.chatHistory.slice(0, -1)),
      solver: state.activeSolver || "", // bind the agent to the chosen solver
      device: getDeviceId(), // scope the resulting job to this device's history
    });
    const eventSource = new EventSource(`/api/chat?${params.toString()}`);

    eventSource.onmessage = async (e) => {
      let data;
      try {
        data = JSON.parse(e.data);
      } catch {
        return;
      }

      if (data.type === "tool_start") {
        hideThinking();
        appendToolIndicator("start", data.name);
      } else if (data.type === "tool_end") {
        const rows = messagesEl.querySelectorAll(
          `.msg-tool[data-tool="${data.name}"][data-type="start"]`,
        );
        if (rows.length > 0) {
          const last = rows[rows.length - 1];
          last.dataset.type = "end";
          last.classList.remove("tool-start");
          last.classList.add("tool-end");
          last.textContent = `✓ ${data.name}`;
        }
      } else if (data.type === "token") {
        hideThinking();
        if (!agentBubble) {
          const { row, bubble } = createAgentRow();
          agentBubble = bubble;
          messagesEl.appendChild(row);
        }
        agentText += data.text;
        agentBubble.textContent = agentText;
        scrollMessages();
      } else if (data.type === "done") {
        eventSource.close();
        hideThinking();

        receivedResult = data.result;
        receivedJobId = data.job_id;
        // The agent is bound to the selected solver, so trust the active solver and
        // fall back to whatever the stream reported only if nothing was selected.
        receivedSolver = state.activeSolver || data.solver;

        const finalText = data.response || agentText;

        if (!agentBubble) {
          if (finalText) {
            appendAgentBubble(
              finalText,
              receivedResult,
              receivedJobId,
              receivedSolver,
            );
          }
        } else {
          // Replace the raw streamed text with clean rendered markdown now that
          // the message is complete, then attach the result card (if any).
          agentBubble.innerHTML = renderMarkdown(finalText);
          if (receivedResult && receivedJobId && receivedSolver) {
            agentBubble.appendChild(
              buildResultCard(receivedResult, receivedJobId, receivedSolver),
            );
          }
        }

        if (finalText) {
          state.chatHistory.push({ role: "assistant", content: finalText });
        }

        if (receivedJobId) {
          // Re-hydrate history from the backend (Redis) — the single source of truth — so the
          // job's authoritative status and the clean final interpretation (the text after the
          // last tool result, not the streamed "I'll set up…" preamble) populate the sidebar
          // and result panel alike. The inline result card rendered above is unaffected: it is
          // built directly from the streamed result, independent of state.jobs.
          await loadJobsFromBackend();
          renderJobHistory();
          // If the result panel is already open on this job, refresh it so the detail view
          // reflects the reconciled status/interpretation rather than a stale live entry.
          if (
            state.currentView === "result" &&
            state.selectedJobId === receivedJobId
          ) {
            renderJobResult(receivedJobId);
          }
        }

        scrollMessages();
        finish();
      } else if (data.type === "error") {
        eventSource.close();
        hideThinking();
        if (!agentBubble) {
          appendAgentBubble(`Error: ${data.message}`);
        } else {
          agentBubble.textContent += `\n\nError: ${data.message}`;
        }
        finish();
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      hideThinking();
      if (!agentBubble && !agentText) {
        appendAgentBubble("Connection error. Please try again.");
      }
      finish();
    };
  } catch (err) {
    hideThinking();
    appendAgentBubble(`Error: ${err.message}`);
    finish();
  }
}

// =============================================================
// JOB RESULT RENDERER (full result panel)
// =============================================================

function renderJobResult(jobId) {
  const job = state.jobs.find((j) => j.jobId === jobId);
  if (!job) return;

  const meta = SOLVER_META[job.solver] || SOLVER_META.lammps;

  const iconEl = document.getElementById("result-solver-icon");
  iconEl.textContent = meta.icon;
  iconEl.style.background = meta.bgColor;
  iconEl.style.color = meta.color;

  document.getElementById("result-sim-name").textContent =
    job.caseName || "Simulation";
  const solverTag = document.getElementById("result-solver-tag");
  solverTag.textContent = meta.name;
  solverTag.style.color = meta.color;
  document.getElementById("result-job-id").textContent =
    job.jobId.slice(0, 8) + "...";

  // Full simulation date + time, straight from the backend's created_at (job.submittedAt).
  const tsEl = document.getElementById("result-timestamp");
  if (tsEl) {
    tsEl.textContent = job.submittedAt
      ? "· " + new Date(job.submittedAt).toLocaleString()
      : "";
  }

  const badge = document.getElementById("result-status-badge");
  badge.textContent = job.status;
  badge.className = `status-badge status-${job.status}`;

  const content = document.getElementById("result-content");
  content.innerHTML = "";

  if (job.status === "PENDING" || job.status === "RUNNING") {
    content.innerHTML = `
      <div style="text-align:center; margin-top: 25vh">
        <div class="spinner"></div>
        <p style="color:var(--text-secondary); margin-top:16px; font-size:14px">
          Simulation running...
        </p>
      </div>`;
    setTimeout(() => {
      if (state.selectedJobId === jobId && state.currentView === "result") {
        fetchJobStatus(jobId).then(() => renderJobResult(jobId));
      }
    }, 3000);
    return;
  }

  if (job.status === "FAILED") {
    content.appendChild(buildFailedResult(job));
    return;
  }

  if (job.status === "COMPLETED") {
    const interp = buildInterpretation(job);
    if (interp) content.appendChild(interp);
    if (job.solver === "lammps") {
      content.appendChild(buildLAMMPSResult(job));
    } else if (job.solver === "openfoam") {
      content.appendChild(buildOpenFOAMResult(job));
    } else {
      const div = document.createElement("div");
      div.style.cssText = "padding:40px; color:var(--text-secondary)";
      div.textContent = `No result renderer for solver: ${job.solver}`;
      content.appendChild(div);
    }
  }
}

// The agent's natural-language summary of the run, stored when the job completed.
// Rendered with textContent (never innerHTML) since it is model-generated text.
function buildInterpretation(job) {
  if (!job.interpretation) return null;
  const sec = document.createElement("div");
  sec.className = "interpretation-section";
  const label = document.createElement("div");
  label.className = "section-label";
  label.textContent = "Agent Interpretation";
  const box = document.createElement("div");
  box.className = "interpretation-box";
  box.innerHTML = renderMarkdown(job.interpretation); // safe: escapes first
  sec.appendChild(label);
  sec.appendChild(box);
  return sec;
}

function buildFailedResult(job) {
  const err = job.error || {};
  const frag = document.createDocumentFragment();
  const card = document.createElement("div");
  card.className = "error-card";

  const header = document.createElement("div");
  header.className = "error-header";
  header.textContent = "⚠ Simulation Failed";
  card.appendChild(header);

  [
    ["Stage", err.stage || "unknown", false],
    ["Code", err.code || "—", true],
    ["Message", err.message || "—", false],
  ].forEach(([label, value, mono]) => {
    const row = document.createElement("div");
    row.className = "error-row";
    const l = document.createElement("span");
    l.className = "error-label";
    l.textContent = label;
    const v = document.createElement("span");
    if (mono) v.style.fontFamily = "monospace";
    v.textContent = value;
    row.appendChild(l);
    row.appendChild(v);
    card.appendChild(row);
  });

  frag.appendChild(card);
  frag.appendChild(buildRawJsonToggle(job.error, job.jobId));
  return frag;
}

function buildLAMMPSResult(job) {
  const result = job.result || {};
  const eq = result.equilibrium || {};
  const traj = result.trajectory || [];
  const frag = document.createDocumentFragment();

  const target = 1.5; // reduced-unit NVT target
  const dev = (v) =>
    typeof v === "number" ? Math.abs((v - target) / target) * 100 : null;

  // Metrics
  const metricsSection = document.createElement("div");
  metricsSection.innerHTML = `
    <div class="section-label">Equilibrium Properties</div>
    <div class="metrics-row" id="lammps-metrics"></div>`;
  const metricsRow = metricsSection.querySelector("#lammps-metrics");
  [
    ["Temperature", eq.temperature, "T* (reduced)", dev(eq.temperature)],
    ["Pressure", eq.pressure, "P* (reduced)", null],
    ["Total Energy", eq.total_energy, "E* (reduced)", null],
    ["Pot. Energy", eq.potential_energy, "E_pot (reduced)", null],
  ].forEach(([label, value, unit, deviation]) => {
    metricsRow.appendChild(metricCard(label, fmt(value, 3), unit, deviation));
  });
  frag.appendChild(metricsSection);

  // Trajectory chart
  if (traj.length > 0) {
    const chartSection = document.createElement("div");
    chartSection.style.marginTop = "28px";
    chartSection.innerHTML = `
      <div class="section-label">Thermodynamic Trajectory</div>
      <div class="chart-box" id="traj-chart-container"></div>`;
    frag.appendChild(chartSection);

    const deviation = dev(eq.temperature) ?? 0;
    const ok = deviation < 5;
    const banner = document.createElement("div");
    banner.className = ok ? "banner-success" : "banner-warning";
    banner.textContent =
      `${ok ? "✓" : "⚠"} System equilibrated to ${fmt(eq.temperature, 3)} ` +
      `(target ${target.toFixed(1)}, deviation ${deviation.toFixed(1)}%)`;
    chartSection.appendChild(banner);

    setTimeout(() => renderTrajectoryChart(traj, "traj-chart-container"), 0);
  }

  // Details grid
  const detailsSection = document.createElement("div");
  detailsSection.style.marginTop = "28px";
  detailsSection.innerHTML = `
    <div class="section-label">Simulation Details</div>
    <div class="details-grid">
      ${detailItem("Steps", result.steps ?? "—")}
      ${detailItem("Trajectory Points", result.trajectory_points ?? traj.length)}
      ${detailItem("Atoms", traj.length || "—")}
      ${detailItem("Temperature", fmt(eq.temperature, 3))}
      ${detailItem("Pressure", fmt(eq.pressure, 3))}
      ${detailItem("Status", "Equilibrated")}
    </div>`;
  frag.appendChild(detailsSection);

  frag.appendChild(buildRawJsonToggle(job.result, job.jobId));
  return frag;
}

function buildOpenFOAMResult(job) {
  const result = job.result || {};
  const pressure = result.pressure || {};
  const velocity = (result.velocity && result.velocity.magnitude) || {};
  const frag = document.createDocumentFragment();

  const metricsSection = document.createElement("div");
  metricsSection.innerHTML = `
    <div class="section-label">Flow Field Summary</div>
    <div class="metrics-row" id="cfd-metrics-p"></div>
    <div class="metrics-row" style="margin-top:12px" id="cfd-metrics-v"></div>`;

  const pRow = metricsSection.querySelector("#cfd-metrics-p");
  [
    ["P min", pressure.min, "m²/s²"],
    ["P mean", pressure.mean, "m²/s²"],
    ["P max", pressure.max, "m²/s²"],
  ].forEach(([label, value, unit]) => {
    pRow.appendChild(metricCard(label, fmt(value, 4), unit, null));
  });

  const vRow = metricsSection.querySelector("#cfd-metrics-v");
  [
    ["V min", velocity.min, "m/s"],
    ["V mean", velocity.mean, "m/s"],
    ["V max", velocity.max, "m/s"],
  ].forEach(([label, value, unit]) => {
    vRow.appendChild(metricCard(label, fmt(value, 3), unit, null));
  });
  frag.appendChild(metricsSection);

  const chartsSection = document.createElement("div");
  chartsSection.style.marginTop = "28px";
  chartsSection.innerHTML = `
    <div class="section-label">Field Visualisation</div>
    <div class="charts-row">
      <div class="chart-box" id="cfd-pressure-bar">
        <div style="font-size:12px; color:var(--text-secondary); margin-bottom:10px">
          Pressure Range (m²/s²)
        </div>
      </div>
      <div class="chart-box" id="cfd-velocity-bar">
        <div style="font-size:12px; color:var(--text-secondary); margin-bottom:10px">
          Velocity Magnitude (m/s)
        </div>
      </div>
    </div>
    <div class="physics-note">
      Full contour plots, streamlines, and vector fields can be explored in
      ParaView using the OpenFOAM reader plugin.
    </div>`;
  frag.appendChild(chartsSection);

  setTimeout(() => {
    if (pressure.min != null) {
      renderBarChart(
        pressure.min,
        pressure.mean,
        pressure.max,
        "cfd-pressure-bar",
      );
    }
    if (velocity.min != null) {
      renderBarChart(
        velocity.min,
        velocity.mean,
        velocity.max,
        "cfd-velocity-bar",
      );
    }
  }, 0);

  frag.appendChild(buildRawJsonToggle(job.result, job.jobId));
  return frag;
}

function metricCard(label, value, unit, deviation) {
  const card = document.createElement("div");
  card.className = "metric-card";
  let deltaHtml = "";
  if (typeof deviation === "number") {
    const cls = deviation < 5 ? "ok" : "warn";
    deltaHtml = `<div class="metric-delta ${cls}">±${deviation.toFixed(1)}% of target</div>`;
  }
  card.innerHTML = `
    <div class="metric-value">${esc(value)}</div>
    <div class="metric-label">${esc(label)}</div>
    <div class="metric-unit">${esc(unit)}</div>
    ${deltaHtml}`;
  return card;
}

function detailItem(label, value) {
  return `
    <div class="detail-item">
      <div class="detail-label">${esc(label)}</div>
      <div class="detail-value">${esc(value)}</div>
    </div>`;
}

function buildRawJsonToggle(data, jobId) {
  const div = document.createElement("div");
  div.style.marginTop = "16px";
  const btn = document.createElement("button");
  btn.className = "btn-toggle-json";
  btn.textContent = "Show raw JSON ▾";
  const pre = document.createElement("pre");
  pre.id = `raw-json-${jobId}`;
  pre.style.display = "none";
  pre.style.marginTop = "10px";
  pre.className = "raw-json-pre";
  let shown = false;
  btn.addEventListener("click", () => {
    shown = !shown;
    btn.textContent = shown ? "Hide raw JSON ▴" : "Show raw JSON ▾";
    pre.style.display = shown ? "block" : "none";
    if (shown && !pre.innerHTML) {
      pre.innerHTML = highlightJSON(JSON.stringify(data ?? {}, null, 2));
    }
  });
  div.appendChild(btn);
  div.appendChild(pre);
  return div;
}

// Escape text destined for innerHTML (labels/units/numbers/ids).
function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Minimal, dependency-free Markdown → HTML for the agent's result text.
// Safety: every piece of source text is HTML-escaped FIRST (via esc inside
// inline()), then a fixed set of tags is emitted — model output can never
// inject markup. Supports headings, bold/italic/code, bullet & numbered
// lists, tables, horizontal rules, and paragraphs. Good enough for the
// solver summaries; anything it doesn't recognise falls through as text.
function renderMarkdown(src) {
  if (!src) return "";

  const inline = (text) =>
    esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");

  const splitRow = (row) => {
    let s = row.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map((c) => c.trim());
  };

  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let para = [];
  let i = 0;

  const flushPara = () => {
    if (para.length) {
      out.push("<p>" + para.map(inline).join("<br>") + "</p>");
      para = [];
    }
  };

  while (i < lines.length) {
    const line = lines[i];
    const t = line.trim();

    if (!t) {
      flushPara();
      i++;
    } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(t)) {
      flushPara();
      out.push("<hr>");
      i++;
    } else if (/^#{1,6}\s+/.test(t)) {
      flushPara();
      const m = /^(#{1,6})\s+(.*)$/.exec(t);
      const tag = "h" + Math.min(m[1].length + 1, 6); // # -> h2 (keep bubbles modest)
      out.push(`<${tag}>${inline(m[2])}</${tag}>`);
      i++;
    } else if (
      t.includes("|") &&
      i + 1 < lines.length &&
      /-/.test(lines[i + 1]) &&
      /^\s*\|?[\s:|-]+$/.test(lines[i + 1])
    ) {
      // table: header row + |---|---| separator + body rows
      flushPara();
      const headers = splitRow(lines[i]);
      i += 2;
      const body = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        body.push(splitRow(lines[i]));
        i++;
      }
      let html = '<table class="md-table"><thead><tr>';
      html += headers.map((c) => `<th>${inline(c)}</th>`).join("");
      html += "</tr></thead><tbody>";
      for (const r of body) {
        html +=
          "<tr>" +
          headers.map((_, k) => `<td>${inline(r[k] || "")}</td>`).join("") +
          "</tr>";
      }
      html += "</tbody></table>";
      out.push(html);
    } else if (/^[-*+]\s+/.test(t)) {
      flushPara();
      const items = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i++;
      }
      out.push(
        "<ul>" + items.map((x) => `<li>${inline(x)}</li>`).join("") + "</ul>",
      );
    } else if (/^\d+\.\s+/.test(t)) {
      flushPara();
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      out.push(
        "<ol>" + items.map((x) => `<li>${inline(x)}</li>`).join("") + "</ol>",
      );
    } else {
      para.push(t);
      i++;
    }
  }
  flushPara();
  return out.join("\n");
}

// =============================================================
// SVG CHARTS
// =============================================================

function renderTrajectoryChart(trajectory, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const W = 560,
    H = 260;
  const pad = { top: 20, right: 20, bottom: 40, left: 50 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const steps = trajectory.map((r) => r.step);
  const temps = trajectory.map((r) => r.temp);
  const presses = trajectory.map((r) => r.press);
  const etotals = trajectory.map((r) => r.etotal);

  const xMin = Math.min(...steps);
  const xMax = Math.max(...steps);
  const xRange = xMax - xMin || 1;
  const allVals = [...temps, ...presses, ...etotals];
  const yMin = Math.min(...allVals);
  const yMax = Math.max(...allVals);
  const yPad = (yMax - yMin) * 0.1 || 1;
  const ySpan = yMax - yMin + 2 * yPad;

  const xScale = (s) => pad.left + ((s - xMin) / xRange) * plotW;
  const yScale = (v) => pad.top + plotH - ((v - (yMin - yPad)) / ySpan) * plotH;

  const toPolyline = (values) =>
    steps.map((s, i) => `${xScale(s)},${yScale(values[i])}`).join(" ");

  let gridLines = "";
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (plotH / 4) * i;
    gridLines += `<line x1="${pad.left}" y1="${y}" x2="${W - pad.right}" y2="${y}" stroke="#2d3148" stroke-width="1"/>`;
  }

  let xLabels = "";
  for (let i = 0; i <= 4; i++) {
    const step = xMin + (xRange / 4) * i;
    const x = xScale(step);
    xLabels += `<text x="${x}" y="${H - 8}" fill="#8b8fa8" font-size="10" text-anchor="middle">${Math.round(step)}</text>`;
  }

  let yLabels = "";
  for (let i = 0; i <= 4; i++) {
    const val = yMin - yPad + (ySpan / 4) * (4 - i);
    const y = pad.top + (plotH / 4) * i;
    yLabels += `<text x="${pad.left - 6}" y="${y + 4}" fill="#8b8fa8" font-size="10" text-anchor="end">${val.toFixed(1)}</text>`;
  }

  const dots = (values, color) =>
    steps
      .map(
        (s, i) =>
          `<circle cx="${xScale(s)}" cy="${yScale(values[i])}" r="3" fill="${color}">` +
          `<title>Step ${s}: ${values[i].toFixed(3)}</title></circle>`,
      )
      .join("");

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">
    ${gridLines}
    <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + plotH}" stroke="#2d3148" stroke-width="1"/>
    <line x1="${pad.left}" y1="${pad.top + plotH}" x2="${W - pad.right}" y2="${pad.top + plotH}" stroke="#2d3148" stroke-width="1"/>
    ${xLabels}${yLabels}
    <polyline points="${toPolyline(temps)}" fill="none" stroke="#4f8ef7" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <polyline points="${toPolyline(presses)}" fill="none" stroke="#f7a44f" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <polyline points="${toPolyline(etotals)}" fill="none" stroke="#2dd4a0" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    ${dots(temps, "#4f8ef7")}
    ${dots(presses, "#f7a44f")}
    ${dots(etotals, "#2dd4a0")}
    <rect x="${pad.left + 10}" y="${pad.top + 6}" width="10" height="3" fill="#4f8ef7" rx="1"/>
    <text x="${pad.left + 24}" y="${pad.top + 10}" fill="#8b8fa8" font-size="10">Temperature</text>
    <rect x="${pad.left + 100}" y="${pad.top + 6}" width="10" height="3" fill="#f7a44f" rx="1"/>
    <text x="${pad.left + 114}" y="${pad.top + 10}" fill="#8b8fa8" font-size="10">Pressure</text>
    <rect x="${pad.left + 175}" y="${pad.top + 6}" width="10" height="3" fill="#2dd4a0" rx="1"/>
    <text x="${pad.left + 189}" y="${pad.top + 10}" fill="#8b8fa8" font-size="10">Total Energy</text>
  </svg>`;
}

function renderSparkline(values, color) {
  const W = 300,
    H = 50;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xStep = W / (values.length - 1);
  const points = values
    .map((v, i) => `${i * xStep},${H - ((v - min) / range) * (H - 4) - 2}`)
    .join(" ");

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.style.cssText = "width:100%; height:50px; display:block";

  const polyline = document.createElementNS(
    "http://www.w3.org/2000/svg",
    "polyline",
  );
  polyline.setAttribute("points", points);
  polyline.setAttribute("fill", "none");
  polyline.setAttribute("stroke", color);
  polyline.setAttribute("stroke-width", "2");
  polyline.setAttribute("stroke-linejoin", "round");
  polyline.setAttribute("stroke-linecap", "round");
  svg.appendChild(polyline);

  return svg;
}

// Small inline min→mean→max bar for the chat result card.
function renderMiniBar(min, mean, max) {
  const wrap = document.createElement("div");
  renderBarChart(min, mean, max, null, wrap);
  return wrap;
}

function renderBarChart(min, mean, max, containerId, targetEl) {
  const container = targetEl || document.getElementById(containerId);
  if (!container) return;

  const W = 400,
    H = 50;
  const pad = { left: 60, right: 60, top: 10, bottom: 24 };
  const plotW = W - pad.left - pad.right;

  const range = max - min || 1;
  const meanX = pad.left + ((mean - min) / range) * plotW;

  const svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">
    <rect x="${pad.left}" y="${pad.top}" width="${plotW}" height="16" fill="#2d3148" rx="3"/>
    <rect x="${pad.left}" y="${pad.top}" width="${Math.max(0, meanX - pad.left)}" height="16" fill="#4f8ef7" rx="3"/>
    <line x1="${meanX}" y1="${pad.top - 2}" x2="${meanX}" y2="${pad.top + 18}" stroke="white" stroke-width="2"/>
    <text x="${pad.left}" y="${H - 4}" fill="#8b8fa8" font-size="9" text-anchor="middle">${min.toFixed(3)}</text>
    <text x="${meanX}" y="${H - 4}" fill="#e8eaf0" font-size="9" text-anchor="middle">${mean.toFixed(3)}</text>
    <text x="${W - pad.right}" y="${H - 4}" fill="#8b8fa8" font-size="9" text-anchor="middle">${max.toFixed(3)}</text>
  </svg>`;

  container.innerHTML += svg;
}

// =============================================================
// JOB HISTORY
// =============================================================

async function fetchJobStatus(jobId) {
  try {
    const res = await fetch(`/jobs/${jobId}`);
    if (!res.ok) return null;
    const data = await res.json();
    const job = state.jobs.find((j) => j.jobId === jobId);
    if (job) {
      if (data.status) job.status = data.status;
      // Only overwrite a result/error we already hold if the server sends one.
      if (data.result != null) job.result = data.result;
      if (data.error != null) job.error = data.error;
      saveJobs();
    }
    return data;
  } catch {
    return null;
  }
}

function renderJobHistory() {
  const list = document.getElementById("job-list");
  if (!state.jobs.length) {
    list.innerHTML = `<div class="job-list-empty">No simulations yet.<br>Select a solver to begin.</div>`;
    return;
  }

  list.innerHTML = "";
  state.jobs.forEach((job) => {
    const meta = SOLVER_META[job.solver] || SOLVER_META.lammps;
    const card = document.createElement("div");
    card.className =
      "job-card" + (job.jobId === state.selectedJobId ? " selected" : "");

    const icon = document.createElement("span");
    icon.className = "job-icon";
    icon.textContent = meta.icon;

    const col = document.createElement("div");
    col.className = "job-meta-col";

    // Title line: the simulation's case name when we have it, else the short job id.
    const title = document.createElement("span");
    title.className = "job-id-text";
    title.textContent = job.caseName || job.jobId.slice(0, 8) + "...";
    title.title = job.caseName || job.jobId;

    // Subtitle line: solver tag (colour-coded) + time, so the solver is always visible.
    const sub = document.createElement("span");
    sub.className = "job-sub";
    const solverTag = document.createElement("span");
    solverTag.className = "job-solver";
    solverTag.textContent = meta.name;
    solverTag.style.color = meta.color;
    const time = document.createElement("span");
    time.className = "job-time";
    time.textContent = new Date(job.submittedAt).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    sub.appendChild(solverTag);
    sub.appendChild(time);

    col.appendChild(title);
    col.appendChild(sub);

    const badge = document.createElement("span");
    badge.className = `status-badge status-${job.status}`;
    badge.textContent = job.status;

    card.appendChild(icon);
    card.appendChild(col);
    card.appendChild(badge);
    card.addEventListener("click", () => showResult(job.jobId));
    list.appendChild(card);
  });
}

// The backend (Redis) is the single source of truth for job history. The client holds an
// in-memory copy for the current view only; it is never persisted, so a cleared backend
// always yields an empty history (no stale client cache to deceive).
function saveJobs() {
  /* intentionally no-op — history is not persisted client-side; see loadJobsFromBackend */
}

// Opaque per-device id — an identifier, NOT data — so the backend can scope history to this
// device. Stored in localStorage so it is stable across sessions; the actual job data is
// always fetched fresh from the backend, filtered by this id.
function getDeviceId() {
  try {
    let id = localStorage.getItem("Solver-MCP-device-id");
    if (!id) {
      id =
        (window.crypto && crypto.randomUUID && crypto.randomUUID()) ||
        Date.now().toString(36) + Math.random().toString(36).slice(2);
      localStorage.setItem("Solver-MCP-device-id", id);
    }
    return id;
  } catch (_) {
    return "anonymous";
  }
}

// Hydrate the job list from the backend, scoped to this device. This is the ONLY source of
// history — there is no client-side persistence to fall back on.
async function loadJobsFromBackend() {
  try {
    const res = await fetch(
      `/api/jobs?owner=${encodeURIComponent(getDeviceId())}`,
    );
    if (!res.ok) return;
    const data = await res.json();
    state.jobs = (data.jobs || []).map((j) => ({
      jobId: j.job_id,
      solver: j.solver,
      caseName: j.case_name,
      status: j.status,
      result: j.result,
      error: j.error,
      interpretation: j.interpretation,
      submittedAt: j.created_at || new Date().toISOString(),
    }));
  } catch (_) {
    /* backend unreachable — leave history empty rather than show stale data */
  }
}

// =============================================================
// JSON HIGHLIGHTER
// =============================================================

function highlightJSON(json) {
  return json
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (match) => {
        let cls = "json-number";
        if (/^"/.test(match)) {
          cls = /:$/.test(match) ? "json-key" : "json-string";
        } else if (/true|false/.test(match)) {
          cls = "json-bool";
        } else if (/null/.test(match)) {
          cls = "json-null";
        }
        return `<span class="${cls}">${match}</span>`;
      },
    );
}

// =============================================================
// INIT
// =============================================================

// Select a solver from a sidebar row or a quick-start chip: sync the active
// row highlight, then open the chat view for that solver.
function selectSolver(solver) {
  document.querySelectorAll(".solver-row").forEach((r) => {
    r.classList.toggle("active", r.dataset.solver === solver);
  });
  showChat(solver);
}

document.addEventListener("DOMContentLoaded", async () => {
  // History is sourced from the backend (Redis), scoped to this device — never from client
  // storage, so a cleared backend shows an empty history rather than a stale cache.
  await loadJobsFromBackend();

  renderJobHistory();
  showView("faq");

  // Solver rows
  document.querySelectorAll(".solver-row").forEach((row) => {
    row.addEventListener("click", () => selectSolver(row.dataset.solver));
  });

  // Suggestion chips (FAQ quick-start)
  document.querySelectorAll(".suggestion-chip").forEach((chip) => {
    chip.addEventListener("click", () => selectSolver(chip.dataset.solver));
  });

  // Back buttons
  document.getElementById("btn-back-chat").addEventListener("click", showFAQ);
  document.getElementById("btn-back-result").addEventListener("click", () => {
    if (state.activeSolver) showChat(state.activeSolver);
    else showFAQ();
  });

  // Send + textarea
  document.getElementById("btn-send").addEventListener("click", sendChat);
  const input = document.getElementById("chat-input");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });

  // Refresh job statuses
  document
    .getElementById("btn-refresh-jobs")
    .addEventListener("click", async () => {
      // Reconcile with the backend: picks up new jobs and drops any the backend no longer
      // has (history is backend truth, scoped to this device).
      await loadJobsFromBackend();
      renderJobHistory();
      if (state.currentView === "result" && state.selectedJobId) {
        renderJobResult(state.selectedJobId);
      }
    });

  // Copy job ID
  document.getElementById("btn-copy-id").addEventListener("click", () => {
    if (!state.selectedJobId) return;
    navigator.clipboard?.writeText(state.selectedJobId);
    const btn = document.getElementById("btn-copy-id");
    btn.textContent = "Copied!";
    setTimeout(() => (btn.textContent = "Copy ID"), 1500);
  });

  // API docs dropdown
  const docsBtn = document.getElementById("btn-api-docs");
  const docsMenu = document.getElementById("api-docs-menu");
  if (docsBtn && docsMenu) {
    docsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      docsMenu.classList.toggle("open");
    });
    document.addEventListener("click", () => docsMenu.classList.remove("open"));
  }

  // Runtime-only styles: JSON highlight colours + pulse keyframe.
  const style = document.createElement("style");
  style.textContent = `
    .json-key    { color: #8b8fa8; }
    .json-string { color: #2dd4a0; }
    .json-number { color: #4f8ef7; }
    .json-bool   { color: #f7a44f; }
    .json-null   { color: #f7a44f; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  `;
  document.head.appendChild(style);
});
