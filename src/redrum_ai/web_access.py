"""Bounded live web lookups for direct CLI questions."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime


def _get_json(url: str, timeout: int = 12) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "redrum-ai/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _weather_location(query: str) -> str | None:
    match = re.search(r"(?:weather|rain|rainy|snow|forecast).*?\b(?:in|for|at)\s+(.+?)(?:\s+today|\s+tomorrow|\s+this week)?$", query, re.I)
    return match.group(1).strip(" ?.,") if match else None


def weather_answer(query: str) -> str | None:
    location = _weather_location(query)
    if not location:
        return None
    geo_name = location.split(",", 1)[0].strip()
    geo_name = re.sub(r"\s+(?:ontario|canada|united kingdom|uk|usa|us)$", "", geo_name, flags=re.I).strip()
    geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": geo_name, "count": 10, "language": "en", "format": "json"})
    results = (_get_json(geo_url).get("results") or [])
    location_terms = {term.lower() for term in re.findall(r"[a-z]+", location)}
    if len(results) > 1:
        matching = [result for result in results if location_terms & {str(result.get("country", "")).lower(), str(result.get("admin1", "")).lower()}]
        if matching:
            results = matching
    if not results:
        return f"I could not locate '{location}' for a weather lookup."
    place = results[0]
    forecast_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({"latitude": place["latitude"], "longitude": place["longitude"], "daily": "precipitation_probability_max,weather_code", "timezone": "auto", "forecast_days": 2})
    daily = _get_json(forecast_url).get("daily") or {}
    dates = daily.get("time") or []
    probabilities = daily.get("precipitation_probability_max") or []
    codes = daily.get("weather_code") or []
    if not dates:
        return f"No forecast was returned for {place.get('name', location)}."
    idx = 0 if "tomorrow" not in query.lower() else min(1, len(dates) - 1)
    probability = probabilities[idx] if idx < len(probabilities) else None
    code = codes[idx] if idx < len(codes) else None
    rain = "yes" if probability is not None and probability >= 40 else "unlikely"
    return (f"{place.get('name', location)}, {place.get('country', '')}: precipitation is {rain} today "
            f"(maximum probability {probability if probability is not None else 'unknown'}%; weather code {code}). "
            f"Source: Open-Meteo, retrieved {datetime.now().astimezone().isoformat(timespec='seconds')}")


def search_answer(query: str) -> str | None:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "redrum-ai/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        html = response.read(120_000).decode("utf-8", errors="ignore")
    snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.I | re.S)
    clean = [re.sub(r"<[^>]+>", "", value).strip() for value in snippets]
    return "\n".join(value for value in clean[:5] if value) or "No live search results found."


def answer(query: str) -> str | None:
    normalized = query.lower()
    if any(word in normalized for word in ("weather", "rain", "rainy", "snow", "forecast")):
        return weather_answer(query)
    if any(word in normalized for word in ("latest", "today", "news", "favorite to win", "who is the favorite")):
        return search_answer(query)
    return None
