"""Minimal client for the Archicad JSON API and the Tapir add-on commands.

Archicad listens on the first free port in 19723..19744 once a project is open.
Set ARCHICAD_URL (e.g. http://127.0.0.1:19723) to skip port discovery.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

PORTS = range(19723, 19745)


class ArchicadError(RuntimeError):
    pass


class Archicad:
    def __init__(self, url: str | None = None, timeout: float = 120.0):
        self.url = url or os.environ.get("ARCHICAD_URL")
        self.timeout = timeout

    # -- transport -----------------------------------------------------------
    def _post(self, url: str, payload: dict, timeout: float) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _discover(self) -> str:
        for port in PORTS:
            url = f"http://127.0.0.1:{port}"
            try:
                r = self._post(url, {"command": "API.IsAlive"}, timeout=1.5)
                if r.get("succeeded") and r.get("result", {}).get("isAlive"):
                    return url
            except (urllib.error.URLError, OSError, ValueError):
                continue
        raise ArchicadError(
            "Archicad is not reachable on ports 19723-19744. Open a project in Archicad "
            "(the JSON API only runs while a project is open)."
        )

    def command(self, name: str, parameters: dict | None = None) -> dict:
        """Run a built-in Archicad JSON API command, e.g. 'API.GetProductInfo'."""
        if not self.url:
            self.url = self._discover()
        payload = {"command": name}
        if parameters is not None:
            payload["parameters"] = parameters
        try:
            r = self._post(self.url, payload, self.timeout)
        except (urllib.error.URLError, OSError) as e:
            self.url = None  # Archicad may have restarted on another port
            raise ArchicadError(f"Lost connection to Archicad: {e}") from e
        if not r.get("succeeded"):
            raise ArchicadError(f"{name} failed: {r.get('error')}")
        return r.get("result", {})

    def tapir(self, name: str, parameters: dict | None = None) -> dict:
        """Run a Tapir add-on command, e.g. 'GetStories'."""
        params = {"addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name}}
        if parameters is not None:
            params["addOnCommandParameters"] = parameters
        res = self.command("API.ExecuteAddOnCommand", params).get("addOnCommandResponse", {})
        if isinstance(res, dict) and res.get("success") is False and "error" in res:
            raise ArchicadError(f"Tapir {name} failed: {res['error']}")
        return res

    # -- helpers ---------------------------------------------------------------
    def elements_by_type(self, element_type: str) -> list[dict]:
        r = self.tapir("GetElementsByType", {"elementType": element_type})
        if "error" in r:
            raise ArchicadError(f"GetElementsByType {element_type}: {r['error']}")
        return r.get("elements", [])

    def details(self, elements: list[dict], fields: list[str] | None = None) -> list[dict]:
        if not elements:
            return []
        p: dict = {"elements": elements}
        if fields:
            p["fields"] = fields
        return self.tapir("GetDetailsOfElements", p).get("detailsOfElements", [])

    def property_values(self, elements: list[dict], property_ids: list[dict]) -> list[list[dict]]:
        """Returns, per element, a list (per property) of {'value': str|None, 'available': bool, 'error': str|None}."""
        if not elements:
            return []
        r = self.tapir(
            "GetPropertyValuesOfElements",
            {
                "elements": elements,
                "properties": [{"propertyId": p} for p in property_ids],
                "includeAvailability": True,
            },
        )
        out = []
        for item in r.get("propertyValuesForElements", []):
            if "error" in item:
                out.append([{"value": None, "available": False, "error": _err(item["error"])}] * len(property_ids))
                continue
            row = []
            for pv in item.get("propertyValues", []):
                if "error" in pv:
                    row.append({"value": None, "available": pv.get("isAvailable", True), "error": _err(pv["error"])})
                else:
                    row.append({"value": pv["propertyValue"].get("value", ""), "available": pv.get("isAvailable", True), "error": None})
            out.append(row)
        return out

    def stories(self) -> dict[int, dict]:
        r = self.tapir("GetStories")
        return {s["index"]: s for s in r.get("stories", [])}

    def resolve(self, names: list[dict], max_close: int = 5) -> list[dict]:
        return self.tapir("ResolveNames", {"names": names, "maxCloseMatches": max_close}).get("results", [])


def _err(e) -> str:
    if isinstance(e, dict):
        return str(e.get("message") or e.get("code") or e)
    return str(e)


def story_name(stories: dict[int, dict], idx) -> str:
    try:
        s = stories.get(int(idx))
    except (TypeError, ValueError):
        s = None
    return f"{int(idx)} {s['name']}".strip() if s else f"{idx}"
