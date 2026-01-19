# 🚀 LLM-D Benchmarking Lab

Accelerate reproducible inference experiments for large language models with [LLM-D](https://github.com/llm-d)! This lab automates the setup of a complete evaluation environment on OpenShift/OKD: GPU worker pools, core operators, observability, traffic control, and ready-to-run example workloads. 

> ⚠️ **Experimental Project:** This is a Work in progress repository. Breaking changes may occur. This project is not meant for production use.

<img src="docs/diagram.svg" alt="Architecture Diagram" width="800"/>

---

## 👤 Who is this for?
- 🛠️ Performance engineers running LLM-D & OpenShift AI benchmarks
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
- 📄 Avoid local script execution: Prefer declarative manifests and Kubernetes control loops over imperative scripts run locally
- ⚡ Low friction and minimal dependencies on the user's workstation tooling
- 🧩 Modular & extensible: Fork and Customize via Kustomize overlays
- ☸️ Cloud-native: Leverage the full potential of Kubernetes, OpenShift, and the Operators pattern
- 🔁 Reproducible: Version-controlled manifests for consistent setups
- 🔬 Experiment-focused: Ready-to-run LLM-D workloads & experiments

------

## 🛠️ Cluster Prerequisites
- OpenShift 4.20+
- Cluster-admin permissions
- Openshift GitOps Operator installed (ArgoCD)

## ⚡ Quickstart on AWS

1. Clone this repo.
2. Fill the GitOps Root Application in [overlays/aws/root-app.yaml](./overlays/aws/root-app.yaml) (See [app-of-apps pattern](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/)):
  - The minimum required values are the ClusterApi identifier, the cluster's region and available zones, and the routes for the Gateway API. You can also fork and replace the repo URL with your own. This is recommended because using the main repo URL directly binds your cluster to the current state of this repo. Further documentation is planned for customizing the environments.
3. Fill in the secrets in `overlays/aws/99-*.example.yaml` and save as `overlays/aws/99-*.yaml`.
4. Deploy with `oc apply -k overlays/aws/`.
5. Wait for all ArgoCD applications to become ready: you can find them in the OpenShift WebUI or via `oc get applications -n openshift-gitops`.
6. From here on any changes to the repo will be automatically applied to the cluster by ArgoCD, and ArgoCD will continuously ensure the cluster state matches the desired state defined in the Git repository.

NOTE: The initial setup will take longer, especially if the cluster requires scaling out worker nodes. The applications will report progressing and degraded states until all dependencies are met and the cluster converges to the desired state.

## ⚡ Quickstart on IBMCloud

1. Clone this repo.
2. Fill the GitOps Root Application in [overlays/ibmcloud/root-app.yaml](./overlays/aws/root-app.yaml) (See [app-of-apps pattern](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/)):
- The minimum required values are the ClusterApi identifier, the cluster's region and available zones, and the routes for the Gateway API. You can also fork and replace the repo URL with your own. This is recommended because using the main repo URL directly binds your cluster to the current state of this repo. Further documentation is planned for customizing the environments.
3. Fill in the secrets in `overlays/ibmcloud/99-*.example.yaml` and save as `overlays/ibmcloud/99-*.yaml`.
4. Deploy with `oc apply -k overlays/ibmcloud/`.
5. Wait for all ArgoCD applications to become ready: you can find them in the OpenShift WebUI or via `oc get applications -n openshift-gitops`.
6. From here on any changes to the repo will be automatically applied to the cluster by ArgoCD, and ArgoCD will continuously ensure the cluster state matches the desired state defined in the Git repository.

NOTE: The initial setup will take longer, especially if the cluster requires scaling out worker nodes. The applications will report progressing and degraded states until all dependencies are met and the cluster converges to the desired state.



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

The `examples/` directory contains sample manifests and Helm charts intended for deploying LLM-D workloads.

## 🧪 Example experiment: Upstream LLM-D w/ Workload Variant Autoscaler

Refer to [experiments/workload-variant-autoscaler](experiments/workload-variant-autoscaler) for a full example of deploying Upstream LLM-D with Workload Variant Autoscaling and gathering metrics for analysis.

## ⚠️ Limitations and Notes

- When deploying the complete env in `env/lab`, MachineSets and Cluster Autoscaling are configured alongside the operators' installation. In SNO clusters, the master is configured not to host user workloads, but the MachineSets and Cluster Autoscaler continue to progress. The cluster will eventually converge to the desired state, but it's recommended to have some worker nodes available in advance to speed up initial setup and improve reliability during this phase.
- The uninstallation of this stack is not yet fully supported. For example, operators managed via OLM will not be removed automatically; manual cleanup may be required. Still, once MachineSets and Cluster Autoscaler are removed, ensure you provision some worker nodes to enable rescheduling of the remaining workloads.

## 📝 Backlog

- [ ] Add IBMCloud overlay
- [ ] RWX Storage Class
- [ ] CertManager configuration
- [ ] Kuadrant configuration
- [ ] Authorino configuration
- [ ] Other Grafana dashboards
- [ ] Pin artifacts (operators, helm charts, ...) to specific versions/commits for reproducibility and enable renovate bot
- [ ] Grafana Authentication should be backed by OpenShift OAuth
- [ ] Review RBACs, resource requests/limits, and other manifests refinements
- [ ] Multi-tenancy and concurrent deployments and experiment jobs management, e.g., via Tekton Pipelines, Kueue, and other tools for workload orchestration
- [ ] Most operators are configured in their simplest form and in the global manifests. Further tuning and customizations may be needed for specific use cases, e.g., configuring the NVIDIA GPU Operator and networking. Such a configuration will be unlocked from the global manifests and moved to dedicated environment overlays or experiments, given the assessment of the requirements to enable multi-tenancy and concurrent experiments on the same cluster (see previous point)
- [ ] HyperShift hosted clusters support/Multi-Cluster management
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
