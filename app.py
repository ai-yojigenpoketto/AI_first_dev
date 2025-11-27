from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI()

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


DUCKDUCKGO_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
SAFESEARCH_MAP = {
    "off": "-2",
    "moderate": "-1",
    "strict": "1",
}


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
    query: str, *, max_results: int, region: str, safesearch: str, timeout: float = 10
) -> tuple[list[SearchResult], list[dict]]:
    """
    Execute a DuckDuckGo search via the HTML endpoint and sanitise the results.
    """

    payload = {
        "q": query,
        "kl": region,
        "kp": SAFESEARCH_MAP.get(safesearch, SAFESEARCH_MAP["moderate"]),
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }

    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            response = client.post(DUCKDUCKGO_HTML_ENDPOINT, data=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - runtime safeguard
        raise HTTPException(
            status_code=502, detail=f"DuckDuckGo search failed: {exc}"
        ) from exc

    soup = BeautifulSoup(response.text, "html.parser")
    structured: list[dict] = []

    for result in soup.select("div.result"):
        title_tag = result.select_one("a.result__a")
        if not title_tag:
            continue
        link = title_tag.get("href") or ""
        snippet_tag = result.select_one("a.result__snippet, div.result__snippet")
        snippet_text = snippet_tag.get_text(strip=True) if snippet_tag else ""
        structured.append(
            {
                "title": title_tag.get_text(strip=True),
                "href": link,
                "body": snippet_text,
            }
        )
        if len(structured) >= max_results:
            break

    search_results = [
        SearchResult(title=item["title"], href=item["href"], body=item["body"])
        for item in structured
    ]

    return search_results, structured


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


def run_agent(payload: ChatRequest) -> tuple[ChatResponse, dict]:
    """
    Shared orchestration logic for both standard and streaming endpoints.
    """

    history: dict = {
        "user_message": payload.message,
        "tool_calls": [],
        "tool_results": [],
        "final_response": None,
    }

    response: ChatResponse

    if payload.tool == "duckduckgo_search":
        tool_call = {
            "tool": "duckduckgo_search",
            "parameters": {
                "keywords": payload.message,
                "max_results": payload.max_results,
                "region": payload.region,
                "safesearch": payload.safesearch,
            },
        }
        history["tool_calls"].append(tool_call)
        results, raw_results = duckduckgo_search_tool(
            payload.message,
            max_results=payload.max_results,
            region=payload.region,
            safesearch=payload.safesearch,
        )
        history["tool_results"].append(
            {"tool": "duckduckgo_search", "data": raw_results}
        )
        reply_prefix = (
            f"duckduckgo_search found {len(results)} result(s)"
            if results
            else "duckduckgo_search returned no results"
        )
        response = ChatResponse(
            reply=f"{reply_prefix} for query: {payload.message}",
            used_tool=True,
            tool="duckduckgo_search",
            results=results or None,
        )
    elif payload.tool == "fetch_url":
        if not payload.url:
            raise HTTPException(
                status_code=422,
                detail="Field 'url' is required when using tool='fetch_url'.",
            )
        tool_call = {
            "tool": "fetch_url",
            "parameters": {
                "url": str(payload.url),
            },
        }
        history["tool_calls"].append(tool_call)
        url_content = fetch_url_tool(str(payload.url))
        history["tool_results"].append(
            {"tool": "fetch_url", "data": url_content.model_dump()}
        )
        response = ChatResponse(
            reply=f"Fetched and parsed {url_content.url}",
            used_tool=True,
            tool="fetch_url",
            url_content=url_content,
        )
    else:
        response = ChatResponse(
            reply=(
                "No tool requested. Provide tool='duckduckgo_search' for web search or "
                "tool='fetch_url' with a 'url' to pull page content."
            ),
            used_tool=False,
        )

    history["final_response"] = response.model_dump()
    return response, history


def chunk_reply(text: str, words_per_chunk: int = 6) -> list[str]:
    """
    Split a reply string into small, word-friendly chunks for streaming purposes.
    """

    if not text:
        return [""]

    words = text.split()
    chunks: list[str] = []
    current: list[str] = []

    for word in words:
        current.append(word)
        if len(current) >= words_per_chunk:
            chunks.append(" ".join(current))
            current = []

    if current:
        chunks.append(" ".join(current))

    return chunks


def format_sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.post("/chat", response_model=ChatResponse)
async def chat_agent(payload: ChatRequest) -> ChatResponse:
    """
    Minimal chat endpoint whose agent can call web-enabled tools on demand.
    """

    response, history = run_agent(payload)
    print(json.dumps(history, default=str))
    return response


@app.post("/chat/stream")
async def chat_agent_stream(payload: ChatRequest) -> StreamingResponse:
    """
    Streaming variant of the chat endpoint using Server-Sent Events.
    """

    response, history = run_agent(payload)

    async def event_generator():
        for chunk in chunk_reply(response.reply):
            yield format_sse({"type": "token", "value": chunk})
            await asyncio.sleep(0)
        yield format_sse({"type": "message", "value": response.model_dump()})

    stream = StreamingResponse(event_generator(), media_type="text/event-stream")
    print(json.dumps(history, default=str))
    return stream


@app.get("/", response_class=HTMLResponse)
async def serve_frontend() -> HTMLResponse:
    """
    Serve the single-page chat application.
    """

    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))

