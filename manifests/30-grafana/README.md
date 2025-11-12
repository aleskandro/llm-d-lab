# Grafana Operator Kustomization

Remember to use `--server-side` when applying this kustomization. Otherwise, some dasbhoards cannot be created properly due to length limitations in annotations.

```bash
kubectl apply --server-side -k .
```