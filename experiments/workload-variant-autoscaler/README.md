# Saturation-Based Workload Variant Autoscaler initial evaluation

## Scenario of testing

This experiment ran on a 4.20 OCP cluster on AWS leveraging 3x g6e.2xlarge GPU instances, each with 4x Nvidia L40S GPUs.

The model under test is LLama-3.1-8B.

The load generator is GuideLLM. ISL/OSL is 1k/2k.

Multiple time-shifted GuideLLM instances apply a stair-step signal to the deployed model:
- 0-30m: RPS stepwise ramp-up
- 0.5 Hz to 2 Hz
- +0.5 Hz / 10 minutes
- 30m-60m: 2Hz

## Deploy the cluster

Day2 requirements:

- NVIDIA GPU Operator
- Node Feature Discovery Operator
- Openshift Service Mesh Operator
- Tekton (Openshfit Pipelines)
- Keda (Custom Metrics Autoscaler)
- A storage class supporting ReadWriteMany PVCs (e.g. NFS, ODF, etc.)
- The Tekton tasks in [llm-d-lab/manifests/50-pipelines](../../manifests/50-pipelines) deployed in the cluster.

The cluster's day2 operations in this experiment are managed with the scripts in this repo (see the main README.md for details), 
running on a fresh OCP 4.20 cluster.

**Disclaimer**: This repo is a continuous work in progress and still very experimental. It might be broken at times as we
conclude the initial PoC phase.

## Deploy LLM-D

Considering the inference scheduling Well-Lit Path, use the values.yaml file in 
[./10-llm-d-upstream/values.yaml](./10-llm-d-upstream/values.yaml).

At the time of writing, using the fork of the llm-d guides repo in [this PR](https://github.com/llm-d/llm-d/pull/430), you
can run:
```shell
helmfile -n experiment-01 apply -f /LLM_D_REPO_PATH/guides/inference-scheduling/helmfile.yaml.gotmpl --state-values-file /path/to/llm-d-lab/examples/llm-d-upstream-simmple/values.yaml
```

If you are using the official llm-d guides repo, you can manually override the llm-d chart values, using the ones in
[./10-llm-d-upstream/values.yaml](./10-llm-d-upstream/values.yaml) as reference.


```shell
oc apply -k .
```

- You can change the HTTPRoute manifest to match your setup via kustomization patches.
- Patch the PVC configuration to match your storage class.

## Deploy the workload variant autoscaler

Use the values files in 
[./10-workload-variant-autoscaler/values.yaml](./10-workload-variant-autoscaler/values.yaml) and deploy the Helm chart
at https://github.com/llm-d-incubation/workload-variant-autoscaler/tree/v0.4.1/charts/workload-variant-autoscaler

## Additional configuration

Duplicate ./20-config/99-hf-secret.example.yaml as ./20-config/99-hf-secret.yaml and fill in your HuggingFace token.

Apply the manifests in ./20-config:
```
oc apply -k ./20-config
```

## Run experiments

Use the Tekton pipeline runs defined in [./30-experiment-runs](./30-experiment-runs).

## Extract and store results

The data are extracted from the Prometheus instance running in the cluster, managed by the Cluster Monitoring Operator.

No data is consumed from the GuideLLM output at this time.

Use the notebook in [/analysis/wva-extract-store.ipynb](../../analysis/wva-extract-store.ipynb) to extract and store the data:

- Extract the time ranges from the Tekton pipeline results
- Create a token with read access to the Prometheus API:
```shell
oc create token bastion-daemon -n debugging --duration 240h
```
- Port-forward the Prometheus service for local execution:
```shell
oc port-forward -n openshift-monitoring svc/thanos-querier 9091:9091
```
- Set up the parameters in the top cell of the notebook and run it.

Use the notebook in [/analysis/wva-analyze.ipynb](../../analysis/wva-analyze.ipynb) to render the analysis report.
