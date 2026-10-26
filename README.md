# [![tests](https://github.com/Astrid3333/openscad-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/Astrid3333/openscad-mcp/actions/workflows/test.yml)
# openscad-mcp

MCP server para OpenSCAD: escribir, validar, renderizar y exportar modelos paramétricos `.scad`.

## Herramientas

| Tool | Descripción |
|------|-------------|
| `write_model` / `read_model` / `list_models` / `delete_model` | Gestión de modelos en `models/` |
| `check_model` | Validación barata (sintaxis/geometría) sin exportar |
| `render_model` | Exporta STL/3MF/OFF/AMF/CSG/PNG |
| `export_stl` | STL binario (wrapper de `render_model`) |
| `preview_png` | PNG isométrico (cámara configurable) |
| `run_code` | Código efímero → check + export en una llamada |
| `project_2d` | Proyección top/front/right → DXF/SVG (laser/CNC) |
| `import_stl` | Genera .scad que importa un STL del workspace |
| `stl_info` | Triángulos + bounding box de un STL |
| `render_views` | iso+front+top+right en 4 PNG (1 llamada) |
| `list_libraries` | Bibliotecas disponibles (BOSL2, MCAD…) |
| `add_asset` | Copia STL/SCAD/etc desde cualquier ruta al workspace |
| `open_in_gui` | Abre el .scad en el GUI de OpenSCAD (no bloqueante, devuelve PID) |
| `openscad_version` | Versión del binario y workspace |

`render_model`/`preview_png` aceptan `camera`, `view` (axes, wireframe…), `projection` (ortho/perspective), `autocenter` y `viewall` para PNG.

**Parámetros customizer**: `render_model`/`run_code` aceptan `params_json='{"w":20,"d":5}'` y `param_set` (genera un parameterSets JSON y pasa `-p/-P`). Los parámetros sobreescriben variables de nivel superior del `.scad`.

```scad
w=10; d=5; h=5;
cube([w,d,h]);
```

**Bibliotecas**: `use <BOSL2/std.scad>` / `use <MCAD/boxes.scad>` funcionan directo.
BOSL2 no va en git: `git clone --depth 1 https://github.com/BelfrySCAD/BOSL2.git libraries/BOSL2`.

Tests: `.venv/bin/python tests.py` (smoke test de las 16 herramientas).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install 'mcp[cli]<2'
.venv/bin/python server.py   # stdio
```

Requiere OpenSCAD (`/usr/bin/openscad`). Para renders PNG sin display, si hay `xvfb-run` en PATH (o en `bin/`) se usa automáticamente.

## opencode

```json
"mcp": {
  "openscad": {
    "type": "local",
    "command": ["/bin/bash", "-lc", "cd /ruta/openscad-mcp && exec .venv/bin/python server.py"],
    "enabled": true
  }
}
```
