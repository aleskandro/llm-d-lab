#!/bin/bash
set +x
set -e

pause() {
  read -r -p "Press Enter to continue..."
}

usage() {
  echo "Usage: $0 <environment> <cloud-provider>"
  echo "  <environment>: The target environment in the 'envs' directory."
  echo "  <cloud-provider>: The cloud provider {aws, ibmcloud}."
}

if [ $# -ne 2 ]; then
  usage
  exit 1
fi

ENV_DIR="${1%%/}"
CLOUD_PROVIDER="${2}"
MANIFESTS_DIR="../manifests"
NAMESPACE=helm-charts
oc get namespace $NAMESPACE || oc create namespace "$NAMESPACE"

echo "Applying Helm charts..."

for chart in "01-infra-ocp-${CLOUD_PROVIDER}" 20-operators; do
  if [ ! -d "$ENV_DIR/$chart" ]; then
    echo "Error: Environment directory '$ENV_DIR/$chart' does not exist."
    exit 1
  fi
  find "$ENV_DIR/$chart/" -type f -name '*values.yaml' -print0 | while IFS= read -r -d '' value_file; do
    echo "Applying Helm chart '$chart' with values file '$value_file'"
    base=$(basename "$value_file")
    release_name=${base%values.yaml}
    helm upgrade --install "h-${chart}-${release_name}" "$MANIFESTS_DIR/$chart/" \
      --namespace $NAMESPACE \
      --values "$value_file"
    pause
  done
done

echo "Applying Kustomization projects..."

find "$MANIFESTS_DIR" -type  f -name kustomization.yaml -exec dirname {} \; | sort | while IFS= read -r -d '' kustomization; do
  echo
  echo "Applying kustomization project '$kustomization'"
  for i in 1..60 MAX; do
    if [ "$i" == "MAX" ]; then
      echo "Error: Max retries reached for kustomization project '$kustomization'"
      exit 1
    fi
    echo "Attempt $i to apply kustomization..."
    if oc apply -k "$kustomization"; then
      break
    fi
    echo "Waiting for CRDs required by the kustomization to be created before retrying..."
    sleep 30
  done
done
