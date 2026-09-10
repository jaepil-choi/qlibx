"""Render a spine stepper from curated scenes and the traces they cite.

    uv run python experiments/exp_230_the_spine_trace/render.py SCENES.py TRACES_DIR OUT.html

`SCENES.py` is a Python module (executed, not imported) that defines `HEADER`, `MAP`, `SCENES`
and `TABLE`. A frame names the trace and the call index it stands on; this script fills in the
frame's `loc` (the definition line the profiler recorded), `fn` (the qualified name, unless the
frame says otherwise), `ev` (`#idx` and `ms` from the trace) and `code` (the source lines at that
definition, read from the tree the traces were taken on). What a frame *says* -- its title, its
prose, the state it leaves -- is the author's, written after reading the trace. Nothing here
invents a number.

The page's CSS and JS are the previous stepper's
(`docs/walkthroughs/2026-09-07-spine-stepper-0.6.0.html`), with the header, the map, the scenes
and the closing table replaced.
"""

# ruff: noqa: E501 -- the JS and HTML templates below are one line each on purpose

from __future__ import annotations

import html as html_module
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "docs" / "walkthroughs" / "2026-09-07-spine-stepper-0.6.0.html"


def load_scenes(path: Path) -> dict:
    # The module sees the tree the traces were taken on, so a frame can quote a source window
    # by an anchor line (`at(file, needle, n)`) instead of a line number that drifts.
    namespace: dict = {"__file__": str(path), "REPO": REPO}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


def source_lines(file: str, start: int, count: int) -> list[str]:
    lines = (REPO / file).read_text(encoding="utf-8").splitlines()
    return [line.rstrip() for line in lines[start - 1 : start - 1 + count]]


def esc(text: str) -> str:
    return html_module.escape(text, quote=False)


def display_path(file: str) -> str:
    """The tree's own files by their repo-relative path; the author's by `sample/<name>`.

    The profiler records the author's components under the traced project directory, which is
    a scratch path nobody needs to see; the file's name is what identifies it.
    """
    if file.startswith(("src/", "experiments/", "tests/")):
        return file
    return f"sample/{Path(file).name}"


def resolve_frame(spec: dict, traces: dict[str, dict]) -> dict:
    trace = traces[spec["trace"]]
    call = trace["calls"][spec["idx"]]
    assert call["idx"] == spec["idx"], (spec["trace"], spec["idx"])
    frame: dict = {
        "loc": f"{display_path(call['file'])}:{call['line']}",
        "fn": spec.get("fn", call["qualname"]),
        "ev": {
            "idx": call["idx"],
            "ms": call["ms"] if call["ms"] is None else round(call["ms"], 1),
        },
        "title": spec["title"],
        "what": spec["what"],
    }
    if "n" in spec:
        frame["ev"]["n"] = spec["n"]
    code = spec.get("code", ("def", 8))
    if code is None:
        pass
    elif isinstance(code, list):
        frame["code"] = code
    else:
        anchor, count = code
        start = call["line"] if anchor == "def" else int(anchor)
        frame["code"] = source_lines(call["file"], start, count)
    for key in ("mem", "disk", "clock", "tip", "caution"):
        if key in spec:
            frame[key] = spec[key]
    if spec.get("author") or call.get("author"):
        frame["author"] = True
    return frame


def scene_js(scene: dict, traces: dict[str, dict]) -> str:
    frames = [resolve_frame(frame, traces) for frame in scene["frames"]]
    payload = {
        "id": scene["id"],
        "key": scene["key"],
        "title": scene["title"],
        "sub": scene["sub"],
        "frames": frames,
        "remember": scene.get("remember", []),
    }
    return "S.push(" + json.dumps(payload, ensure_ascii=False) + ");\n"


def map_js(map_spec: list) -> str:
    out = [
        "function buildMap(){",
        "  const map = $('map');",
        "  const mk = (i, k, t, s) => { const b=document.createElement('button'); b.className='node'; b.dataset.s=i; b.innerHTML=`<div class=\"k\">${k}</div><div class=\"t\">${t}</div><div class=\"s\">${s}</div>`; b.addEventListener('click',()=>go(i,0)); return b; };",
        "  const arrow = ()=>{ const d=document.createElement('div'); d.className='arrow'; d.textContent='→'; return d; };",
    ]
    index = 0
    first = True
    for item in map_spec:
        if isinstance(item, dict) and "loop" in item:
            if not first:
                out.append("  map.appendChild(arrow());")
            out.append("  const loop=document.createElement('div'); loop.className='loop';")
            for j, (key, title, sub) in enumerate(item["loop"]):
                if j:
                    out.append("  loop.appendChild(arrow());")
                out.append(
                    f"  loop.appendChild(mk({index},{json.dumps(key, ensure_ascii=False)},{json.dumps(title, ensure_ascii=False)},{json.dumps(sub, ensure_ascii=False)}));"
                )
                index += 1
            out.append("  map.appendChild(loop);")
        else:
            key, title, sub = item
            if not first:
                out.append("  map.appendChild(arrow());")
            out.append(
                f"  map.appendChild(mk({index},{json.dumps(key, ensure_ascii=False)},{json.dumps(title, ensure_ascii=False)},{json.dumps(sub, ensure_ascii=False)}));"
            )
            index += 1
        first = False
    out.append("}")
    return "\n".join(out) + "\n"


def header_html(header: dict) -> str:
    facts = "".join(
        f'<div class="fact"><div class="k">{f["k"]}</div><div class="v">{f["v"]}</div><div class="s">{f["s"]}</div></div>'
        for f in header["facts"]
    )
    return (
        f'<main>\n<div class="eyebrow">{header["eyebrow"]}</div>\n'
        f'<h1>{header["h1"]}</h1>\n<p class="lede">{header["lede"]}</p>\n\n'
        f'<div class="facts">{facts}</div>\n'
        f'<div class="fix">{header["fix"]}</div>\n\n'
    )


def table_html(table: dict) -> str:
    rows = "".join(
        f'<tr><td>{r[0]}</td><td class="num">{r[1]}</td><td>{r[2]}</td></tr>' for r in table["rows"]
    )
    return (
        f'<h2>{table["title"]}</h2>\n<div class="tablewrap"><table>\n'
        f"<tr><th>관측</th><th>증거 (트레이스)</th><th>뜻</th></tr>\n{rows}\n</table></div>\n"
    )


def render(scenes_path: Path, traces_dir: Path, out: Path) -> None:
    spec = load_scenes(scenes_path)
    template = TEMPLATE.read_text(encoding="utf-8")
    traces = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(traces_dir.glob("*.json"))
    }

    head_end = template.index("<main>")
    head = template[:head_end]
    head = head.replace(
        "<title>vqapr 0.6.0 척추 디버거</title>", f"<title>{spec['HEADER']['title']}</title>"
    )
    map_start = template.index("<h2>척추 지도")
    table_start = template.index("<h2>트레이스가 확인한 것")
    script_start = template.index("<script>")
    middle = template[map_start:table_start]
    script = template[script_start:]
    data_start = script.index("const S = [];\n") + len("const S = [];\n")
    data_end = script.index("const $ = id =>")
    map_fn_start = script.index("function buildMap(){")
    map_fn_end = script.index("function buildTabs(){")
    script_prefix = script[:data_start]
    script_between = script[data_end:map_fn_start]
    script_suffix = script[map_fn_end:]
    script_suffix = script_suffix.replace("vqapr-stepper-041", spec["HEADER"]["storage_key"])

    scenes = "".join(scene_js(scene, traces) for scene in spec["SCENES"])
    page = (
        head
        + header_html(spec["HEADER"])
        + middle
        + table_html(spec["TABLE"])
        + script_prefix
        + scenes
        + script_between
        + map_js(spec["MAP"])
        + script_suffix
    )
    out.write_text(page, encoding="utf-8", newline="\n")
    frames = sum(len(scene["frames"]) for scene in spec["SCENES"])
    print(f"wrote {out} ({len(page):,} bytes): {len(spec['SCENES'])} scenes, {frames} frames")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: render.py SCENES.py TRACES_DIR OUT.html")
    render(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
