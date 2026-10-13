"""Record canvas clicks → MaaFW pipeline JSON draft (stable TemplateMatch preferred)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class RecordStep:
    """One recorded authoring step."""

    kind: str  # click_template | click_xy | wait
    name: str
    x: int = 0
    y: int = 0
    delay_ms: int = 500
    # OR: attach as sibling candidate on previous sequential node's next
    or_with_prev: bool = False
    # template relative path under resource/ (e.g. image/rec_001.png)
    template: str = ""
    threshold: float = 0.7
    desc: str = ""
    roi: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class Recording:
    steps: list[RecordStep] = field(default_factory=list)
    entry_name: str = "RecStart"
    task_label: str = "录制草稿"

    def clear(self) -> None:
        self.steps.clear()

    def add(self, step: RecordStep) -> None:
        self.steps.append(step)


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip()).strip("_")
    return s or "Rec"


def _unique_node(base: str, used: set[str]) -> str:
    name = base
    n = 2
    while name in used:
        name = f"{base}_{n}"
        n += 1
    used.add(name)
    return name


def crop_template_png(
    qimage,
    cx: int,
    cy: int,
    half: int,
    dest: Path,
) -> tuple[str, tuple[int, int, int, int]]:
    """
    Crop around (cx,cy) from a QImage, save PNG.
    Returns (relative hint path name, roi x,y,w,h in image coords).
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage

    if not isinstance(qimage, QImage) or qimage.isNull():
        raise ValueError("no frame")
    w, h = qimage.width(), qimage.height()
    x0 = max(0, cx - half)
    y0 = max(0, cy - half)
    x1 = min(w, cx + half)
    y1 = min(h, cy + half)
    rw, rh = x1 - x0, y1 - y0
    if rw < 8 or rh < 8:
        raise ValueError("crop too small")
    cropped = qimage.copy(QRect(x0, y0, rw, rh))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not cropped.save(str(dest), "PNG"):
        raise OSError(f"save failed: {dest}")
    return dest.name, (x0, y0, rw, rh)


def build_pipeline(rec: Recording) -> dict[str, Any]:
    """
    Convert steps to MaaFW pipeline nodes.

    Sequential: A.next = [B], B.next = [C], ...
    or_with_prev=True: step joins the previous *chain head* next list (OR candidates).
    Stable path: TemplateMatch + Click; fallback: DirectHit + Click target [x,y].
    """
    used: set[str] = set()
    nodes: dict[str, Any] = {}
    if not rec.steps:
        end = _unique_node("RecEnd", used)
        nodes[end] = {"action": {"type": "DoNothing"}, "desc": "empty recording"}
        return nodes

    # Build groups: each group is a list of OR-siblings that share one next pointer target
    groups: list[list[RecordStep]] = []
    for st in rec.steps:
        if st.or_with_prev and groups:
            groups[-1].append(st)
        else:
            groups.append([st])

    entry = _unique_node(_slug(rec.entry_name), used)
    end = _unique_node("RecEnd", used)
    nodes[end] = {
        "desc": "录制结束",
        "action": {"type": "DoNothing"},
    }

    group_entry_names: list[str] = []
    for gi, group in enumerate(groups):
        names_in_group: list[str] = []
        for si, st in enumerate(group):
            base = _slug(st.name) or f"Step{gi}_{si}"
            node_name = _unique_node(base, used)
            names_in_group.append(node_name)
            node: dict[str, Any] = {"desc": st.desc or st.name, "post_delay": int(st.delay_ms)}
            if st.kind == "wait":
                node["action"] = {"type": "DoNothing"}
            elif st.kind == "click_template" and st.template:
                # Prefer TemplateMatch (stable). Filename relative to resource/image/.
                tpl = st.template.replace("\\", "/")
                if "/" in tpl:
                    tpl = tpl.rsplit("/", 1)[-1]
                roi = list(st.roi) if st.roi and st.roi != (0, 0, 0, 0) else [0, 0, 0, 0]
                node["recognition"] = {
                    "type": "TemplateMatch",
                    "param": {
                        "template": tpl,
                        "threshold": float(st.threshold),
                        "roi": roi,
                    },
                }
                node["action"] = {"type": "Click"}
            else:
                # Absolute click — less stable across resolution; use as fallback.
                node["recognition"] = {"type": "DirectHit"}
                node["action"] = {
                    "type": "Click",
                    "param": {"target": [int(st.x), int(st.y)]},
                }
                node["desc"] = (node["desc"] + f" @({st.x},{st.y})").strip()
            nodes[node_name] = node
        group_entry_names.append(names_in_group[0] if len(names_in_group) == 1 else names_in_group)

    # Wire next pointers
    # First group: if multiple OR, create RecStart that nexts to all; else entry is that node
    # Simpler: always create entry node that nexts to first group's candidates
    first = group_entry_names[0]
    if isinstance(first, list):
        nodes[entry] = {
            "desc": "录制入口（OR：谁先识别到走谁）",
            "recognition": {"type": "DirectHit"},
            "action": {"type": "DoNothing"},
            "next": list(first),
            "post_delay": 0,
        }
        # each OR sibling points to next group or end
        next_target = _next_target(group_entry_names, 0, end)
        for n in first:
            nodes[n]["next"] = next_target
        pipeline_entry = entry
    else:
        # single node — use it as entry (rename mentally)
        pipeline_entry = first
        # If entry name differs, alias: keep entry pointing to first
        if first != entry:
            nodes[entry] = {
                "desc": "录制入口",
                "recognition": {"type": "DirectHit"},
                "action": {"type": "DoNothing"},
                "next": [first],
                "post_delay": 0,
            }
            pipeline_entry = entry
        next_target = _next_target(group_entry_names, 0, end)
        nodes[first]["next"] = next_target

    for gi in range(1, len(group_entry_names)):
        g = group_entry_names[gi]
        nxt = _next_target(group_entry_names, gi, end)
        if isinstance(g, list):
            for n in g:
                nodes[n]["next"] = nxt
        else:
            nodes[g]["next"] = nxt

    # Ensure entry key exists for task registration
    if entry not in nodes and pipeline_entry in nodes:
        pass
    return nodes


def _next_target(group_entry_names: list, gi: int, end: str) -> list[str]:
    if gi + 1 >= len(group_entry_names):
        return [end]
    nxt = group_entry_names[gi + 1]
    if isinstance(nxt, list):
        return list(nxt)
    return [nxt]


def export_pipeline(
    project_root: Path,
    rec: Recording,
    *,
    filename: Optional[str] = None,
    register_task: bool = True,
    save_meta: bool = True,
) -> dict[str, Any]:
    """
    Write resource/pipeline/<file>.json and optionally append task to interface.json.
    Returns {pipeline_path, entry, task_name, nodes}.
    """
    project_root = Path(project_root)
    pipe_dir = project_root / "resource" / "pipeline"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = filename or f"recorded_{stamp}.json"
    if not fname.endswith(".json"):
        fname += ".json"
    nodes = build_pipeline(rec)
    # Determine entry: prefer RecStart-like key
    entry = rec.entry_name if rec.entry_name in nodes else next(iter(nodes))
    for k, v in nodes.items():
        if k.startswith("RecStart") or (v.get("desc") or "").startswith("录制入口"):
            entry = k
            break

    out_path = pipe_dir / fname
    out_path.write_text(json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    task_name = rec.task_label or "录制草稿"
    if register_task:
        _register_task(project_root, task_name=task_name, entry=entry, desc=f"由编辑·录制导出 {fname}")

    if save_meta:
        meta = {
            "when": datetime.now().isoformat(timespec="seconds"),
            "entry": entry,
            "file": fname,
            "steps": [asdict(s) for s in rec.steps],
        }
        (pipe_dir / (fname.replace(".json", ".record.json"))).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return {
        "pipeline_path": str(out_path.resolve()),
        "entry": entry,
        "task_name": task_name,
        "nodes": nodes,
    }


def _register_task(project_root: Path, *, task_name: str, entry: str, desc: str) -> None:
    iface_path = project_root / "interface.json"
    if not iface_path.is_file():
        return
    data = json.loads(iface_path.read_text(encoding="utf-8"))
    tasks = data.setdefault("task", [])
    # replace same name or append
    for t in tasks:
        if t.get("name") == task_name or t.get("entry") == entry:
            t["name"] = task_name
            t["label"] = task_name
            t["entry"] = entry
            t["description"] = desc
            break
    else:
        tasks.append(
            {
                "name": task_name,
                "label": task_name,
                "entry": entry,
                "description": desc,
            }
        )
    iface_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
