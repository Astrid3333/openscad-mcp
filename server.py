#!/usr/bin/env python3
"""OpenSCAD MCP server — write, check, render and export .scad models."""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

WORKSPACE = Path(os.environ.get("OPENSCAD_WORKSPACE", Path.home() / "openscad-mcp" / "models"))
WORKSPACE.mkdir(parents=True, exist_ok=True)

OPENSCAD = shutil.which("openscad") or "/usr/bin/openscad"
LOCAL_BIN = Path(__file__).resolve().parent / "bin"
mcp = FastMCP(
    "openscad",
    instructions=(
        "OpenSCAD solid-modeling tools. Write parametric CAD with .scad code, "
        "validate syntax, render PNG previews, and export STL/3MF/OFF/DXF/SVG."
    ),
)


def _model_path(name: str) -> Path:
    name = name.removesuffix(".scad")
    if "/" in name or name.startswith("."):
        raise ValueError("name must be a plain filename without directories")
    return WORKSPACE / f"{name}.scad"


def _run_openscad(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = [OPENSCAD, *args]
    env = os.environ.copy()
    if LOCAL_BIN.is_dir():
        env["PATH"] = f"{LOCAL_BIN}:{env.get('PATH', '')}"
    xvfb = shutil.which("xvfb-run", path=env["PATH"])
    if not env.get("DISPLAY") and xvfb:
        cmd = [xvfb, "-a", *cmd]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=WORKSPACE,
        env=env,
    )


@mcp.tool()
def list_models() -> str:
    """List .scad models saved in the workspace."""
    files = sorted(WORKSPACE.glob("*.scad"))
    if not files:
        return f"No models in {WORKSPACE}"
    lines = []
    for f in files:
        lines.append(f"{f.name}  ({f.stat().st_size} bytes, mtime {time.strftime('%Y-%m-%d %H:%M', time.localtime(f.stat().st_mtime))})")
    return "\n".join(lines)


@mcp.tool()
def write_model(name: str, code: str, overwrite: bool = False) -> str:
    """Write OpenSCAD source to models/<name>.scad. code is full .scad source."""
    path = _model_path(name)
    if path.exists() and not overwrite:
        return f"ERROR: {path.name} exists; pass overwrite=true"
    path.write_text(code)
    return f"Saved {path} ({len(code)} bytes)"


@mcp.tool()
def read_model(name: str) -> str:
    """Read the source of a saved .scad model."""
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found. Use list_models."
    return path.read_text()


@mcp.tool()
def check_model(name: str, timeout: int = 60) -> str:
    """Validate a .scad model (syntax/geometry) WITHOUT exporting. Cheap; use before rendering."""
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found"
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=True) as tmp:
        proc = _run_openscad(["-o", tmp.name, path.name], timeout=timeout)
    status = "OK" if proc.returncode == 0 else f"FAIL (exit {proc.returncode})"
    out = (proc.stdout + proc.stderr).strip() or "(no output)"
    return f"{status}\n{out}"


@mcp.tool()
def render_model(
    name: str,
    output: str = "",
    fmt: str = "stl",
    img_width: int = 800,
    img_height: int = 600,
    camera: str = "",
    colorscheme: str = "Tomorrow",
    timeout: int = 300,
) -> str:
    """Render a model to STL/OFF/AMF/3MF or PNG (fmt='png').

    For PNG: optional camera='translate_x,translate_y,translate_z,rotx,roty,rotz,dist' or '0,0,0,55,0,25,140'.
    Output lands in the models workspace. Returns the path and any warnings.
    """
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found"
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"stl", "off", "amf", "3mf", "png", "csg", "dxf", "svg"}:
        return f"ERROR: unsupported fmt '{fmt}'"
    out_name = output or f"{path.stem}.{fmt}"
    out_path = WORKSPACE / out_name
    args = ["-o", str(out_path)]
    if fmt == "png":
        args += ["--imgsize", f"{img_width},{img_height}", "--colorscheme", colorscheme]
        if camera:
            args += ["--camera", camera]
    t0 = time.time()
    try:
        proc = _run_openscad(args + [path.name], timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"ERROR: render timed out after {timeout}s"
    dt = time.time() - t0
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0 or not out_path.exists():
        return f"FAIL (exit {proc.returncode}, {dt:.1f}s)\n{out}"
    size = out_path.stat().st_size
    return f"OK: {out_path} ({size} bytes, {dt:.1f}s)\n{out}"


@mcp.tool()
def export_stl(name: str, output: str = "", timeout: int = 300) -> str:
    """Export model to STL (binary). Convenience wrapper around render_model."""
    return render_model(name, output=output or f"{Path(name).stem}.stl", fmt="stl", timeout=timeout)


@mcp.tool()
def preview_png(
    name: str,
    width: int = 800,
    height: int = 600,
    camera: str = "0,0,0,55,0,25,140",
    colorscheme: str = "Tomorrow",
    timeout: int = 180,
) -> str:
    """Render a PNG preview of the model (default isometric camera). Returns the PNG path."""
    return render_model(
        name,
        output=f"{Path(name).stem}_preview.png",
        fmt="png",
        img_width=width,
        img_height=height,
        camera=camera,
        colorscheme=colorscheme,
        timeout=timeout,
    )


@mcp.tool()
def run_code(code: str, fmt: str = "stl", timeout: int = 300) -> str:
    """Write ephemeral .scad code, check it, and export the result. No named model saved unless you use write_model.

    Use for quick experiments. On success returns the exported file path and geometry stats from OpenSCAD output.
    """
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"stl", "png", "csg", "off", "3mf", "amf"}:
        return f"ERROR: unsupported fmt '{fmt}'"
    with tempfile.NamedTemporaryFile("w", suffix=".scad", dir=WORKSPACE, delete=False, prefix="_tmp_") as src:
        src.write(code)
        src_path = Path(src.name)
    out_path = src_path.with_suffix(f".{fmt}")
    try:
        args = ["-o", str(out_path)]
        if fmt == "png":
            args += ["--imgsize", "800,600", "--camera", "0,0,0,55,0,25,140"]
        t0 = time.time()
        proc = _run_openscad(args + [src_path.name], timeout=timeout)
        dt = time.time() - t0
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0 or not out_path.exists():
            return f"FAIL (exit {proc.returncode}, {dt:.1f}s)\n{out}"
        size = out_path.stat().st_size
        return f"OK: {out_path.name} ({size} bytes, {dt:.1f}s)\n{out}"
    finally:
        src_path.unlink(missing_ok=True)


@mcp.tool()
def delete_model(name: str) -> str:
    """Delete a saved .scad model and its common render outputs."""
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found"
    removed = [path.name]
    path.unlink()
    for ext in (".stl", ".png", ".3mf", ".off", ".amf", ".csg"):
        p = WORKSPACE / f"{path.stem}{ext}"
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return "Deleted: " + ", ".join(removed)


@mcp.tool()
def openscad_version() -> str:
    """Return the OpenSCAD binary version and the models workspace path."""
    try:
        proc = subprocess.run([OPENSCAD, "--version"], capture_output=True, text=True, timeout=10)
        ver = (proc.stdout + proc.stderr).strip()
    except Exception as e:
        ver = f"ERROR: {e}"
    return f"{ver}\nworkspace: {WORKSPACE}\nbinary: {OPENSCAD}"


if __name__ == "__main__":
    mcp.run()
