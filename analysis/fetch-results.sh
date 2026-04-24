#!/usr/bin/env bash
#
# Fetch GuideLLM benchmark results and component logs from a Tekton
# PipelineRun PVC to the local _out/ directory.  Uses a temporary busybox
# pod to mount the PVC, then `oc rsync` to pull the files.
#
# The PVC contains both the GuideLLM JSON benchmark reports and the
# application logs (vLLM, EPP, WVA) collected by the pipeline's
# collect-application-logs finally task.
#
# Usage:
#   ./fetch-results.sh                          # interactive -- lists PVCs and prompts
#   ./fetch-results.sh <pvc-name>               # explicit PVC name
#   ./fetch-results.sh <pvc-name> <namespace>   # explicit PVC + namespace
#
# The script creates:
#   _in/<pvc-name>/...          (mirror of the PVC contents)
#
set -euo pipefail

NAMESPACE="${2:-experiment-01}"
LOCAL_OUT="$(dirname "$0")/_in"
HELPER_POD="pvc-reader-$$"

cleanup() {
    echo "Cleaning up helper pod ${HELPER_POD}..."
    oc delete pod "${HELPER_POD}" -n "${NAMESPACE}" --ignore-not-found --wait=false 2>/dev/null || true
}
trap cleanup EXIT

if [[ $# -ge 1 ]]; then
    PVC_NAME="$1"
else
    echo "Available PVCs in namespace ${NAMESPACE}:"
    echo "---"
    oc get pvc -n "${NAMESPACE}" \
        -o custom-columns='NAME:.metadata.name,STATUS:.status.phase,SIZE:.spec.resources.requests.storage,CREATED:.metadata.creationTimestamp' \
        --sort-by=.metadata.creationTimestamp
    echo "---"
    read -rp "Enter PVC name to fetch from: " PVC_NAME
    if [[ -z "${PVC_NAME}" ]]; then
        echo "No PVC name provided, exiting."
        exit 1
    fi
fi

echo "==> Namespace:  ${NAMESPACE}"
echo "==> PVC:        ${PVC_NAME}"
echo "==> Local dest: ${LOCAL_OUT}/${PVC_NAME}/"
echo ""

echo "==> Creating helper pod ${HELPER_POD}..."
oc run "${HELPER_POD}" \
    --image=busybox \
    --restart=Never \
    -n "${NAMESPACE}" \
    --overrides="$(cat <<EOF
{
  "spec": {
    "containers": [{
      "name": "reader",
      "image": "busybox",
      "command": ["sleep", "600"],
      "volumeMounts": [{"name": "data", "mountPath": "/data"}]
    }],
    "volumes": [{
      "name": "data",
      "persistentVolumeClaim": {"claimName": "${PVC_NAME}"}
    }],
    "nodeSelector": {"kubernetes.io/arch": "amd64"}
  }
}
EOF
)"

echo "==> Waiting for pod to be ready..."
oc wait --for=condition=Ready "pod/${HELPER_POD}" -n "${NAMESPACE}" --timeout=120s

echo ""
echo "==> Files on PVC:"
oc exec "${HELPER_POD}" -n "${NAMESPACE}" -- find /data -type f -name "*.json" -o -name "*.txt" | sort
echo ""

DEST="${LOCAL_OUT}/${PVC_NAME}"
mkdir -p "${DEST}"

echo "==> Syncing to ${DEST}/ ..."
oc rsync "${HELPER_POD}:/data/" "${DEST}/" -n "${NAMESPACE}" --progress

COUNT=$(find "${DEST}" -name "*.json" -type f 2>/dev/null | wc -l | tr -d ' ')
echo ""
echo "==> Done. ${COUNT} JSON file(s) synced to ${DEST}/"
echo ""
echo "Hint: use in the notebook as:"
echo "  from data_source.guidellm import discover_runs"
echo "  GUIDELLM_RESULTS = discover_runs('${DEST}')"
