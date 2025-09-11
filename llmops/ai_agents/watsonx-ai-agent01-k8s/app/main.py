from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
import os  # ensure this is present; main.py uses os.getenv

import time
from typing import List, Optional, Union

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
import uuid
from datetime import datetime, timezone
from typing import Literal  # keep only what you need
import logging

APP_NAME = "watsonx-ai-agent01"
API_URL = os.getenv("WATSONX_API_URL", "https://eu-de.ml.cloud.ibm.com").rstrip("/")
PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")
LLM_MODEL_ID = os.getenv("WATSONX_LLM_MODEL_ID", "mistralai/mistral-large")
EMBED_MODEL_ID = os.getenv("WATSONX_EMBEDDING_MODEL_ID", "ibm/slate-125m-english-rtrvr")
IBM_API_KEY = os.getenv("IBMCLOUD_API_KEY", "")
VERIFY_TLS = os.getenv("WATSONX_VERIFY_TLS", "true").lower() != "false"
WATSONX_USE_CHAT = os.getenv("WATSONX_USE_CHAT", "false").lower() == "true"  # toggle chat vs generation

IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
WATSONX_GENERATE_URL = f"{API_URL}/ml/v1/text/generation?version=2023-05-29"
WATSONX_EMBED_URL = f"{API_URL}/ml/v1/text/embeddings?version=2023-05-29"
# Add chat endpoint (preferred over legacy generation)
WATSONX_CHAT_URL = f"{API_URL}/ml/v1/text/chat?version=2023-05-29"

app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    description="FastAPI agent with Watsonx LLM endpoints. Use /docs to test.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str
    max_new_tokens: int = 256
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: Optional[int] = None
    repetition_penalty: Optional[float] = 1.1
    stop_sequences: Optional[List[str]] = None
    model_id: Optional[str] = None  # allow overriding model per request

    @validator("top_k", pre=True)
    def coerce_top_k(cls, v):
        # Treat 0/invalid as None; only >=1 is valid for watsonx
        if v is None:
            return None
        try:
            iv = int(v)
        except Exception:
            return None
        return iv if iv >= 1 else None

    @validator("model_id", pre=True)
    def normalize_model_id(cls, v):
        # Swagger "Try it out" shows "string" placeholder; ignore it
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s.lower() in {"", "string", "none", "null"}:
                return None
            return s
        return None


class GenerateResponse(BaseModel):
    generated_text: str
    raw: dict


class EmbeddingsRequest(BaseModel):
    input: Union[str, List[str]]


class EmbeddingsResponse(BaseModel):
    embeddings: List[List[float]]
    raw: dict


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


# initialize logger for error details
logger = logging.getLogger("uvicorn.error")


def _wx_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _wx_chat_call(messages: List[ChatMessage], model_id: str, params: dict) -> dict:
    # Call watsonx chat API with proper message format (list of content blocks)
    token = _get_iam_token(IBM_API_KEY)
    wx_messages = [
        {
            "role": m.role,
            "content": [
                {"type": "text", "text": m.content}
            ],
        }
        for m in messages
    ]
    body = {
        "messages": wx_messages,
        "model_id": model_id,
        "project_id": PROJECT_ID,
        "parameters": params,
    }
    resp = requests.post(WATSONX_CHAT_URL, json=body, headers=_wx_headers(token), timeout=60, verify=VERIFY_TLS)
    resp.raise_for_status()
    return resp.json()


# Add legacy generation helper (used as fallback)
def _wx_generate_call(prompt: str, model_id: str, params: dict) -> dict:
    token = _get_iam_token(IBM_API_KEY)
    body = {
        "input": prompt,
        "model_id": model_id,
        "project_id": PROJECT_ID,
        "parameters": params,
    }
    resp = requests.post(WATSONX_GENERATE_URL, json=body, headers=_wx_headers(token), timeout=60, verify=VERIFY_TLS)
    resp.raise_for_status()
    return resp.json()


def _flatten_messages_for_prompt(messages: List[ChatMessage]) -> str:
    system = "\n".join(m.content for m in messages if m.role == "system")
    user = "\n".join(m.content for m in messages if m.role == "user")
    parts = [p for p in (system, user) if p]
    return "\n\n".join(parts) if parts else (messages[-1].content if messages else "")


_token_cache = {"token": None, "exp": 0.0}


def _get_iam_token(apikey: str) -> str:
    if not apikey:
        raise HTTPException(status_code=500, detail="Missing IBMCLOUD_API_KEY")
    now = time.time()
    if _token_cache["token"] and _token_cache["exp"] > now + 60:
        return _token_cache["token"]
    data = {
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": apikey,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    try:
        r = requests.post(IAM_TOKEN_URL, data=data, headers=headers, timeout=20)
        r.raise_for_status()
        j = r.json()
        token = j["access_token"]
        expires_in = int(j.get("expires_in", 3600))
        _token_cache["token"] = token
        _token_cache["exp"] = now + expires_in
        return token
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"IAM token error: {str(e)}")


@app.get("/", include_in_schema=False)
async def redirect_to_docs():
    return RedirectResponse(url="/docs")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(openapi_url=app.openapi_url, title="API Docs")


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(openapi_url=app.openapi_url, title="API Docs")


@app.get("/health")
def health():
    return {"status": "ok", "service": APP_NAME}


@app.get("/example")
async def read_example():
    return {"message": "This is an example endpoint."}


@app.post("/v1/generate", response_model=GenerateResponse, tags=["LLM"])
def generate(req: GenerateRequest):
    if not PROJECT_ID:
        raise HTTPException(status_code=500, detail="Missing WATSONX_PROJECT_ID")

    parameters = {
        "decoding_method": "greedy" if req.temperature == 0 else "sample",
        "max_new_tokens": req.max_new_tokens,
        "temperature": req.temperature,
        "top_p": req.top_p,
    }
    # Only include top_k if >=1
    if req.top_k is not None and req.top_k >= 1:
        parameters["top_k"] = req.top_k
    if req.repetition_penalty is not None:
        parameters["repetition_penalty"] = req.repetition_penalty
    if req.stop_sequences:
        parameters["stop_sequences"] = req.stop_sequences

    model_id = req.model_id or LLM_MODEL_ID

    try:
        if WATSONX_USE_CHAT:
            data = _wx_chat_call(
                messages=[ChatMessage(role="user", content=req.prompt)],
                model_id=model_id,
                params=parameters,
            )
        else:
            data = _wx_generate_call(prompt=req.prompt, model_id=model_id, params=parameters)

        results = data.get("results") or []
        text = results[0].get("generated_text", "") if results else ""
        return GenerateResponse(generated_text=text, raw=data)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response else 502
        body = e.response.text if e.response else str(e)

        # If the requested model is unsupported, retry with default model
        if status in (400, 404) and isinstance(req.model_id, str) and req.model_id and req.model_id != LLM_MODEL_ID and "model_not_supported" in body:
            try:
                fallback_data = _wx_generate_call(prompt=req.prompt, model_id=LLM_MODEL_ID, params=parameters) if not WATSONX_USE_CHAT \
                    else _wx_chat_call(messages=[ChatMessage(role="user", content=req.prompt)], model_id=LLM_MODEL_ID, params=parameters)
                results = fallback_data.get("results") or []
                text = results[0].get("generated_text", "") if results else ""
                return GenerateResponse(generated_text=text, raw=fallback_data)
            except requests.RequestException as ee:
                raise HTTPException(status_code=502, detail=f"watsonx request error: {str(ee)}")
            except requests.HTTPError as ee:
                raise HTTPException(status_code=ee.response.status_code if ee.response else 502, detail=ee.response.text if ee.response else str(ee))

        raise HTTPException(status_code=status, detail=body)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"watsonx request error: {str(e)}")


@app.post("/v1/embeddings", response_model=EmbeddingsResponse, tags=["LLM"])
def embeddings(req: EmbeddingsRequest):
    if not PROJECT_ID:
        raise HTTPException(status_code=500, detail="Missing WATSONX_PROJECT_ID")
    token = _get_iam_token(IBM_API_KEY)
    inputs = req.input if isinstance(req.input, list) else [req.input]

    # IBM watsonx requires "inputs" (plural)
    body = {
        "inputs": inputs,  # <— changed from "input" to "inputs"
        "model_id": EMBED_MODEL_ID,
        "project_id": PROJECT_ID,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = requests.post(WATSONX_EMBED_URL, json=body, headers=headers, timeout=60, verify=VERIFY_TLS)
        resp.raise_for_status()
        data = resp.json()
        # Expected: {"results":[{"embedding":[...]} , ...]}
        results = data.get("results") or []
        vecs: List[List[float]] = [r.get("embedding", []) for r in results]
        return EmbeddingsResponse(embeddings=vecs, raw=data)
    except requests.HTTPError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=e.response.status_code if e.response else 502, detail=detail)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"watsonx embeddings error: {str(e)}")
