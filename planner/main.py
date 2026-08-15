"""Planner — GUI-to-prompt compiler for backend design. FastAPI monolith."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.compiler import compile_design

BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="Planner", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


class CompileRequest(BaseModel):
    design: dict


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health():
    return JSONResponse({"ok": True, "service": "planner"})


@app.post("/api/compile")
def api_compile(body: CompileRequest):
    """Compile a Planner design into the deterministic JSON prompt bundle."""
    try:
        compiled = compile_design(body.design)
    except Exception as exc:  # pragma: no cover - defensive
        return JSONResponse({"ok": False, "error": f"compile failed: {exc}"}, status_code=400)
    return JSONResponse({"ok": True, "compiled": compiled})


@app.get("/api/example")
def api_example():
    """A small example design so the builder starts with something concrete."""
    with open(BASE / "app" / "example_design.json", encoding="utf-8") as fh:
        return JSONResponse({"ok": True, "design": json.load(fh)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)