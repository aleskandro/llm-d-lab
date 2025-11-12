# LLM Parameter Estimation Pipeline

This directory contains Tekton Pipeline and Tasks to estimate parameters for the LLM-D's [Workload Variant Autoscaler](https://github.com/llm-d-incubation/workload-variant-autoscaler).

## Overview

The pipeline runs two sequential benchmarks and calculates parameters:

1. **Synchronous Benchmark** - Measures baseline latency (ITL_synchronous)
2. **Throughput Benchmark** - Measures latency under load (ITL_throughput)
3. **Parameter Calculation** - Computes alpha and beta values

## Architecture

This pipeline uses the **cluster resolver** to reference the `guidellm-load-generator` task from the `pipelines` namespace. This allows for:
- **Centralized task management**: The load generator task is maintained in one place
- **Reusability**: Multiple pipelines can use the same task
- **Separation of concerns**: Experiment-specific pipelines stay focused on workflow

## Files

- `namespace.yaml` - Namespace definition (`wva-training`)
- `task-calculate-params.yaml` - Task to calculate alpha and beta parameters
- `pipeline.yaml` - Pipeline orchestrating benchmarks and calculations
- `pipelinerun.example.yaml` - Example PipelineRun
- `99-hf-secret.example.yaml` - HuggingFace token secret template
- `kustomization.yaml` - Kustomize configuration for deployment

## Prerequisites

The `guidellm-load-generator` task must be deployed in the `pipelines` namespace. See the load generator task documentation for deployment instructions.

## Parameters

All parameters are configurable in the Pipeline:

- `target-url` - Target LLM service URL (default: `http://vllm:8000`)
- `model` - Model to benchmark (default: `unsloth/Meta-Llama-3.1-8B`)
- `prompt-tokens` - Number of prompt tokens (default: `128`)
- `output-tokens` - Number of output tokens (default: `128`)
- `max-seconds` - Duration of each benchmark (default: `360`)
- `max-concurrency` - Concurrency for throughput test (default: `64`)
- `batch-size` - Batch size for parameter calculation (default: `64`, should match `max-concurrency`)
- `hf-secret-name` - Name of secret containing HuggingFace token (default: `huggingface-secret`)

## Usage

### 1. Create HuggingFace Token Secret (Optional)

If your model requires authentication:

```bash
# Copy and edit the example
cp 99-hf-secret.example.yaml 99-hf-secret.yaml
# Edit 99-hf-secret.yaml with your token

# Or create directly
kubectl create secret generic huggingface-secret \
  --from-literal=token=YOUR_HUGGINGFACE_TOKEN_HERE \
  -n wva-training
```

### 2. Deploy the Pipeline and Tasks

Using kustomize (recommended):

```bash
kubectl apply -k . --server-side
```

### 3. Run the Pipeline

Using the example:

```bash
kubectl apply -f pipelinerun.example.yaml
```

Or create a custom run:

```bash
kubectl create -f - <<EOF
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: llm-parameter-estimation-
  namespace: wva-training
spec:
  pipelineRef:
    name: llm-parameter-estimation
  params:
    - name: target-url
      value: "http://my-vllm-service:8000"
    - name: batch-size
      value: "128"
    - name: max-concurrency
      value: "128"
    - name: prompt-tokens
      value: "256"
    - name: output-tokens
      value: "256"
  workspaces:
    - name: shared-workspace
      volumeClaimTemplate:
        spec:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 1Gi
EOF
```

### 4. Monitor Progress

```bash
# List pipeline runs
kubectl get pipelinerun -n wva-training

# Watch a specific run
tkn pipelinerun logs llm-parameter-estimation-run -f -n wva-training

# Or with kubectl
kubectl logs -f -n wva-training -l tekton.dev/pipelineRun=llm-parameter-estimation-run

# View pipeline run results/artifacts
tkn pipelinerun describe llm-parameter-estimation-run -n wva-training
```

## Results

### Pipeline Results (Outputs)

The pipeline exposes the following results, visible in the OpenShift Pipeline Run "Output" tab:

- `alpha` - Calculated alpha parameter (base latency)
- `beta` - Calculated beta parameter (incremental latency)
- `parameters-file` - Path to the parameters JSON file
- `synchronous-report` - Path to synchronous benchmark JSON report
- `throughput-report` - Path to throughput benchmark JSON report

### Task Results (Artifacts)

Each task emits results that can be viewed using `tkn pipelinerun describe`:

**Synchronous Benchmark Task:**
- `benchmark-report` - Path to synchronous.json
- `log-file` - Path to synchronous-log.txt

**Throughput Benchmark Task:**
- `benchmark-report` - Path to throughput.json
- `log-file` - Path to throughput-log.txt

**Calculate Parameters Task:**
- `alpha` - Calculated alpha value
- `beta` - Calculated beta value
- `parameters-file` - Path to parameters.json

### Workspace Files

The pipeline stores results in the shared workspace:

- `synchronous.json` - Synchronous benchmark results
- `synchronous-log.txt` - Synchronous benchmark logs
- `throughput.json` - Throughput benchmark results
- `throughput-log.txt` - Throughput benchmark logs
- `parameters.json` - Calculated alpha and beta values

The final calculation task prints:
- ITL_synchronous
- ITL_throughput
- alpha (base latency)
- beta (incremental latency per request)

## Formula

The WVA model analyzer uses the linear relationship:

```
ITL = alpha + beta × batch_size
```

The parameter calculation solves this system of equations:
1. ITL_synchronous = alpha + beta (batch size = 1)
2. ITL_throughput = alpha + beta × batch_size (batch size = max_concurrency)

The solution is:

```
beta = (ITL_throughput - ITL_synchronous) / (batch_size - 1)
alpha = ITL_synchronous - beta
```

Where:
- **alpha** represents the base overhead per request
- **beta** represents the incremental overhead per request in a batch
- **batch_size** should match the `max-concurrency` value used in the throughput test

## Accessing Results

### Via OpenShift Console

Navigate to the PipelineRun details page and click the **Output** tab to see:
- Alpha and beta values
- Paths to all report files

### Via Tekton CLI

View pipeline results:

```bash
# View all pipeline results
tkn pipelinerun describe llm-parameter-estimation-run -n wva-training

# Get alpha and beta values directly
kubectl get pipelinerun llm-parameter-estimation-run -n wva-training \
  -o jsonpath='{.status.results[?(@.name=="alpha")].value}'

kubectl get pipelinerun llm-parameter-estimation-run -n wva-training \
  -o jsonpath='{.status.results[?(@.name=="beta")].value}'

# Get all results as JSON
kubectl get pipelinerun llm-parameter-estimation-run -n wva-training \
  -o jsonpath='{.status.results}'
```

### Via Workspace PVC

To access the full benchmark files from the workspace:

```bash
# Get the PVC name
kubectl get pvc -n wva-training

# Create a debug pod to access the workspace
kubectl run -it --rm debug --image=busybox -n wva-training \
  --overrides='{"spec":{"containers":[{"name":"debug","image":"busybox","command":["sh"],"volumeMounts":[{"name":"workspace","mountPath":"/workspace"}]}],"volumes":[{"name":"workspace","persistentVolumeClaim":{"claimName":"<pvc-name>"}}]}}'

# Inside the pod, view results
cat /workspace/parameters.json
cat /workspace/synchronous.json
cat /workspace/throughput.json
cat /workspace/synchronous-log.txt
cat /workspace/throughput-log.txt
```

## Example Output

After a successful run, the `parameters.json` file will contain:

```json
{
  "itl_synchronous": 7.0,
  "itl_throughput": 8.7,
  "batch_size": 64.0,
  "alpha": 6.973,
  "beta": 0.027
}
```

## Troubleshooting

### Pipeline fails to find guidellm-load-generator task

Ensure the `guidellm-load-generator` task is deployed in the `pipelines` namespace:

```bash
kubectl get task guidellm-load-generator -n pipelines
```

If not found, deploy the load generator task to the `pipelines` namespace first.

### Permission errors with cluster resolver

Ensure your Tekton installation has cluster resolver enabled and the necessary RBAC permissions to access tasks across namespaces.

### Benchmark timeouts

If benchmarks timeout, consider:
- Increasing `max-seconds` parameter
- Reducing `max-concurrency` for throughput test
- Checking target service availability and capacity
