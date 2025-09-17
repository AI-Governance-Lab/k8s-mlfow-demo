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
from typing import Optional, List, Literal
import uuid
from datetime import datetime, timezone
import logging
import json

APP_NAME = "watsonx-ai-agent01"
API_URL = os.getenv("WATSONX_API_URL", "https://eu-de.ml.cloud.ibm.com").rstrip("/")
PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")
LLM_MODEL_ID = os.getenv("WATSONX_LLM_MODEL_ID", "mistralai/mistral-large")
EMBED_MODEL_ID = os.getenv("WATSONX_EMBEDDING_MODEL_ID", "ibm/slate-125m-english-rtrvr")
IBM_API_KEY = os.getenv("IBMCLOUD_API_KEY", "")
VERIFY_TLS = os.getenv("WATSONX_VERIFY_TLS", "true").lower() != "false"
WATSONX_USE_CHAT = os.getenv("WATSONX_USE_CHAT", "false").lower() == "true"  # toggle chat vs generation

# Add these missing constants
IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
WX_API_VERSION = os.getenv("WATSONX_API_VERSION", "2023-05-29")
WATSONX_GENERATE_URL = f"{API_URL}/ml/v1/text/generation?version={WX_API_VERSION}"
WATSONX_CHAT_URL = f"{API_URL}/ml/v1/text/chat?version={WX_API_VERSION}"
WATSONX_EMBED_URL = f"{API_URL}/ml/v1/text/embeddings?version={WX_API_VERSION}"

# MLflow server-side logging flags (add these)
MLFLOW_AUTO_LOG = os.getenv("MLFLOW_AUTO_LOG", "false").lower() == "true"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "ai-agent01")

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
    mlflow_run_id: Optional[str] = None  # add this so clients can link to the run


class EmbeddingsRequest(BaseModel):
    input: Union[str, List[str]]


class EmbeddingsResponse(BaseModel):
    embeddings: List[List[float]]
    raw: dict


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class FeedbackRequest(BaseModel):
    run_id: str
    rating: int  # e.g., -1 (down), 0 (neutral), 1 (up) or 1..5
    comment: Optional[str] = None
    label: Optional[str] = None  # optional short label (e.g., "correctness", "style")


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
    t0 = time.time()
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
        resp = GenerateResponse(generated_text=text, raw=data)  # initial response
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

    # Optional server-side MLflow logging
    if MLFLOW_AUTO_LOG and MLFLOW_TRACKING_URI:
        try:
            import mlflow
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
            run = mlflow.start_run(run_name="generate")
            try:
                # 1) Description (shows in UI)
                note = f"Prompt (truncated): {req.prompt[:200]}{'...' if len(req.prompt) > 200 else ''}"
                mlflow.set_tag("mlflow.note.content", note)

                # 2) Helpful tags for search/compare
                mlflow.set_tags({
                    "route": "v1/generate",
                    "model_id": data.get("model_id") or (req.model_id or LLM_MODEL_ID),
                    "pod": os.getenv("HOSTNAME", ""),
                    "api_version": os.getenv("WATSONX_API_VERSION", "2023-05-29"),
                })

                # 3) System metrics (CPU, mem, net) while the run is active
                try:
                    mlflow.enable_system_metrics_logging()
                except Exception:
                    pass  # not fatal if unsupported

                # 4) Params / metrics / artifacts (existing)
                res0 = (data.get("results") or [{}])[0]
                mlflow.log_params({
                    "max_new_tokens": req.max_new_tokens,
                    "temperature": req.temperature,
                    "top_p": req.top_p,
                    **({"top_k": req.top_k} if req.top_k else {}),
                })
                if "generated_token_count" in res0: mlflow.log_metric("gen_tokens", res0["generated_token_count"])
                if "input_token_count" in res0: mlflow.log_metric("input_tokens", res0["input_token_count"])
                mlflow.log_metric("latency_s", time.time() - t0)
                mlflow.log_text(req.prompt, "prompt.txt")
                mlflow.log_text(resp.generated_text, "response.txt")
                mlflow.log_dict(resp.raw, "raw.json")

                # 5) Optional: log the request as a Dataset (fills “Datasets used”)
                # Requires pandas; if not installed, this silently skips.
                try:
                    import pandas as pd
                    from mlflow.data import from_pandas
                    ds = from_pandas(pd.DataFrame([{
                        "prompt": req.prompt,
                        "max_new_tokens": req.max_new_tokens,
                        "temperature": req.temperature,
                        "top_p": req.top_p,
                        "top_k": req.top_k or None,
                    }]), source="api")
                    mlflow.log_input(ds, context="inference")
                except Exception:
                    pass

                # Include run_id in response (useful for deep-linking)
                try:
                    resp.mlflow_run_id = run.info.run_id  # if your response model supports it
                except Exception:
                    pass

            finally:
                try:
                    mlflow.end_run(status="FINISHED")
                except Exception:
                    pass
        except Exception as ex:
            logger.warning(f"MLflow auto-log init skipped: {ex}")

    return resp


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


@app.post("/v1/feedback", tags=["LLM"])
def feedback(req: FeedbackRequest):
    if not MLFLOW_TRACKING_URI:
        raise HTTPException(status_code=400, detail="MLFLOW_TRACKING_URI not set")
    try:
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        # Log as metrics + tags on the existing run
        # Note: MLflow requires an active run to log; use client API to set tags/metrics on run_id.
        from mlflow.tracking import MlflowClient
        c = MlflowClient()
        ts = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        c.log_metric(req.run_id, key="human_rating", value=float(req.rating), timestamp=ts)
        if req.comment:
            c.set_tag(req.run_id, "human_comment", req.comment)
        if req.label:
            c.set_tag(req.run_id, "human_label", req.label)
        return {"status": "ok", "run_id": req.run_id}
    except Exception as e:
        logger.warning(f"feedback log failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
