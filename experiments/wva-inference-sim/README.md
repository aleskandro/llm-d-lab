# WVA Benchmark with llm-d-inference-sim (No GPU Required)

This experiment evaluates the Workload Variant Autoscaler (WVA) using
[llm-d-inference-sim](https://github.com/llm-d/llm-d-inference-sim) as a
drop-in replacement for vLLM. The simulator exposes the same Prometheus metrics
WVA consumes (`vllm:kv_cache_usage_perc`, `vllm:num_requests_waiting`,
`vllm:cache_config_info`, etc.) while requiring zero GPU resources.

This is a variant of the [original WVA experiment](../workload-variant-autoscaler)
that runs in namespace `experiment-02`.

## Key differences from the GPU-based experiment

| Aspect | Original (experiment-01) | Simulator (experiment-02) |
|---|---|---|
| Backend | vLLM via llm-d-modelservice chart | llm-d-inference-sim Deployment |
| GPU | Required (1x per replica) | Not required |
| Model download | 32 Gi PVC + HF token | Tokenizer files only (initContainer + HF token) |
| Startup time | Minutes (model loading) | Configurable (default 120s init container) |
| Namespace | `experiment-01` | `experiment-02` |
| GAIE ArgoCD app | `llm-d-inference-scheduling` | `inference-sim-scheduling` |

## Prerequisites

Day2 requirements (same as the original experiment):
- ArgoCD (OpenShift GitOps Operator)
- OpenShift Service Mesh Operator (Istio)
- Tekton (OpenShift Pipelines)
- KEDA (Custom Metrics Autoscaler)
- The Tekton tasks in [manifests/50-pipelines](../../manifests/50-pipelines)

**Not required** (unlike the original):
- NVIDIA GPU Operator
- Node Feature Discovery Operator
- GPU-capable nodes
- ReadWriteMany storage class

**Additional requirement:**
- A HuggingFace token with access to `meta-llama/Llama-3.1-8B` (Meta license
  accepted). Update `10-inference-sim/99-secret.yaml` with your token.

## Deploy the inference simulator and GAIE
Update `10-inference-sim/99-secret.yaml` with your HuggingFace token (needed by GuideLLM for tokenization), then:

```shell
oc apply -k ./10-inference-sim
```

This creates:
- Namespace `experiment-02` with user-monitoring enabled
- Gateway API Inference Extension CRDs
- Istio Gateway + HTTPRoute + OpenShift Route
- ArgoCD Application for GAIE (InferencePool + EPP)
- ServiceAccount `inference-sim` with `anyuid` SCC (needed for KV cache)
- HuggingFace secret (used by the tokenizer download initContainer)
- ConfigMap with the simulator configuration
- `inference-sim-decode` Deployment and Service (the simulator)
- PodMonitor for Prometheus metric scraping

Verify the simulator is running:
```shell
oc get pods -n experiment-02 -l app=inference-sim-decode
```

Quick test:
```shell
curl -X POST http://inference-sim-gateway.apps.<your-cluster-domain>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "meta-llama/Llama-3.1-8B", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Deploy the Workload Variant Autoscaler

> If WVA is already running from another experiment (e.g. experiment-01),
> this step can be skipped. WVA runs with `namespaceScoped: false` and
> watches VariantAutoscaling CRs across all namespaces.

Update `patch-wva-values.yaml` with your cluster's Prometheus CA certificate, then:

```shell
oc apply -k ./10-workload-variant-autoscaler
```

Wait for the ArgoCD application to become healthy.

## Apply experiment configuration

```shell
oc apply -k ./20-config
```

This creates:
- `VariantAutoscaling` CR targeting the simulator deployment
- Tekton Pipeline `wva-sim-incremental-stepped-load-test`
- KEDA RBAC, TriggerAuthentication, and SA token secret
- HuggingFace secret for GuideLLM

## Run experiments

Use the Tekton PipelineRuns in [./30-experiment-runs](./30-experiment-runs):

| Run | Description |
|---|---|
| `autoscaling-test-wva.yaml` | WVA-driven autoscaling via KEDA (1-4 replicas) |
| `autoscaling-test-one-replica.yaml` | Fixed 1 replica baseline |
| `autoscaling-test-more-replicas.yaml` | Fixed 4 replicas baseline |

```shell
oc create -f ./30-experiment-runs/autoscaling-test-wva.yaml
```

## Simulator tuning

The simulator is configured via a YAML file in the ConfigMap
`10-inference-sim/simulator-config.yaml`. Startup behavior is controlled
by init container env vars in `10-inference-sim/simulator-deployment.yaml`.

### Startup delay

The `simulate-model-loading` init container delays pod readiness to mimic
real vLLM model loading. New replicas stay in `PodInitializing` for this
duration before becoming ready.

| Env var | Default | Description |
|---|---|---|
| `STARTUP_DELAY_SECONDS` | `120` | Base simulated model loading time (seconds) |
| `STARTUP_JITTER_SECONDS` | `10` | Random jitter ± around the base (seconds) |

Each pod gets a random startup delay in the range `[base - jitter, base + jitter]`,
so the default produces 110-130s. Set both to `0` for instant startup, or increase
the base to `300`+ to simulate larger models on slower storage.

### Inference latency

Prefill time scales with prompt length (`latency-calculator: per-token`) instead
of using a fixed TTFT, matching real vLLM where longer prompts take longer to prefill.

| Config key | Value | Description |
|---|---|---|
| `latency-calculator` | `per-token` | Prefill time proportional to prompt length |
| `prefill-overhead` | `50ms` | Constant prefill overhead |
| `prefill-time-per-token` | `0.15ms` | Per-token prefill cost (1024 tokens ≈ 200ms total) |
| `inter-token-latency` | `30ms` | Decode inter-token latency |
| `inter-token-latency-std-dev` | `5ms` | Jitter on decode latency |
| `time-factor-under-load` | `1.5` | At max concurrency, latency is 1.5x baseline |

### Capacity and KV cache

| Config key | Value | Description |
|---|---|---|
| `max-num-seqs` | `64` | Max concurrent sequences |
| `max-model-len` | `4096` | Context window size |
| `max-waiting-queue-length` | `10000` | Queue depth (real vLLM queues nearly unbounded) |
| `enable-kvcache` | `true` | Block-level KV cache tracking |
| `kv-cache-size` | `4096` | Total KV cache blocks |
| `block-size` | `16` | Tokens per cache block |

**KV cache simulation** is critical for realistic `vllm:kv_cache_usage_perc`
values. Without it, cache usage is derived from request counts; with it, usage
tracks actual token block allocation/eviction, matching real vLLM behavior.

**Tokenization note**: `enable-kvcache` requires actual token IDs to allocate
cache blocks. The `llm-d-kv-cache-manager` library needs a real HuggingFace
tokenizer for block hash computation. A `download-tokenizer` init container
pre-downloads `tokenizer.json` and `tokenizer_config.json` into a shared
`emptyDir` volume; the `LOCAL_TOKENIZER_DIR` env var tells the library to use
these local files instead of downloading at runtime. The simulator itself uses
`model: sim/Llama-3.1-8B` to activate its built-in regex tokenizer for request
processing, while `served-model-name: meta-llama/Llama-3.1-8B` controls the
name exposed via the API and Prometheus metric labels.

**Security context**: The deployment runs as root (`runAsUser: 0`) via the
`anyuid` SCC because the `llm-d-kv-cache-manager` library writes to its Go
module path (`/go/pkg/mod/...`) at runtime. The `inference-sim` ServiceAccount
and its `anyuid` RoleBinding are created by `simulator-rbac.yaml`.

**Load-dependent slowdown** (`time-factor-under-load: 1.5`) makes the simulator
progressively slower as concurrency increases, modeling real GPU contention. At 64
concurrent requests latency is 1.5x baseline; at low concurrency it's near 1.0x.

## Grafana Dashboard

The same Grafana dashboard at
[manifests/30-grafana/dashboards/llmd-vllm-wva.yaml](../../manifests/30-grafana/dashboards/llmd-vllm-wva.yaml)
works with the simulator since it exposes identical vLLM metric names. Filter by
`namespace="experiment-02"`.

## Metrics compatibility

The simulator provides all metrics WVA needs:

| WVA metric | Purpose | Simulator support |
|---|---|---|
| `vllm:kv_cache_usage_perc` | KV cache saturation | Yes |
| `vllm:num_requests_waiting` | Queue saturation | Yes |
| `vllm:cache_config_info` | Token capacity (V2) | Yes |
| `vllm:request_success_total` | Scale-to-zero | Yes |
| `vllm:time_to_first_token_seconds` | TTFT analysis | Yes |
| `vllm:time_per_output_token_seconds` | ITL analysis | Yes |
| `vllm:prefix_cache_hits/queries` | Cache hit rate | Yes |
