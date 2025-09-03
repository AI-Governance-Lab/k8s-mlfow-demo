# MLflow on k3s with Helm (minimal production)

This chart deploys a small-footprint MLflow stack:
- PostgreSQL (Bitnami) as backend store
- MinIO (Bitnami) for artifacts (S3-compatible)
- MLflow Tracking Server exposed via NodePort

Optimized for your k3s cluster with NFS (nfs-client) StorageClass. You can switch to local-path if preferred.

## Prerequisites

- kubectl context to your k3s cluster
- Helm v3
- StorageClass available: nfs-client (recommended) or local-path

Namespace: mlflow

```sh
kubectl create namespace mlflow
```

## Install

From repo root:

```sh
# Add Bitnami repo for dependencies
helm repo add bitnami https://charts.bitnami.com/bitnami

# Go to the chart folder and pull dependencies
cd helm/mlflow-stack
helm dependency update

# Install with small resources and NodePort 30500 (change as needed)
helm install mlflow . -n mlflow --create-namespace \
  --set postgresql.primary.persistence.storageClass=nfs-client \
  --set minio.persistence.storageClass=nfs-client \
  --set mlflow.service.nodePort=30500
```

Access the UI:
- http://<any-node-ip>:30500
  - Examples from your nodes: http://192.168.1.91:30500, http://192.168.6.250:30500, http://192.168.1.38:30500

Verify:

```sh
kubectl -n mlflow get pods
kubectl -n mlflow get svc
kubectl -n mlflow rollout status deploy/mlflow-mlflow
```

Set envs in your apps:

```sh
export MLFLOW_TRACKING_URI=http://192.168.1.91:30500
```

## Uninstall

```sh
helm uninstall mlflow -n mlflow
kubectl delete ns mlflow
```

## Notes

- Storage: defaults use nfs-client; switch to local-path via --set ...storageClass=local-path
- Small footprint: resources are modest; tune in values.yaml
- Single MLflow replica; safe with Postgres + MinIO
- If the MLflow image lacks psycopg2-binary/boto3, set mlflow.image to a custom image that includes them

## Files

- helm/mlflow-stack: Helm chart with dependencies on Bitnami PostgreSQL and MinIO

## Architecture

```mermaid
flowchart LR
  U[Client Browser / App] -->|HTTP :30500| SVC[Service: NodePort (mlflow)]
  SVC --> POD[Deployment: mlflow pod]
  POD -->|Backend store| PG[(PostgreSQL - Bitnami)]
  POD -->|Artifacts (S3 API)| MINIO[(MinIO - Bitnami)]

  subgraph k3s Cluster (mlflow namespace)
    SVC
    POD
    PG
    MINIO
    subgraph Storage (nfs-client)
      PVCpg[(PVC for PostgreSQL)]
      PVCminio[(PVC for MinIO)]
    end
  end

  PG --- PVCpg
  MINIO --- PVCminio

  classDef svc fill:#eef,stroke:#66f;
  classDef pod fill:#efe,stroke:#2a2;
  classDef storage fill:#ffe,stroke:#cc7;
  class SVC svc;
  class POD pod;
  class PG,MINIO storage;
  class PVCpg,PVCminio storage;
```

Summary:
- MLflow exposed via NodePort (default 30500) on all nodes.
- PostgreSQL stores runs/metadata; MinIO stores artifacts in bucket mlflow-artifacts.
- Both use PVCs with the nfs-client StorageClass (switch to local-path if needed).