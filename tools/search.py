"""Web search for the ``genre-researcher`` subagent: outside-world context for newsletters
(what's happening in a genre, why a catalog moment matters).

Uses Tavily when ``TAVILY_API_KEY`` is set; otherwise falls back to a small offline corpus,
so the demo never depends on the network. The fallback says so in its output, so the
agent (and an eval) can tell the two apart.
"""

from __future__ import annotations

import os

from langchain.tools import tool

OFFLINE_NOTES: dict[str, list[str]] = {
    "latin": [
        "Latin catalog demand is driven by playlist placement and cross-over collaborations; bossa nova and MPB classics see steady long-tail sales.",
        "Marketing angle: pair heritage artists (Jobim, Gilberto Gil, Caetano Veloso) with a 'rediscover' framing rather than 'new release'.",
    ],
    "jazz": [
        "Jazz buyers over-index on complete albums and remasters; single-track sales cluster around standards.",
        "Marketing angle: curated 'listening room' bundles (5-8 tracks) convert better than genre-wide promotions.",
    ],
    "rock": [
        "Rock remains the largest catalog segment; anniversary reissues and live recordings drive spikes.",
        "Marketing angle: lead with the best-selling album of the period and offer the back catalog at a bundle price.",
    ],
    "metal": [
        "Metal has the most loyal repeat buyers; discography completion is the main purchase driver.",
        "Marketing angle: 'complete your collection' offers with per-artist bundles.",
    ],
    "bossa nova": [
        "Bossa nova is evergreen in cafe/retail playlists; commercial licensing requests for background music are common.",
    ],
    "blues": ["Blues catalog sales are stable and seasonal; live sessions and compilations perform best."],
    "pop": ["Pop catalog is playlist-driven; short promotional windows and bundles work best."],
    "reggae": ["Reggae sells on compilations and summer campaigns; artist-led bundles perform well."],
}


def _offline_search(query: str, max_results: int) -> str:
    q = query.lower()
    hits = [(g, n) for g, notes in OFFLINE_NOTES.items() if g in q for n in notes]
    if not hits:
        return (
            "(offline corpus) No notes match that query. Try a genre name such as Latin, Jazz, Rock, "
            "Metal, Bossa Nova, Blues, Pop or Reggae."
        )
    return "(offline corpus; set TAVILY_API_KEY for live web results)\n" + "\n".join(
        f"- [{g}] {n}" for g, n in hits[:max_results]
    )


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for context on a genre, artist or music-industry trend.

    Returns short snippets with sources when a live search backend is configured, or
    curated offline notes otherwise (the output says which). Cite what you use; never
    present a search snippet as a fact about our own sales data.
    """
    if os.getenv("TAVILY_API_KEY"):
        try:
            from langchain_tavily import TavilySearch  # optional dependency

            result = TavilySearch(max_results=max_results).invoke({"query": query})
            items = result.get("results", []) if isinstance(result, dict) else result
            return "\n".join(f"- {r.get('title')}: {r.get('content', '')[:300]} ({r.get('url')})" for r in items) or "No results."
        except Exception as e:  # noqa: BLE001 - degrade to the offline corpus, and say so
            return f"(live search failed: {e}; falling back)\n" + _offline_search(query, max_results)
    return _offline_search(query, max_results)


SEARCH_TOOLS = [web_search]
