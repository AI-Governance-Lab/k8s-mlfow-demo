#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="ai-agent01"
SRC_FILE="app/main.py"
DEST_PATH="/app/main.py"
CONTAINER_NAME="ai-agent01"
APP_LABEL="app=ai-agent01"

# Usage: kubectl-copy-main.sh [-n|--namespace <ns>] [-f|--file <src>] [-c|--container <name>]
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2 ;;
    -f|--file) SRC_FILE="$2"; shift 2 ;;
    -c|--container) CONTAINER_NAME="$2"; shift 2 ;;
    *) echo "Usage: $0 [-n|--namespace <ns>] [-f|--file <src>] [-c|--container <name>]"; exit 1 ;;
  esac
done

# Ensure namespace exists (namespace must be created manually)
kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || { echo "Namespace $NAMESPACE not found. Create it first."; exit 1; }

# Wait for a pod with the label to be ready, then get its name
kubectl wait --for=condition=Ready pod -l "$APP_LABEL" -n "$NAMESPACE" --timeout=120s >/dev/null 2>&1 || true
POD_NAME=$(kubectl get pods -n "$NAMESPACE" -l "$APP_LABEL" -o jsonpath='{.items[0].metadata.name}')

if [[ -z "${POD_NAME:-}" ]]; then
  echo "No pod with label $APP_LABEL found in namespace $NAMESPACE."
  exit 1
fi

kubectl cp "$SRC_FILE" -n "$NAMESPACE" "$POD_NAME":"$DEST_PATH" -c "$CONTAINER_NAME"
echo "Copied $SRC_FILE to $POD_NAME:$DEST_PATH in namespace $NAMESPACE."