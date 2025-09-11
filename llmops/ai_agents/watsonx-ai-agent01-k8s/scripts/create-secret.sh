#!/bin/bash

# Load environment variables from .env file
set -o allexport
source .env
set +o allexport

# Create the Kubernetes secret
kubectl create secret generic $existingSecretName \
  --from-literal=IBMCLOUD_API_KEY=$IBMCLOUD_API_KEY \
  --from-literal=WATSONX_PROJECT_ID=$WATSONX_PROJECT_ID \
  --from-literal=WATSONX_API_URL=$WATSONX_API_URL \
  --from-literal=WATSONX_LLM_MODEL_ID=$WATSONX_LLM_MODEL_ID \
  --from-literal=WATSONX_EMBEDDING_MODEL_ID=$WATSONX_EMBEDDING_MODEL_ID \
  --dry-run=client -o yaml | kubectl apply -f -