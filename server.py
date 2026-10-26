#!/usr/bin/env python3
"""OpenSCAD MCP server — write, check, render and export .scad models."""

import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

WORKSPACE = Path(os.environ.get("OPENSCAD_WORKSPACE", Path.home() / "openscad-mcp" / "models"))
WORKSPACE.mkdir(parents=True, exist_ok=True)

LIBRARIES = Path(__file__).resolve().parent / "libraries"
LIBRARIES.mkdir(exist_ok=True)

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
    existing = env.get("OPENSCADPATH", "")
    env["OPENSCADPATH"] = os.pathsep.join(x for x in [str(LIBRARIES), existing] if x)
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


def _issues(text: str) -> str:
    """Append a structured summary of ERROR:/WARNING: lines from OpenSCAD output."""
    errs = [ln for ln in text.splitlines() if ln.startswith("ERROR:")]
    warns = [ln for ln in text.splitlines() if ln.startswith("WARNING:")]
    if not errs and not warns:
        return text
    summary = f"[issues: {len(errs)} error(s), {len(warns)} warning(s)]"
    detail = "\n".join(errs + warns[:5])
    return f"{text}\n{summary}\n{detail}"


def _param_args(params_json: str, param_set: str, tag: str) -> tuple[list[str], Path | None]:
    """Build [-p file, -P set] args from a JSON string of customizer parameters.

    params_json: {"w": 20, "d": 5} or a full customizer file dict.
    Params override TOP-LEVEL variable assignments in the .scad (customizer rules).
    """
    if not params_json.strip():
        return [], None
    import json

    try:
        data = json.loads(params_json)
    except Exception as e:
        raise ValueError(f"params_json is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("params_json must be a JSON object")
    if "parameterSets" in data:
        payload = data
        sets = payload.get("parameterSets", {})
        if not sets:
            raise ValueError("params_json parameterSets is empty")
        param_set = param_set or next(iter(sets))
        if param_set not in sets:
            raise ValueError(f"param_set '{param_set}' not in parameterSets {sorted(sets)}")
    else:
        param_set = param_set or "set"
        payload = {
            "fileFormatVersion": "1",
            "parameterSets": {param_set: data},
            "parameters": {},
        }
    pfile = WORKSPACE / f"_params_{tag}.json"
    pfile.write_text(json.dumps(payload))
    return ["-p", str(pfile), "-P", param_set], pfile


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
    out = _issues((proc.stdout + proc.stderr).strip() or "(no output)")
    return f"{status}\n{out}"


def _export_2d(path: Path, out_path: Path, rotate_cmd: str = "", timeout: int = 300) -> str:
    """Export 2D (DXF/SVG): try source as-is (already 2D), else wrap in projection().

    rotate_cmd: e.g. 'rotate([90,0,0])' applied before projection for front/right views.
    """
    t0 = time.time()
    src_text = path.read_text()
    first = _run_openscad(["-o", str(out_path), path.name], timeout=timeout)
    if first.returncode == 0 and out_path.exists():
        dt = time.time() - t0
        return f"OK: {out_path} ({out_path.stat().st_size} bytes, {dt:.1f}s)\n" + (first.stdout + first.stderr).strip()
    wrapper = WORKSPACE / f"_2d_{path.stem}.scad"
    brace = ""
    if src_text.strip().count("{") != src_text.strip().count("}"):
        brace = "}"
    src_indented = "\n".join("  " + line for line in src_text.splitlines())
    wrapper.write_text(f"projection(cut=false) {rotate_cmd} {{\n{src_indented}\n{brace}\n}}\n")
    try:
        second = _run_openscad(["-o", str(out_path), wrapper.name], timeout=timeout)
        dt = time.time() - t0
        out = (first.stdout + first.stderr + second.stdout + second.stderr).strip()
        if second.returncode != 0 or not out_path.exists():
            return f"FAIL (exit {second.returncode}, {dt:.1f}s)\n{out}"
        return f"OK: {out_path} ({out_path.stat().st_size} bytes, {dt:.1f}s)\n{out}"
    finally:
        wrapper.unlink(missing_ok=True)


@mcp.tool()
def render_model(
    name: str,
    output: str = "",
    fmt: str = "stl",
    img_width: int = 800,
    img_height: int = 600,
    camera: str = "",
    colorscheme: str = "Tomorrow",
    view: str = "",
    projection: str = "",
    autocenter: bool = False,
    viewall: bool = False,
    params_json: str = "",
    param_set: str = "",
    timeout: int = 300,
) -> str:
    """Render a model to STL/OFF/AMF/3MF/DXF/SVG or PNG (fmt='png').

    For PNG: optional camera='translate_x,translate_y,translate_z,rotx,roty,rotz,dist' or '0,0,0,55,0,25,140'.
    view: comma list of 'axes,crosshair,edges,scales,wireframe'. projection: 'ortho'|'perspective'.
    autocenter/viewall fit the model in frame (recommended with viewall=true, camera ignored).
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
    if fmt in {"dxf", "svg"}:
        return _export_2d(path, out_path, timeout=timeout)
    try:
        pargs, pfile = _param_args(params_json, param_set, tag=path.stem)
    except ValueError as e:
        return f"ERROR: {e}"
    args = ["-o", str(out_path), *pargs]
    if fmt == "png":
        args += ["--imgsize", f"{img_width},{img_height}", "--colorscheme", colorscheme]
        if camera:
            args += ["--camera", camera]
        if view:
            args += ["--view", view]
        if projection in {"ortho", "perspective"}:
            args += ["--projection", projection]
        if autocenter:
            args.append("--autocenter")
        if viewall:
            args.append("--viewall")
    t0 = time.time()
    try:
        proc = _run_openscad(args + [path.name], timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"ERROR: render timed out after {timeout}s"
    finally:
        if pfile:
            pfile.unlink(missing_ok=True)
    dt = time.time() - t0
    out = _issues((proc.stdout + proc.stderr).strip())
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
    projection: str = "ortho",
    view: str = "",
    autocenter: bool = True,
    viewall: bool = True,
    timeout: int = 180,
) -> str:
    """Render a PNG preview of the model (isometric, auto-fit by default). Returns the PNG path."""
    return render_model(
        name,
        output=f"{Path(name).stem}_preview.png",
        fmt="png",
        img_width=width,
        img_height=height,
        camera=camera,
        colorscheme=colorscheme,
        projection=projection,
        view=view,
        autocenter=autocenter,
        viewall=viewall,
        timeout=timeout,
    )


@mcp.tool()
def project_2d(name: str, plane: str = "top", fmt: str = "dxf", timeout: int = 120) -> str:
    """Export the 2D projection of a 3D model for laser/CNC (DXF or SVG).

    plane: 'top' (XY), 'front' (XZ) or 'right' (YZ). Writes models/<name>_<plane>.<fmt>.
    """
    planes = {
        "top": "",
        "front": "rotate([90,0,0])",
        "right": "rotate([0,90,0])",
    }
    if plane not in planes:
        return f"ERROR: plane must be one of {sorted(planes)}"
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"dxf", "svg"}:
        return f"ERROR: fmt must be 'dxf' or 'svg'"
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found"
    out_path = WORKSPACE / f"{path.stem}_{plane}.{fmt}"
    try:
        return _export_2d(path, out_path, rotate_cmd=planes[plane], timeout=timeout)
    finally:
        (WORKSPACE / f"_2d_{path.stem}.scad").unlink(missing_ok=True)


@mcp.tool()
def import_stl(stl_file: str, model_name: str, overwrite: bool = False) -> str:
    """Create models/<model_name>.scad that imports an STL already in the workspace.

    Use to embed/modify an existing mesh: the generated file contains import("<stl_file>").
    """
    stl = WORKSPACE / Path(stl_file).name
    if not stl.exists() or stl.suffix.lower() != ".stl":
        return f"ERROR: {stl.name} not found in {WORKSPACE} (only .stl allowed)"
    path = _model_path(model_name)
    if path.exists() and not overwrite:
        return f"ERROR: {path.name} exists; pass overwrite=true"
    path.write_text(f'import("{stl.name}");\n')
    return f"Saved {path} importing {stl.name}"


@mcp.tool()
def stl_info(name: str) -> str:
    """Triangle count, bounding box and format of a .stl in the workspace (no OpenSCAD needed)."""
    path = WORKSPACE / Path(name).name
    if not path.exists() or path.suffix.lower() != ".stl":
        return f"ERROR: {path.name} not found in {WORKSPACE}"
    data = path.read_bytes()
    binary = len(data) >= 84 and 84 + int.from_bytes(data[80:84], "little") * 50 == len(data)
    if binary:
        n = int.from_bytes(data[80:84], "little")
        pts = []
        unpack = struct.Struct("<9f").unpack_from
        for i in range(n):
            tri = unpack(data, 84 + i * 50 + 12)
            pts.append(tri[0:3])
            pts.append(tri[3:6])
            pts.append(tri[6:9])
    else:
        verts = re.findall(rb"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", data)
        n = len(verts) // 3
        pts = [tuple(map(float, v)) for v in verts]
    if not pts:
        return f"{path.name}: no vertices found"
    mins = [min(p[i] for p in pts) for i in range(3)]
    maxs = [max(p[i] for p in pts) for i in range(3)]
    dims = [maxs[i] - mins[i] for i in range(3)]
    fmt_name = "binary" if binary else "ascii"
    return (
        f"{path.name}: {fmt_name} STL, {n} triangles, {path.stat().st_size} bytes\n"
        f"bbox min: ({mins[0]:.2f}, {mins[1]:.2f}, {mins[2]:.2f})\n"
        f"bbox max: ({maxs[0]:.2f}, {maxs[1]:.2f}, {maxs[2]:.2f})\n"
        f"size: {dims[0]:.2f} x {dims[1]:.2f} x {dims[2]:.2f}"
    )


@mcp.tool()
def run_code(code: str, fmt: str = "stl", params_json: str = "", param_set: str = "", timeout: int = 300) -> str:
    """Write ephemeral .scad code, check it, and export the result. No named model saved unless you use write_model.

    Use for quick experiments. On success returns the exported file path and geometry stats from OpenSCAD output.
    params_json: JSON object of customizer params overriding top-level assignments, e.g. '{"w": 20}'.
    """
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"stl", "png", "csg", "off", "3mf", "amf"}:
        return f"ERROR: unsupported fmt '{fmt}'"
    with tempfile.NamedTemporaryFile("w", suffix=".scad", dir=WORKSPACE, delete=False, prefix="_tmp_") as src:
        src.write(code)
        src_path = Path(src.name)
    out_path = src_path.with_suffix(f".{fmt}")
    try:
        try:
            pargs, pfile = _param_args(params_json, param_set, tag=src_path.stem)
        except ValueError as e:
            return f"ERROR: {e}"
        args = ["-o", str(out_path), *pargs]
        if fmt == "png":
            args += ["--imgsize", "800,600", "--camera", "0,0,0,55,0,25,140"]
        t0 = time.time()
        try:
            proc = _run_openscad(args + [src_path.name], timeout=timeout)
        finally:
            if pfile:
                pfile.unlink(missing_ok=True)
        dt = time.time() - t0
        out = _issues((proc.stdout + proc.stderr).strip())
        if proc.returncode != 0 or not out_path.exists():
            return f"FAIL (exit {proc.returncode}, {dt:.1f}s)\n{out}"
        size = out_path.stat().st_size
        return f"OK: {out_path.name} ({size} bytes, {dt:.1f}s)\n{out}"
    finally:
        src_path.unlink(missing_ok=True)


@mcp.tool()
def render_views(name: str, width: int = 800, height: int = 600, timeout: int = 600) -> str:
    """Render iso, front, top and right PNG views of the model in one call (for visual verification).

    Writes models/<name>_iso|front|top|right.png and returns all four paths.
    """
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found"
    cameras = {
        "iso": "0,0,0,55,0,25,140",
        "front": "0,0,0,90,0,0,140",
        "top": "0,0,0,0,0,0,140",
        "right": "0,0,0,90,0,90,140",
    }
    results, failed = [], []
    for label, cam in cameras.items():
        res = render_model(
            name,
            output=f"{path.stem}_{label}.png",
            fmt="png",
            img_width=width,
            img_height=height,
            camera=cam,
            autocenter=True,
            viewall=True,
            timeout=timeout,
        )
        (results if res.startswith("OK") else failed).append(f"{label}: {res.splitlines()[0]}")
    body = "\n".join(results + failed)
    return ("OK: 4 views rendered\n" if not failed else "PARTIAL:\n") + body


@mcp.tool()
def list_libraries() -> str:
    """List available OpenSCAD libraries (OPENSCADPATH dirs + system): use <Lib/file.scad>."""
    seen, lines = set(), []
    env_path = os.environ.get("OPENSCADPATH", "")
    for raw in [str(LIBRARIES), env_path, "/usr/share/openscad/libraries"]:
        for d in (x for x in raw.split(os.pathsep) if x):
            p = Path(d)
            if not p.is_dir() or str(p) in seen:
                continue
            seen.add(str(p))
            libs = sorted(x.name for x in p.iterdir() if x.is_dir() or x.suffix == ".scad")
            lines.append(f"{p}:")
            lines.extend(f"  - {n}" for n in libs)
    return "\n".join(lines) if lines else "No library paths found"


@mcp.tool()
def add_asset(source_path: str, name: str = "", overwrite: bool = False) -> str:
    """Copy a file (stl/3mf/off/dxf/svg/scad/png) from anywhere on this machine into the MCP workspace.

    Then use it by filename: import_stl(name) or in code as import("<name>").
    """
    src = Path(source_path).expanduser()
    if not src.is_file():
        return f"ERROR: {src} not found"
    if src.suffix.lower() not in {".stl", ".3mf", ".off", ".dxf", ".svg", ".scad", ".png"}:
        return f"ERROR: unsupported extension '{src.suffix}'"
    dst = WORKSPACE / (name or src.name)
    if dst.suffix.lower() != src.suffix.lower():
        dst = dst.with_suffix(src.suffix.lower())
    if dst.exists() and not overwrite:
        return f"ERROR: {dst.name} exists; pass overwrite=true"
    shutil.copyfile(src, dst)
    return f"Copied {src} -> {dst} ({dst.stat().st_size} bytes)"


@mcp.tool()
def delete_model(name: str) -> str:
    """Delete a saved .scad model and its common render outputs."""
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found"
    removed = [path.name]
    path.unlink()
    for ext in (".stl", ".png", ".3mf", ".off", ".amf", ".csg", ".dxf", ".svg", ".json"):
        p = WORKSPACE / f"{path.stem}{ext}"
        if p.exists():
            p.unlink()
            removed.append(p.name)
        for extra in WORKSPACE.glob(f"{path.stem}_*{ext}"):
            extra.unlink()
            removed.append(extra.name)
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


@mcp.tool()
def open_in_gui(name: str) -> str:
    """Launch the OpenSCAD GUI with the given .scad file for visual inspection. Non-blocking (returns immediately with the PID)."""
    path = _model_path(name)
    if not path.exists():
        return f"ERROR: {path.name} not found"
    display = os.environ.get("DISPLAY") or ":0"
    env = os.environ.copy()
    env["DISPLAY"] = display
    if LOCAL_BIN.is_dir():
        env["PATH"] = f"{LOCAL_BIN}:{env.get('PATH', '')}"
    try:
        proc = subprocess.Popen(
            [OPENSCAD, str(path)],
            cwd=WORKSPACE,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return f"ERROR: {e}"
    time.sleep(1.5)
    if proc.poll() is not None:
        return f"FAIL: GUI exited immediately with code {proc.returncode} (DISPLAY={display})"
    return f"OK: OpenSCAD GUI pid={proc.pid} showing {path.name} (DISPLAY={display})"


if __name__ == "__main__":
    mcp.run()
