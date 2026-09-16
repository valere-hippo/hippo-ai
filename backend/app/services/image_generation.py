from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import settings

_ALLOWED_ELEMENT_TYPES = {
    "sun",
    "moon",
    "mountain",
    "tree",
    "river",
    "building",
    "road",
    "book",
    "computer",
    "bat",
    "bird",
    "flower",
    "leaf",
    "microscope",
    "waveform",
    "camera",
    "gears",
    "map_pin",
    "person",
    "abstract",
    "cloud",
    "star",
    "water",
    "house",
    "field",
}


def _normalize_base_url(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    if raw.endswith("/v1/chat/completions"):
        return raw
    if raw.endswith("/v1"):
        return f"{raw}/chat/completions"
    return f"{raw}/v1/chat/completions"


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _heuristic_scene(message: str, assistant_reply: str | None = None) -> dict[str, Any]:
    text = f"{message}\n{assistant_reply or ''}".lower()
    palette = ["#0b1016", "#16222f", "#63d7bf", "#9ab2ff", "#f4d35e"]
    topic = "abstract"
    elements: list[dict[str, Any]] = []

    def add(element_type: str, x: float, y: float, scale: float = 1.0, color: str = "#ffffff", rotation: float = 0.0, layer: int = 1) -> None:
        if element_type not in _ALLOWED_ELEMENT_TYPES:
            element_type = "abstract"
        elements.append({"type": element_type, "x": x, "y": y, "scale": scale, "color": color, "rotation": rotation, "layer": layer})

    if any(word in text for word in ("forest", "tree", "nature", "landscape", "mountain", "river", "lake", "field", "wilderness")):
        topic = "nature"
        palette = ["#07131b", "#173528", "#4da36d", "#9fd3c7", "#f4d35e"]
        add("mountain", 0.28, 0.58, 1.4, "#27465c", layer=1)
        add("mountain", 0.55, 0.62, 1.8, "#123e2f", layer=1)
        add("tree", 0.78, 0.62, 1.0, "#3d8053", layer=2)
        add("tree", 0.14, 0.65, 1.2, "#4da36d", layer=2)
        add("river", 0.64, 0.82, 1.0, "#4dc4e0", layer=0)
        add("sun", 0.84, 0.2, 0.7, "#f4d35e", layer=3)
    elif any(word in text for word in ("city", "town", "building", "architecture", "street", "urban")):
        topic = "city"
        palette = ["#0b1016", "#131d2b", "#586b8f", "#9ab2ff", "#f4d35e"]
        add("building", 0.16, 0.61, 1.5, "#24344a", layer=1)
        add("building", 0.41, 0.54, 1.8, "#2d4059", layer=1)
        add("building", 0.68, 0.58, 1.7, "#1d2c40", layer=1)
        add("road", 0.5, 0.88, 1.0, "#3b4e67", layer=0)
        add("sun", 0.83, 0.18, 0.55, "#f4d35e", layer=3)
    elif any(word in text for word in ("book", "report", "document", "analysis", "writing", "letter")):
        topic = "book"
        palette = ["#0a1016", "#16222f", "#9ab2ff", "#63d7bf", "#f3c969"]
        add("book", 0.5, 0.58, 1.6, "#24344a", layer=1)
        add("person", 0.2, 0.66, 0.7, "#63d7bf", layer=2)
        add("person", 0.78, 0.66, 0.7, "#9ab2ff", layer=2)
        add("star", 0.82, 0.22, 0.5, "#f4d35e", layer=3)
    elif any(word in text for word in ("bat", "bat detector", "batcall", "ultrasound", "ultraschall")):
        topic = "bat_detector"
        palette = ["#06111a", "#1a2636", "#63d7bf", "#9ab2ff", "#f4d35e"]
        add("waveform", 0.72, 0.58, 1.3, "#f48fb1", layer=2)
        add("bat", 0.35, 0.35, 1.1, "#2b2522", layer=3)
        add("computer", 0.63, 0.58, 1.0, "#16222f", layer=2)
        add("map_pin", 0.84, 0.26, 0.55, "#63d7bf", layer=3)
    elif any(word in text for word in ("animal", "wildlife", "bird", "bat", "frog", "fish", "dog", "cat", "nature reserve", "species")):
        topic = "animal"
        palette = ["#0a1016", "#172631", "#63d7bf", "#9ab2ff", "#f4d35e"]
        add("leaf", 0.2, 0.55, 1.0, "#4da36d", layer=1)
        add("bird", 0.52, 0.42, 1.2, "#9ab2ff", layer=3)
        add("flower", 0.8, 0.66, 0.8, "#f4d35e", layer=2)
    elif any(word in text for word in ("computer", "software", "qgis", "hipponalyze", "app", "screen", "tech", "technology")):
        topic = "tech"
        palette = ["#061018", "#132235", "#63d7bf", "#9ab2ff", "#f4d35e"]
        add("computer", 0.5, 0.5, 1.5, "#1d2c40", layer=2)
        add("gears", 0.78, 0.68, 0.7, "#63d7bf", layer=3)
        add("waveform", 0.23, 0.68, 0.7, "#9ab2ff", layer=1)
        add("cloud", 0.2, 0.22, 0.75, "#f4d35e", layer=1)
    elif any(word in text for word in ("map", "gis", "geodata", "coordinates", "polygon", "territory", "route")):
        topic = "map"
        palette = ["#08121c", "#1c3043", "#4da36d", "#9ab2ff", "#f4d35e"]
        add("map_pin", 0.63, 0.42, 1.0, "#f4d35e", layer=3)
        add("road", 0.52, 0.7, 1.0, "#3b4e67", layer=1)
        add("field", 0.22, 0.58, 1.2, "#2a5d3d", layer=1)
        add("river", 0.75, 0.78, 0.8, "#4dc4e0", layer=1)
    else:
        add("abstract", 0.22, 0.28, 1.1, "#63d7bf", layer=1)
        add("abstract", 0.62, 0.36, 1.4, "#9ab2ff", layer=2)
        add("abstract", 0.78, 0.72, 1.0, "#f4d35e", layer=1)

    return {
        "topic": topic,
        "palette": palette,
        "elements": elements,
        "mood": "dramatic" if any(word in text for word in ("night", "dark", "mystery", "storm")) else "balanced",
    }


async def build_image_scene_spec(message: str, assistant_reply: str | None = None) -> dict[str, Any]:
    base_url = _normalize_base_url(settings.hippo_api_url)
    if not base_url:
        return _heuristic_scene(message, assistant_reply)

    prompt = (
        "Du bist ein Bild-Regisseur. Erzeuge ausschließlich gültiges JSON ohne Markdown und ohne Zusatztext. "
        "Ziel: Eine echte visuelle Illustration, kein Textbild, kein Poster mit Schrift. "
        "Gib nur ein JSON-Objekt mit diesen Schlüsseln zurück: topic, mood, palette, elements. "
        "palette ist ein Array von 4-6 Hex-Farben. elements ist ein Array von 3-8 Objekten. "
        "Jedes Element hat type, x, y, scale, color, rotation, layer. "
        f"Erlaubte Typen: {', '.join(sorted(_ALLOWED_ELEMENT_TYPES))}. "
        "Benutze nur diese Typen. Wähle eine Illustration, die das Sujet deutlich und ohne Text vermittelt."
    )
    payload = {
        "model": settings.hippo_model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": message.strip()},
        ],
        "temperature": 0.2,
        "max_tokens": 384,
    }
    headers = {"Content-Type": "application/json"}
    api_key = (settings.hippo_api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = await client.post(base_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        text = ""
        if isinstance(data, dict) and data.get("choices"):
            text = str(data["choices"][0]["message"].get("content") or "")
        else:
            text = json.dumps(data)
        scene = _parse_json_object(text)
        if not scene:
            scene = _heuristic_scene(message, assistant_reply)
        return scene
    except Exception:
        return _heuristic_scene(message, assistant_reply)
