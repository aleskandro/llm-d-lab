# 🚀 LLM-D Benchmarking Lab

Accelerate reproducible inference experiments for large language models with [LLM-D](https://github.com/llm-d)! This lab automates the setup of a complete evaluation environment on OpenShift/OKD: GPU worker pools, core operators, observability, traffic control, and ready-to-run example workloads. 

> ⚠️ **Experimental Project:** This is a Work in progress repository. Breaking changes may occur. This project is not meant for production use.

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
- OpenShift 4.20+
- Cluster-admin permissions

## ⚡ Quickstart on AWS

1. Clone this repo.
2. Fill the GitOps Root Application in `deploy/app-of-apps.yaml` (See [app-of-apps pattern](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/)):
   - The minimum required values are the ClusterApi identifier, region and available zones of the cluster, and the routes for the Gateway API. You can also fork and replace the repo URL with your own. This is recommended as using the main repo URL directly means binding your cluster to the current state of this repo. Further documentation is planned for customizations of the environments.
3. Fill the secrets in `deploy/99-*.example.yaml` and save as `deploy/99-*.yaml`.
4. Deploy via `oc apply -k deploy/`.
5. Wait for all the ArgoCD applications to become ready: you can find them in the Openshift WebUI or via `oc get applications -n openshift-gitops`.

## ⚡ Quickstart on IBMCloud

To be documented.

---

## 📦 What Gets Deployed

- **Infrastructure:**  
  MachineSet, MachineAutoscaler, ClusterAutoscaler
- **Core Operators:**  
  GPU Operator, Node Feature Discovery, Descheduler, KEDA
- **Networking & API Gateway:**  
  Gateway API, Kuadrant, Authorino, cert-manager
- **Observability:**  
  Grafana, NetObserv, LokiStack
- **GPU & System Tuning:**  
  NVIDIA GPU Operator, NFD, Descheduler
- **LLM-D & RHOAI Scaffolding:**  
  Upstream & downstream pre-reqs

---

## 🏃 Running Example Workloads

The `examples/` folder contains example manifests and Helmfiles to deploy LLM-D workloads on top of the deployed platform.

## 🧪 Example experiment: Upstream LLM-D w/ Workload Variant Autoscaler

See [experiments/workload-variant-autoscaler/README.md](experiments/workload-variant-autoscaling/README.md) for a complete example of deploying Upstream LLM-D with Workload Variant Autoscaling and collect some metrics for analysis.

## Structure of the repo

To be refined and documented

## 🔧 Customizing the environments

To be documented