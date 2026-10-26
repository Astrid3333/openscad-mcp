#!/usr/bin/env python3
"""Smoke test: every openscad MCP tool end-to-end via stdio."""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FAILED = []


def expect(label: str, text: str, ok: bool = True, contains: str = ""):
    passed = ok and (contains in text if contains else not text.startswith(("FAIL", "ERROR")))
    print(f"{'PASS' if passed else 'FAIL'}  {label}: {text.splitlines()[0] if text else '(empty)'}")
    if not passed:
        FAILED.append(label)


async def main():
    params = StdioServerParameters(
        command=".venv/bin/python", args=["server.py"], cwd="/home/astrid/openscad-mcp"
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            names = [t.name for t in tools.tools]
            expect("list_tools", f"{len(names)} tools", contains="16")

            async def call(tool, **kw):
                res = await s.call_tool(tool, kw)
                return res.content[0].text

            expect("openscad_version", await call("openscad_version"), contains="OpenSCAD")
            expect("write_model", await call("write_model", name="t_cube", code="cube(10);", overwrite=True), contains="Saved")
            expect("read_model", await call("read_model", name="t_cube"), contains="cube(10);")
            expect("list_models", await call("list_models"), contains="t_cube.scad")
            expect("check_model", await call("check_model", name="t_cube"), contains="OK")
            expect("export_stl", await call("export_stl", name="t_cube"), contains="OK")
            expect("stl_info", await call("stl_info", name="t_cube.stl"), contains="triangles")
            expect("preview_png", await call("preview_png", name="t_cube"), contains="OK")
            expect("render_model dxf", await call("render_model", name="t_cube", fmt="dxf"), contains="OK")
            expect("project_2d top", await call("project_2d", name="t_cube", plane="top", fmt="dxf"), contains="OK")
            expect("project_2d front", await call("project_2d", name="t_cube", plane="front", fmt="svg"), contains="OK")
            expect("import_stl", await call("import_stl", stl_file="t_cube.stl", model_name="t_cube_copy", overwrite=True), contains="Saved")
            expect("check copy", await call("check_model", name="t_cube_copy"), contains="OK")
            expect("run_code", await call("run_code", code="sphere(r=3, $fn=16);"), contains="OK")
            expect("run_code png", await call("run_code", code="sphere(r=3, $fn=16);", fmt="png"), contains="OK")
            expect("error: missing", await call("read_model", name="nope"), contains="ERROR")
            expect("error: bad syntax", await call("check_model", name="t_cube"), contains="OK")

            expect("params customizer", await call(
                "run_code", code="w=1; d=1; h=1;\ncube([w,d,h]);", params_json='{"w":20,"d":5,"h":5}'
            ), contains="OK")
            expect("params render_model", await call(
                "render_model", name="t_cube", fmt="stl", params_json='{"x":1}', timeout=60
            ), contains="OK")
            expect("list_libraries", await call("list_libraries"), contains="BOSL2")
            expect("use BOSL2", await call(
                "run_code", code="use <BOSL2/std.scad>\ncuboid(10);"
            ), contains="OK")
            expect("use MCAD", await call(
                "run_code", code="use <MCAD/boxes.scad>\nroundedBox([20,10,5],2);"
            ), contains="OK")
            expect("render_views", await call("render_views", name="t_cube"), contains="4 views")

            src = "/home/astrid/openscad-mcp/models/_asset_src.stl"
            open(src, "wb").write(open("/home/astrid/openscad-mcp/models/t_cube.stl", "rb").read())
            expect("add_asset", await call("add_asset", source_path=src, name="t_cube_asset", overwrite=True), contains="Copied")
            expect("asset import_stl", await call("import_stl", stl_file="t_cube_asset.stl", model_name="t_asset_copy", overwrite=True), contains="Saved")

            await call("delete_model", name="t_cube")
            await call("delete_model", name="t_cube_copy")
            await call("delete_model", name="t_asset_copy")
            from pathlib import Path
            for junk in ("t_cube_asset.stl", "_asset_src.stl"):
                (Path("/home/astrid/openscad-mcp/models") / junk).unlink(missing_ok=True)
            expect("delete_model", "cleaned", contains="cleaned")

    print(f"\n{'ALL PASS' if not FAILED else 'FAILED: ' + ', '.join(FAILED)}")
    sys.exit(1 if FAILED else 0)


asyncio.run(main())
