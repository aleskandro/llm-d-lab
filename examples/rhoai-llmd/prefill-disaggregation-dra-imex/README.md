# LLM-D P/D Disaggregation with deepseek-ai/DeepSeek-R1-Distill-Llama-70B

## Prerequisites:

- Kuadrant and Authorino are disabled.
- Nvidia GPU Operator, NFD, RHCL installed
- StorageClass supporting RWX PersistentVolumes (`nfs-client` in this example, see [Persistent Volume Claim](./persistent-volume-claim.yaml)).
- A backend for LoadBalancer type Services (e.g. MetalLB, cloud provider LB, etc.)
- Openshift AI is installed and configured as in [here](../../../manifests/60-llm-d-rhoai-pre).
- The Gateway is configured as in [here](../../../manifests/40-gateway-api/).
- Nvidia DRA Driver
- Nvidia GPU Operator configured to use DRA and IMEX.

## Deploy

```shell
kubectl apply -k . 
```

## Label all nodes to be used with the ComputeDomain ID

Example:

```shell
oc get resourceclaimtemplate imex-channel \
	-n llm-d-pd-disaggregation \
	-o jsonpath='{.metadata.labels.resource\.nvidia\.com/computeDomain}{"\n"}'
# output: 19bc1698-3153-428b-867f-b0cda2102149

# in this example, all nodes should be involved in the compute domain
for n in $(oc get node -o name); do 
	oc label $n resource.nvidia.com/computeDomain=19bc1698-3153-428b-867f-b0cda2102149
done
```

Verify:

```shell
oc get daemonset -n nvidia-dra-driver-gpu                          
NAME                                   DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR                                                            AGE
compute-domain-r7zxh                   3         3         3       3            3           resource.nvidia.com/computeDomain=19bc1698-3153-428b-867f-b0cda2102149   23m
```

The `READY` column should match the `DESIRED` column and the number of nodes labeled with the compute domain ID.