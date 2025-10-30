## LLM-D Benchmarking Lab

Accelerate reproducible inference experiments for large language models with [LLM-D](https://github.com/llm-d). This lab automates the provisioning of a complete evaluation environment on OpenShift/OKD: GPU worker pools, core operators, observability, traffic control, and ready-to-run example workloads. Bring your model configs and focus on research and performance engineering—not on cluster plumbing.

Note: this is an experimental, evolving project. Breaking changes may occur.

<img src="docs/diagram.svg" alt="Diagram of the architecture" width="800"/>

## Who is this for?
- Researchers validating distributed inference engines and orchestration strategies
- Performance engineers running experiments on LLM-D and Openshift AI
- Platform engineers and SREs building reliable LLM serving at scale
- Solution architects prototyping LLM-backed solutions on Kubernetes/OpenShift

## Key capabilities
- Support for AWS and IBM Cloud
- Automated infrastructure:
  - MachineSets per zone/arch and per-pool autoscaling
  - ClusterAutoscaler with optional priority expander
- Operators and platform services (installed via OLM/Helm/Kustomize):
  - NVIDIA GPU Operator + Node Feature Discovery
  - Descheduler (Compact-and-Scale friendly)
  - Custom Metrics Autoscaler (KEDA)
  - Gateway API, Kuadrant, Authorino, cert-manager
  - Optional SR-IOV (for advanced networking scenarios)
  - User workload monitoring enabled
  - NetObserv + LokiStack
  - Grafana with curated dashboards (cluster, NVIDIA, node-exporter, vLLM) - WIP
  - KubeView and Open WebUI (optional convenience UIs)
- LLM-D upstream and Red Hat OpenShift AI downstream paths
- Example manifests for KServe LLMInferenceService (RHOAI) and KV-cache routing
- Example scenarios for precise-prefix cache-aware experiments
- [WIP] GitOps App-of-Apps via Argo CD

## Cluster prerequisites
- OpenShift 4.20+ (OKD should work; enable `redhat-operators` and `certified-operators` catalogs)
- Cluster-admin permissions
- Cloud credentials with permissions to manage compute nodes
- GPU instance types available in your region

## Quickstart
1. Fork this repo (recommended) if you plan to use GitOps later.
2. Copy the example environment and edit values for your setup:
   - Duplicate `envs/example-env` to a new directory (e.g., `envs/my-env`).
   - Review and fill provider-specific values and toggles.
3. Provide required secrets using `99-*secret.example.yaml` files as references:
   - `manifests/60-llm-d-upstream-pre/99-secret.example.yaml`
   - `manifests/90-llm-d-rhoai/99-secret.yaml`
4. Deploy:
```shell
bash envs/bootstrap-no-gitops.sh $YOUR_ENV_NAME $YOUR_CLOUD_PROVIDER
```
5. Monitor progress until all components are healthy.

## What gets deployed
- Infrastructure (cloud-specific):
  - `MachineSet`, `MachineAutoscaler`, `ClusterAutoscaler` via `manifests/01-infra-ocp`
- Core operators and platform add-ons (`manifests/20-operators`):
  - GPU Operator, Node Feature Discovery
  - Descheduler
  - Custom Metrics Autoscaler (KEDA)
  - CatalogSources, OperatorGroups, Subscriptions wiring
- Networking and API Gateway (`manifests/40-gateway-api`, `manifests/30-kuadrant`):
  - Gateway API, GatewayClasses and Gateways
  - Kuadrant + Authorino for policy and auth
  - cert-manager for certificates
- Observability (`manifests/30-grafana`, `manifests/30-netobserv`):
  - Grafana operator resources, Prometheus datasource, curated dashboards
  - NetObserv and LokiStack
  - User workload monitoring enabled
- GPU and system tuning:
  - NVIDIA GPU Operator + NFD (`manifests/30-gpu-operator-nfd`)
  - Optional SR-IOV stack (`manifests/30-sriov-operator`)
  - Descheduler policy (`manifests/25-descheduler`)
- Optional UIs and utilities:
  - KubeView with auth-layer (`manifests/80-kubeview`)
  - Open WebUI reference (`manifests/80-open-webui`)
- LLM-D upstream and RHOAI downstream scaffolding:
  - Upstream pre-reqs and namespace (`manifests/60-llm-d-upstream-pre`)
  - RHOAI pre-reqs and sample `LLMInferenceService` (`manifests/60-llm-d-rhoai-pre`, `manifests/90-llm-d-rhoai`)
- Example experiments:
  - Precise prefix cache-aware scenarios (`manifests/90-examples-llmd/precise-prefix-cache-aware`)

## Running example workloads
- Red Hat OpenShift AI examples:
  - `manifests/90-llm-d-rhoai/llm-inference-service-qwen2-7b-gpu.yaml`
  - `manifests/90-llm-d-rhoai/llm-inference-service-kv-cache-routing.yaml` (includes KV-cache metrics knobs)
- LLM-D experiments:
  - `manifests/90-examples-llmd/precise-prefix-cache-aware/*`

After deployment, you can use helper scripts in `hack/` (for example, `hack/curl-model.sh`) to validate endpoints.

## Observability
- Grafana namespace `grafana` with dashboards for:
  - Cluster monitoring, NVIDIA GPU, node-exporter, vLLM
- NetObserv + LokiStack for network flows and logs
- Prometheus user workload monitoring enabled for custom metrics

## Networking and access
- Gateway API exposes traffic through `GatewayClass` and `Gateway` resources
- Kuadrant + Authorino for policy management and authn/z
- cert-manager provisions certificates for routes

## GitOps (optional)
The repo includes GitOps scaffolding under `manifests/27-gitops` to bootstrap an App-of-Apps approach with Argo CD. For now, the primary path is the non-GitOps bootstrap script; GitOps is planned for future iterations.

# LLM-D paths

LLM-D paths are not automated here as the project is in a too early stage and evolving rapidly.

## Open Data Hub/RHOAI

Most of the supporting objects (GatewayClass, Gateway, Open Data Science Resources...) are provided under `manifests/60-llm-d-rhoai-pre` and you will need to deploy your LLMInferenceService object and any other scenario-specific object.

Some examples will be provided here soon. Examples of LLMInferenceService objects can be found in the  [kserve repo (release-0.15)](https://github.com/opendatahub-io/kserve/tree/release-v0.15/docs/samples/llmisvc).

## Upstream LLM-D
You won't need to deploy any dependencies provided in the Helmfile projects in the [guides](https://github.com/llm-d/llm-d/tree/main/guides).

Upstream LLM-D deploys the Gateway API, GAIE, and a provider (Istio, KGateway, ...) via the [prereq](https://github.com/llm-d/llm-d/tree/d87d637a41911ca81dbdf1590b7d3a02274f9bf3/guides/prereq/gateway-provider) scripts and Helm charts.

When users choose Istio, Istio is deployed as the controller for the GatewayClass, usually in the same namespace where the inference workloads are created.

Isio is the upstream for Red Hat OpenShift ServiceMesh 3.0. When installing the upstream distribution in an OCP cluster that already runs Red Hat OpenShift ServiceMesh 3.0, be sure to skip [this](https://github.com/llm-d/llm-d/blob/d87d637a41911ca81dbdf1590b7d3a02274f9bf3/guides/prereq/gateway-provider/istio.helmfile.yaml#L2-L9) chart and remove the [dependency](https://github.com/llm-d/llm-d/blob/d87d637a41911ca81dbdf1590b7d3a02274f9bf3/guides/prereq/gateway-provider/istio.helmfile.yaml#L16-L17) in the second one.

LLM-D on RHOAI/ODH relies on the Gateway API using the deployment istiod-openshift-gateway in the namespace openshift-ingress-controller, managed by OSSM3's IstioRevision openshift-gateway.

The Gateway API (and extensions) installed upstream via install-gateway-provider-dependencies are slightly different in the API group, for example:

(inferencepools|...).inference.networking.k8s.io <- used by the downstream
(inferencepools|...).inference.networking.x-k8s.io <- used by the upstream helm apps

An example Helmfile will be provided soon for defining your own paths in a cluster running this infrastructure.