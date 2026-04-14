# NFS Server and Provisioner

This folder contains the setup for an in-cluster NFS server and NFS client provisioner that enables dynamic provisioning of NFS-backed PersistentVolumeClaims.

## Architecture

This uses a **combined deployment** with three containers in a single pod:

1. **NFS Server Container**: Serves files via NFS protocol
2. **NFS Provisioner Container**: Manages dynamic PVC provisioning
3. **Permission Fixer Container**: Ensures 777 permissions on all directories

All three containers share the same PersistentVolumeClaim (backed by `local-sc` storage class) mounted at `/exports`, allowing direct filesystem access without NFS protocol overhead.

```
User Pod (any node, any UID/GID)
    ↓ (kubelet mounts via NFS to ClusterIP)
    ↓ (kube-proxy routes ClusterIP → pod IP)
User PVC (storageClassName: nfs)
    ↓ (provisioner creates PV with nfs.server: <ClusterIP>, path: /exports/pvc-xxx)
┌────────────────────────────────────────────────────────────┐
│ Combined Pod (normal pod network)                          │
│ ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│ │NFS Server│  │Provisioner  │  │Permission Fixer      │   │
│ │:2049     │  │(creates PVs)│  │(chmod 777 every 10s) │   │
│ │/exports  │  │/exports     │  │/exports              │   │
│ └────┬─────┘  └──────┬──────┘  └──────────┬───────────┘   │
│      │               │                    │                │
│      └───────────────┴────────────────────┘                │
│                   All mount at /exports                    │
│                      │ (shared PVC)                        │
└──────────────────────┼─────────────────────────────────────┘
                       ↓
           Local Storage PVC (storageClassName: local-sc)
                       ↓
           Local disk on storage node (/dev/vdb)
                       
Service (ClusterIP: 172.30.250.250)
    → Routes to pod IP via kube-proxy
```

## Components

### Combined Deployment
- **ServiceAccount**: `nfs-client-provisioner` service account with RBAC for managing PVs/PVCs
- **Node Selector**: Scheduled on nodes with `benchmark.llm-d.ai/storage: "true"`
- **Network**: Normal pod networking (no hostNetwork needed)
- **Storage**: Single PVC mounted at both `/exports` (NFS server) and `/persistentvolumes` (provisioner)
- **Containers**: 3 containers in one pod:
  - `nfs-server`: NFS server daemon
  - `nfs-provisioner`: Dynamic PVC provisioner
  - `permission-fixer`: Sidecar that sets 777 permissions on all directories
- **SCC**: Requires privileged SecurityContextConstraints (`nfs-server-provisioner-scc`) for OpenShift

### NFS Server Container
- **Image**: `registry.k8s.io/volume-nfs:0.8`
- **Ports**: 2049 (NFS), 20048 (mountd), 111 (rpcbind)
- **Security**: Runs privileged with `SYS_ADMIN` and `SETPCAP` capabilities

### NFS Provisioner Container
- **Image**: `registry.k8s.io/sig-storage/nfs-subdir-external-provisioner:v4.0.2`
- **Function**: Watches for PVCs, creates subdirectories, creates PVs
- **Auto-configuration**: Uses Kubernetes Downward API to get node IP (`status.hostIP`)

### StorageClass
- **Name**: `nfs`
- **Provisioner**: `nfs-provisioner/nfs`
- **Features**: Dynamic provisioning, volume expansion support

## OpenShift Security

OpenShift-specific SecurityContextConstraints (SCC):

- **nfs-server-provisioner-scc**: 
  - Allows privileged containers (for NFS server)
  - Grants `SYS_ADMIN` and `SETPCAP` capabilities (required for NFS server)
  - Normal pod networking (no hostNetwork)
  - Bound to `system:serviceaccount:nfs-provisioner:nfs-client-provisioner`

## Configuration

⚠️ **Configuration Required**: Set a static ClusterIP for the NFS server

Before deploying, update both `nfs-server-service.yaml` and `nfs-combined-deployment.yaml` with an available ClusterIP from your cluster's service CIDR:

```bash
# Find your cluster's service CIDR
kubectl cluster-info dump | grep -m 1 service-cluster-ip-range
# OR
kubectl get svc -n default kubernetes -o jsonpath='{.spec.clusterIP}'
# (The kubernetes service is typically the first IP in the range)

# Pick an available IP from that range (e.g., 10.96.100.100)
# Update both files:
# - nfs-server-service.yaml: spec.clusterIP
# - nfs-combined-deployment.yaml: env.NFS_SERVER
```

**Why a static ClusterIP?**
- The provisioner puts `NFS_SERVER` value directly into PersistentVolume specs
- Kubelets (on worker nodes) cannot resolve service DNS names
- Kubelets CAN route to ClusterIPs via kube-proxy
- A static ClusterIP provides a stable address that works everywhere

## Usage

**No fsGroup required!** The permission-fixer sidecar automatically sets directories to 777, allowing any UID/GID to write.

### Basic Example

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-nfs-pvc
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  # No securityContext.fsGroup needed!
  containers:
  - name: app
    image: myapp:latest
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: my-nfs-pvc
```

See `example-usage.yaml` for more examples including StatefulSets.

The provisioner will automatically:
1. Create a subdirectory on the shared PVC
2. Create a PersistentVolume pointing to the NFS server's ClusterIP
3. Bind the PV to the PVC

## Permissions and SELinux

The setup handles OpenShift/Kubernetes permissions automatically, **eliminating the need for fsGroup in client pods**:

1. **NFS Export Permissions**: 
   - The NFS server runs a postStart hook to `chmod 777 /exports`
   - SELinux context is set if available (`svirt_sandbox_file_t`)

2. **Provisioner Runs as Root**:
   - Ensures created subdirectories have proper ownership
   - Required for setting permissions on NFS-shared filesystems

3. **Permission Fixer Sidecar**:
   - Continuously monitors `/persistentvolumes` and sets all directories to `777`
   - Sets all files to `666` (readable/writable by all)
   - Runs every 10 seconds to catch newly created PVCs
   - **This means client pods don't need fsGroup** - any UID/GID can write

4. **StorageClass Mount Options**:
   - Uses NFSv4.1 for better performance and security
   - Optimized read/write sizes (1MB)
   - Hard mount with retries

## Troubleshooting

### Permission Denied Errors

If pods get "permission denied" when writing to NFS volumes:

1. **Check the NFS export permissions**:
   ```bash
   kubectl exec -n nfs-provisioner deployment/nfs-server-provisioner -c nfs-server -- ls -la /exports
   ```
   Should show `drwxrwxrwx` (777 permissions)

2. **Check subdirectory ownership**:
   ```bash
   kubectl exec -n nfs-provisioner deployment/nfs-server-provisioner -c nfs-provisioner -- ls -la /exports
   ```

3. **Verify the permission-fixer sidecar is running**:
   ```bash
   kubectl logs -n nfs-provisioner deployment/nfs-server-provisioner -c permission-fixer
   ```
   Should show "Starting permission fixer sidecar..."

4. **Wait 10-20 seconds after PVC creation** for the permission-fixer to run and set permissions

5. **If you prefer to use fsGroup anyway** (for additional security), you can - it's optional but not required

## Key Design Benefits

1. **No fsGroup Required**: Permission-fixer sidecar automatically sets 777 on all directories
2. **Works with Any UID/GID**: Pods can run as any user without permission issues
3. **Simplified Architecture**: Single pod with three containers instead of multiple deployments
4. **No NFS Mount for Provisioner**: Direct filesystem access via shared PVC (more efficient)
5. **No hostNetwork Required**: Uses ClusterIP that's routable from all nodes via kube-proxy
6. **Guaranteed Co-location**: All containers always run on the same node (shared PVC)
7. **Stable Addressing**: Static ClusterIP provides consistent address for all PVs
