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

## 💡 Philosophy

- 🔁 GitOps-first: Everything is managed via ArgoCD applications
- 📄 Avoid local scripts execution: Prefer declarative manifests and Kubernetes control loops over imperative scripts to run locally
- ⚡ Low friction and dependencies on the user's workstation tooling
- 🧩 Modular & extensible: Fork Customize via Kustomize overlays
- ☸️ Cloud-native: Leverage OpenShift operators & best practices
- 🔁 Reproducible: Version-controlled manifests for consistent setups
- 🔬 Experiment-focused: Ready-to-run LLM-D workloads & experiments

------

## 🛠️ Cluster Prerequisites
- OpenShift 4.20+
- Cluster-admin permissions

## ⚡ Quickstart on AWS

1. Clone this repo.
2. Fill the GitOps Root Application in [overlays/aws/root-app.yaml](./overlays/aws/root-app.yaml) (See [app-of-apps pattern](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/)):
   - The minimum required values are the ClusterApi identifier, region and available zones of the cluster, and the routes for the Gateway API. You can also fork and replace the repo URL with your own. This is recommended as using the main repo URL directly means binding your cluster to the current state of this repo. Further documentation is planned for customizations of the environments.
3. Fill the secrets in `overlays/aws/99-*.example.yaml` and save as `overlays/aws/99-*.yaml`.
4. Deploy via `oc apply -k overlays/aws/`.
5. Wait for all the ArgoCD applications to become ready: you can find them in the Openshift WebUI or via `oc get applications -n openshift-gitops`.

## ⚡ Quickstart on IBMCloud

To be tested and documented.

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

See [experiments/workload-variant-autoscaler](experiments/workload-variant-autoscaler) for a complete example of deploying Upstream LLM-D with Workload Variant Autoscaling and collect some metrics for analysis.

## ⚠️ Limitations and Notes

- When deploying the full env in `env/lab`, MachineSets and Cluster Autoscaling are configured together with the operators installation. In case of SNO clusters, the master is configured to not host user workloads anymore, but the MachineSets and Cluster Autoscaler are still progressing. The cluster will eventually converge to the desired state, but it's suggested to have some worker nodes already available to speed up the initial setup and make it more reliable.
- The uninstallation of this stack is not yet fully supported. For example, operators manged via OLM will not be removed automatically and manual clean-up might be needed. Still, as MachineSets and Cluster Autoscaler are removed, be sure to provision some worker nodes to allow the re-scheduling of the remaining workloads.

## 📝 Backlog

- [ ] Add IBMCloud overlay
- [ ] CertManager configuration
- [ ] Kuadrant configuration
- [ ] Authorino configuration
- [ ] Other Grafana dashboards
- [ ] Grafana Authentication should be backed by Openshift OAuth
- [ ] Review RBACs, resource requests/limits, and other manifests refinements
- [ ] Multi-tenancy and concurrent deployments and experiment jobs management, e.g., via Tekton Pipelines, Kueue, and other tools for workload orchestration
- [ ] Most operators are configured in their simplest form and in the global manifests. Further tuning and customizations might be needed for specific use cases, e.g., for the configuration of the NVidia GPU Operator and networking. Such configuration will be unlocked from the global manifests and moved to dedicated environment overlays or experiments, given the assessment of the requiremeents to enable multi-tenancy and concurrent experiments on the same cluster (see previous point)
- [ ] More example workloads and experiments
- [ ] Documentation

## 📁 Structure of the repo

```shell
apps/                  # ArgoCD Applications manifests. Each folder should refer to an Helm or Kustomize project, defined in /manifests if not external.
envs/                  # Kustomize base for different environments (e.g., lab, demo, AWS, IBMCloud)
examples/              # Example Helmfiles and manifests to deploy LLM-D workloads on top of the deployed platform, either Upstream or via RHOAI/ODH.
experiments/           # Example experiments leveraging the deployed platform
manifests/             # Helm charts and Kustomize bases for operators and platform services
overlays/              # Kustomize overlays for different environments. 
```

`/overlays/` in this repo only contains examples at the time of writing.
Clusters-specific `overlays/` should not have secrets and might stay in private forks to control several clusters with different configurations (cloud providers, hostnames, secrets, ...), fully leveraging the GitOps App of Apps pattern.

The examples inherently violate the pattern as they change the children applications with information about the managed cluster we prefer not to disclose publicly, e.g., the base domain of the managed clusters. This is today a practical compromise for experimentation purposes to avoid over-complicating secrets management and delivery.

## 🔧 Customizing the environments

To be documented