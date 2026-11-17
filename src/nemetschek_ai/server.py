"""MCP server: AI productivity tools for Archicad (via the Tapir add-on).

Part 1  Doors with a missing fire rating: find -> check -> batch fix (preview first, then confirm).
        Only property values are written. Nothing is created, moved or deleted.
Part 2  Wall cost estimate by wall type. Read-only: the model is never changed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .ac import Archicad, ArchicadError, story_name

INSTRUCTIONS = """\
You drive Archicad through these tools. Rules:
- Before using a name from the user's words (property, story, composite...), check it with
  resolve_names. found -> use it; closeMatches -> ask the user which one; notFound -> say the
  project has no such item. Never guess a name.
- Part 1 (door fire ratings): find_doors_missing_property -> inspect_doors -> state the rule you
  will apply -> preview_property_update -> show the preview table and WAIT for the user's explicit
  confirmation -> apply_property_update with the token. Never apply without a confirmation.
  Only property values may change; never create, move or delete elements.
- Part 2 (wall costs) is read-only: wall_takeoff -> agree the rates and assumptions with the
  user (heights, hidden layers, exclusions) -> price_walls. Always list the assumptions.
"""

mcp = MCPServer("nemetschek-ai", instructions=INSTRUCTIONS)
ac = Archicad()

OUT_DIR = Path(os.environ.get("NEMETSCHEK_AI_OUT", Path.home() / "Documents" / "nemetschek-ai"))
_plans: dict[str, dict] = {}  # preview token -> plan (Part 1 confirm step)
_last_takeoff: dict = {}


def _now() -> float:
    return time.perf_counter()


def _guid(e: dict) -> str:
    return e["elementId"]["guid"]


def _resolve_property(name: str) -> tuple[dict | None, dict]:
    """Returns (propertyMatch, rawResult). propertyMatch only when unambiguous (found, one property)."""
    res = ac.resolve([{"name": name, "kind": "Property"}])[0]
    found = [m for m in res.get("found", []) if m.get("propertyId")]
    if res["status"] == "found" and len(found) == 1:
        return found[0], res
    return None, res


def _prop_label(m: dict) -> str:
    g = m.get("propertyGroupName")
    return f"{g} / {m['name']}" if g else m["name"]


# ---------------------------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------------------------
@mcp.tool()
def project_overview() -> dict:
    """Stories of the open project with the number of doors and walls on each. Read-only."""
    t = _now()
    stories = ac.stories()
    counts: dict[str, Counter] = defaultdict(Counter)
    for et in ("Door", "Wall"):
        els = ac.elements_by_type(et)
        for d in ac.details(els, ["floorIndex"]):
            counts[story_name(stories, d.get("floorIndex"))][et] += 1
    rows = []
    for idx in sorted(stories):
        k = story_name(stories, idx)
        rows.append({"story": k, "level_m": stories[idx].get("level"), "doors": counts[k]["Door"], "walls": counts[k]["Wall"]})
    return {"stories": rows, "seconds": round(_now() - t, 2)}


@mcp.tool()
def resolve_names(names: list[str], kind: str | None = None) -> list[dict]:
    """Check words from the user against the names in the open project before using them.
    kind: Story, Property, Composite, BuildingMaterial, Layer, ElementType, Classification ... (optional).
    Returns status found / closeMatches / notFound for each name. Read-only."""
    q = [{"name": n, **({"kind": kind} if kind else {})} for n in names]
    out = []
    for r in ac.resolve(q):
        def slim(m):
            return {k: m.get(k) for k in ("kind", "name", "match", "propertyGroupName", "propertyType", "storyIndex") if m.get(k) is not None}
        out.append({"name": r["name"], "status": r["status"], "found": [slim(m) for m in r["found"]], "closeMatches": [slim(m) for m in r["closeMatches"]]})
    return out


# ---------------------------------------------------------------------------------------------
# Part 1: doors with a missing fire rating
# ---------------------------------------------------------------------------------------------
@mcp.tool()
def find_doors_missing_property(property_name: str = "Fire Rating") -> dict:
    """FIND step. Lists every door whose given property (default 'Fire Rating') is empty,
    with a count per story. Read-only."""
    t = _now()
    prop, raw = _resolve_property(property_name)
    if not prop:
        return {"error": f"Property '{property_name}' is not unambiguous in this project", "resolve": raw}
    stories = ac.stories()
    doors = ac.elements_by_type("Door")
    det = ac.details(doors, ["elementId", "floorIndex", "details"])
    vals = ac.property_values(doors, [prop["propertyId"], _element_id_prop()])
    per_story_total, per_story_missing = Counter(), Counter()
    missing, not_available = [], 0
    for e, d, v in zip(doors, det, vals):
        fr, eid = v[0], v[1]
        st = story_name(stories, d.get("floorIndex"))
        per_story_total[st] += 1
        if not fr["available"]:
            not_available += 1
            continue
        if fr["error"] or not (fr["value"] or "").strip():
            per_story_missing[st] += 1
            missing.append({
                "guid": _guid(e),
                "elementId": eid["value"],
                "story": st,
                "doorType": (d.get("details") or {}).get("libPart", {}).get("name"),
            })
    table = [{"story": s, "doors": per_story_total[s], "missingRating": per_story_missing[s]} for s in per_story_total]
    return {
        "property": _prop_label(prop),
        "doorsTotal": len(doors),
        "doorsMissing": len(missing),
        "propertyNotAvailableOn": not_available,
        "perStory": sorted(table, key=lambda r: r["story"]),
        "missing": missing,
        "seconds": round(_now() - t, 2),
    }


_EID: dict | None = None


def _element_id_prop() -> dict:
    global _EID
    if _EID is None:
        r = ac.command("API.GetPropertyIds", {"properties": [{"type": "BuiltIn", "nonLocalizedName": "General_ElementID"}]})
        _EID = r["properties"][0]["propertyId"]
    return _EID


@mcp.tool()
def inspect_doors(door_guids: list[str], property_name: str = "Fire Rating") -> dict:
    """CHECK step. For the given doors: door type (library part), size, story, and the host wall
    (composite or material, thickness and the host wall's own value of the same property),
    plus a summary per door type. Use it to propose a rule such as 'EI60 for type X'. Read-only."""
    t = _now()
    prop, raw = _resolve_property(property_name)
    if not prop:
        return {"error": f"Property '{property_name}' is not unambiguous", "resolve": raw}
    stories = ac.stories()
    doors = [{"elementId": {"guid": g}} for g in door_guids]
    det = ac.details(doors, ["floorIndex", "details"])
    hosts = []
    for d in det:
        oid = (d.get("details") or {}).get("ownerElementId")
        hosts.append({"elementId": oid} if oid else None)
    host_list = [h for h in hosts if h]
    host_det = {(_guid(h)): hd for h, hd in zip(host_list, ac.details(host_list, ["details"]))}
    host_val = {(_guid(h)): hv[0] for h, hv in zip(host_list, ac.property_values(host_list, [prop["propertyId"]]))}
    comp_names = _composite_names([hd.get("details", {}).get("compositeId") for hd in host_det.values()])
    eids = ac.property_values(doors, [_element_id_prop()])
    rows, by_type = [], defaultdict(lambda: {"count": 0, "hostWalls": Counter(), "hostRatings": Counter()})
    for g, d, h, e in zip(door_guids, det, hosts, eids):
        dd = d.get("details") or {}
        row = {
            "guid": g,
            "elementId": e[0]["value"],
            "story": story_name(stories, d.get("floorIndex")),
            "doorType": dd.get("libPart", {}).get("name"),
            "width_m": _r(dd.get("width")),
            "height_m": _r(dd.get("height")),
        }
        if h:
            hd = host_det.get(_guid(h), {}).get("details", {})
            wall = _wall_label(hd, comp_names)
            row.update({"hostWall": wall, "hostThickness_mm": _mm(hd.get("begThickness")), "hostWallRating": (host_val.get(_guid(h)) or {}).get("value") or ""})
        else:
            wall = "(no host wall)"
            row["hostWall"] = wall
        rows.append(row)
        bt = by_type[row["doorType"]]
        bt["count"] += 1
        bt["hostWalls"][wall] += 1
        bt["hostRatings"][row.get("hostWallRating") or "(empty)"] += 1
    summary = [{"doorType": k, "count": v["count"], "hostWalls": dict(v["hostWalls"]), "hostWallRatings": dict(v["hostRatings"])} for k, v in by_type.items()]
    return {"property": _prop_label(prop), "doors": rows, "byDoorType": summary, "seconds": round(_now() - t, 2)}


@mcp.tool()
def preview_property_update(assignments: list[dict], property_name: str = "Fire Rating") -> dict:
    """PREVIEW step (dry run, changes nothing). assignments: [{"guid": door guid, "value": "EI60"}, ...].
    Archicad checks every write and reports old -> new value. Returns a token; show the table to the
    user and only call apply_property_update(token) after they explicitly confirm."""
    t = _now()
    prop, raw = _resolve_property(property_name)
    if not prop:
        return {"error": f"Property '{property_name}' is not unambiguous", "resolve": raw}
    items = [{"elementId": {"guid": a["guid"]}, "propertyId": prop["propertyId"], "propertyValue": {"value": str(a["value"])}} for a in assignments]
    r = ac.tapir("SetPropertyValuesOfElements", {"elementPropertyValues": items, "dryRun": True})
    results = r.get("executionResults", [])
    eids = ac.property_values([{"elementId": {"guid": a["guid"]}} for a in assignments], [_element_id_prop()])
    table, problems = [], []
    for a, res, e in zip(assignments, results, eids):
        if res.get("success") is False or "error" in res:
            problems.append({"guid": a["guid"], "elementId": e[0]["value"], "error": str(res.get("error"))})
            continue
        wc = res.get("wouldChange") or {}
        table.append({"elementId": e[0]["value"], "guid": a["guid"], "old": wc.get("oldValue", ""), "new": wc.get("newValue", a["value"])})
    token = hashlib.sha1(json.dumps(items, sort_keys=True).encode()).hexdigest()[:10]
    _plans[token] = {"items": items, "property": prop, "propertyName": property_name, "created": dt.datetime.now().isoformat(timespec="seconds")}
    return {
        "dryRun": True,
        "property": _prop_label(prop),
        "token": token,
        "wouldChange": len(table),
        "problems": problems,
        "changes": table,
        "valuesSummary": dict(Counter(row["new"] for row in table)),
        "next": "Show this to the user. Apply only after explicit confirmation: apply_property_update(token).",
        "seconds": round(_now() - t, 2),
    }


@mcp.tool()
def apply_property_update(token: str) -> dict:
    """FIX step. Writes exactly the previewed plan (by token) in one batch (one undo step in Archicad),
    then re-counts the doors that are still missing the property. Only call after the user confirmed."""
    t = _now()
    plan = _plans.pop(token, None)
    if not plan:
        return {"error": "Unknown or already used token. Run preview_property_update again."}
    r = ac.tapir("SetPropertyValuesOfElements", {"elementPropertyValues": plan["items"]})
    res = r.get("executionResults", [])
    ok = sum(1 for x in res if x.get("success", True) and "error" not in x)
    failed = [{"guid": i["elementId"]["guid"], "error": str(x.get("error"))} for i, x in zip(plan["items"], res) if not (x.get("success", True) and "error" not in x)]
    after = find_doors_missing_property(plan["propertyName"])
    return {
        "written": ok,
        "failed": failed,
        "after": {"doorsMissing": after.get("doorsMissing"), "perStory": after.get("perStory")},
        "undo": "Edit > Undo in Archicad reverts the whole batch.",
        "seconds": round(_now() - t, 2),
    }


# ---------------------------------------------------------------------------------------------
# Part 2: wall cost estimate (read-only)
# ---------------------------------------------------------------------------------------------
@mcp.tool()
def wall_takeoff(include_hidden_layers: bool = False) -> dict:
    """Measure every wall: type (composite / basic material + thickness / profile), story, length,
    height, net and gross area of one face, volume, layer and whether that layer is hidden.
    Grouped per wall type. Read-only: the model is not changed."""
    t = _now()
    stories = ac.stories()
    walls = ac.elements_by_type("Wall")
    det = ac.details(walls, ["elementId", "floorIndex", "layerIndex", "details"])
    q = ac.tapir("GetQuantitiesOfElements", {"elements": walls, "calculateInOneCall": True}).get("quantitiesOfElements", [])
    comp_names = _composite_names([(d.get("details") or {}).get("compositeId") for d in det])
    mat_names = _material_names([(d.get("details") or {}).get("buildingMaterialId") for d in det])
    layers = _layers()
    rows = []
    for e, d, qq in zip(walls, det, q):
        dd = d.get("details") or {}
        qs = (qq or {}).get("quantities") or {}
        layer = layers.get(int(d.get("layerIndex", -1)), {})
        rows.append({
            "guid": _guid(e),
            "story": story_name(stories, d.get("floorIndex")),
            "wallType": _wall_label(dd, comp_names, mat_names),
            "thickness_mm": _mm(dd.get("begThickness")),
            "length_m": _r(qs.get("length")),
            "height_m": _r(qs.get("maxHeight") or dd.get("height")),
            "netArea_m2": _r(max(qs.get("referenceSideSurface") or 0, qs.get("oppositeSideSurface") or 0)),
            "grossArea_m2": _r(max(qs.get("grossReferenceSideSurface") or 0, qs.get("grossOppositeSideSurface") or 0)),
            "volume_m3": _r(qs.get("volume")),
            "layer": layer.get("name", str(d.get("layerIndex"))),
            "layerHidden": bool(layer.get("isHidden")),
        })
    used = [r for r in rows if include_hidden_layers or not r["layerHidden"]]
    groups = _group(used)
    _last_takeoff.clear()
    _last_takeoff.update({"rows": rows, "include_hidden_layers": include_hidden_layers, "at": dt.datetime.now().isoformat(timespec="seconds")})
    return {
        "wallsTotal": len(rows),
        "wallsOnHiddenLayers": sum(r["layerHidden"] for r in rows),
        "hiddenIncluded": include_hidden_layers,
        "byWallType": groups,
        "heightsRange_m": [min((r["height_m"] for r in used), default=None), max((r["height_m"] for r in used), default=None)],
        "questionsForUser": [
            "Rate per wall type ($/m2): one number, or low/mid/high?",
            "Price the net area (openings deducted) or the gross area?",
            "Include walls on hidden layers?" + (f" ({sum(r['layerHidden'] for r in rows)} walls)" if any(r['layerHidden'] for r in rows) else " (none in this project)"),
            "Any wall heights to override, or wall types to exclude?",
        ],
        "seconds": round(_now() - t, 2),
    }


@mcp.tool()
def price_walls(
    rates: dict,
    area_basis: str = "net",
    spread_pct: float = 10.0,
    exclude_types: list[str] | None = None,
    height_override_m: dict | None = None,
    currency: str = "USD",
    assumptions: list[str] | None = None,
    project_label: str = "",
) -> dict:
    """Cost table per wall type from the last wall_takeoff. Read-only.
    rates: {"<wallType>": mid_rate} or {"<wallType>": [low, mid, high]} in currency per m2.
    area_basis: "net" (openings deducted) or "gross". spread_pct: low/high = mid -/+ this % when only one rate is given.
    height_override_m: {"<wallType>": height} rescales that type's area to the given height.
    Writes an Excel file (Cost table, Walls, Assumptions) and returns its path."""
    t = _now()
    if not _last_takeoff:
        wall_takeoff()
    rows = [r for r in _last_takeoff["rows"] if _last_takeoff["include_hidden_layers"] or not r["layerHidden"]]
    exclude = set(exclude_types or [])
    hov = height_override_m or {}
    table, missing_rate = [], []
    for g in _group(rows):
        wt = g["wallType"]
        if wt in exclude:
            continue
        rate = rates.get(wt)
        if rate is None:
            missing_rate.append(wt)
            continue
        low, mid, high = (rate if isinstance(rate, (list, tuple)) else [rate * (1 - spread_pct / 100), rate, rate * (1 + spread_pct / 100)])
        area = g["netArea_m2"] if area_basis == "net" else g["grossArea_m2"]
        if wt in hov and g["avgHeight_m"]:
            area = area * float(hov[wt]) / g["avgHeight_m"]
        table.append({
            "wallType": wt, "walls": g["walls"], "length_m": g["length_m"], "avgHeight_m": hov.get(wt, g["avgHeight_m"]),
            "area_m2": _r(area), "rateLow": _r(low), "rateMid": _r(mid), "rateHigh": _r(high),
            "costLow": _r(area * low), "costMid": _r(area * mid), "costHigh": _r(area * high),
        })
    totals = {k: _r(sum(r[k] for r in table)) for k in ("length_m", "area_m2", "costLow", "costMid", "costHigh")}
    auto = [
        f"Area basis: {'net (openings deducted)' if area_basis == 'net' else 'gross (openings not deducted)'}, one face per wall.",
        f"Walls on hidden layers {'included' if _last_takeoff['include_hidden_layers'] else 'excluded'}.",
        f"Low/high = mid -/+ {spread_pct:g}% where a single rate was given.",
        f"Quantities measured by Archicad (Tapir GetQuantitiesOfElements) on {_last_takeoff['at']}.",
    ]
    if exclude:
        auto.append("Excluded wall types: " + ", ".join(sorted(exclude)))
    if hov:
        auto.append("Height overrides: " + ", ".join(f"{k} = {v} m" for k, v in hov.items()))
    path = _write_xlsx(table, totals, rows, auto + list(assumptions or []), currency, project_label)
    return {
        "currency": currency, "costTable": table, "totals": totals,
        "wallTypesWithoutRate": missing_rate, "assumptions": auto + list(assumptions or []),
        "excel": str(path), "seconds": round(_now() - t, 2),
    }


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _mm(x):
    return None if x is None else round(float(x) * 1000)


def _composite_names(ids: list) -> dict:
    ids = [i for i in ids if i and i.get("guid")]
    uniq = list({i["guid"]: i for i in ids}.values())
    if not uniq:
        return {}
    try:
        r = ac.tapir("GetComposites", {"attributeIds": [{"attributeId": i} for i in uniq], "fields": ["name"]})
        return {i["guid"]: c.get("name") for i, c in zip(uniq, r.get("composites", [])) if "name" in c}
    except ArchicadError:
        return {}


def _material_names(ids: list) -> dict:
    ids = [i for i in ids if i and i.get("guid")]
    uniq = list({i["guid"]: i for i in ids}.values())
    if not uniq:
        return {}
    try:
        r = ac.command("API.GetBuildingMaterialAttributes", {"attributeIds": [{"attributeId": i} for i in uniq]})
        out = {}
        for i, a in zip(uniq, r.get("attributes", [])):
            bm = a.get("buildingMaterialAttribute") or {}
            if bm.get("name"):
                out[i["guid"]] = bm["name"]
        return out
    except ArchicadError:
        return {}


def _layers() -> dict:
    try:
        ids = ac.command("API.GetAttributesByType", {"attributeType": "Layer"}).get("attributeIds", [])
        r = ac.command("API.GetLayerAttributes", {"attributeIds": ids})
        out = {}
        for a in r.get("attributes", []):
            la = a.get("layerAttribute") or {}
            idx = la.get("attributeIndex", la.get("index"))
            if idx is None:
                idx = (la.get("attributeId") or {}).get("index")
            if idx is not None:
                out[int(idx)] = {"name": la.get("name"), "isHidden": la.get("isHidden", False)}
        return out
    except ArchicadError:
        return {}


def _wall_label(dd: dict, comp_names: dict, mat_names: dict | None = None) -> str:
    st = dd.get("structureType")
    if st == "Composite" and dd.get("compositeId"):
        return comp_names.get(dd["compositeId"]["guid"]) or "Composite (unnamed)"
    if st == "Profile":
        return "Profile wall"
    th = _mm(dd.get("begThickness"))
    mat = (mat_names or {}).get((dd.get("buildingMaterialId") or {}).get("guid", ""), "Basic")
    return f"{mat} {th} mm" if th else mat


def _group(rows: list[dict]) -> list[dict]:
    g: dict[str, dict] = {}
    for r in rows:
        x = g.setdefault(r["wallType"], {"wallType": r["wallType"], "walls": 0, "length_m": 0.0, "netArea_m2": 0.0, "grossArea_m2": 0.0, "_h": 0.0})
        x["walls"] += 1
        x["length_m"] += r["length_m"] or 0
        x["netArea_m2"] += r["netArea_m2"] or 0
        x["grossArea_m2"] += r["grossArea_m2"] or 0
        x["_h"] += (r["height_m"] or 0) * (r["length_m"] or 0)
    out = []
    for x in g.values():
        x["avgHeight_m"] = _r(x.pop("_h") / x["length_m"]) if x["length_m"] else None
        for k in ("length_m", "netArea_m2", "grossArea_m2"):
            x[k] = _r(x[k])
        out.append(x)
    return sorted(out, key=lambda x: -x["netArea_m2"])


def _write_xlsx(table, totals, rows, assumptions, currency, label) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"wall-cost-estimate-{dt.datetime.now():%Y%m%d-%H%M%S}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Cost table"
    ws.append([f"Wall cost estimate {label}".strip(), f"Currency: {currency}"])
    ws["A1"].font = Font(bold=True, size=13)
    hdr = ["Wall type", "Walls", "Length (m)", "Avg height (m)", "Area (m2)", "Rate low", "Rate mid", "Rate high", "Cost low", "Cost mid", "Cost high"]
    ws.append([])
    ws.append(hdr)
    for c in ws[3]:
        c.font = Font(bold=True)
    for r in table:
        ws.append([r["wallType"], r["walls"], r["length_m"], r["avgHeight_m"], r["area_m2"], r["rateLow"], r["rateMid"], r["rateHigh"], r["costLow"], r["costMid"], r["costHigh"]])
    ws.append(["TOTAL", sum(r["walls"] for r in table), totals["length_m"], None, totals["area_m2"], None, None, None, totals["costLow"], totals["costMid"], totals["costHigh"]])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.column_dimensions["A"].width = 38
    w2 = wb.create_sheet("Walls")
    keys = ["story", "wallType", "thickness_mm", "length_m", "height_m", "netArea_m2", "grossArea_m2", "volume_m3", "layer", "layerHidden", "guid"]
    w2.append(keys)
    for r in rows:
        w2.append([r[k] for k in keys])
    w3 = wb.create_sheet("Assumptions")
    w3.append(["Assumptions"])
    w3["A1"].font = Font(bold=True)
    for a in assumptions:
        w3.append([a])
    w3.column_dimensions["A"].width = 110
    wb.save(path)
    return path


def main():
    mcp.run()


if __name__ == "__main__":
    main()
