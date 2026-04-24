# Helmfile deployment llm-d/guides

1. Clone llm-d/llm-d
2. cd llm-d/guides/inference-scheduling
3. Patch ms-inference-scheduling/values with the one provided in this folder
4. helmfile apply -n experiment-01
5. Patch the Gateway to use the GatewayClass openshift-default

