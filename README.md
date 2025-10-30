# 🚀 LLM-D Benchmarking Lab

Accelerate reproducible inference experiments for large language models with [LLM-D](https://github.com/llm-d)! This lab automates the setup of a complete evaluation environment on OpenShift/OKD: GPU worker pools, core operators, observability, traffic control, and ready-to-run example workloads. 

> ⚠️ **Experimental Project:** This is a Work in progress repository. Breaking changes may occur.

<img src="docs/diagram.svg" alt="Architecture Diagram" width="800"/>

---

## 👤 Who is this for?
- 🛠️ Performance engineers running LLM-D & OpenShift AI experiments
- 🏗️ Platform engineers & SREs building scalable LLM serving
- 🧩 Solution architects prototyping LLM-backed solutions
- 🧑‍🔬 Researchers validating distributed inference engines and orchestration strategies

---

## ✨ Key Capabilities
- ☁️ AWS & IBM Cloud support
- ⚡ Automated infrastructure: MachineSets, autoscaling, ClusterAutoscaler
- 🧩 Operators & platform services: NVIDIA GPU Operator, Node Feature Discovery, Descheduler, KEDA, Gateway API, Kuadrant, Authorino, cert-manager
- 🕵️ Observability: NetObserv, LokiStack, Grafana dashboards (WIP)
- 🔬 Example manifests for KServe LLMInferenceService & KV-cache routing
- 🧪 Precise-prefix cache-aware experiments
- 🔄 GitOps App-of-Apps via Argo CD (WIP)

---

## 🛠️ Cluster Prerequisites
- OpenShift 4.20+ (OKD supported)
- Cluster-admin permissions
- Cloud credentials for compute node management
- GPU instance types available

---

## ⚡ Quickstart

1. **Fork/Clone** this repo (Fork is critical for GitOps).
2. **Copy & edit environment:**
   - Duplicate `envs/example-env` → `envs/my-env`
   - Fill in provider-specific values.
3. **Add secrets:** Duplicate the secrets examples from 99-(*).secret.example.yaml to 99-(*).secret.yaml and fill in your sensitive data.
4. **Deploy:**
   ```shell
   pushd envs
   bash bootstrap-no-gitops.sh $YOUR_ENV_NAME $YOUR_CLOUD_PROVIDER
   popd
   ```
5. **Monitor** until all components are healthy.

---

## 📦 What Gets Deployed

- **Infrastructure:**  
  MachineSet, MachineAutoscaler, ClusterAutoscaler (`manifests/01-infra-ocp`)
- **Core Operators:**  
  GPU Operator, Node Feature Discovery, Descheduler, KEDA (`manifests/20-operators`)
- **Networking & API Gateway:**  
  Gateway API, Kuadrant, Authorino, cert-manager (`manifests/40-gateway-api`, `manifests/30-kuadrant`)
- **Observability:**  
  Grafana, NetObserv, LokiStack (`manifests/30-grafana`, `manifests/30-netobserv`)
- **GPU & System Tuning:**  
  NVIDIA GPU Operator, NFD, SR-IOV, Descheduler (`manifests/30-gpu-operator-nfd`, `manifests/30-sriov-operator`, `manifests/25-descheduler`)
- **Optional UIs:**  
  KubeView, Open WebUI (`manifests/80-kubeview`, `manifests/80-open-webui`)
- **LLM-D & RHOAI Scaffolding:**  
  Upstream & downstream pre-reqs, sample workloads (`manifests/60-llm-d-upstream-pre`, `manifests/60-llm-d-rhoai-pre`, `manifests/90-llm-d-rhoai`)

---

## 🏃 Running Example Workloads

- **OpenShift AI Examples:**
  - `manifests/90-llm-d-rhoai/llm-inference-service-qwen2-7b-gpu.yaml`
  - `manifests/90-llm-d-rhoai/llm-inference-service-kv-cache-routing.yaml`
- **LLM-D Experiments:**
  - `manifests/90-examples-llmd/precise-prefix-cache-aware/*`

Use helper scripts in `hack/` (e.g., `hack/curl-model.sh`) to validate endpoints.

---

## 📊 Observability

- **Grafana** (`grafana` namespace): Cluster, NVIDIA GPU, node-exporter, vLLM dashboards
- **NetObserv + LokiStack:** Network flows & logs
- **Prometheus:** User workload monitoring for custom metrics

---

## 🌐 Networking & Access

- **Gateway API:** Traffic via GatewayClass & Gateway resources
- **Kuadrant + Authorino:** Policy management & authentication
- **cert-manager:** Certificate provisioning

---

## 🔄 GitOps (Optional)

GitOps scaffolding is available under `manifests/27-gitops` for App-of-Apps bootstrapping with Argo CD.  
Primary path is non-GitOps bootstrap; GitOps is planned for future releases.

---

## 🛤️ LLM-D Paths

LLM-D paths are not automated yet due to rapid project evolution.

### Open Data Hub / RHOAI

Supporting objects (GatewayClass, Gateway, Open Data Science Resources) are in `manifests/60-llm-d-rhoai-pre`.  
Deploy your `LLMInferenceService` and scenario-specific objects.  
See [kserve repo (release-0.15)](https://github.com/opendatahub-io/kserve/tree/release-v0.15/docs/samples/llmisvc) for examples.

### Upstream LLM-D

Upstream LLM-D deploys Gateway API, GAIE, and a gateway controller (Istio, KGateway, ...) via [prereq scripts](https://github.com/llm-d/llm-d/tree/d87d637a41911ca81dbdf1590b7d3a02274f9bf3/guides/prereq/gateway-provider) and Helm charts.

- If using Istio, deploy as GatewayClass controller in the inference namespace.
- For OCP clusters with Red Hat OpenShift ServiceMesh 3.0, skip [this chart](https://github.com/llm-d/llm-d/blob/d87d637a41911ca81dbdf1590b7d3a02274f9bf3/guides/prereq/gateway-provider/istio.helmfile.yaml#L2-L9) and remove [this dependency](https://github.com/llm-d/llm-d/blob/d87d637a41911ca81dbdf1590b7d3a02274f9bf3/guides/prereq/gateway-provider/istio.helmfile.yaml#L16-L17).

API group differences:
- Downstream: `(inferencepools|...).inference.networking.k8s.io`
- Upstream: `(inferencepools|...).inference.networking.x-k8s.io`

Example Helmfile coming soon!

