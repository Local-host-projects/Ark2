/* Planner — frontend application logic (vanilla JS). */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ *
   * Utilities
   * ------------------------------------------------------------------ */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function uid(p) { return (p || "x") + Math.random().toString(36).slice(2, 8); }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (m) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[m]));
  }

  let toastTimer = null;
  function toast(msg, kind) {
    const el = $("#toast");
    el.textContent = msg;
    el.className = kind ? "show " + kind : "show";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = ""), 2600);
  }

  const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];
  const COLTYPES = ["int", "bigint", "string", "text", "uuid", "bool", "float", "decimal", "datetime", "date", "json", "enum"];
  const KINDS = ["one-to-many", "one-to-one", "many-to-many"];

  const LEVEL_DESC = [
    "",
    "Bare canvas. No tips, no help cards — you already know what you are doing.",
    "Moderate guidance: hints on forms, a connecting shortcut, rail explanations.",
    "More helping text, mention insert buttons and guided empty states.",
    "Maximum assistance: inline tutorials and step-by-step cards everywhere.",
  ];

  /* ------------------------------------------------------------------ *
   * State
   * ------------------------------------------------------------------ */
  const LS_STATE = "planner.state.v1";
  const LS_COMPILED = "planner.compiled.v1";

  function defaultState() {
    return {
      project: {
        name: "My Backend", description: "", architecture: "monolithic",
        language: "python", level: 2,
      },
      tables: [],
      relations: [],
      middleware: [],
      routes: [],
      jobs: [],
      feedback: [],
    };
  }

  let state = defaultState();
  let compiled = null;

  function load() {
    try {
      const raw = localStorage.getItem(LS_STATE);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      state = Object.assign(defaultState(), parsed);
      state.project = Object.assign(defaultState().project, parsed.project || {});
      state.tables = Array.isArray(parsed.tables) ? parsed.tables : [];
      state.relations = Array.isArray(parsed.relations) ? parsed.relations : [];
      state.middleware = Array.isArray(parsed.middleware) ? parsed.middleware : [];
      state.routes = Array.isArray(parsed.routes) ? parsed.routes : [];
      state.jobs = Array.isArray(parsed.jobs) ? parsed.jobs : [];
      state.feedback = Array.isArray(parsed.feedback) ? parsed.feedback : [];
    } catch (e) { state = defaultState(); }
    try {
      const c = localStorage.getItem(LS_COMPILED);
      if (c) compiled = JSON.parse(c);
    } catch (e) { compiled = null; }
  }

  function save() {
    try { localStorage.setItem(LS_STATE, JSON.stringify(state)); } catch (e) {}
    if (compiled) {
      try { localStorage.setItem(LS_COMPILED, JSON.stringify(compiled)); } catch (e) {}
    }
  }

  const tableById = (id) => state.tables.find((t) => t.id === id);
  const routeById = (id) => state.routes.find((r) => r.id === id);
  const colById = (t, cid) => (t ? t.columns.find((c) => c.id === cid) : null);

  /* ------------------------------------------------------------------ *
   * Runtime UI state (not persisted)
   * ------------------------------------------------------------------ */
  const U = {
    screen: "launch",
    tab: "design",
    selTable: null,
    selRel: null,
    selRoute: null,
    selMW: null,
    selJob: null,
    expandCol: null,
    connectFrom: null,
    connectMode: false,
    expTab: "prompt",
    launchArch: "monolithic",
  };

  /* ------------------------------------------------------------------ *
   * Levels & settings
   * ------------------------------------------------------------------ */
  function setLevel(l) {
    l = Math.max(1, Math.min(4, Math.round(l)));
    state.project.level = l;
    document.body.dataset.level = String(l);
    const s1 = $("#p-level"), s2 = $("#top-level");
    if (s1) s1.value = l;
    if (s2) s2.value = l;
    const v = $("#top-level-val");
    if (v) v.textContent = l;
    const d = $("#level-desc");
    if (d) d.textContent = LEVEL_DESC[l];
    applyLevelVisibility();
  }

  function applyLevelVisibility() {
    $$("[data-lvl]").forEach((el) => {
      el.classList.toggle("hidden", Number(el.dataset.lvl) > state.project.level);
    });
  }

  /* ------------------------------------------------------------------ *
   * Screen switching
   * ------------------------------------------------------------------ */
  function show(screen) {
    U.screen = screen;
    ["launch", "builder", "export"].forEach((s) => {
      $("#screen-" + s).classList.toggle("hidden", s !== screen);
    });
    if (screen === "builder") { renderAll(); bindCanvasEvents(); }
    if (screen === "export") renderExportUI();
    window.scrollTo(0, 0);
  }

  function renderAll() {
    renderTopbar();
    renderRailCounts();
    renderContent();
    renderInspector();
    applyLevelVisibility();
  }

  function renderTopbar() {
    $("#project-name").textContent = state.project.name || "Untitled";
    $("#export-title").textContent = state.project.name || "Untitled";
    setLevel(state.project.level);
  }

  function renderRailCounts() {
    $("#count-tables").textContent = state.tables.length;
    $("#count-routes").textContent = state.routes.length;
    $("#count-mw").textContent = state.middleware.length;
    $("#count-jobs").textContent = state.jobs.length;
    $("#count-feedback").textContent = state.feedback.length;
    $$("#rail .nav-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.tab === U.tab);
    });
  }

  /* ------------------------------------------------------------------ *
   * DESIGN TAB — canvas
   * ------------------------------------------------------------------ */
  function colConstraints(c) {
    const bits = [];
    if (c.pk) bits.push("PK");
    if (c.auto) bits.push("AUTO");
    if (!c.nullable) bits.push("NN");
    if (c.unique) bits.push("UQ");
    return bits.join(" \u00B7 ");
  }

  function tableCardHTML(t) {
    const sel = U.selTable === t.id ? " selected" : "";
    const src = U.connectFrom && U.connectFrom.tableId === t.id ? " connect-source" : "";
    const pkCount = t.columns.filter((c) => c.pk).length;
    let rows;
    if (t.columns.length === 0) {
      rows = '<div class="empty-cols">no columns yet — click the table to add</div>';
    } else {
      rows = t.columns.map((c) => {
        const cc = colConstraints(c);
        return (
          '<div class="tc-col" data-table="' + t.id + '" data-col="' + c.id + '" title="click to link">' +
          '<span class="anchor"></span>' +
          '<span class="c-name">' + esc(c.name) + "</span>" +
          '<span class="c-type">' + esc(c.type) + "</span>" +
          (cc ? '<span class="c-constraints">' + esc(cc) + "</span>" : "") +
          "</div>"
        );
      }).join("");
    }
    return (
      '<div class="table-card' + sel + src + '" data-table="' + t.id + '" style="left:' + (t.x || 80) + "px;top:" + (t.y || 80) + 'px">' +
      '<div class="tc-head" data-table="' + t.id + '">' +
      '<span class="tc-name">' + esc(t.name) + "</span>" +
      (pkCount ? '<span class="pk-badge">' + pkCount + " PK</span>" : "") +
      "</div>" +
      (t.notes ? '<div class="tc-notes">' + esc(t.notes) + "</div>" : "") +
      rows +
      "</div>"
    );
  }

  function renderCanvas() {
    const content = $("#content");
    if (!content) return;
    let html = '<div class="canvas-wrap">';
    const bars = [];
    if (U.connectFrom) {
      bars.push(
        '<div class="connect-bar">Linking… click a column on another table <span class="kbd">Esc</span> cancels</div>'
      );
    } else if (U.connectMode) {
      bars.push(
        '<div class="connect-bar">Connection mode — click a source column, then a target column <span class="kbd">Esc</span> exits</div>'
      );
    }
    html += bars.join("");
    html += '<div class="canvas-inner" id="canvas-inner">';
    html += '<svg class="edges" id="edges" width="2400" height="1500"></svg>';
    html += state.tables.map(tableCardHTML).join("");
    html += "</div>";
    if (state.tables.length === 0) {
      html +=
        '<div class="canvas-empty"><div class="box">' +
        '<div style="font-weight:700;font-size:15px;margin-bottom:6px;">Start your data model</div>' +
        '<div class="hint" style="margin-bottom:12px;">Add a table, give it columns, then click column-to-column to draw relations.</div>' +
        '<button class="btn btn-primary" onclick="P.newTable()">+ New table</button> ' +
        '<button class="btn" onclick="P.loadSample()">Load example</button>' +
        "</div></div>";
    }
    html += "</div>";
    content.innerHTML = html;
    renderEdges();
    bindCanvasEvents();
  }

  function renderEdges() {
    const inner = $("#canvas-inner");
    const svg = $("#edges");
    if (!inner || !svg) return;
    const iRect = inner.getBoundingClientRect();
    const wrapped = state.relations.map((r) => {
      const a = inner.querySelector('.table-card[data-table="' + r.fromTable + '"] .tc-col[data-col="' + r.fromColumn + '"] .anchor');
      const b = inner.querySelector('.table-card[data-table="' + r.toTable + '"] .tc-col[data-col="' + r.toColumn + '"] .anchor');
      if (!a || !b) return null;
      const aRect = a.getBoundingClientRect();
      const bRect = b.getBoundingClientRect();
      const ax = aRect.left - iRect.left + aRect.width / 2;
      const ay = aRect.top - iRect.top + aRect.height / 2;
      const bx = bRect.left - iRect.left + bRect.width / 2;
      const by = bRect.top - iRect.top + bRect.height / 2;
      const dir = bx > ax ? 1 : -1;
      const off = Math.min(70, Math.abs(bx - ax) / 2);
      const cx = ax + dir * Math.max(24, off);
      const dx = bx - dir * Math.max(24, off);
      const mid = { x: (ax + bx) / 2, y: (ay + by) / 2 };
      const warn = r.fromColumn === r.toColumn ? " warn" : "";
      const label = (r.label && r.label.length <= 16 ? r.label : r.kind || "link");
      return {
        r,
        d:
          "M" + ax.toFixed(1) + " " + ay.toFixed(1) +
          " C" + cx.toFixed(1) + " " + ay.toFixed(1) +
          ", " + dx.toFixed(1) + " " + by.toFixed(1) +
          ", " + bx.toFixed(1) + " " + by.toFixed(1),
        mid, warn, label,
      };
    }).filter(Boolean);

    svg.innerHTML =
      wrapped.map((w) => {
        const wl = Math.max(46, w.label.length * 5.6 + 14);
        const x = w.mid.x - wl / 2;
        const y = w.mid.y - 10;
        const on = 'onclick="P.selectRel(\'' + w.r.id + '\', event)"';
        return (
          '<path class="edge-path' + w.warn + '" d="' + w.d + '"/>' +
          '<g class="edge-label-wrap" ' + on + ">" +
          '<rect class="edge-label-bg" width="' + wl.toFixed(1) + '" height="18" rx="8" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '"/>' +
          '<text class="edge-label" x="' + w.mid.x.toFixed(1) + '" y="' + (w.mid.y + 3).toFixed(1) + '">' + esc(w.label) + "</text>" +
          "</g>"
        );
      }).join("");
  }

  let _drag = null;

  function bindCanvasEvents() {
    const inner = $("#canvas-inner");
    if (!inner) return;

    inner.removeEventListener("pointerdown", onCanvasDown);
    inner.addEventListener("pointerdown", onCanvasDown);

    inner.removeEventListener("click", onCanvasClick);
    inner.addEventListener("click", onCanvasClick);
  }

  function onCanvasDown(e) {
    const head = e.target.closest(".tc-head");
    if (!head) return;
    _drag = {
      tid: head.dataset.table,
      dx: e.clientX,
      dy: e.clientY,
      startX: null,
      startY: null,
      moved: false,
    };
  }

  function onDocPointerMove(e) {
    if (!_drag) return;
    const t = tableById(_drag.tid);
    if (!t) { _drag = null; return; }
    if (_drag.startX == null) { _drag.startX = _drag.dx; _drag.startY = _drag.dy; }
    _drag.moved = _drag.moved || Math.abs(e.clientX - _drag.startX) + Math.abs(e.clientY - _drag.startY) > 4;
    t.x = Math.max(0, Math.round(t.x + (e.clientX - _drag.dx)));
    t.y = Math.max(0, Math.round(t.y + (e.clientY - _drag.dy)));
    _drag.dx = e.clientX;
    _drag.dy = e.clientY;
    const el = $('.table-card[data-table="' + t.id + '"]');
    if (el) { el.style.left = t.x + "px"; el.style.top = t.y + "px"; }
    renderEdges();
  }

  function onDocPointerUp() {
    if (!_drag) return;
    if (_drag.moved) save();
    _drag = null;
  }

  function onCanvasClick(e) {
    if (_drag && _drag.moved) return;
    const colEl = e.target.closest(".tc-col");
    if (colEl) {
      P.pickColumn(colEl.dataset.table, colEl.dataset.col);
      return;
    }
    if (e.target.closest(".table-card")) {
      const card = e.target.closest(".table-card");
      const t = tableById(card.dataset.table);
      if (t) {
        if (U.connectFrom && U.connectFrom.tableId !== t.id) return;
        U.selTable = t.id;
        U.selRel = null;
        U.connectFrom = null;
        U.connectMode = false;
        renderInspector();
        renderCanvas();
      }
      return;
    }
    if (e.target.closest(".canvas-inner")) {
      U.selTable = null;
      U.selRel = null;
      U.connectFrom = null;
      renderInspector();
      renderCanvas();
    }
  }

  function inner() { return $("#canvas-inner"); }

  function arrangeTables() {
    state.tables.forEach((t, i) => {
      t.x = 80 + (i % 4) * 320;
      t.y = 80 + Math.floor(i / 4) * 360;
    });
    save();
    renderCanvas();
  }

  /* ------------------------------------------------------------------ *
   * DESIGN TAB — inspector
   * ------------------------------------------------------------------ */
  function renderInspector() {
    const ins = $("#inspector");
    if (!ins) return;
    let html = "";
    if (U.tab === "design") html = designInspector();
    else if (U.tab === "routes") html = routesInspector();
    else if (U.tab === "middleware") html = mwInspector();
    else if (U.tab === "jobs") html = jobsInspector();
    else if (U.tab === "feedback") html = feedbackInspector();
    ins.innerHTML = html;
    bindMentionTextareas();
  }

  function designInspector() {
    if (U.selRel) return relEditor();
    const t = tableById(U.selTable);
    if (!t) {
      return (
        '<div class="insp-title">Data model</div>' +
        '<div class="insp-sub">Click a table on the canvas to edit its columns.</div>' +
        '<div class="help" data-lvl="2">Drag table headers to move them. Click a column, then a column on another table, to draw a relation. Click an edge label to edit it.</div>' +
        '<div style="display:grid;gap:8px;margin-top:14px;">' +
        '<button class="btn btn-primary btn-sm" onclick="P.newTable()">+ New table</button>' +
        '<button class="btn btn-sm" onclick="P.arrange()">↔ Auto arrange</button>' +
        '<button class="btn btn-sm" onclick="P.loadSample()">Load example design</button>' +
        '<button class="btn btn-danger btn-sm" onclick="P.clearAll()">Clear everything</button>' +
        "</div>" +
        '<div class="help" data-lvl="3" style="margin-top:14px;">' +
        "<b>Connection mode</b> is for precision. If the canvas gets crowded, use Auto arrange to lay tables out in a grid again.</div>"
      );
    }
    const pkRow =
      '<div class="field-label-group"><label class="lbl">Table name</label>' +
      '<input type="text" value="' + esc(t.name) + '" onchange="P.tableName(this.value)"/></div>';
    const notesRow =
      '<label class="lbl">Notes</label>' +
      '<textarea rows="2" placeholder="what does this table hold?" onchange="P.tableNotes(this.value)">' + esc(t.notes) + "</textarea>";

    let cols =
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-top:14px;">' +
      '<label class="lbl" style="margin:0;">Columns</label>' +
      '<span class="count">' + t.columns.length + "</span></div>";
    if (t.columns.length === 0) {
      cols += '<div class="hint">No columns yet — add the first one below.</div>';
    } else {
      cols += t.columns.map(colRowHTML).join("");
    }

    const exp = U.expandCol ? columnEditExtras(U.expandCol) : "";
    const typeOpts = COLTYPES.map((c) => "<option>" + c + "</option>").join("");
    const addForm =
      '<div style="margin-top:10px;border-top:1px solid var(--border);padding-top:10px;">' +
      '<label class="lbl">Add column</label>' +
      '<input id="new-col-name" type="text" placeholder="column name, e.g. email" />' +
      '<div class="field-grid" style="margin-top:8px;"><select id="new-col-type">' + typeOpts + "</select>" +
      '<input id="new-col-def" type="text" placeholder="default (optional)" /></div>' +
      '<div style="display:flex;gap:14px;margin-top:8px;flex-wrap:wrap;">' +
      checkbox("new-col-pk", "primary key") +
      checkbox("new-col-auto", "auto-increment") +
      checkbox("new-col-nn", "not null") +
      checkbox("new-col-uq", "unique") +
      "</div>" +
      '<button class="btn btn-primary btn-sm" style="margin-top:9px;" onclick="P.addColumn()">+ Add column</button>' +
      "</div>";

    return (
      '<div class="insp-header"><span class="insp-title">Table</span>' +
      '<button class="btn btn-danger btn-xs" onclick="P.deleteTable()">Delete</button></div>' +
      pkRow + notesRow + cols + exp + addForm
    );
  }

  function checkbox(id, label) {
    return '<label class="check-row"><input type="checkbox" id="' + id + '"/>' + label + "</label>";
  }

  function colRowHTML(c) {
    const t = tableById(U.selTable);
    const open = U.expandCol === c.id ? " background:var(--accent-dim);" : "";
    const typeOps = COLTYPES.map((o) =>
      "<option" + (o === c.type ? " selected" : "") + ">" + o + "</option>"
    ).join("");
    return (
      '<div class="col-row" style="' + open + '">' +
      '<button class="icon-btn" onclick="P.toggleExpandCol(\'' + c.id + '\')">' + (U.expandCol === c.id ? "\u25BE" : "\u25B8") + "</button>" +
      "<input " + "style='width:92px;' type='text' value='" + esc(c.name) + "' onchange='P.colName(\"" + c.id + "\",this.value)'/>" +
      "<select style='width:98px;' onchange='P.colType(\"" + c.id + "\",this.value)'>" + typeOps + "</select>" +
      '<span class="c-extra" style="flex:1;">' + esc(colConstraints(c) || "\u00A0") + "</span>" +
      '<button class="icon-btn" title="delete" onclick="P.deleteColumn(\'' + c.id + '\')">\u2715</button>' +
      "</div>" +
      (U.expandCol === c.id ? columnEditExtras(c.id) : "")
    );
  }

  function columnEditExtras(cid) {
    const t = tableById(U.selTable);
    const c = colById(t, cid);
    if (!c) return "";
    return (
      '<div class="help" style="margin:0 0 8px;display:grid;gap:6px;">' +
      '<div style="display:flex;gap:12px;flex-wrap:wrap;">' +
      checkbox("f-pk" , "PK") + checkbox("f-auto", "auto") +
      checkbox("f-nn", "not null") + checkbox("f-uq", "unique") +
      "</div>" +
      '<input type="text" placeholder="default value" value="' + esc(c.default || "") + '" onchange="P.colDefault(\'' + cid + '\',this.value)"/>' +
      '<textarea rows="2" placeholder="column notes" onchange="P.colNotes(\'' + cid + '\',this.value)">' + esc(c.notes || "") + "</textarea>" +
      '<div>' +
      '<button class="btn btn-xs" onclick="P.reflectFlags(\'' + cid + '\')">Apply flags</button> ' +
      '<button class="btn btn-xs btn-ghost" onclick="P.toggleExpandCol(\'' + cid + '\')">Close</button>' +
      "</div></div>"
    );
  }

  function relEditor() {
    const r = state.relations.find((x) => x.id === U.selRel);
    if (!r) return '<div class="insp-sub">Relation not found.</div>';
    const tf = tableById(r.fromTable), tt = tableById(r.toTable);
    const cf = colById(tf, r.fromColumn), ct = colById(tt, r.toColumn);
    const kindOpts = KINDS.map((k) => "<option" + (k === r.kind ? " selected" : "") + ">" + k + "</option>").join("");
    return (
      '<div class="insp-header"><span class="insp-title">Relation</span>' +
      '<button class="btn btn-danger btn-xs" onclick="P.deleteRel()">Delete</button></div>' +
      '<div class="insp-sub" style="margin-top:9px;">A relation becomes a foreign key in the generated schema.</div>' +
      '<div class="mono" style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:9px;font-size:12.5px;">' +
      esc((tf && tf.name) || "?") + " (" + esc((cf && cf.name) || "?") + ") " +
      "&rarr; " + esc((tt && tt.name) || "?") + " (" + esc((ct && ct.name) || "?") + ")" +
      "</div>" +
      '<label class="lbl">Cardinality</label>' +
      '<select onchange="P.relKind(this.value)">' + kindOpts + "</select>" +
      '<label class="lbl">Short label (shown on the edge)</label>' +
      '<input type="text" value="' + esc(r.label || "") + '" placeholder="e.g. belongs to" onchange="P.relLabel(this.value)"/>' +
      '<div class="help" data-lvl="3">The label is decorative on the canvas but is included in the compiled spec, so name it meaningfully.</div>'
    );
  }

  /* ------------------------------------------------------------------ *
   * ROUTES TAB
   * ------------------------------------------------------------------ */
  function renderRoutes() {
    const c = $("#content");
    let list = "";
    if (state.routes.length === 0) {
      list = '<div class="hint" style="margin:14px 0 10px;">No routes yet. Define the endpoints your backend will expose.</div>';
    } else {
      list = state.routes.map((rt) => {
        const t = tableById(rt.table);
        const mws = rt.middleware
          .map((id) => state.middleware.find((m) => m.id === id))
          .filter(Boolean)
          .map((m) => '<span class="mw-badge">' + esc(m.name) + "</span>")
          .join("");
        const sel = U.selRoute === rt.id ? " selected" : "";
        return (
          '<div class="item-card' + sel + '" onclick="P.openRoute(\'' + rt.id + '\')">' +
          '<div class="method m-' + rt.method + '">' + esc(rt.method) + "</div>" +
          "<div><div class='path'>" + esc(rt.path) + "</div>" +
          '<div class="summary">' + esc(rt.summary || (t ? "works on " + t.name : "")) + "</div></div>" +
          '<div class="meta">' + (t ? esc(t.name) : "") +
          (rt.functionBatches.length ? " · " + rt.functionBatches.length + " batches" : "") +
          '<br/>' + mws + "</div>" +
          "</div>"
        );
      }).join("");
    }
    c.innerHTML =
      '<div class="list-view">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">' +
      "<h2 style='margin:0;font-size:16px;'>Endpoints</h2>" +
      '<button class="btn btn-primary btn-sm" onclick="P.newRoute()">+ New route</button></div>' +
      '<div class="help" data-lvl="2" style="margin-bottom:10px;">Each route pairs a URL with natural-language execution. You can split that text into named "function batches" — the compiler treats them as the endpoint\u2019s internal call graph.</div>' +
      list + "</div>";
  }

  function routesInspector() {
    const rt = routeById(U.selRoute);
    if (!rt) {
      return (
        '<div class="insp-title">Route</div>' +
        '<div class="insp-sub">Pick a route to edit it, or create one.</div>' +
        '<div class="help" data-lvl="3">Tip: reference columns with <span class="kbd">@table:C:column</span> and open requirements with <span class="kbd">free:</span>.</div>' +
        '<div style="margin-top:14px;"><button class="btn btn-primary btn-sm" onclick="P.newRoute()">+ New route</button></div>'
      );
    }
    let mws = "";
    if (state.middleware.length) {
      mws = '<label class="lbl">Middleware</label><div class="mw-pick">' +
        state.middleware.map((m) => {
          const on = rt.middleware.includes(m.id);
          return '<span class="chip' + (on ? " on" : "") + '" onclick="P.toggleRouteMW(\'' + rt.id + "','" + m.id + '\')">' +
            (on ? "✕ " : "+ ") + esc(m.name) + "</span>";
        }).join("") + "</div>";
    }
    let batches = '<div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px;">' +
      '<label class="lbl" style="margin:0;">Function batches</label> ' +
      '<button class="btn btn-xs" onclick="P.addBatch()">+ add batch</button></div>';
    if (!rt.functionBatches.length) {
      batches += '<div class="hint" style="margin-top:6px;">Split the execution into named steps — the AI will implement them as internal functions.</div>';
    } else {
      batches += rt.functionBatches.map((b, i) =>
        '<div class="batch-row">' +
        '<div style="flex:1;">' +
        '<div class="b-name">' + (i + 1) + ". " + esc(b.name) + "</div>" +
        '<textarea class="mention" rows="2" placeholder="what does this function do?" onchange="P.batchDesc(\'' + b.id + '\',this.value)">' + esc(b.description || "") + "</textarea>" +
        "</div>" +
        '<button class="icon-btn" onclick="P.deleteBatch(\'' + b.id + '\')">\u2715</button>' +
        "</div>"
      ).join("");
    }
    return (
      '<div class="insp-header"><span class="insp-title">Route</span>' +
      '<button class="btn btn-danger btn-xs" onclick="P.deleteRoute()">Delete</button></div>' +
      '<div class="field-grid" style="margin-top:8px;">' +
      "<div><label class='lbl'>Method</label>" + methodSelect(rt.method) + "</div>" +
      "<div><label class='lbl'>Path</label><input type='text' value='" + esc(rt.path) + "' placeholder='/orders/{id}' onchange='P.routePath(this.value)'/></div>" +
      "</div>" +
      "<label class='lbl'>Resource table (optional)</label>" + tableSelect(rt.table) +
      "<label class='lbl'>Purpose (one line)</label>" +
      "<input type='text' value='" + esc(rt.summary || "") + "' placeholder='what is this endpoint for?' onchange='P.routeSummary(this.value)'/>" +
      mws + batches +
      '<label class="lbl" style="margin-top:12px;">Execution — how should this endpoint behave?</label>' +
      '<div class="hint" style="margin-bottom:4px;" data-lvl="2">Write it in plain language. Use <span class="kbd">@user:C:email</span> to pin columns, or <span class="kbd">free:</span> to add free-form requirements.</div>' +
      '<textarea class="mention" rows="9" placeholder="e.g. Load the order from @order:C:id — if it does not exist or does not belong to the caller, return 404. Return the order with its @order_item lines." onchange="P.routeExec(this.value)">' +
      esc(rt.execution) + "</textarea>" +
      "<label class='lbl'>Notes</label>" +
      "<input type='text' value='" + esc(rt.notes || "") + "' onchange='P.routeNotes(this.value)'/>"
    );
  }

  function methodSelect(cur) {
    const ops = METHODS.map((m) => "<option" + (m === cur ? " selected" : "") + ">" + m + "</option>").join("");
    return "<select onchange='P.routeMethod(this.value)'>" + ops + "</select>";
  }

  function tableSelect(cur) {
    const ops =
      '<option value="">— none (pure logic) —</option>' +
      state.tables.map((t) => "<option value='" + t.id + "'" + (t.id === cur ? " selected" : "") + ">" + esc(t.name) + "</option>").join("");
    return "<select onchange='P.routeTable(this.value)'>" + ops + "</select>";
  }

  /* ------------------------------------------------------------------ *
   * MIDDLEWARE TAB
   * ------------------------------------------------------------------ */
  function renderMW() {
    const c = $("#content");
    let list = "";
    if (!state.middleware.length) {
      list = '<div class="hint" style="margin:14px 0 10px;">No middleware yet. Describe cross-cutting behavior in plain language.</div>';
    } else {
      list = state.middleware.map((m) => {
        const sel = U.selMW === m.id ? " selected" : "";
        const rtCount = m.scope === "routes" ? m.routes.length : null;
        return (
          '<div class="item-card' + sel + '" onclick="P.openMW(\'' + m.id + '\')">' +
          '<span class="toggle-swatch' + (m.enabled ? "" : " off") + '"></span>' +
          "<div style='flex:1;'><b>" + esc(m.name) + "</b> " +
          '<span class="scope-badge">' + esc(m.scope) + (rtCount != null ? " · " + rtCount + " routes" : "") + "</span>" +
          '<div class="summary">' + esc((m.description || "").slice(0, 90)) + "</div></div>" +
          '<div class="meta">' + (m.enabled ? "on" : "off") + "</div></div>"
        );
      }).join("");
    }
    c.innerHTML =
      '<div class="list-view">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">' +
      "<h2 style='margin:0;font-size:16px;'>Middleware</h2>" +
      '<button class="btn btn-primary btn-sm" onclick="P.newMW()">+ New middleware</button></div>' +
      '<div class="help" data-lvl="2" style="margin-bottom:10px;">Middleware is described in natural language and attached to routes or the whole app. The compiler wires it into the build instructions.</div>' +
      list + "</div>";
  }

  function mwInspector() {
    const m = state.middleware.find((x) => x.id === U.selMW);
    if (!m) {
      return '<div class="insp-title">Middleware</div><div class="insp-sub">Select or create one to edit.</div>' +
        '<div style="margin-top:14px;"><button class="btn btn-primary btn-sm" onclick="P.newMW()">+ New middleware</button></div>';
    }
    const scopeOpts = ["global", "routes"].map((s) =>
      "<option" + (s === m.scope ? " selected" : "") + ">" + s + "</option>").join("");
    let routePick = "";
    if (m.scope === "routes") {
      routePick = '<label class="lbl">Applies to routes</label><div class="mw-pick">' +
        (state.routes.length
          ? state.routes.map((rt) => {
              const on = m.routes.includes(rt.id);
              return '<span class="chip' + (on ? " on" : "") + '" onclick="P.toggleMWRoute(\'' + m.id + "','" + rt.id + '\')">' +
                (on ? "✕ " : "+ ") + esc(rt.method + " " + rt.path) + "</span>";
            }).join("")
          : '<span class="hint">Create routes first.</span>') +
        "</div>";
    }
    return (
      '<div class="insp-header"><span class="insp-title">Middleware</span>' +
      '<button class="btn btn-danger btn-xs" onclick="P.deleteMW()">Delete</button></div>' +
      '<label class="lbl">Name</label>' +
      "<input type='text' value='" + esc(m.name) + "' onchange='P.mwName(this.value)'/>" +
      '<label class="lbl">Scope</label>' +
      "<select onchange='P.mwScope(this.value)'>" + scopeOpts + "</select>" +
      routePick +
      '<label class="lbl">Behavior (plain language)</label>' +
      '<div class="hint" data-lvl="2" style="margin-bottom:4px;">Reference columns with <span class="kbd">@user:C:id</span> so the AI knows exactly what you mean.</div>' +
      '<textarea class="mention" rows="6" placeholder="e.g. Parse the JWT from the Authorization header and set the request identity. Reject with 401 on failure." onchange="P.mwDesc(this.value)">' +
      esc(m.description || "") + "</textarea>" +
      '<div style="margin-top:10px;">' + checkbox("mw-enabled", "enabled") + "</div>" +
      '<div style="margin-top:8px;"><button class="btn btn-xs" onclick="P.commitFlagsMW()">Apply</button></div>'
    );
  }

  /* ------------------------------------------------------------------ *
   * JOBS TAB
   * ------------------------------------------------------------------ */
  function renderJobs() {
    const c = $("#content");
    let list = "";
    if (!state.jobs.length) {
      list = '<div class="hint" style="margin:14px 0 10px;">No scheduled jobs yet. Anything the backend must do on a timer lives here.</div>';
    } else {
      list = state.jobs.map((j) => {
        const sel = U.selJob === j.id ? " selected" : "";
        return (
          '<div class="item-card' + sel + '" onclick="P.openJob(\'' + j.id + '\')">' +
          '<span class="toggle-swatch' + (j.enabled ? "" : " off") + '"></span>' +
          "<div style='flex:1;'><b>" + esc(j.name) + "</b> " +
          '<span class="scope-badge">' + esc(j.schedule || "?") + "</span>" +
          (j.duration ? '<span class="scope-badge">\u2264 ' + esc(j.duration) + "</span>" : "") +
          '<div class="summary">' + esc((j.execution || "").slice(0, 90)) + "</div></div>" +
          '<div class="meta">' + (j.enabled ? "on" : "off") + "</div></div>"
        );
      }).join("");
    }
    c.innerHTML =
      '<div class="list-view">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">' +
      "<h2 style='margin:0;font-size:16px;'>Jobs</h2>" +
      '<button class="btn btn-primary btn-sm" onclick="P.newJob()">+ New job</button></div>' +
      '<div class="help" data-lvl="2" style="margin-bottom:10px;">Give each job a schedule (cron or plain words) and an execution budget, then describe the work.</div>' +
      list + "</div>";
  }

  function jobsInspector() {
    const j = state.jobs.find((x) => x.id === U.selJob);
    if (!j) {
      return '<div class="insp-title">Job</div><div class="insp-sub">Select or create one.</div>' +
        '<div style="margin-top:14px;"><button class="btn btn-primary btn-sm" onclick="P.newJob()">+ New job</button></div>';
    }
    return (
      '<div class="insp-header"><span class="insp-title">Job</span>' +
      '<button class="btn btn-danger btn-xs" onclick="P.deleteJob()">Delete</button></div>' +
      '<div class="field-grid" style="margin-top:8px;">' +
      "<div><label class='lbl'>Name</label><input type='text' value='" + esc(j.name) + "' onchange='P.jobName(this.value)'/></div>" +
      "<div><label class='lbl'>Schedule</label><input type='text' value='" + esc(j.schedule || "") + "' placeholder='every 10 minutes' onchange='P.jobSchedule(this.value)'/></div>" +
      "</div>" +
      "<label class='lbl'>Execution budget (max duration)</label>" +
      "<input type='text' value='" + esc(j.duration || "") + "' placeholder='< 1 min' onchange='P.jobDuration(this.value)'/>" +
      '<label class="lbl">What the job does</label>' +
      '<div class="hint" data-lvl="2" style="margin-bottom:4px;">Plain language, with <span class="kbd">@order</span> / <span class="kbd">free:</span> tokens if needed.</div>' +
      '<textarea class="mention" rows="7" placeholder="e.g. Find orders older than 30 minutes still pending, cancel them, and return their stock to @product." onchange="P.jobExec(this.value)">' +
      esc(j.execution || "") + "</textarea>" +
      '<div style="margin-top:10px;">' + checkbox("job-enabled", "enabled") + "</div>" +
      '<div style="margin-top:8px;"><button class="btn btn-xs" onclick="P.commitFlagsJob()">Apply</button></div>'
    );
  }

  /* ------------------------------------------------------------------ *
   * FEEDBACK / REVIEW LOOP TAB
   * ------------------------------------------------------------------ */
  function renderFeedback() {
    const c = $("#content");
    let list = "";
    if (!state.feedback.length) {
      list = '<div class="hint" style="margin:14px 0 10px;">No clarifications recorded yet.</div>';
    } else {
      list = state.feedback.map((f) =>
        '<div class="feedback-item">' +
        '<div style="display:flex;justify-content:space-between;"><span class="f-src">' + esc(f.source) + "</span>" +
        '<button class="icon-btn" onclick="P.deleteFeedback(\'' + f.id + '\')">\u2715</button></div>' +
        '<div class="f-txt">' + esc(f.content) + "</div></div>"
      ).join("");
    }
    c.innerHTML =
      '<div class="list-view">' +
      "<h2 style='margin:0 0 6px;font-size:16px;'>Review loop</h2>" +
      '<div class="help" style="margin-bottom:12px;" data-lvl="2"><b>How it works:</b> (1) Compile the design &rarr; give the <i>Quiz blueprint</i> to any AI. The AI builds a small HTML quiz app that interrogates the spec. ' +
      "(2) Answer the quiz as the product owner. (3) Paste the answers here — they become authoritative clarifications. (4) Re-compile; the clarifications are folded into every future prompt.</div>" +
      list + "</div>";
  }

  function feedbackInspector() {
    return (
      '<div class="insp-title">Add clarifications</div>' +
      '<div class="insp-sub">Paste answers from the AI-generated quiz, or any reviewer feedback.</div>' +
      '<label class="lbl">Source</label>' +
      '<select id="fb-source"><option value="quiz answers">quiz answers</option>' +
      "<option value='reviewer'>reviewer</option></select>" +
      '<label class="lbl">Content</label>' +
      '<textarea class="mention" id="fb-content" rows="8" placeholder="Paste the quiz answers / feedback verbatim here. The next compile will treat them as decisions."></textarea>' +
      '<div class="hint" data-lvl="2">Anything you type with <span class="kbd">free:</span> inside is labeled as free-form rationale in the compiled spec.</div>' +
      '<button class="btn btn-primary btn-sm" style="margin-top:10px;" onclick="P.addFeedback()">Add clarification</button>'
    );
  }

  /* ------------------------------------------------------------------ *
   * Mention autocomplete  @table:C:column  ·  free:...
   * ------------------------------------------------------------------ */
  function bindMentionTextareas() {
    closePopover();
    $$("#inspector textarea.mention, #content textarea.mention").forEach((ta) => {
      ta.dataset.bound = "1";
      ta.addEventListener("input", () => onMentionInput(ta), { passive: true });
      ta.addEventListener("blur", () => setTimeout(closePopover, 120));
      ta.addEventListener("scroll", closePopover);
    });
  }

  function mentionToken(el) {
    const before = el.value.slice(0, el.selectionStart);
    const m = before.match(/(@[A-Za-z0-9_]*(?::C:[A-Za-z0-9_]*)?|free:)$/);
    return m ? { start: el.selectionStart - m[1].length, token: m[1] } : null;
  }

  function onMentionInput(ta) {
    const tok = mentionToken(ta);
    if (!tok) { closePopover(); return; }
    if (tok.token === "free:") { showFreeHint(ta); return; }
    closePopover();
    const parts = tok.token.split(":");
    // parts = ["@table", "C", "col"]  OR  ["@table"]
    const tblPrefix = (parts[0] || "").replace(/^@/, "").toLowerCase();
    const wantCols = parts.length >= 2 && parts[1].toLowerCase() === "c";
    const colPrefix = wantCols && parts[2] ? parts[2].toLowerCase() : "";
    const matchedTables = wantCols
      ? state.tables.filter((t) => t.name.toLowerCase() === tblPrefix.replace(/^@/, ""))
      : state.tables.filter((t) => t.name.toLowerCase().startsWith(tblPrefix));
    let items = [];
    if (wantCols) {
      matchedTables.forEach((t) => {
        t.columns
          .filter((c) => c.name.toLowerCase().startsWith(colPrefix))
          .forEach((c) => items.push({ k: "@" + t.name + ":C:" + c.name, d: "column", t }));
      });
    } else {
      items = matchedTables.map((t) => ({ k: "@" + t.name, d: "table", t }));
      // + columns of the first exact match (convenience)
      if (matchedTables.length === 1) {
        matchedTables[0].columns.forEach((c) => items.push({ k: "@" + matchedTables[0].name + ":C:" + c.name, d: "column", t: null }));
      }
    }
    openPopover(ta, items, tok.start);
  }

  function openPopover(ta, items, tokenStart) {
    const pop = $("#popover");
    if (items.length === 0) {
      pop.innerHTML = '<div class="po-empty">No tables or columns match. Create tables on the canvas first.</div>';
    } else {
      let html = "";
      items.forEach((it) => {
        html += '<div class="po-item" data-k="' + esc(it.k) + '"><span class="po-k">' + esc(it.k) + "</span>" +
          '<span class="po-d">' + esc(it.d) + "</span></div>";
      });
      pop.innerHTML = html + '<div class="po-empty" style="padding-top:4px;font-size:11px;">start typing to filter · the format survives into the compiled spec</div>';
    }
    const r = ta.getBoundingClientRect();
    pop.style.left = Math.min(r.left, window.innerWidth - 320) + "px";
    pop.style.top = r.bottom + 6 + "px";
    pop.classList.remove("hidden");
    pop.dataset.tokenStart = tokenStart;
    $$("#popover .po-item").forEach((el) =>
      el.addEventListener("click", () => insertMention(ta, tokenStart, el.dataset.k))
    );
  }

  function insertMention(ta, tokenStart, insert) {
    const v = ta.value;
    const caret = ta.selectionStart;
    ta.value = v.slice(0, tokenStart) + insert + " " + v.slice(caret);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = tokenStart + insert.length + 1;
    closePopover();
  }

  function showFreeHint(ta) {
    const fh = $("#freehint");
    const r = ta.getBoundingClientRect();
    fh.textContent = "free: — anything after this marker is free-form requirement prose. The compiler keeps it verbatim; the AI treats it as authoritative.";
    fh.style.left = Math.min(r.left, window.innerWidth - 340) + "px";
    fh.style.top = r.bottom + 6 + "px";
    fh.classList.remove("hidden");
    clearTimeout(U._fhT);
    U._fhT = setTimeout(() => fh.classList.add("hidden"), 5000);
  }

  function closePopover() {
    const pop = $("#popover");
    if (pop) pop.classList.add("hidden");
    const fh = $("#freehint");
    if (fh) fh.classList.add("hidden");
  }

  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("#popover") && !e.target.closest(".mention")) closePopover();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closePopover();
      if (U.connectFrom) { U.connectFrom = null; U.connectMode = false; renderCanvas(); }
      if (U.screen === "builder") { renderInspector(); }
    }
  });

  /* ------------------------------------------------------------------ *
   * Compile + Export
   * ------------------------------------------------------------------ */
  async function compile() {
    const btn = $("#btn-compile");
    if (btn) { btn.disabled = true; btn.textContent = "Compiling…"; }
    try {
      const res = await fetch("/api/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ design: state }),
      });
      const j = await res.json();
      if (!j.ok) throw new Error(j.error || "compile failed");
      compiled = j.compiled;
      save();
      U.expTab = "prompt";
      show("export");
      const n = (compiled.diagnostics || []).filter((d) => d.level === "error").length;
      n ? toast("Compiled with " + n + " error(s) — check Diagnostics") : toast("Compiled. Copy the AI Prompt.");
    } catch (e) {
      toast("Compile failed: " + e.message, "err");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Compile & Export"; }
    }
  }

  function renderExportUI() {
    if (!compiled) { compiled = null; }
    // stats
    const s = compiled ? compiled.stats : null;
    $("#export-stats").innerHTML = s
      ? ["tables", "relations", "routes", "middleware", "jobs"]
          .map((k) => "<span>" + s[k] + " " + k + "</span>")
          .join("")
      : "nothing compiled yet";
    renderExportTab();
  }

  function renderExportTab() {
    const pane = $("#export-pane");
    const tabs = $$("#export-tabs .exp-tab");
    tabs.forEach((t) => t.classList.toggle("active", t.dataset.exp === U.expTab));
    if (!compiled) {
      pane.innerHTML = '<div class="insp-sub">Go back and compile the design first.</div>';
      return;
    }
    const paneHTML = {
      prompt: codePane("AI Prompt", compiled.prompt, "Prompt for the code-generating AI — deterministic, every field mapped from your design."),
      json: codePane("JSON spec", JSON.stringify(compiled, null, 2), "The full compiled bundle. Copy, or download as a file."),
      quiz: codePane("Quiz blueprint",
        compiled.quizPrompt,
        "Give this to any AI (e.g. ChatGPT). It will build a self-contained HTML quiz app that interrogates your spec. Run it, answer as the product owner, then paste the answers into the Review loop in Planner."),
      feedback: codePane("Feedback template",
        compiled.feedbackPromptTemplate,
        "Paste the quiz answers where it says {{PASTE_ANSWERS_HERE}}, send it to the same AI, and it returns the spec updated with your decisions."),
      diagnostics: diagPane(),
    }[U.expTab];
    pane.innerHTML = paneHTML;
    pane.scrollTop = 0;
  }

  function codePane(title, text, explain) {
    return (
      '<div class="insp-header" style="margin-bottom:4px;"><span class="insp-title">' + title + "</span></div>" +
      '<div class="hint" style="margin-bottom:10px;">' + explain + "</div>" +
      '<div class="code-box"><div class="actions">' +
      '<button class="btn btn-sm" onclick="P.copy(\'#exp-code\')">Copy</button>' +
      '<button class="btn btn-sm" onclick="P.downloadPane()">Download</button>' +
      "</div>" +
      '<textarea id="exp-code" readonly wrap="off">' + esc(text) + "</textarea></div>"
    );
  }

  function diagPane() {
    const ds = compiled.diagnostics || [];
    const rows = ds.length
      ? ds.map((d) =>
          '<div class="diag ' + d.level + '"><b>' + esc(d.level) + " · " + esc(d.kind) + "</b><div>" + esc(d.message) + "</div></div>").join("")
      : '<div class="hint">No diagnostics. The design compiled cleanly.</div>';
    return (
      '<div class="insp-header"><span class="insp-title">Diagnostics</span></div>' +
      '<div class="insp-sub">Everything the compiler could verify automatically.</div>' +
      rows
    );
  }

  /* ------------------------------------------------------------------ *
   * Clipboard / download / print
   * ------------------------------------------------------------------ */
  function copyText(text, done) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => done(true), () => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }

  function fallbackCopy(text, done) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
    done(ok);
  }

  function makeFileName(ext) {
    const base = (state.project.name || "planner").replace(/[^A-Za-z0-9_-]+/g, "_").toLowerCase();
    return base + "." + ext;
  }

  function paneFileNames() {
    return {
      prompt: makeFileName("spec-prompt.txt"),
      json: makeFileName("spec.json"),
      quiz: makeFileName("quiz-blueprint.txt"),
      feedback: makeFileName("feedback-template.txt"),
      diagnostics: makeFileName("diagnostics.txt"),
    };
  }

  /* ------------------------------------------------------------------ *
   * Public handlers
   * ------------------------------------------------------------------ */
  window.P = {
    /* launch */
    start() {
      const name = $("#p-name").value.trim() || "My Backend";
      Object.assign(state.project, {
        name,
        description: $("#p-desc").value.trim(),
        architecture: U.launchArch,
        level: Number($("#p-level").value),
      });
      save();
      U.selTable = null; U.selRel = null; U.selRoute = null; U.selMW = null; U.selJob = null;
      show("builder");
      toast("Builder ready — add tables on the canvas.");
    },
    async loadSample() {
      try {
        const res = await fetch("/api/example");
        const j = await res.json();
        if (!j.ok) throw new Error("no sample");
        state = j.design;
        setLevel(state.project.level || 2);
        save();
        U.selTable = null; U.selRel = null; U.selRoute = null;
        show("builder");
        toast("Example design loaded (SnackShop API).");
      } catch (e) { toast("Could not load example: " + e.message, "err"); }
    },
    settings() {
      $("#p-name").value = state.project.name || "";
      $("#p-desc").value = state.project.description || "";
      setLevel(state.project.level);
      show("launch");
    },
    setLevel,
    pickArch(arch) {
      U.launchArch = arch;
      $$("#arch-grid .arch-opt").forEach((el) => el.classList.toggle("active", el.dataset.arch === arch));
    },

    /* tabs */
    setTab(t) {
      U.tab = t;
      U.selRoute = null; U.selMW = null; U.selJob = null; U.connectFrom = null;
      if (t !== "design") { U.selTable = null; U.selRel = null; }
      renderAll();
    },

    newTable() {
      const i = state.tables.length;
      const t = {
        id: uid("t"), name: "table_" + String(i + 1), x: 80 + (i % 4) * 320, y: 80 + Math.floor(i / 4) * 360,
        notes: "", columns: [
          { id: uid("c"), name: "id", type: "uuid", pk: true, auto: false, nullable: false, unique: true, default: "", notes: "" },
        ],
      };
      state.tables.push(t);
      U.selTable = t.id; U.selRel = null;
      save(); renderAll();
    },
    arrange() { arrangeTables(); },
    clearAll() {
      if (!confirm("Delete every table, route, middleware and job?")) return;
      state.tables = []; state.relations = []; state.routes = []; state.middleware = []; state.jobs = []; state.feedback = [];
      U.connectFrom = null;
      save(); renderAll();
    },

    /* canvas selection */
    pickColumn(tableId, colId) {
      if (U.connectMode && !U.connectFrom) U.connectFrom = null;
      if (U.connectFrom && U.connectFrom.tableId !== tableId) {
        const src = U.connectFrom;
        U.connectFrom = null;
        if (src.tableId === tableId && src.colId === colId) { renderCanvas(); return; }
        addRelation(src.tableId, src.colId, tableId, colId);
        U.selRel = lastRelId;
        renderCanvas(); renderInspector();
        return;
      }
      // same table or starting
      if (U.connectFrom && U.connectFrom.tableId === tableId) { U.connectFrom = null; renderCanvas(); return; }
      U.connectFrom = { tableId, colId };
      U.connectMode = true;
      U.selTable = tableId;
      renderCanvas(); renderInspector();
    },
    selectRel(id, ev) {
      if (ev) { ev.stopPropagation(); ev.preventDefault(); }
      U.selRel = id; U.selTable = null; U.connectFrom = null;
      renderInspector();
      renderCanvas();
    },
    enterConnect() {
      U.connectMode = true;
      renderCanvas();
      toast("Click a source column, then a target column. Esc to cancel.");
    },
    exitConnect() { U.connectMode = false; U.connectFrom = null; renderCanvas(); },

    /* table editing */
    tableName(v) {
      const t = tableById(U.selTable); if (!t) return;
      t.name = v.trim() || t.name; save(); renderRailCounts(); renderContent();
    },
    tableNotes(v) {
      const t = tableById(U.selTable); if (!t) return;
      t.notes = v; save(); renderCanvas();
    },
    toggleExpandCol(cid) { U.expandCol = U.expandCol === cid ? null : cid; renderInspector(); },
    colName(cid, v) {
      const t = tableById(U.selTable), c = colById(t, cid); if (!c) return;
      c.name = v.trim() || c.name; save(); renderCanvas();
    },
    colType(cid, v) {
      const t = tableById(U.selTable), c = colById(t, cid); if (!c) return;
      c.type = v; save(); renderCanvas();
    },
    reflectFlags(cid) {
      const t = tableById(U.selTable), c = colById(t, cid); if (!c) return;
      c.pk = $("#f-pk").checked;
      c.auto = $("#f-auto").checked;
      c.nullable = !$("#f-nn").checked;
      c.unique = $("#f-uq").checked;
      save(); renderInspector(); renderCanvas();
    },
    colDefault(cid, v) {
      const t = tableById(U.selTable), c = colById(t, cid); if (!c) return;
      c.default = v; save();
    },
    colNotes(cid, v) {
      const t = tableById(U.selTable), c = colById(t, cid); if (!c) return;
      c.notes = v; save();
    },
    addColumn() {
      const t = tableById(U.selTable); if (!t) return;
      const name = ($("#new-col-name").value || "").trim();
      if (!name) { toast("Column needs a name", "err"); return; }
      const c = {
        id: uid("c"), name,
        type: $("#new-col-type").value,
        pk: $("#new-col-pk").checked,
        auto: $("#new-col-auto").checked,
        nullable: !$("#new-col-nn").checked,
        unique: $("#new-col-uq").checked,
        default: $("#new-col-def").value.trim(),
        notes: "",
      };
      t.columns.push(c);
      save(); renderInspector(); renderCanvas();
    },
    deleteColumn(cid) {
      const t = tableById(U.selTable); if (!t) return;
      t.columns = t.columns.filter((c) => c.id !== cid);
      state.relations = state.relations.filter((r) => !(r.fromTable === t.id && r.fromColumn === cid) && !(r.toTable === t.id && r.toColumn === cid));
      save(); renderInspector(); renderCanvas();
    },
    deleteTable() {
      const t = tableById(U.selTable); if (!t) return;
      if (!confirm('Delete table "' + t.name + '" and its relations?')) return;
      state.tables = state.tables.filter((x) => x.id !== t.id);
      state.relations = state.relations.filter((r) => r.fromTable !== t.id && r.toTable !== t.id);
      state.routes.forEach((rt) => { if (rt.table === t.id) rt.table = ""; });
      U.selTable = null;
      save(); renderAll();
    },

    /* relations */
    relKind(v) {
      const r = state.relations.find((x) => x.id === U.selRel); if (!r) return;
      r.kind = v; save(); renderCanvas();
    },
    relLabel(v) {
      const r = state.relations.find((x) => x.id === U.selRel); if (!r) return;
      r.label = v; save(); renderCanvas();
    },
    deleteRel() {
      state.relations = state.relations.filter((x) => x.id !== U.selRel);
      U.selRel = null; save(); renderInspector(); renderCanvas();
    },

    /* routes */
    openRoute(id) { U.selRoute = id; renderInspector(); renderContent(); },
    newRoute() {
      const rt = {
        id: uid("rt"), method: "GET", path: "/new-endpoint", table: state.tables[0] ? state.tables[0].id : "",
        summary: "", middleware: [], functionBatches: [], execution: "", notes: "",
      };
      state.routes.push(rt);
      U.selRoute = rt.id;
      save(); renderAll();
    },
    routeMethod(v) { const rt = routeById(U.selRoute); if (!rt) return; rt.method = v; save(); renderContent(); },
    routeTable(v) { const rt = routeById(U.selRoute); if (!rt) return; rt.table = v; save(); renderContent(); },
    routePath(v) { const rt = routeById(U.selRoute); if (!rt) return; rt.path = v; save(); renderContent(); },
    routeSummary(v) { const rt = routeById(U.selRoute); if (!rt) return; rt.summary = v; save(); },
    routeExec(v) { const rt = routeById(U.selRoute); if (!rt) return; rt.execution = v; save(); },
    routeNotes(v) { const rt = routeById(U.selRoute); if (!rt) return; rt.notes = v; save(); },
    toggleRouteMW(rid, mid) {
      const rt = routeById(rid); if (!rt) return;
      rt.middleware = rt.middleware.includes(mid) ? rt.middleware.filter((x) => x !== mid) : rt.middleware.concat(mid);
      save(); renderInspector(); renderContent();
    },
    addBatch() {
      const rt = routeById(U.selRoute); if (!rt) return;
      const n = "fn_" + (rt.functionBatches.length + 1);
      rt.functionBatches.push({ id: uid("fb"), name: n, description: "" });
      save(); renderInspector(); renderContent();
    },
    batchDesc(bid, v) {
      const rt = routeById(U.selRoute); if (!rt) return;
      const b = rt.functionBatches.find((x) => x.id === bid); if (!b) return;
      b.description = v; save();
    },
    deleteBatch(bid) {
      const rt = routeById(U.selRoute); if (!rt) return;
      rt.functionBatches = rt.functionBatches.filter((x) => x.id !== bid);
      save(); renderInspector(); renderContent();
    },
    deleteRoute() {
      const rt = routeById(U.selRoute); if (!rt) return;
      if (!confirm('Delete route "' + rt.method + " " + rt.path + '"?')) return;
      state.routes = state.routes.filter((x) => x.id !== rt.id);
      state.middleware.forEach((m) => { m.routes = m.routes.filter((r) => r !== rt.id); });
      U.selRoute = null; save(); renderAll();
    },

    /* middleware */
    openMW(id) { U.selMW = id; renderInspector(); renderContent(); },
    newMW() {
      const m = { id: uid("m"), name: "middleware_" + (state.middleware.length + 1), scope: "global", routes: [], description: "", enabled: true };
      state.middleware.push(m);
      U.selMW = m.id;
      save(); renderAll();
    },
    mwName(v) { const m = state.middleware.find((x) => x.id === U.selMW); if (!m) return; m.name = v.trim() || m.name; save(); renderContent(); },
    mwScope(v) { const m = state.middleware.find((x) => x.id === U.selMW); if (!m) return; m.scope = v; m.routes = []; save(); renderInspector(); },
    toggleMWRoute(mid, rid) {
      const m = state.middleware.find((x) => x.id === mid); if (!m) return;
      m.routes = m.routes.includes(rid) ? m.routes.filter((x) => x !== rid) : m.routes.concat(rid);
      save(); renderInspector();
    },
    mwDesc(v) { const m = state.middleware.find((x) => x.id === U.selMW); if (!m) return; m.description = v; save(); },
    commitFlagsMW() {
      const m = state.middleware.find((x) => x.id === U.selMW); if (!m) return;
      m.enabled = $("#mw-enabled").checked;
      save(); renderInspector();
    },
    deleteMW() {
      const m = state.middleware.find((x) => x.id === U.selMW); if (!m) return;
      if (!confirm('Delete middleware "' + m.name + '"?')) return;
      state.middleware = state.middleware.filter((x) => x.id !== m.id);
      state.routes.forEach((rt) => { rt.middleware = rt.middleware.filter((id) => id !== m.id); });
      U.selMW = null; save(); renderAll();
    },

    /* jobs */
    openJob(id) { U.selJob = id; renderInspector(); renderContent(); },
    newJob() {
      const j = { id: uid("j"), name: "job_" + (state.jobs.length + 1), schedule: "every 24 hours", duration: "< 1 min", execution: "", enabled: true };
      state.jobs.push(j);
      U.selJob = j.id;
      save(); renderAll();
    },
    jobName(v) { const j = state.jobs.find((x) => x.id === U.selJob); if (!j) return; j.name = v.trim() || j.name; save(); renderContent(); },
    jobSchedule(v) { const j = state.jobs.find((x) => x.id === U.selJob); if (!j) return; j.schedule = v; save(); renderContent(); },
    jobDuration(v) { const j = state.jobs.find((x) => x.id === U.selJob); if (!j) return; j.duration = v; save(); },
    jobExec(v) { const j = state.jobs.find((x) => x.id === U.selJob); if (!j) return; j.execution = v; save(); },
    commitFlagsJob() {
      const j = state.jobs.find((x) => x.id === U.selJob); if (!j) return;
      j.enabled = $("#job-enabled").checked;
      save(); renderInspector();
    },
    deleteJob() {
      const j = state.jobs.find((x) => x.id === U.selJob); if (!j) return;
      if (!confirm('Delete job "' + j.name + '"?')) return;
      state.jobs = state.jobs.filter((x) => x.id !== j.id);
      U.selJob = null; save(); renderAll();
    },

    /* feedback */
    addFeedback() {
      const src = $("#fb-source") ? $("#fb-source").value : "reviewer";
      const content = ($("#fb-content") ? $("#fb-content").value : "").trim();
      if (!content) { toast("Paste some answers first", "err"); return; }
      state.feedback.push({ id: uid("f"), source: src, content });
      save(); renderAll();
      U.tab = "feedback";
      renderAll();
      toast("Clarification recorded — it will be folded into the next compile.");
    },
    deleteFeedback(id) {
      state.feedback = state.feedback.filter((f) => f.id !== id);
      save(); renderAll();
    },

    /* compile + export */
    compile,
    async compileMenu() { await compile(); },
    back() { show("builder"); },
    expTab(t) { U.expTab = t; renderExportTab(); },
    copy(sel) {
      const ta = $(sel); if (!ta) return;
      copyText(ta.value, (ok) => toast(ok ? "Copied to clipboard." : "Copy failed — select manually.", ok ? "ok" : "err"));
    },
    download(name, sel) {
      const ta = $(sel); if (!ta) return;
      const blob = new Blob([ta.value], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name || makeFileName("txt");
      document.body.appendChild(a); a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 300);
      toast("Downloaded.");
    },
    downloadPane() {
      const name = paneFileNames()[U.expTab] || makeFileName("txt");
      this.download(name, "#exp-code");
    },
    print() {
      if (!compiled) return;
      const w = window.open("", "_blank");
      if (!w) { toast("Pop-up blocked. Allow pop-ups to print.", "err"); return; }
      w.document.write(
        "<html><head><title>" + esc(state.project.name) + " — compiled spec</title>" +
        '<style>body{font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap;line-height:1.5;max-width:900px;margin:24px auto;padding:0 16px;}</style>' +
        "</head><body>" + esc(compiled.prompt) + "</body></html>"
      );
      w.document.close();
      setTimeout(() => w.print(), 350);
    },
  };

  let lastRelId = null;
  function addRelation(fromT, fromC, toT, toC) {
    const rel = { id: uid("r"), fromTable: fromT, fromColumn: fromC, toTable: toT, toColumn: toC, kind: "one-to-many", label: "" };
    state.relations.push(rel);
    lastRelId = rel.id;
    save();
  }

  /* ------------------------------------------------------------------ *
   * renderContent dispatcher
   * ------------------------------------------------------------------ */
  function renderContent() {
    if (U.tab === "design") renderCanvas();
    else if (U.tab === "routes") renderRoutes();
    else if (U.tab === "middleware") renderMW();
    else if (U.tab === "jobs") renderJobs();
    else if (U.tab === "feedback") renderFeedback();
  }

  /* ------------------------------------------------------------------ *
   * Boot
   * ------------------------------------------------------------------ */
  function boot() {
    load();
    document.addEventListener("pointermove", onDocPointerMove);
    document.addEventListener("pointerup", onDocPointerUp);
    if (!Array.isArray(state.tables)) state.tables = [];
    setLevel(state.project.level || 2);

    // Launch controls
    $("#p-name").value = state.project.name || "";
    $("#p-desc").value = state.project.description || "";
    U.launchArch = state.project.architecture || "monolithic";
    $$("#arch-grid .arch-opt").forEach((el) =>
      el.classList.toggle("active", el.dataset.arch === U.launchArch)
    );
    $("#arch-grid").addEventListener("click", (e) => {
      const opt = e.target.closest(".arch-opt");
      if (opt) P.pickArch(opt.dataset.arch);
    });
    $("#p-level").addEventListener("input", (e) => setLevel(Number(e.target.value)));
    $("#top-level").addEventListener("input", (e) => setLevel(Number(e.target.value)));
    $("#btn-start").addEventListener("click", () => P.start());
    $("#btn-sample").addEventListener("click", () => P.loadSample());
    $("#btn-project-settings").addEventListener("click", () => P.settings());
    $("#btn-compile").addEventListener("click", () => compile());
    $("#btn-back").addEventListener("click", () => P.back());
    $("#btn-download").addEventListener("click", () => P.download(makeFileName("json"), "exp-code"));
    $("#btn-print").addEventListener("click", () => P.print());

    $("#rail").addEventListener("click", (e) => {
      const item = e.target.closest(".nav-item");
      if (item) P.setTab(item.dataset.tab);
    });
    $("#btn-new-table").addEventListener("click", () => P.newTable());
    $("#btn-connect").addEventListener("click", () => P.enterConnect());
    $("#btn-arrange").addEventListener("click", () => P.arrange());
    $("#export-tabs").addEventListener("click", (e) => {
      const t = e.target.closest(".exp-tab");
      if (t) P.expTab(t.dataset.exp);
    });

    // Resume or launch?
    const hasWork =
      state.tables.length || state.routes.length ||
      state.middleware.length || state.jobs.length || state.feedback.length;
    show(hasWork ? "builder" : "launch");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();