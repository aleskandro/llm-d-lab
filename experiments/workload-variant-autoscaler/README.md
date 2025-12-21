# Saturation-Based Workload Variant Autoscaler initial evaluation

## Scenario of testing

This experiment ran on a 4.20 OCP cluster on AWS leveraging 3x g6e.12xlarge GPU instances, each with 4x Nvidia L40S GPUs.

The model under test is LLama-3.1-8B.

The load generator is GuideLLM. ISL/OSL is 1k/2k.

Multiple time-shifted GuideLLM instances apply a stair-step signal to the deployed model:
- 0-30m: RPS stepwise ramp-up
- 0.5 Hz to 2 Hz
- +0.5 Hz / 10 minutes
- 30m-60m: 2Hz

## Provision the cluster and infrastructure

### Using the full setup
1. Deploy a fresh cluster and only install the Openshift GitOps Operator (ArgoCD).
2. Clone this repo or fork it if you need to make changes to the infra manifests.
3. Deploy the Kustomize project in [llm-d-lab/overlays/aws](../../overlays/aws) to set up the cluster Day2 infra. Be sure to have some workers to host the initial configuration load. The GitOps project will also deploy MachineSets and autoscaling to add other nodes as needed.
4. Wait until all the applications are healthy in ArgoCD.

### Other information for manual setups

Day2 requirements:
- ArgoCD (Openshift GitOps Operator)
- NVIDIA GPU Operator
- Node Feature Discovery Operator
- Openshift Service Mesh Operator
- Tekton (Openshfit Pipelines)
- Keda (Custom Metrics Autoscaler)
- A storage class supporting ReadWriteMany PVCs (e.g. NFS, ODF, etc.)
- The Tekton tasks in [llm-d-lab/manifests/50-pipelines](../../manifests/50-pipelines) deployed in the cluster.

The cluster's day2 operations in this experiment are managed with the scripts in this repo (see the main README.md for details), running on a fresh OCP 4.20 cluster.

If you use the full, make sure you're in a fresh OCP Cluster and that you have deployed ArgoCD (Openshift GitOps Operator) in the cluster (no other configuration is needed).

**Disclaimer**: This repo is a continuous work in progress and still very experimental. It might be broken at times as we conclude the initial PoC phase.

## Deploy LLM-D and the Workload Variant Autoscaler

This procedure is only tested in clusters using the full setup described above.

```shell
oc apply -k ./10-llm-d-upstream
oc apply -k ./10-workload-variant-autoscaler
```

You'll find the deployment of LLM-D in the namespace `experiment-01`.
The Workload Variant Autoscaler is deployed in the namespace `llm-d-autoscaler`.

Ensure the ArgoCD applications are healthy.

Apply the additional configuration in ./20-config.
```shell
oc apply -k ./20-config
```

## Run experiments

Use the Tekton pipeline runs defined in [./30-experiment-runs](./30-experiment-runs).

## Grafana Dashboard

A grafana dashboard is provided in [/manifests/30-grafana/dashboards/llmd-vllm-wva.yaml](../../manifests/30-grafana/dashboards/llmd-vllm-wva.yaml) to monitor the autoscaling behavior.

The Grafana dashboard should be already available if using the full setup.

## Jupyter notebook for data visualization

The data are extracted from the Prometheus instance running in the cluster, managed by the Cluster Monitoring Operator.

No data is consumed from the GuideLLM output at this time.

Use the notebook in [/analysis/wva-extract-store.ipynb](../../analysis/wva-extract-store.ipynb) to extract and store the data:

- Extract the time ranges from the Tekton pipeline results
- Create a token with read access to the Prometheus API:
```shell
oc create token bastion-daemon -n debugging --duration 240h
```
- Set the values in the top cell of the notebook.
- Port-forward the Prometheus service for local execution:
```shell
oc port-forward -n openshift-monitoring svc/thanos-querier 9091:9091
```

Set up the parameters in the top cell of the notebook and run it.
