# LLM-D P/D Disaggregation with deepseek-ai/DeepSeek-R1-Distill-Llama-70B

## Prerequisites:

- Kuadrant and Authorino are disabled
- Nvidia GPU Operator, NFD, RHCL installed
- StorageClass supporting RWX PersistentVolumes (`nfs-client` in this example, see [Persistent Volume Claim](./persistent-volume-claim.yaml)).
- A backend for LoadBalancer type Services (e.g. MetalLB, cloud provider LB, etc.)
- Openshift AI is installed and configured as in [here](../../../manifests/60-llm-d-rhoai-pre)
- The Gateway is configured as in [here](../../../manifests/40-gateway-api/)

## Deploy

```shell
kubectl apply -k . 
```

