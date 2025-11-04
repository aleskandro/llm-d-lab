# LLM-D example

Considering the well-lit paths defined at https://github.com/llm-d/llm-d/tree/d87d637a41911ca81dbdf1590b7d3a02274f9bf3/guides,
to override the values of the [ModelService](https://github.com/llm-d-incubation/llm-d-modelservice) chart, you can:

1. Build your values.yaml file (see example in this folder)
2. Run:

```shell
helmfile -n experiment-01 apply -f $LLM_D_REPO_PATH/guides/inference-scheduling/helmfile.yaml.gotmpl -f values.yaml
```

NOTE: At the time of writing, this depends on https://github.com/llm-d/llm-d/pull/430.