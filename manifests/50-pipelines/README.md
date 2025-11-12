# Shared Tekton Pipeline Resources

This directory contains reusable Tekton tasks and resources that can be referenced by experiment pipelines across the project.

## Overview

These resources are deployed in the `pipelines` namespace and are designed to be used by multiple experiments via Tekton's **cluster resolver**. This approach provides:

- **Centralized management**: Tasks are maintained in one location
- **Reusability**: Multiple experiment pipelines can use the same tasks
- **Consistency**: All experiments use the same tested implementations
- **Versioning**: Updates to tasks automatically benefit all experiments

## Contents

### task-load-generator.yaml

A flexible, generalized Tekton task for running LLM load tests using [GuideLL](https://github.com/neuralmagic/guidellm).

**Key features:**
- Multiple load patterns: synchronous, throughput, poisson, constant
- Configurable request rates and concurrency levels
- Support for custom data files
- Extensible via additional GuideLL arguments
- Returns benchmark JSON reports and full logs as artifacts

**Use cases:**
- Parameter estimation for autoscalers
- Performance benchmarking under various load patterns
- Stress testing LLM inference services
- Collecting metrics for analysis

The task is deliberately generic and does not extract specific metrics, allowing downstream tasks in your pipeline to perform domain-specific analysis.

### namespace.yaml

Defines the `pipelines` namespace where shared resources are deployed.

### example-custom-load-test.yaml

Example pipeline demonstrating various usage patterns of the load generator task.

## Usage in Experiment Pipelines

To use these tasks from your experiment pipeline, reference them using the cluster resolver:

```yaml
apiVersion: tekton.dev/v1
kind: Pipeline
metadata:
  name: my-experiment
  namespace: my-experiment-namespace
spec:
  tasks:
    - name: run-benchmark
      taskRef:
        resolver: cluster
        params:
          - name: kind
            value: task
          - name: name
            value: guidellm-load-generator
          - name: namespace
            value: pipelines
      params:
        - name: rate-type
          value: throughput
        - name: max-concurrency
          value: "64"
        - name: output-basename
          value: my-benchmark
      workspaces:
        - name: results
          workspace: shared-workspace
```

## Deployment

Deploy all shared resources:

```bash
kubectl apply -k . --server-side
```

Verify deployment:

```bash
kubectl get tasks -n pipelines
```

## Task Parameters

### guidellm-load-generator

For complete parameter documentation and usage examples, see the examples in `example-custom-load-test.yaml`.

**Essential parameters:**
- `target-url` - LLM service endpoint
- `model` - Model name to benchmark
- `rate-type` - Load pattern (synchronous, throughput, poisson, constant)
- `output-basename` - Name prefix for output files

**Load control:**
- `max-seconds` / `max-requests` - Duration or count limit
- `max-concurrency` - Concurrent requests (throughput mode)
- `rate` - Requests per second (poisson/constant modes)

**Results:**
- `benchmark-report` - Path to JSON report
- `log-file` - Path to full logs

## Examples

See experiments using these tasks:
- `experiments/workload-variant-autoscaler/10-parameter-estimation/` - Parameter estimation pipeline

## Contributing

When adding new shared tasks:
1. Ensure they are generic and reusable across experiments
2. Document parameters thoroughly
3. Add to kustomization.yaml
4. Update this README with usage examples
5. Test with cluster resolver from a different namespace
