# watsonx-ai-agent01-k8s Project

This project deploys a FastAPI application as a Kubernetes service using Helm. The application is designed to interact with IBM Watson services and is configured using environment variables stored in a Kubernetes secret.

## Project Structure

```
watsonx-ai-agent01-k8s
├── helm
│   └── ai-agent01
│       ├── Chart.yaml          # Helm chart metadata
│       ├── values.yaml         # Configuration values for the Helm chart
│       └── templates           # Kubernetes resource templates
│           ├── deployment.yaml  # Deployment configuration
│           ├── service.yaml     # Service configuration
│           ├── secret.yaml      # Secret configuration
│           ├── configmap.yaml   # ConfigMap configuration
│           ├── _helpers.tpl     # Helper templates
│           └── NOTES.txt        # Installation notes
├── app
│   ├── main.py                 # Main FastAPI application
│   ├── requirements.txt        # Python dependencies
│   └── tests
│       └── test_main.py        # Unit tests for the FastAPI application
├── scripts
│   ├── create-secret.sh        # Script to create Kubernetes secret
│   └── kubectl-copy-main.sh    # Script to copy main.py to running container
├── .env                        # Environment variables for the application
├── .env.example                # Example environment variables
├── .gitignore                  # Git ignore file
└── README.md                   # Project documentation
```

## Getting Started

### Prerequisites

- Kubernetes cluster
- Helm installed
- Docker installed

### Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd watsonx-ai-agent01-k8s
   ```

2. **Create the Kubernetes secret:**
   Ensure that your `.env` file is properly configured with the necessary environment variables. Then run:
   ```bash
   ./scripts/create-secret.sh
   ```

3. **Deploy the application using Helm:**
   ```bash
   helm install ai-agent01 helm/ai-agent01
   ```

4. **Access the application:**
   The application will be exposed on NodePort 30005. You can access it via:
   ```
   http://<node-ip>:30005
   ```

### Testing the Application

To run the tests for the FastAPI application, navigate to the `app` directory and execute:
```bash
pytest tests/
```

### Manual Copy of main.py

If you need to manually copy the `main.py` file into the running container, use the following command:
```bash
./scripts/kubectl-copy-main.sh
```

### Additional Notes

- The FastAPI application includes automatic API documentation and testing capabilities.
- For more information on the API endpoints, visit the documentation available at `/docs` or `/redoc` after deploying the application.

## Install on Kubernetes

Prereqs:
- kubectl and Helm configured to your cluster
- .env file with IBM Cloud/watsonx vars

1) Create namespace (manual)
- kubectl create namespace ai-agent01

2) Create Secret from .env in that namespace
- kubectl -n ai-agent01 create secret generic ai-agent01-env --from-env-file=.env
# or:
- bash scripts/create-secret.sh .env

3) Deploy with Helm
- helm upgrade --install ai-agent01 ./helm/ai-agent01 -n ai-agent01

4) Verify
- kubectl get pods -n ai-agent01
- kubectl get svc -n ai-agent01 ai-agent01
Service is exposed on NodePort 30005:
- http://<NodeIP>:30005/docs
- http://<NodeIP>:30005/redoc

## Copy and run FastAPI app manually

After install, the container stays Running in idle mode (sleep). You can copy main.py and start FastAPI manually:

- POD=$(kubectl get pods -n ai-agent01 -l app.kubernetes.io/name=ai-agent01 -o jsonpath="{.items[0].metadata.name}")
- kubectl cp app/main.py -n ai-agent01 "$POD":/app/main.py -c ai-agent01
- Foreground (blocks your terminal):
  - kubectl exec -n ai-agent01 -it "$POD" -c ai-agent01 -- sh -lc 'cd /app && uvicorn main:app --host 0.0.0.0 --port 8000'
- Background (keeps running after you disconnect):
  - kubectl exec -n ai-agent01 -it "$POD" -c ai-agent01 -- sh -lc 'cd /app && nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &'
  - Tail logs: kubectl exec -n ai-agent01 "$POD" -c ai-agent01 -- sh -lc 'tail -n 200 -f /tmp/uvicorn.log'

Access:
- http://<NodeIP>:30005/docs
- http://<NodeIP>:30005/redoc

## Run mode (idle) and manual start

After deploying with Helm, the container runs in idle mode (sleep infinity) so the pod stays Running. Then you can:
- Copy code: POD=$(kubectl get pods -n ai-agent01 -l app.kubernetes.io/name=ai-agent01 -o jsonpath="{.items[0].metadata.name}")
- kubectl cp app/main.py -n ai-agent01 "$POD":/app/main.py -c ai-agent01
- Start API (foreground): kubectl exec -n ai-agent01 -it "$POD" -c ai-agent01 -- sh -lc 'cd /app && uvicorn main:app --host 0.0.0.0 --port 8000'
- Start API (background): kubectl exec -n ai-agent01 -it "$POD" -c ai-agent01 -- sh -lc 'cd /app && nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &'
- Tail logs: kubectl exec -n ai-agent01 "$POD" -c ai-agent01 -- sh -lc 'tail -f /tmp/uvicorn.log'

Access Swagger UI and ReDoc via NodePort 30005:
- http://<NodeIP>:30005/docs
- http://<NodeIP>:30005/redoc

## LLM documentation

### Environment variables (from Secret ai-agent01-env)
- IBMCLOUD_API_KEY: IBM Cloud API key used to obtain an IAM access token (required).
- WATSONX_PROJECT_ID: Target watsonx.ai project ID (required).
- WATSONX_API_URL: Regional endpoint, e.g. https://eu-de.ml.cloud.ibm.com (must match project region).
- WATSONX_LLM_MODEL_ID: Text generation model ID, e.g. mistralai/mistral-large.
- WATSONX_EMBEDDING_MODEL_ID: Embedding model ID, e.g. ibm/slate-125m-english-rtrvr.
- WATSONX_VERIFY_TLS (optional): set to "false" to disable TLS verification (not recommended).

### Text generation (POST /v1/generate)
- Purpose: produce natural-language text (Q&A, summaries, drafting).
- Request fields:
  - prompt (string): your instruction/question.
  - max_new_tokens (int): cap on generated length (64–512 typical).
  - temperature (float): 0 deterministic; 0.3–0.9 more creative.
  - top_p (float): nucleus sampling cutoff (e.g., 0.9).
  - top_k (int, optional): top-k sampling cutoff.
  - repetition_penalty (float, optional): >1 discourages repeats (e.g., 1.1).
  - stop_sequences ([string], optional): stop early if sequences appear.
- Decoding: greedy when temperature=0; sampling otherwise (top_p/top_k apply).
- Errors: 401/403 => bad token/permissions; 400 => bad request body.

### Embeddings (POST /v1/embeddings)
- Purpose: convert text into numeric vectors for semantic search/similarity/RAG.
- Request field:
  - input (string | [string]): one or many texts. The service forwards as "inputs" to watsonx.
- Response:
  - embeddings: List[List[float]] (vector length depends on model).
- Note: by default nothing is stored. If you need reuse, persist vectors (see “Index & search” section or use a vector DB).

### API behavior
- IAM token: obtained from IBMCLOUD_API_KEY and cached until expiry.
- Upstream API version: version=2023-05-29 for both generation and embeddings.
- Network: cluster must reach https://iam.cloud.ibm.com and your WATSONX_API_URL.

### Model selection tips
- WATSONX_LLM_MODEL_ID:
  - Larger models => better reasoning, more latency/cost.
  - Choose per task (chat vs. summarization) and region availability.
- WATSONX_EMBEDDING_MODEL_ID:
  - Choose based on language coverage and vector dimension that fits your retrieval system.
  - Normalize vectors (L2) if you compute cosine similarity downstream.

### Helm/runtime controls
- service: NodePort 30005, containerPort 8000 exposed for FastAPI.
- secrets.existingSecretName: name of Secret with the env vars.
- command/args: defaults to sleep infinity so the pod stays Running; you can override to auto-run uvicorn.
  - Example override:
    - helm upgrade --install ai-agent01 ./helm/ai-agent01 -n ai-agent01 --set command[0]=/bin/sh --set command[1]=-c --set args[0]='uvicorn app.main:app --host 0.0.0.0 --port 8000'
- persistence: enable and mount /data if you want to store an index (demo) or attach a vector DB client config.
- probes (optional): point liveness/readiness to /health.

### Testing
- Swagger UI: http://<NodeIP>:30005/docs (try POST /v1/generate, POST /v1/embeddings).
- Health: curl http://<NodeIP>:30005/health
- Curl (Linux) examples:
  - Generation:
    curl -sS -X POST http://<NodeIP>:30005/v1/generate \
      -H "Content-Type: application/json" \
      -d '{ "prompt": "Explain Kubernetes briefly.", "max_new_tokens": 128, "temperature": 0.7 }'
  - Embeddings:
    curl -sS -X POST http://<NodeIP>:30005/v1/embeddings \
      -H "Content-Type: application/json" \
      -d '{ "input": ["Kubernetes orchestration", "Container runtime"] }'

### Security
- Keep .env out of Git; rotate API keys regularly.
- Restrict who can reach the NodePort in production (Ingress + auth is recommended).

## Change model or other configuration

This app reads runtime config from the Kubernetes Secret ai-agent01-env (created from your .env).

1) Edit .env (example: switch to a non‑deprecated model)
- WATSONX_LLM_MODEL_ID=mistralai/mistral-medium-2505
- Optional: change embeddings model, API URL, project:
  - WATSONX_EMBEDDING_MODEL_ID=ibm/slate-125m-english-rtrvr
  - WATSONX_API_URL=https://<region>.ml.cloud.ibm.com
  - WATSONX_PROJECT_ID=<your_project_id>

2) Recreate the Secret in the namespace
- kubectl -n ai-agent01 delete secret ai-agent01-env
- kubectl -n ai-agent01 create secret generic ai-agent01-env --from-env-file=.env

3) Restart the deployment to pick up new env vars
- kubectl rollout restart deploy/ai-agent01 -n ai-agent01
- Verify env in pod:
  - POD=$(kubectl get pods -n ai-agent01 -l app.kubernetes.io/name=ai-agent01 -o jsonpath="{.items[0].metadata.name}")
  - kubectl exec -n ai-agent01 "$POD" -c ai-agent01 -- sh -lc 'env | egrep "WATSONX_(LLM_MODEL_ID|EMBEDDING_MODEL_ID|API_URL)|WATSONX_PROJECT_ID"'

4) If FastAPI was started manually (idle container by default)
- Restart the server after rollout (or kill and relaunch):
  - kubectl exec -n ai-agent01 "$POD" -c ai-agent01 -- sh -lc 'pkill -f "uvicorn" || true; cd /app && nohup uvicorn main:app --host 0.0.0.0 --port 8000 >/tmp/uvicorn.log 2>&1 &'

Notes
- Model availability is region-specific; ensure WATSONX_API_URL matches your project region.
- IBM warns the legacy generation API; chat endpoints may be preferred in future. You can switch the app later if needed.

### Using Swagger (Try it out)
- Leave model_id empty to use the default from environment (recommended).
- Do not send "model_id": "string" (placeholder) — it causes “model_not_supported”.
- top_k must be >= 1. Omit it if unsure.

Minimal payload that works:
```json
{
  "prompt": "Explain Kubernetes briefly.",
  "max_new_tokens": 128,
  "temperature": 0.7
}
```

Optional fields (only if needed):
- top_p: 0.9
- top_k: 1 (or higher)
- repetition_penalty: 1.1
- stop_sequences: ["\nUser:"]

## Quick working requests

Use these exact commands to avoid common pitfalls.

- Linux
```bash
curl -sS -X POST http://<NodeIP>:30005/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{ "prompt": "Ce este Romania?", "max_new_tokens": 64, "temperature": 0.7 }'
```

- Windows CMD
```cmd
curl -sS -X POST http://<NodeIP>:30005/v1/generate ^
  -H "Content-Type: application/json" ^
  -d "{ \"prompt\": \"Ce este Romania?\", \"max_new_tokens\": 64, \"temperature\": 0.7 }"
```

- PowerShell
```powershell
curl.exe -sS -X POST http://<NodeIP>:30005/v1/generate `
  -H "Content-Type: application/json" `
  -d '{ "prompt": "Ce este Romania?", "max_new_tokens": 64, "temperature": 0.7 }'
```

Troubleshooting
- model_not_supported: Remove the model_id field (uses default from .env) or set a valid model (e.g., mistralai/mistral-medium-2505) in .env and recreate the Secret.
- parameters.top_k should be at least 1: Omit top_k or set top_k >= 1.
- JSON decode error / “Extra data”: Ensure you run a single curl command (don’t paste two on one line).
- Legacy warning: It’s safe. This service currently uses the text/generation API; you can switch later to chat if desired.