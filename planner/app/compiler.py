"""Deterministic compiler: turns a Planner design into a compiled JSON prompt.

The compiled output is stable for a given design (no randomness). It contains:
  * prompt                  - the human/AI prompt text (copy-paste ready)
  * quizPrompt              - instructions to have an AI generate an HTML/JS quiz app
  * feedbackPromptTemplate  - template to fold quiz answers back into the spec
  * diagnostics             - deterministic warnings/errors the compiler found
  * design                  - the normalized machine-readable spec (mention-expanded)
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

FORMAT_VERSION = "1.0"

COLUMN_TYPES = {
    "int", "bigint", "string", "text", "uuid", "bool", "float",
    "decimal", "datetime", "date", "json", "enum",
}
CARDINALITIES = {"one-to-one", "one-to-many", "many-to-many"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ARCHITECTURES = {"monolithic", "modular-monolithic"}

_MENTION_RE = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)(?::C:([A-Za-z_][A-Za-z0-9_]*))?")


@dataclass
class Diag:
    level: str          # "error" | "warning" | "info"
    kind: str           # machine key e.g. "mention.unknown_table"
    message: str
    entity: str = ""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _clean(design: dict) -> dict:
    """Deep-copy the design so the compiler never mutates caller data."""
    return json.loads(json.dumps(design))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _table_map(tables: list[dict]) -> dict[str, dict]:
    return {t["id"]: t for t in tables}


def _name_to_table(tables: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in tables:
        key = t.get("name", "").strip().lower()
        if key and key not in out:
            out[key] = t
    return out


# --------------------------------------------------------------------------- #
# Mention expansion:  @table:C:column   ->  table.column
# --------------------------------------------------------------------------- #
def _expand_in_text(text: str, by_name: dict[str, dict], diags: list[Diag]) -> str:
    warned: set[tuple[str, str | None]] = set()

    def repl(m: re.Match) -> str:
        tbl_name, col_name = m.group(1), m.group(2)
        table = by_name.get(tbl_name.lower())
        if table is None:
            key = (tbl_name, None)
            if key not in warned:
                warned.add(key)
                diags.append(Diag(
                    "error", "mention.unknown_table",
                    f"Mention @{tbl_name} does not match any table.",
                    tbl_name,
                ))
            return m.group(0)
        if col_name is None:
            return table.get("name", tbl_name)
        col = next((c for c in table.get("columns", [])
                    if c.get("name", "").lower() == col_name.lower()), None)
        if col is None:
            key = (tbl_name, col_name)
            if key not in warned:
                warned.add(key)
                diags.append(Diag(
                    "error", "mention.unknown_column",
                    f"Mention @{tbl_name}:C:{col_name} does not match any column.",
                    f"{tbl_name}.{col_name}",
                ))
            return m.group(0)
        return f"{table['name']}.{col['name']}"

    return _MENTION_RE.sub(repl, text)


def expand_mentions(design: dict, diags: list[Diag] | None = None) -> None:
    """Expand @table / @table:C:column mentions inside every free-text field in place."""
    if diags is None:
        diags = []
    by_name = _name_to_table(design.get("tables", []))
    for rt in design.get("routes", []):
        rt["execution"] = _expand_in_text(rt.get("execution", ""), by_name, diags)
        for fb in rt.get("functionBatches", []):
            fb["description"] = _expand_in_text(fb.get("description", ""), by_name, diags)
    for md in design.get("middleware", []):
        md["description"] = _expand_in_text(md.get("description", ""), by_name, diags)
    for j in design.get("jobs", []):
        j["execution"] = _expand_in_text(j.get("execution", ""), by_name, diags)
    for f in design.get("feedback", []):
        f["content"] = _expand_in_text(f.get("content", ""), by_name, diags)


# --------------------------------------------------------------------------- #
# Structural validation (deterministic diagnostics)
# --------------------------------------------------------------------------- #
def validate(design: dict, diags: list[Diag]) -> None:
    tables = design.get("tables", [])
    tmap = _table_map(tables)

    seen_names: dict[str, str] = {}
    for t in tables:
        n = t.get("name", "").strip()
        tid = t.get("id", "")
        if not n:
            diags.append(Diag("error", "table.no_name", "A table has no name.", tid))
        elif n.lower() in seen_names:
            diags.append(Diag("error", "table.duplicate_name",
                              f"Duplicate table name '{n}'.", tid))
        else:
            seen_names[n.lower()] = tid

        seen_cols: set[str] = set()
        for c in t.get("columns", []):
            cn = c.get("name", "").strip()
            if not cn:
                diags.append(Diag("error", "column.no_name",
                                  f"Table '{n}' has a column without a name.", tid))
                continue
            if cn.lower() in seen_cols:
                diags.append(Diag("error", "column.duplicate_name",
                                  f"Column '{cn}' duplicated in table '{n}'.", tid))
            seen_cols.add(cn.lower())
            if c.get("type", "") not in COLUMN_TYPES:
                diags.append(Diag("warning", "column.unknown_type",
                                  f"Unknown column type '{c.get('type')}' on {n}.{cn}.", tid))

    route_paths: dict[str, str] = {}
    for rt in design.get("routes", []):
        m = rt.get("method", "")
        p = rt.get("path", "").strip()
        rid = rt.get("id", "")
        if m not in HTTP_METHODS:
            diags.append(Diag("error", "route.unknown_method",
                              f"Unsupported method '{m}'.", rid))
        if not p.startswith("/"):
            diags.append(Diag("error", "route.path_format",
                              f"Route path '{p}' must start with '/'.", rid))
        key = f"{m} {p}"
        if key in route_paths:
            diags.append(Diag("error", "route.duplicate",
                              f"Duplicate route '{key}'.", rid))
        route_paths[key] = rid
        if rt.get("table") and rt["table"] not in tmap:
            diags.append(Diag("error", "route.unknown_table",
                              f"Route '{key}' references missing table '{rt['table']}'.", rid))
        if not (rt.get("execution") or rt.get("functionBatches")):
            diags.append(Diag("warning", "route.empty_behavior",
                              f"Route '{key}' has no execution or function batches.", rid))

    for r in design.get("relations", []):
        for side in ("fromTable", "toTable"):
            if r.get(side) not in tmap:
                diags.append(Diag("error", "relation.unknown_table",
                                  f"Relation {r.get('id')} references missing table.", r.get("id", "")))
        if r.get("kind", "") not in CARDINALITIES:
            diags.append(Diag("warning", "relation.unknown_kind",
                              f"Relation {r.get('id')} has unknown kind.", r.get("id", "")))

    valid_route_ids = {r["id"] for r in design.get("routes", [])}
    for mdi in design.get("middleware", []):
        for rid in mdi.get("routes", []):
            if rid not in valid_route_ids:
                diags.append(Diag("warning", "middleware.unknown_route",
                                  f"Middleware '{mdi.get('name')}' targets missing route.", mdi.get("id", "")))

    linked = {rt.get("table") for rt in design.get("routes", []) if rt.get("table")}
    for t in tables:
        if t["id"] not in linked:
            diags.append(Diag("info", "table.unused",
                              f"Table '{t.get('name')}' is defined but no route is bound to it.",
                              t["id"]))


# --------------------------------------------------------------------------- #
# Markdown prompt builders
# --------------------------------------------------------------------------- #
def _fmt_type(c: dict) -> str:
    s = c.get("type", "string")
    if c.get("pk"):
        s += " PK"
    if c.get("auto"):
        s += " auto"
    if not c.get("nullable", True):
        s += " NOT NULL"
    if c.get("unique"):
        s += " UNIQUE"
    if c.get("default"):
        s += f" default={c['default']}"
    if c.get("notes"):
        s += f" ({c['notes']})"
    return s


def _column_rows(table: dict) -> list[str]:
    cols = table.get("columns", [])
    if not cols:
        return ["  * _(no columns yet)_"]
    width = max(len(c.get("name", "")) for c in cols)
    return [f"  * `{c.get('name',''):<{width}}` : {_fmt_type(c)}" for c in cols]


def _table_definition_block(design: dict) -> list[str]:
    tmap = _table_map(design.get("tables", []))
    rels = design.get("relations", [])
    out = ["## Data model", ""]
    for t in design.get("tables", []):
        out.append(f"### Table `{t.get('name')}`")
        out.extend(_column_rows(t))
        if t.get("notes"):
            out.append(f"  Notes: {t['notes']}")
        out.append("")
    if rels:
        out.append("### Relations")
        for r in rels:
            a = tmap.get(r.get("fromTable", {}), {}).get("name", "?")
            b = tmap.get(r.get("toTable", {}), {}).get("name", "?")
            out.append(f"  * `{a}` {r.get('kind')} `{b}`")
        out.append("")
    else:
        out.append("_(no relations defined yet)_")
        out.append("")
    return out


def _route_full_block(design: dict) -> list[str]:
    tmap = _table_map(design.get("tables", []))
    mw_by_id = {m["id"]: m for m in design.get("middleware", [])}
    out = ["## Endpoints", ""]
    for rt in design.get("routes", []):
        label = f"{rt.get('method', 'GET')} `{rt.get('path', '/')}`"
        out.append(f"### {label}")
        tbl = tmap.get(rt.get("table"))
        if tbl:
            out.append(f"  Resource table: `{tbl['name']}`")
        mids = [mw_by_id[i] for i in rt.get("middleware", []) if i in mw_by_id]
        if mids:
            for m in mids:
                out.append(f"  Middleware: `{m['name']}` ({m.get('scope', 'route')})")
        if rt.get("summary"):
            out.append(f"  Purpose: {rt['summary']}")
        fbs = rt.get("functionBatches", [])
        if fbs:
            out.append("  Function batches:")
            for i, fb in enumerate(fbs, 1):
                out.append(f"  1. `{fb.get('name')}` — {fb.get('description')}")
        if rt.get("execution"):
            out.append(f"  Execution: {rt['execution']}")
        if not fbs and not rt.get("execution"):
            out.append("  Execution: _(not specified)_")
        out.append("")
    if not design.get("routes"):
        out.append("_(no endpoints defined yet)_")
        out.append("")
    return out


def _middleware_block(design: dict) -> list[str]:
    out = ["## Middleware", ""]
    mids = design.get("middleware", [])
    if not mids:
        out.append("_(none)_")
        out.append("")
        return out
    valid_route_ids = {r["id"] for r in design.get("routes", [])}
    tmap = _table_map(design.get("tables", []))
    path_of = {}
    for r in design.get("routes", []):
        path_of[r["id"]] = r if r["id"] not in path_of else r
    for m in mids:
        scope = m.get("scope", "global")
        out.append(f"### `{m['name']}`  ·  scope: {scope}")
        if m.get("description"):
            out.append(f"  {m['description']}")
        if scope == "routes":
            names = [path_of.get(i, {}).get("path", i)
                     for i in m.get("routes", []) if i in valid_route_ids]
            if names:
                out.append(f"  Applied to: {', '.join(names)}")
        out.append("")
    return out


def _jobs_block(design: dict) -> list[str]:
    out = ["## Scheduled jobs", ""]
    jobs = design.get("jobs", [])
    if not jobs:
        out.append("_(none)_")
        return out
    for j in jobs:
        out.append(f"### `{j.get('name')}`  ·  schedule: {j.get('schedule')}"
                   + (f"  ·  budget: {j.get('duration')}" if j.get("duration") else ""))
        if j.get("execution"):
            out.append(f"  {j['execution']}")
        out.append("")
    return out


def _feedback_block(design: dict) -> list[str]:
    out = ["## Clarifications (from review feedback)", ""]
    fb = [f for f in design.get("feedback", []) if f.get("content")]
    if not fb:
        out.append("_(none — proceed with the spec as written)_")
        return out
    for f in fb:
        out.append(f"* [{f.get('source', 'review')}] {f['content']}")
    return out


# --------------------------------------------------------------------------- #
# Compile entry point
# --------------------------------------------------------------------------- #
def compile_design(design: dict) -> dict[str, Any]:
    design = _clean(design)
    project = design.get("project", {})

    diags: list[Diag] = []
    expand_mentions(design, diags)
    validate(design, diags)

    diagnostics = [d.__dict__ for d in diags]
    errors = [d for d in diags if d.level == "error"]

    # Resolve ids -> display names for clarity in the prompt
    tmap = _table_map(design.get("tables", []))
    for rt in design.get("routes", []):
        rt["_tableName"] = tmap.get(rt["table"], {}).get("name", "") if rt.get("table") else ""
        rt["_middleware"] = [m for m in design.get("middleware", []) if m["id"] in rt.get("middleware", [])]

    sections: list[str] = []
    sections.append(f"# Backend specification — {project.get('name') or 'Untitled'}")
    sections.append("")
    sections.append(f"Architecture: `{project.get('architecture', 'monolithic')}`")
    if project.get("description"):
        sections.append(f"")
        sections.append(f"Overview: {project['description']}")
    if errors:
        err_lines = "  * " + "\n  * ".join(d.message for d in errors)
        sections.append("")
        sections.append("## Compiler diagnostics (must resolve before building)")
        sections.append(err_lines)
    sections.append("")
    sections.extend(_table_definition_block(design))
    sections.extend(_route_full_block(design))
    sections.extend(_middleware_block(design))
    sections.extend(_jobs_block(design))
    sections.extend(_feedback_block(design))
    sections.append("## Build instructions")
    sections.append("")
    sections.append(
        "You are a senior backend engineer. Implement the entire system described above "
        "exactly and completely, using the machine-readable spec embedded at the end of this "
        "message as the source of truth. Resolve every ambiguity yourself or flag it clearly. "
        "Requirements:"
    )
    sections.append("")
    sections.append("  1. Real, runnable code — not pseudocode.")
    sections.append("  2. Schema/migrations matching ALL tables, columns and relations exactly.")
    sections.append("  3. Every endpoint implemented with correct HTTP semantics and the stated "
                    "middleware applied.")
    sections.append("  4. Function batches treated as the internal call graph of each endpoint.")
    sections.append("  5. Scheduled jobs implemented with the stated schedules and budgets.")
    sections.append("  6. Tests covering the critical paths.")
    sections.append("  7. Mention every decision you had to guess, so they can be reviewed.")
    sections.append("")
    sections.append("If any compiler diagnostic is present, fix the design before writing code.")
    sections.append("")
    sections.append("--- machine-readable spec (JSON) ---")
    sections.append(json.dumps(design, indent=2, ensure_ascii=False))

    prompt = "\n".join(sections)

    quiz = build_quiz_prompt(design, prompt)
    feedback_tpl = build_feedback_template(design, prompt)

    compiled_id = uuid.uuid4().hex
    return {
        "formatVersion": FORMAT_VERSION,
        "id": compiled_id,
        "generatedAt": _today(),
        "title": f"{project.get('name') or 'Untitled'} — compiled specification",
        "stats": {
            "tables": len(design.get("tables", [])),
            "columns": sum(len(t.get("columns", [])) for t in design.get("tables", [])),
            "relations": len(design.get("relations", [])),
            "routes": len(design.get("routes", [])),
            "middleware": len(design.get("middleware", [])),
            "jobs": len(design.get("jobs", [])),
        },
        "diagnostics": diagnostics,
        "hasErrors": bool(errors),
        "design": design,
        "prompt": prompt,
        "quizPrompt": quiz,
        "feedbackPromptTemplate": feedback_tpl,
    }


def build_quiz_prompt(design: dict, prompt: str) -> str:
    return (
        "You are acting as a requirements interviewer for the backend spec below.\n\n"
        "1. Read the specification carefully. Think about ambiguities, missing business rules, "
        "edge cases, and choices the spec leaves open (auth, pagination, error codes, validation, "
        "nullable data, race conditions, transaction boundaries, key generation, etc.).\n"
        "2. Generate a SINGLE self-contained HTML file (no external libraries, no CDN, vanilla JS "
        "and inline CSS) that renders an interactive quiz about those open questions. It must:\n"
        "   * contain between 8 and 15 questions;\n"
        "   * support multiple-choice AND free-text questions;\n"
        "   * annotate each question with the source area it refers to (table name, route path, "
        "job or middleware name) taken from the spec;\n"
        "   * have a progress indicator and a submit button that prints a summary of all answers "
        "in a copy-friendly way.\n"
        "3. Return ONLY the HTML document as your output, so it can be saved as quiz.html and "
        "opened directly in a browser.\n\n"
        "The user will answer the quiz and paste the answers back. Those answers will be folded "
        "into the spec as authoritative clarifications.\n\n"
        "--- specification ---\n\n" + prompt
    )


def build_feedback_template(design: dict, prompt: str) -> str:
    return (
        "You are the same senior engineer who reviewed the backend spec below and generated a "
        "quiz from it. The quiz answers (authoritative decisions made by the product owner) are "
        "provided at the end of this message.\n\n"
        "1. Re-read the spec and the answers.\n"
        "2. Fold every answer into the spec as a concrete clarification (update the affected "
        "tables, routes, middleware, or jobs; resolve the ambiguity permanently).\n"
        "3. Output: (a) a short list of the concrete changes you made, and (b) the final "
        "updated spec in the same format as the original, showing every decision you had to "
        "still guess.\n\n"
        "Only guess where the answers genuinely do not cover the question — and say so.\n\n"
        "--- specification ---\n\n" + prompt + "\n\n--- quiz answers ---\n\n{{PASTE_ANSWERS_HERE}}"
    )