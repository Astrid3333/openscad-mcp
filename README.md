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
| `openscad_version` | Versión del binario y workspace |

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
