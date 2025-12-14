# RHOAI / LLM-D

```shell
oc apply -k .
```

See kustomization.yaml and the other examples at https://github.com/opendatahub-io/kserve/tree/57e3509b6d0e5fa9fdbd5dc70e0565817cb193c9/docs/samples/llmisvc.

You can setup the kustomization.yaml to point to a base LLMInferenceService manifest and 
then patch it as needed for your setup.