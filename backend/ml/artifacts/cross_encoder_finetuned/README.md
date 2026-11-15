---
tags:
- sentence-transformers
- cross-encoder
- reranker
- generated_from_trainer
- dataset_size:412
- loss:BinaryCrossEntropyLoss
base_model: cross-encoder/ms-marco-MiniLM-L6-v2
pipeline_tag: text-ranking
library_name: sentence-transformers
---

# CrossEncoder based on cross-encoder/ms-marco-MiniLM-L6-v2

This is a [Cross Encoder](https://www.sbert.net/docs/cross_encoder/usage/usage.html) model finetuned from [cross-encoder/ms-marco-MiniLM-L6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) using the [sentence-transformers](https://www.SBERT.net) library. It computes scores for pairs of texts, which can be used for text reranking and semantic search.

## Model Details

### Model Description
- **Model Type:** Cross Encoder
- **Base model:** [cross-encoder/ms-marco-MiniLM-L6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) <!-- at revision 233902d25c440f23af6f7d6e94d2946bac0bee0a -->
- **Maximum Sequence Length:** 512 tokens
- **Number of Output Labels:** 1 label
- **Supported Modality:** Text
<!-- - **Training Dataset:** Unknown -->
<!-- - **Language:** Unknown -->
<!-- - **License:** Unknown -->

### Model Sources

- **Documentation:** [Sentence Transformers Documentation](https://sbert.net)
- **Documentation:** [Cross Encoder Documentation](https://www.sbert.net/docs/cross_encoder/usage/usage.html)
- **Repository:** [Sentence Transformers on GitHub](https://github.com/huggingface/sentence-transformers)
- **Hugging Face:** [Cross Encoders on Hugging Face](https://huggingface.co/models?library=sentence-transformers&other=cross-encoder)

### Full Model Architecture

```
CrossEncoder(
  (0): Transformer({'transformer_task': 'sequence-classification', 'modality_config': {'text': {'method': 'forward', 'method_output_name': 'logits'}}, 'module_output_name': 'scores', 'architecture': 'BertForSequenceClassification'})
)
```

## Usage

### Direct Usage (Sentence Transformers)

First install the Sentence Transformers library:

```bash
pip install -U sentence-transformers
```

Then you can load this model and run inference.
```python
from sentence_transformers import CrossEncoder

# Download from the 🤗 Hub
model = CrossEncoder("cross_encoder_model_id")
# Get scores for pairs of inputs
pairs = [
    ['Junior Data Analyst · Data Science focus\nBianca Weber\nJunior Data Analyst\nAustin, United States | bianca.weber@jobrec.test\n\nData analyst who turns messy event streams into clear, checked reporting.\n\nSKILLS: SQL, Pandas, NumPy, Spark, Kafka\n\nEXPERIENCE\nNorthstar Systems — Junior Data Analyst | Jan 2017 - Feb 2021\n- queried warehouses with SQL, shaped datasets with Pandas for internal tools.\n- vectorised maths with NumPy with steady releas\nProfile skills: Kafka, NumPy, Pandas, SQL, Spark', 'Lead Machine Learning & Backend Engineer\nProficiency with Python, FastAPI, and vector embeddings.\nArchitect candidate matching and two-stage ranking pipeline.\nRequired skills: Python, Machine Learning, FastAPI'],
    ['Junior Data Analyst · Data Science focus\nBianca Weber\nJunior Data Analyst\nAustin, United States | bianca.weber@jobrec.test\n\nData analyst who turns messy event streams into clear, checked reporting.\n\nSKILLS: SQL, Pandas, NumPy, Spark, Kafka\n\nEXPERIENCE\nNorthstar Systems — Junior Data Analyst | Jan 2017 - Feb 2021\n- queried warehouses with SQL, shaped datasets with Pandas for internal tools.\n- vectorised maths with NumPy with steady releas\nProfile skills: Kafka, NumPy, Pandas, SQL, Spark', 'Cloud & DevOps Infrastructure Lead\nDeep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.\nOwn container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.\nRequired skills: Kubernetes, Docker, AWS, Terraform, CI/CD'],
    ['Junior Backend Engineer · Backend Engineering focus\nGrace Lindqvist\nJunior Backend Engineer\nBengaluru, India | grace.lindqvist@jobrec.test\n\nBackend engineer focused on steady services, clear contracts, and short feedback loops.\n\nSKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask\n\nEXPERIENCE\nNorthstar Systems — Junior Backend Engineer | Jan 2016 - Feb 2019\n- wrote Python services, designed FastAPI endpoints for internal tools.\n- mo\nProfile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis', 'Lead Machine Learning & Backend Engineer\nProficiency with Python, FastAPI, and vector embeddings.\nArchitect candidate matching and two-stage ranking pipeline.\nRequired skills: Python, Machine Learning, FastAPI'],
    ['Junior Backend Engineer · Backend Engineering focus\nGrace Lindqvist\nJunior Backend Engineer\nBengaluru, India | grace.lindqvist@jobrec.test\n\nBackend engineer focused on steady services, clear contracts, and short feedback loops.\n\nSKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask\n\nEXPERIENCE\nNorthstar Systems — Junior Backend Engineer | Jan 2016 - Feb 2019\n- wrote Python services, designed FastAPI endpoints for internal tools.\n- mo\nProfile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis', 'Senior Data Platform Engineer\nSolid experience with SQL, PostgreSQL, Redis caches, event streaming, and distributed data pipelines.\nBuild high-throughput ingestion pipelines and feature stores supporting near real-time recommendation updates and analytical modeling.\nRequired skills: PostgreSQL, Python, Redis, SQL, System Design'],
    ['Junior Backend Engineer · Backend Engineering focus\nGrace Lindqvist\nJunior Backend Engineer\nBengaluru, India | grace.lindqvist@jobrec.test\n\nBackend engineer focused on steady services, clear contracts, and short feedback loops.\n\nSKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask\n\nEXPERIENCE\nNorthstar Systems — Junior Backend Engineer | Jan 2016 - Feb 2019\n- wrote Python services, designed FastAPI endpoints for internal tools.\n- mo\nProfile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis', 'Cloud & DevOps Infrastructure Lead\nDeep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.\nOwn container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.\nRequired skills: Kubernetes, Docker, AWS, Terraform, CI/CD'],
]
scores = model.predict(pairs)
print(scores)
# [-9.09   -9.7851  2.1198 -0.339  -4.758 ]

# Or rank different texts based on similarity to a single text
ranks = model.rank(
    'Junior Data Analyst · Data Science focus\nBianca Weber\nJunior Data Analyst\nAustin, United States | bianca.weber@jobrec.test\n\nData analyst who turns messy event streams into clear, checked reporting.\n\nSKILLS: SQL, Pandas, NumPy, Spark, Kafka\n\nEXPERIENCE\nNorthstar Systems — Junior Data Analyst | Jan 2017 - Feb 2021\n- queried warehouses with SQL, shaped datasets with Pandas for internal tools.\n- vectorised maths with NumPy with steady releas\nProfile skills: Kafka, NumPy, Pandas, SQL, Spark',
    [
        'Lead Machine Learning & Backend Engineer\nProficiency with Python, FastAPI, and vector embeddings.\nArchitect candidate matching and two-stage ranking pipeline.\nRequired skills: Python, Machine Learning, FastAPI',
        'Cloud & DevOps Infrastructure Lead\nDeep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.\nOwn container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.\nRequired skills: Kubernetes, Docker, AWS, Terraform, CI/CD',
        'Lead Machine Learning & Backend Engineer\nProficiency with Python, FastAPI, and vector embeddings.\nArchitect candidate matching and two-stage ranking pipeline.\nRequired skills: Python, Machine Learning, FastAPI',
        'Senior Data Platform Engineer\nSolid experience with SQL, PostgreSQL, Redis caches, event streaming, and distributed data pipelines.\nBuild high-throughput ingestion pipelines and feature stores supporting near real-time recommendation updates and analytical modeling.\nRequired skills: PostgreSQL, Python, Redis, SQL, System Design',
        'Cloud & DevOps Infrastructure Lead\nDeep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.\nOwn container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.\nRequired skills: Kubernetes, Docker, AWS, Terraform, CI/CD',
    ]
)
# [{'corpus_id': ..., 'score': ...}, {'corpus_id': ..., 'score': ...}, ...]
```

<!--
### Direct Usage (Transformers)

<details><summary>Click to see the direct usage in Transformers</summary>

</details>
-->

<!--
### Downstream Usage (Sentence Transformers)

You can finetune this model on your own dataset.

<details><summary>Click to expand</summary>

</details>
-->

<!--
### Out-of-Scope Use

*List how the model may foreseeably be misused and address what users ought not to do with the model.*
-->

<!--
## Bias, Risks and Limitations

*What are the known or foreseeable issues stemming from this model? You could also flag here known failure cases or weaknesses of the model.*
-->

<!--
### Recommendations

*What are recommendations with respect to the foreseeable issues? For example, filtering explicit content.*
-->

## Training Details

### Training Dataset

#### Unnamed Dataset

* Size: 412 training samples
* Columns: <code>sentence1</code>, <code>sentence2</code>, and <code>label</code>
* Approximate statistics based on the first 100 samples:
  |          | sentence1                                                                             | sentence2                                                                           | label                                                         |
  |:---------|:--------------------------------------------------------------------------------------|:------------------------------------------------------------------------------------|:--------------------------------------------------------------|
  | type     | string                                                                                | string                                                                              | float                                                         |
  | modality | text                                                                                  | text                                                                                |                                                               |
  | details  | <ul><li>min: 114 tokens</li><li>mean: 130.51 tokens</li><li>max: 150 tokens</li></ul> | <ul><li>min: 45 tokens</li><li>mean: 78.73 tokens</li><li>max: 100 tokens</li></ul> | <ul><li>min: 0.0</li><li>mean: 0.1</li><li>max: 1.0</li></ul> |
* Samples:
  | sentence1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | sentence2                                                                                                                                                                                                                                                                                                                                                                               | label            |
  |:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-----------------|
  | <code>Lead Machine Learning Engineer · Machine Learning Engineering focus<br>Jonas Haddad<br>Lead Machine Learning Engineer<br>Berlin, Germany \| jonas.haddad@jobrec.test<br><br>Machine Learning engineer who measures first and ships models with clear monitoring.<br><br>SKILLS: Python, PyTorch, TensorFlow, Machine Learning, Deep Learning, NLP, Pandas<br><br>EXPERIENCE<br>Northstar Systems — Lead Machine Learning Engineer \| Jan 2017 - Feb 2021<br>- wrote Python training scripts, trained models with PyTorc<br>Profile skills: Deep Learning, Machine Learning, NLP, Pandas, PyTorch, Python, TensorFlow</code> | <code>Cloud & DevOps Infrastructure Lead<br>Deep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.<br>Own container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.<br>Required skills: Kubernetes, Docker, AWS, Terraform, CI/CD</code>                | <code>0.0</code> |
  | <code>Lead Machine Learning Engineer · Machine Learning Engineering focus<br>Jonas Haddad<br>Lead Machine Learning Engineer<br>Berlin, Germany \| jonas.haddad@jobrec.test<br><br>Machine Learning engineer who measures first and ships models with clear monitoring.<br><br>SKILLS: Python, PyTorch, TensorFlow, Machine Learning, Deep Learning, NLP, Pandas<br><br>EXPERIENCE<br>Northstar Systems — Lead Machine Learning Engineer \| Jan 2017 - Feb 2021<br>- wrote Python training scripts, trained models with PyTorc<br>Profile skills: Deep Learning, Machine Learning, NLP, Pandas, PyTorch, Python, TensorFlow</code> | <code>Lead Machine Learning & Backend Engineer<br>Proficiency with Python, FastAPI, and vector embeddings.<br>Architect candidate matching and two-stage ranking pipeline.<br>Required skills: Python, Machine Learning, FastAPI</code>                                                                                                                                                 | <code>0.0</code> |
  | <code>Lead Machine Learning Engineer · Machine Learning Engineering focus<br>Jonas Haddad<br>Lead Machine Learning Engineer<br>Berlin, Germany \| jonas.haddad@jobrec.test<br><br>Machine Learning engineer who measures first and ships models with clear monitoring.<br><br>SKILLS: Python, PyTorch, TensorFlow, Machine Learning, Deep Learning, NLP, Pandas<br><br>EXPERIENCE<br>Northstar Systems — Lead Machine Learning Engineer \| Jan 2017 - Feb 2021<br>- wrote Python training scripts, trained models with PyTorc<br>Profile skills: Deep Learning, Machine Learning, NLP, Pandas, PyTorch, Python, TensorFlow</code> | <code>Full-Stack Next.js & FastAPI Developer<br>3+ years building responsive SPAs with React, Next.js, TailwindCSS, and integrating RESTful backend services.<br>Join our product engineering pod to build modern web interfaces with Next.js 16, TypeScript, and high-performance Python FastAPI services.<br>Required skills: Next.js, TypeScript, React, FastAPI, TailwindCSS</code> | <code>0.0</code> |
* Loss: [<code>BinaryCrossEntropyLoss</code>](https://sbert.net/docs/package_reference/cross_encoder/losses.html#binarycrossentropyloss) with these parameters:
  ```json
  {
      "activation_fn": "torch.nn.modules.linear.Identity",
      "pos_weight": null
  }
  ```

### Evaluation Dataset

#### Unnamed Dataset

* Size: 104 evaluation samples
* Columns: <code>sentence1</code>, <code>sentence2</code>, and <code>label</code>
* Approximate statistics based on the first 100 samples:
  |          | sentence1                                                                             | sentence2                                                                           | label                                                          |
  |:---------|:--------------------------------------------------------------------------------------|:------------------------------------------------------------------------------------|:---------------------------------------------------------------|
  | type     | string                                                                                | string                                                                              | float                                                          |
  | modality | text                                                                                  | text                                                                                |                                                                |
  | details  | <ul><li>min: 114 tokens</li><li>mean: 129.93 tokens</li><li>max: 150 tokens</li></ul> | <ul><li>min: 45 tokens</li><li>mean: 76.04 tokens</li><li>max: 100 tokens</li></ul> | <ul><li>min: 0.0</li><li>mean: 0.12</li><li>max: 1.0</li></ul> |
* Samples:
  | sentence1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | sentence2                                                                                                                                                                                                                                                                                                                                                                | label            |
  |:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-----------------|
  | <code>Junior Data Analyst · Data Science focus<br>Bianca Weber<br>Junior Data Analyst<br>Austin, United States \| bianca.weber@jobrec.test<br><br>Data analyst who turns messy event streams into clear, checked reporting.<br><br>SKILLS: SQL, Pandas, NumPy, Spark, Kafka<br><br>EXPERIENCE<br>Northstar Systems — Junior Data Analyst \| Jan 2017 - Feb 2021<br>- queried warehouses with SQL, shaped datasets with Pandas for internal tools.<br>- vectorised maths with NumPy with steady releas<br>Profile skills: Kafka, NumPy, Pandas, SQL, Spark</code>                                             | <code>Lead Machine Learning & Backend Engineer<br>Proficiency with Python, FastAPI, and vector embeddings.<br>Architect candidate matching and two-stage ranking pipeline.<br>Required skills: Python, Machine Learning, FastAPI</code>                                                                                                                                  | <code>0.0</code> |
  | <code>Junior Data Analyst · Data Science focus<br>Bianca Weber<br>Junior Data Analyst<br>Austin, United States \| bianca.weber@jobrec.test<br><br>Data analyst who turns messy event streams into clear, checked reporting.<br><br>SKILLS: SQL, Pandas, NumPy, Spark, Kafka<br><br>EXPERIENCE<br>Northstar Systems — Junior Data Analyst \| Jan 2017 - Feb 2021<br>- queried warehouses with SQL, shaped datasets with Pandas for internal tools.<br>- vectorised maths with NumPy with steady releas<br>Profile skills: Kafka, NumPy, Pandas, SQL, Spark</code>                                             | <code>Cloud & DevOps Infrastructure Lead<br>Deep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.<br>Own container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.<br>Required skills: Kubernetes, Docker, AWS, Terraform, CI/CD</code> | <code>0.0</code> |
  | <code>Junior Backend Engineer · Backend Engineering focus<br>Grace Lindqvist<br>Junior Backend Engineer<br>Bengaluru, India \| grace.lindqvist@jobrec.test<br><br>Backend engineer focused on steady services, clear contracts, and short feedback loops.<br><br>SKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask<br><br>EXPERIENCE<br>Northstar Systems — Junior Backend Engineer \| Jan 2016 - Feb 2019<br>- wrote Python services, designed FastAPI endpoints for internal tools.<br>- mo<br>Profile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis</code> | <code>Lead Machine Learning & Backend Engineer<br>Proficiency with Python, FastAPI, and vector embeddings.<br>Architect candidate matching and two-stage ranking pipeline.<br>Required skills: Python, Machine Learning, FastAPI</code>                                                                                                                                  | <code>1.0</code> |
* Loss: [<code>BinaryCrossEntropyLoss</code>](https://sbert.net/docs/package_reference/cross_encoder/losses.html#binarycrossentropyloss) with these parameters:
  ```json
  {
      "activation_fn": "torch.nn.modules.linear.Identity",
      "pos_weight": null
  }
  ```

### Training Hyperparameters
#### Non-Default Hyperparameters

- `per_device_train_batch_size`: 16
- `num_train_epochs`: 2.0
- `learning_rate`: 2e-05
- `warmup_steps`: 5
- `per_device_eval_batch_size`: 16
- `data_seed`: 42
- `dataloader_pin_memory`: False
- `remove_unused_columns`: False

#### All Hyperparameters
<details><summary>Click to expand</summary>

- `per_device_train_batch_size`: 16
- `num_train_epochs`: 2.0
- `max_steps`: -1
- `learning_rate`: 2e-05
- `lr_scheduler_type`: linear
- `lr_scheduler_kwargs`: None
- `warmup_steps`: 5
- `optim`: adamw_torch_fused
- `optim_args`: None
- `weight_decay`: 0.0
- `adam_beta1`: 0.9
- `adam_beta2`: 0.999
- `adam_epsilon`: 1e-08
- `optim_target_modules`: None
- `gradient_accumulation_steps`: 1
- `average_tokens_across_devices`: True
- `max_grad_norm`: 1.0
- `label_smoothing_factor`: 0.0
- `bf16`: False
- `fp16`: False
- `bf16_full_eval`: False
- `fp16_full_eval`: False
- `tf32`: None
- `gradient_checkpointing`: False
- `gradient_checkpointing_kwargs`: None
- `torch_compile`: False
- `torch_compile_backend`: None
- `torch_compile_mode`: None
- `use_liger_kernel`: False
- `liger_kernel_config`: None
- `use_cache`: False
- `neftune_noise_alpha`: None
- `torch_empty_cache_steps`: None
- `auto_find_batch_size`: False
- `log_on_each_node`: True
- `logging_nan_inf_filter`: True
- `include_num_input_tokens_seen`: no
- `log_level`: passive
- `log_level_replica`: warning
- `disable_tqdm`: False
- `project`: huggingface
- `trackio_space_id`: None
- `trackio_bucket_id`: None
- `trackio_static_space_id`: None
- `per_device_eval_batch_size`: 16
- `prediction_loss_only`: True
- `eval_on_start`: False
- `eval_do_concat_batches`: True
- `eval_use_gather_object`: False
- `eval_accumulation_steps`: None
- `include_for_metrics`: []
- `batch_eval_metrics`: False
- `save_only_model`: False
- `save_on_each_node`: False
- `enable_jit_checkpoint`: False
- `push_to_hub`: False
- `hub_private_repo`: None
- `hub_model_id`: None
- `hub_strategy`: every_save
- `hub_always_push`: False
- `hub_revision`: None
- `load_best_model_at_end`: False
- `ignore_data_skip`: False
- `restore_callback_states_from_checkpoint`: False
- `full_determinism`: False
- `seed`: 42
- `data_seed`: 42
- `use_cpu`: False
- `accelerator_config`: {'split_batches': False, 'dispatch_batches': None, 'even_batches': True, 'use_seedable_sampler': True, 'non_blocking': False, 'gradient_accumulation_kwargs': None}
- `parallelism_config`: None
- `dataloader_drop_last`: False
- `dataloader_num_workers`: 0
- `dataloader_pin_memory`: False
- `dataloader_persistent_workers`: False
- `dataloader_prefetch_factor`: None
- `remove_unused_columns`: False
- `label_names`: None
- `train_sampling_strategy`: random
- `length_column_name`: length
- `ddp_find_unused_parameters`: None
- `ddp_bucket_cap_mb`: None
- `ddp_broadcast_buffers`: False
- `ddp_static_graph`: None
- `ddp_backend`: None
- `ddp_timeout`: 1800
- `fsdp`: []
- `fsdp_config`: {'min_num_params': 0, 'xla': False, 'xla_fsdp_v2': False, 'xla_fsdp_grad_ckpt': False}
- `deepspeed`: None
- `debug`: []
- `skip_memory_metrics`: True
- `do_predict`: False
- `resume_from_checkpoint`: None
- `warmup_ratio`: None
- `local_rank`: -1
- `prompts`: None
- `batch_sampler`: batch_sampler
- `multi_dataset_batch_sampler`: proportional
- `router_mapping`: {}
- `learning_rate_mapping`: {}

</details>

### Training Logs
| Epoch  | Step | Training Loss | Validation Loss |
|:------:|:----:|:-------------:|:---------------:|
| 0.0385 | 1    | 0.5082        | -               |
| 0.0769 | 2    | 0.4179        | -               |
| 0.1154 | 3    | 0.3457        | -               |
| 0.1538 | 4    | 0.2676        | -               |
| 0.1923 | 5    | 0.2109        | -               |
| 0.2308 | 6    | 0.1697        | -               |
| 0.2692 | 7    | 0.3325        | -               |
| 0.3077 | 8    | 0.1199        | -               |
| 0.3462 | 9    | 0.2191        | -               |
| 0.3846 | 10   | 0.1313        | -               |
| 0.4231 | 11   | 0.0087        | -               |
| 0.4615 | 12   | 0.2554        | -               |
| 0.5    | 13   | 0.0240        | -               |
| 0.5385 | 14   | 0.1685        | -               |
| 0.5769 | 15   | 0.2390        | -               |
| 0.6154 | 16   | 0.1561        | -               |
| 0.6538 | 17   | 0.4493        | -               |
| 0.6923 | 18   | 0.1086        | -               |
| 0.7308 | 19   | 0.0044        | -               |
| 0.7692 | 20   | 0.9334        | -               |
| 0.8077 | 21   | 0.0652        | -               |
| 0.8462 | 22   | 0.0258        | -               |
| 0.8846 | 23   | 0.0355        | -               |
| 0.9231 | 24   | 0.2117        | -               |
| 0.9615 | 25   | 0.0800        | -               |
| 1.0    | 26   | 0.0179        | 0.2456          |
| 1.0385 | 27   | 0.2778        | -               |
| 1.0769 | 28   | 0.0793        | -               |
| 1.1154 | 29   | 0.0356        | -               |
| 1.1538 | 30   | 0.0427        | -               |
| 1.1923 | 31   | 0.0464        | -               |
| 1.2308 | 32   | 0.0924        | -               |
| 1.2692 | 33   | 0.2082        | -               |
| 1.3077 | 34   | 0.0983        | -               |
| 1.3462 | 35   | 0.1553        | -               |
| 1.3846 | 36   | 0.0151        | -               |
| 1.4231 | 37   | 0.2500        | -               |
| 1.4615 | 38   | 0.0059        | -               |
| 1.5    | 39   | 0.0357        | -               |
| 1.5385 | 40   | 0.0057        | -               |
| 1.5769 | 41   | 0.5375        | -               |
| 1.6154 | 42   | 0.0751        | -               |
| 1.6538 | 43   | 0.6294        | -               |
| 1.6923 | 44   | 0.4290        | -               |
| 1.7308 | 45   | 0.1190        | -               |
| 1.7692 | 46   | 0.2216        | -               |
| 1.8077 | 47   | 0.0042        | -               |
| 1.8462 | 48   | 0.1756        | -               |
| 1.8846 | 49   | 0.0777        | -               |
| 1.9231 | 50   | 0.3535        | -               |
| 1.9615 | 51   | 0.1891        | -               |
| 2.0    | 52   | 0.0261        | 0.2005          |


### Training Time
- **Training**: 4.7 minutes
- **Evaluation**: 17.6 seconds
- **Total**: 5.0 minutes

### Framework Versions
- Python: 3.13.5
- Sentence Transformers: 6.0.1
- Transformers: 5.7.0
- PyTorch: 2.11.0+cpu
- Accelerate: 1.15.0
- Datasets: 4.8.5
- Tokenizers: 0.22.2

## Additional Resources

- [Training and Finetuning Reranker Models with Sentence Transformers](https://huggingface.co/blog/train-reranker): the end-to-end guide for training or finetuning Cross Encoder (reranker) models.
- [Multimodal Embedding & Reranker Models with Sentence Transformers](https://huggingface.co/blog/multimodal-sentence-transformers): use text, image, audio, and video reranker models through the same API.
- [Training and Finetuning Multimodal Embedding & Reranker Models with Sentence Transformers](https://huggingface.co/blog/train-multimodal-sentence-transformers): training multimodal Cross Encoders.

## Citation

### BibTeX

#### Sentence Transformers
```bibtex
@inproceedings{reimers-2019-sentence-bert,
    title = "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
    author = "Reimers, Nils and Gurevych, Iryna",
    booktitle = "Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing",
    month = "11",
    year = "2019",
    publisher = "Association for Computational Linguistics",
    url = "https://arxiv.org/abs/1908.10084",
}
```

<!--
## Glossary

*Clearly define terms in order to be accessible across audiences.*
-->

<!--
## Model Card Authors

*Lists the people who create the model card, providing recognition and accountability for the detailed work that goes into its construction.*
-->

<!--
## Model Card Contact

*Provides a way for people who have updates to the Model Card, suggestions, or questions, to contact the Model Card authors.*
-->