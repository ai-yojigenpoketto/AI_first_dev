from __future__ import annotations

from typing import Literal

import httpx
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI()


@app.get("/hello/{user_input}")
async def read_hello(user_input: str) -> dict[str, str]:
    """
    Return a greeting mentioning the provided input text.
    """
    return {"message": f"Hello, World {user_input}"}


class ChatRequest(BaseModel):
    """
    Request payload that instructs the agent which tool to call.
    """

    message: str = Field(..., min_length=1, description="User prompt or search query.")
    tool: Literal["duckduckgo_search", "fetch_url"] | None = Field(
        default=None, description="Optional tool name to invoke."
    )
    url: HttpUrl | None = Field(
        default=None,
        description="URL to fetch when using tool='fetch_url'.",
    )
    max_results: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Limit the number of DuckDuckGo results returned.",
    )
    region: str = Field(
        default="wt-wt",
        description="DuckDuckGo region, e.g. 'us-en', 'wt-wt'.",
    )
    safesearch: Literal["off", "moderate", "strict"] = Field(
        default="moderate", description="DuckDuckGo safesearch setting."
    )


class SearchResult(BaseModel):
    title: str
    href: str
    body: str


class UrlContent(BaseModel):
    url: HttpUrl
    status_code: int
    content_type: str | None = None
    title: str | None = None
    description: str | None = None
    headings: list[str] | None = None
    preview: str | None = None


class ChatResponse(BaseModel):
    reply: str
    used_tool: bool
    tool: str | None = None
    results: list[SearchResult] | None = None
    url_content: UrlContent | None = None


def duckduckgo_search_tool(
    query: str, *, max_results: int, region: str, safesearch: str
) -> list[SearchResult]:
    """
    Execute a DuckDuckGo search with basic result sanitisation.
    """
    try:
        with DDGS(timeout=10) as ddgs:
            raw_results = ddgs.text(
                keywords=query,
                max_results=max_results,
                region=region,
                safesearch=safesearch,
            )
            return [
                SearchResult(
                    title=item.get("title", ""),
                    href=item.get("href", ""),
                    body=item.get("body", ""),
                )
                for item in raw_results
            ]
    except Exception as exc:  # pragma: no cover - runtime safeguard
        raise HTTPException(
            status_code=502,
            detail=f"DuckDuckGo search failed: {exc}",
        ) from exc


def fetch_url_tool(url: str, *, timeout: float = 10.0) -> UrlContent:
    """
    Retrieve and parse the given URL, extracting lightweight metadata.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - runtime safeguard
        raise HTTPException(
            status_code=502, detail=f"URL fetch failed: {exc}"
        ) from exc

    soup = BeautifulSoup(response.text, "html.parser")

    def _first_text(elements: list[str]) -> str | None:
        for selector in elements:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(strip=True)
                if text:
                    return text
        return None

    headings = [
        heading.get_text(strip=True)
        for heading in soup.find_all(["h1", "h2"])
        if heading.get_text(strip=True)
    ][:5]

    paragraph_chunks = [
        paragraph.get_text(strip=True)
        for paragraph in soup.find_all("p")
        if paragraph.get_text(strip=True)
    ]
    preview_text = " ".join(paragraph_chunks)
    if preview_text:
        preview_text = preview_text[:500]

    return UrlContent(
        url=str(response.url),
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        title=_first_text(["title"]),
        description=_first_text(
            ['meta[name="description"]', 'meta[property="og:description"]']
        ),
        headings=headings or None,
        preview=preview_text or None,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat_agent(payload: ChatRequest) -> ChatResponse:
    """
    Minimal chat endpoint whose agent can call web-enabled tools on demand.
    """

    if payload.tool == "duckduckgo_search":
        results = duckduckgo_search_tool(
            payload.message,
            max_results=payload.max_results,
            region=payload.region,
            safesearch=payload.safesearch,
        )
        reply_prefix = (
            f"duckduckgo_search found {len(results)} result(s)"
            if results
            else "duckduckgo_search returned no results"
        )
        return ChatResponse(
            reply=f"{reply_prefix} for query: {payload.message}",
            used_tool=True,
            tool="duckduckgo_search",
            results=results or None,
        )

    if payload.tool == "fetch_url":
        if not payload.url:
            raise HTTPException(
                status_code=422,
                detail="Field 'url' is required when using tool='fetch_url'.",
            )
        url_content = fetch_url_tool(str(payload.url))
        return ChatResponse(
            reply=f"Fetched and parsed {url_content.url}",
            used_tool=True,
            tool="fetch_url",
            url_content=url_content,
        )

    return ChatResponse(
        reply=(
            "No tool requested. Provide tool='duckduckgo_search' for web search or "
            "tool='fetch_url' with a 'url' to pull page content."
        ),
        used_tool=False,
    )

