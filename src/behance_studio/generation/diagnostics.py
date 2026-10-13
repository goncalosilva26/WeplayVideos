"""Section diagnostics: why every image ended up where it is.

Written after each generation to ``<project>/Diagnostics/``:

* ``sections-<date-time>.txt`` / ``.json`` and a copy as ``latest.txt`` /
  ``latest.json`` (the last 10 runs are kept);
* one line per image in the log file as well.

For every image: the imported path, the section its folder names (if any),
the measured (heuristic) type, the AI result and what was done with it
(applied / not applied / rejected, with the reason), the final type and who
decided it, the intended section and whether it came from the folder or
from content analysis — and, per proposal, where it was placed. Any image
shown outside its intended section is listed as a violation.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from behance_studio.core.fsutil import atomic_write_json, atomic_write_text
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

KEEP_RUNS = 10


def _asset_record(asset, assignment) -> dict[str, Any]:
    from behance_studio.assets.folders import folder_parts

    a = asset.analysis or {}
    fmap = assignment.folder_map if assignment is not None else None
    folder_section = fmap.by_asset.get(asset.id) if fmap is not None else None
    placement = assignment.placements.get(asset.id) if assignment is not None else None
    heuristic = a.get("classification") or {}
    ai = a.get("ai") or {}
    if asset.user_kind:
        source = "user"
    elif asset.kind_source == "ai":
        source = "ai"
    else:  # measured heuristics; "fallback" when the model answered but was not applied
        source = "measured (AI not applied)" if ai.get("kind") else "measured"
    parts = folder_parts(asset)
    root = fmap.root.split("/") if fmap is not None and fmap.root else []
    if root and parts[: len(root)] == root:
        parts = parts[len(root):]
    return {
        "asset_id": asset.id,
        "file": "/".join(parts + [asset.filename]),
        "source_folder": "/".join(folder_parts(asset)),
        "imported_from": asset.source_path,
        "sha256": asset.sha256,
        "folder_section": folder_section.to_dict() if folder_section else None,
        "measured_type": {"kind": heuristic.get("kind", asset.kind if asset.kind_source == "heuristic" else None),
                          "confidence": heuristic.get("confidence"), "reasons": heuristic.get("reasons", [])[:4]},
        "ai": {k: ai.get(k) for k in ("kind", "presentation", "confidence", "description", "model", "decision", "applied",
                                      "rejected", "from_cache", "last_attempt") if k in ai} or {"decision": "not run"},
        "final_type": asset.effective_kind,
        "type_source": source,
        "ai_influence": ai_influence(asset),
        "intended_section": placement.to_dict() if placement else None,
        "placements": [],
    }


def ai_influence(asset) -> list[str]:
    """What the vision model's answer changes in the layouts for this image."""
    from behance_studio.ai.vision import cover_score, nature_from_ai, subject_box
    from behance_studio.assets.understanding import AMBIGUOUS_KINDS

    out = []
    if asset.kind_source == "ai" and not asset.user_kind:
        out.append("type")
    if asset.effective_kind in AMBIGUOUS_KINDS and nature_from_ai(asset):
        out.append("presentation (crop or stage)")
    if subject_box(asset):
        out.append("crop focus")
    if cover_score(asset) is not None:
        out.append("ranking (cover / lead images)")
    return out


def build_report(project, assets, assignment, proposals, ai_note: str = "") -> dict[str, Any]:
    """Diagnostics as a dictionary (see module docstring)."""
    from behance_studio.layout.families import family_info
    from behance_studio.planning.fit import placement_violations

    usable = [a for a in assets if a.is_visual and not a.excluded]
    records = {a.id: _asset_record(a, assignment) for a in usable}
    runs = []
    for name, proposal in proposals:
        plan = proposal.plan
        modules = {s.plan_id: s.meta.get("module", s.pattern) for s in proposal.presentation.sections if s.plan_id}
        rendered = {b.asset_id for s in proposal.presentation.sections for b in s.blocks if b.asset_id}
        sections = []
        for index, sp in enumerate(plan.sections):
            module = modules.get(sp.id) or sp.meta.get("module", "")
            for aid in sp.asset_ids:
                if aid in records:
                    records[aid]["placements"].append({"proposal": name, "section": sp.title, "section_type": sp.type,
                                                       "section_index": index, "module": module, "rendered": aid in rendered})
            sections.append({"title": sp.title, "type": sp.type, "module": module, "folder_section": sp.meta.get("folder_section"),
                             "images": [records[a]["file"] if a in records else a for a in sp.asset_ids]})
        violations = [{"file": records[a]["file"] if a in records else a, "shown_in": shown, "belongs_to": wanted}
                      for a, shown, wanted in placement_violations(plan, plan.asset_sections or {})]
        not_rendered = sorted({records[a]["file"] for s in plan.sections for a in s.asset_ids if a in records and a not in rendered})
        cover = next((s.asset_ids[0] for s in plan.sections if s.type == "cover" and s.asset_ids), None)
        runs.append({"cover": records[cover]["file"] if cover in records else None,
                     "proposal": name, "family": family_info(proposal.spec.family).name,
                     "director": proposal.sources.get("director", ""), "sections": sections,
                     "violations": violations, "planned_but_not_rendered": not_rendered})
    return {
        "project": project.name,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sections_from": "folders" if assignment is not None and assignment.by_folders else "content",
        "folder_root": assignment.folder_map.root if assignment is not None and assignment.folder_map else "",
        "folder_sections": [s.to_dict() for s in (assignment.folder_map.sections if assignment and assignment.folder_map else [])],
        "ai": ai_note,
        "notes": list(assignment.notes) if assignment is not None else [],
        "assets": list(records.values()),
        "proposals": runs,
    }


def _short(text: Any, n: int) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"Behance Studio — section diagnostics — {report['generated_at']} — project “{report['project']}”",
        f"Sections from: {'your folders' if report['sections_from'] == 'folders' else 'content analysis (AI / measured types)'}"
        + (f" (project folder “{report['folder_root']}” skipped)" if report.get("folder_root") else ""),
        f"AI: {report['ai'] or 'not used'}",
    ]
    lines += [f"Note: {n}" for n in report.get("notes", [])]
    influence: dict[str, int] = {}
    for r in report["assets"]:
        for k in r.get("ai_influence", []):
            influence[k] = influence.get(k, 0) + 1
    if influence:
        lines.append("AI influence on the layouts: " + ", ".join(f"{k} for {v} image(s)" for k, v in influence.items()))
    elif report.get("ai") and report["ai"] != "not used":
        lines.append("AI influence on the layouts: none (no answer was confident and consistent enough to use)")
    if report.get("folder_sections"):
        lines.append("Folder sections: " + " › ".join(s["title"] for s in report["folder_sections"]))
    lines += ["", f"{'FILE':<44} {'FOLDER SECTION':<16} {'MEASURED':<12} {'AI RESULT':<26} {'FINAL TYPE (DECIDED BY)':<34} INTENDED SECTION"]
    for r in report["assets"]:
        fs = (r["folder_section"] or {}).get("title", "—")
        ai = r["ai"]
        ai_text = f"{ai.get('kind')} {float(ai.get('confidence') or 0):.2f}" if ai.get("kind") else "—"
        if ai.get("kind"):
            ai_text += " ✓" if ai.get("applied") else " ✗"
            if ai.get("from_cache"):
                ai_text += " (cache)"
        intended = r["intended_section"] or {}
        lines.append(f"{_short(r['file'], 44):<44} {_short(fs, 16):<16} {_short(r['measured_type'].get('kind') or '—', 12):<12} "
                     f"{_short(ai_text, 26):<26} {_short(r['final_type'] + ' (' + r['type_source'] + ')', 34):<34} "
                     f"{intended.get('title', '—')} ({intended.get('source', '—')})")
    lines += ["", "Decisions and reasons:"]
    for r in report["assets"]:
        decision = r["ai"].get("decision")
        reasons = (r["intended_section"] or {}).get("reasons", [])
        retry = f" (latest attempt {r['ai']['last_attempt']})" if r["ai"].get("last_attempt") else ""
        used = f"; AI used for: {', '.join(r['ai_influence'])}" if r.get("ai_influence") else ""
        lines.append(f"  {r['file']}: AI {decision or 'not run'}{retry}{used}; section: {'; '.join(reasons) or '—'}")
    lines += ["", "Layout placement:"]
    for run in report["proposals"]:
        ok = not run["violations"] and not run["planned_but_not_rendered"]
        lines.append(f"  {run['proposal']} ({run['family']}, director: {run['director'] or '—'}, cover: {run.get('cover') or 'logo'}) — "
                     + ("all images in their intended sections" if ok else
                        f"{len(run['violations'])} misplaced, {len(run['planned_but_not_rendered'])} not rendered"))
        for sec in run["sections"]:
            if sec["images"]:
                lines.append(f"      {_short(sec['title'], 22):<22} [{sec['module']}] {', '.join(_short(i.split('/')[-1], 24) for i in sec['images'])}")
        for v in run["violations"]:
            lines.append(f"      ✗ {v['file']} shown in “{v['shown_in']}”, belongs to “{v['belongs_to']}”")
        for f in run["planned_but_not_rendered"]:
            lines.append(f"      ✗ {f} planned but not rendered")
    return "\n".join(lines) + "\n"


def write_report(project, report: dict[str, Any]) -> Path:
    folder = project.root / "Diagnostics"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    text = render_text(report)
    for name in (f"sections-{stamp}", "latest"):
        atomic_write_json(folder / f"{name}.json", report)
        atomic_write_text(folder / f"{name}.txt", text)
    runs = sorted(folder.glob("sections-*.json"))
    for old in runs[:-KEEP_RUNS]:
        for path in (old, old.with_suffix(".txt")):
            try:
                path.unlink()
            except OSError:
                pass
    for r in report["assets"]:
        log.info("Section diagnostics: %s | folder section %s | AI %s | type %s (%s) | intended %s",
                 r["file"], (r["folder_section"] or {}).get("title", "—"), r["ai"].get("decision", "not run"), r["final_type"],
                 r["type_source"], (r["intended_section"] or {}).get("title", "—"))
    return folder / "latest.txt"
