---
tags:
- sentence-transformers
- sentence-similarity
- feature-extraction
- dense
- generated_from_trainer
- dataset_size:37
- loss:MultipleNegativesRankingLoss
base_model: BAAI/bge-base-en-v1.5
widget:
- source_sentence: 'Lead Data Analyst · Data Science focus

    Jonas Haddad

    Lead Data Analyst

    Sydney, Australia | jonas.haddad@jobrec.test


    Data analyst who turns messy event streams into clear, checked reporting.


    SKILLS: SQL, Pandas, NumPy, Spark, Kafka


    EXPERIENCE

    Northstar Systems — Lead Data Analyst | Jan 2015 - Feb 2018

    - queried warehouses with SQL, shaped datasets with Pandas for internal tools.

    - vectorised maths with NumPy with steady release cadenc

    Profile skills: Kafka, NumPy, Pandas, SQL, Spark'
  sentences:
  - 'Cloud & DevOps Infrastructure Lead

    Deep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment
    automation. 6+ years in DevOps/SRE.

    Own container orchestration, multi-stage CI/CD pipelines, and cloud observability
    for our growing recommendation microservices.

    Required skills: Kubernetes, Docker, AWS, Terraform, CI/CD'
  - 'Lead Machine Learning & Backend Engineer

    Proficiency with Python, FastAPI, and vector embeddings.

    Architect candidate matching and two-stage ranking pipeline.

    Required skills: Python, Machine Learning, FastAPI'
  - 'Senior Data Platform Engineer

    Solid experience with SQL, PostgreSQL, Redis caches, event streaming, and distributed
    data pipelines.

    Build high-throughput ingestion pipelines and feature stores supporting near real-time
    recommendation updates and analytical modeling.

    Required skills: PostgreSQL, Python, Redis, SQL, System Design'
pipeline_tag: sentence-similarity
library_name: sentence-transformers
---

# SentenceTransformer based on BAAI/bge-base-en-v1.5

This is a [sentence-transformers](https://www.SBERT.net) model finetuned from [BAAI/bge-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5). It maps inputs to a 768-dimensional dense vector space and can be used for semantic textual similarity, semantic search, paraphrase mining, classification, clustering, and more.

## Model Details

### Model Description
- **Model Type:** Sentence Transformer
- **Base model:** [BAAI/bge-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5) <!-- at revision a5beb1e3e68b9ab74eb54cfd186867f64f240e1a -->
- **Maximum Sequence Length:** 256 tokens
- **Output Dimensionality:** 768 dimensions
- **Similarity Function:** Cosine Similarity
- **Supported Modality:** Text
<!-- - **Training Dataset:** Unknown -->
<!-- - **Language:** Unknown -->
<!-- - **License:** Unknown -->

### Model Sources

- **Documentation:** [Sentence Transformers Documentation](https://sbert.net)
- **Repository:** [Sentence Transformers on GitHub](https://github.com/huggingface/sentence-transformers)
- **Hugging Face:** [Sentence Transformers on Hugging Face](https://huggingface.co/models?library=sentence-transformers)

### Full Model Architecture

```
SentenceTransformer(
  (0): Transformer({'transformer_task': 'feature-extraction', 'modality_config': {'text': {'method': 'forward', 'method_output_name': 'last_hidden_state'}}, 'module_output_name': 'token_embeddings', 'architecture': 'BertModel'})
  (1): Pooling({'embedding_dimension': 768, 'pooling_mode': 'cls', 'include_prompt': True})
  (2): Normalize({'module_input_name': 'sentence_embedding', 'module_output_name': 'sentence_embedding'})
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
from sentence_transformers import SentenceTransformer

# Download from the 🤗 Hub
model = SentenceTransformer("sentence_transformers_model_id")
# Run inference
sentences = [
    'Lead Data Analyst · Data Science focus\nJonas Haddad\nLead Data Analyst\nSydney, Australia | jonas.haddad@jobrec.test\n\nData analyst who turns messy event streams into clear, checked reporting.\n\nSKILLS: SQL, Pandas, NumPy, Spark, Kafka\n\nEXPERIENCE\nNorthstar Systems — Lead Data Analyst | Jan 2015 - Feb 2018\n- queried warehouses with SQL, shaped datasets with Pandas for internal tools.\n- vectorised maths with NumPy with steady release cadenc\nProfile skills: Kafka, NumPy, Pandas, SQL, Spark',
    'Lead Machine Learning & Backend Engineer\nProficiency with Python, FastAPI, and vector embeddings.\nArchitect candidate matching and two-stage ranking pipeline.\nRequired skills: Python, Machine Learning, FastAPI',
    'Senior Data Platform Engineer\nSolid experience with SQL, PostgreSQL, Redis caches, event streaming, and distributed data pipelines.\nBuild high-throughput ingestion pipelines and feature stores supporting near real-time recommendation updates and analytical modeling.\nRequired skills: PostgreSQL, Python, Redis, SQL, System Design',
]
embeddings = model.encode(sentences)
print(embeddings.shape)
# [3, 768]

# Get the similarity scores for the embeddings
similarities = model.similarity(embeddings, embeddings)
print(similarities)
# tensor([[1.0000, 0.5788, 0.6589],
#         [0.5788, 1.0000, 0.6468],
#         [0.6589, 0.6468, 1.0000]])
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

* Size: 37 training samples
* Columns: <code>sentence1</code> and <code>sentence2</code>
* Approximate statistics based on the first 37 samples:
  |          | sentence1                                                                             | sentence2                                                                           |
  |:---------|:--------------------------------------------------------------------------------------|:------------------------------------------------------------------------------------|
  | type     | string                                                                                | string                                                                              |
  | modality | text                                                                                  | text                                                                                |
  | details  | <ul><li>min: 118 tokens</li><li>mean: 136.32 tokens</li><li>max: 150 tokens</li></ul> | <ul><li>min: 45 tokens</li><li>mean: 65.68 tokens</li><li>max: 100 tokens</li></ul> |
* Samples:
  | sentence1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | sentence2                                                                                                                                                                                                                               |
  |:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
  | <code>Backend Engineer · Backend Engineering focus<br>Hiro Novak<br>Backend Engineer<br>Austin, United States \| hiro.novak@jobrec.test<br><br>Backend engineer focused on steady services, clear contracts, and short feedback loops.<br><br>SKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask<br><br>EXPERIENCE<br>Northstar Systems — Backend Engineer \| Jan 2017 - Feb 2020<br>- wrote Python services, designed FastAPI endpoints for internal tools.<br>- modelled PostgreSQL s<br>Profile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis</code>        | <code>Lead Machine Learning & Backend Engineer<br>Proficiency with Python, FastAPI, and vector embeddings.<br>Architect candidate matching and two-stage ranking pipeline.<br>Required skills: Python, Machine Learning, FastAPI</code> |
  | <code>Lead Backend Engineer · Backend Engineering focus<br>Jonas Haddad<br>Lead Backend Engineer<br>Berlin, Germany \| jonas.haddad@jobrec.test<br><br>Backend engineer focused on steady services, clear contracts, and short feedback loops.<br><br>SKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask<br><br>EXPERIENCE<br>Northstar Systems — Lead Backend Engineer \| Jan 2015 - Feb 2018<br>- wrote Python services, designed FastAPI endpoints for internal tools.<br>- modelled Post<br>Profile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis</code>   | <code>Lead Machine Learning & Backend Engineer<br>Proficiency with Python, FastAPI, and vector embeddings.<br>Architect candidate matching and two-stage ranking pipeline.<br>Required skills: Python, Machine Learning, FastAPI</code> |
  | <code>Backend Engineer Intern · Backend Engineering focus<br>Aarav Iyer<br>Backend Engineer Intern<br>Toronto, Canada \| aarav.iyer@jobrec.test<br><br>Backend engineer focused on steady services, clear contracts, and short feedback loops.<br><br>SKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask<br><br>EXPERIENCE<br>Northstar Systems — Backend Engineer Intern \| Jan 2016 - Feb 2020<br>- wrote Python services, designed FastAPI endpoints for internal tools.<br>- modelled Post<br>Profile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis</code> | <code>Lead Machine Learning & Backend Engineer<br>Proficiency with Python, FastAPI, and vector embeddings.<br>Architect candidate matching and two-stage ranking pipeline.<br>Required skills: Python, Machine Learning, FastAPI</code> |
* Loss: [<code>MultipleNegativesRankingLoss</code>](https://sbert.net/docs/package_reference/sentence_transformer/losses.html#multiplenegativesrankingloss) with these parameters:
  ```json
  {
      "scale": 20.0,
      "similarity_fct": "cos_sim",
      "gather_across_devices": false,
      "directions": [
          "query_to_doc"
      ],
      "partition_mode": "joint",
      "hardness_mode": null,
      "hardness_strength": 0.0
  }
  ```

### Evaluation Dataset

#### Unnamed Dataset

* Size: 8 evaluation samples
* Columns: <code>sentence1</code> and <code>sentence2</code>
* Approximate statistics based on the first 8 samples:
  |          | sentence1                                                                            | sentence2                                                                           |
  |:---------|:-------------------------------------------------------------------------------------|:------------------------------------------------------------------------------------|
  | type     | string                                                                               | string                                                                              |
  | modality | text                                                                                 | text                                                                                |
  | details  | <ul><li>min: 120 tokens</li><li>mean: 134.0 tokens</li><li>max: 147 tokens</li></ul> | <ul><li>min: 45 tokens</li><li>mean: 60.88 tokens</li><li>max: 100 tokens</li></ul> |
* Samples:
  | sentence1                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | sentence2                                                                                                                                                                                                                                                                                                                                                                |
  |:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
  | <code>Lead DevOps Engineer · DevOps Engineering focus<br>Elena Silva<br>Lead DevOps Engineer<br>Bengaluru, India \| elena.silva@jobrec.test<br><br>DevOps engineer who keeps rollouts small, observable, and easy to reverse.<br><br>SKILLS: Docker, Kubernetes, Terraform, AWS, Git, CI/CD, Linux, GitHub Actions<br><br>EXPERIENCE<br>Northstar Systems — Lead DevOps Engineer \| Jan 2014 - Feb 2018<br>- containerised workloads with Docker, ran clusters on Kubernetes for internal tools.<br>- declar<br>Profile skills: AWS, CI/CD, Docker, Git, GitHub Actions, Kubernetes, Linux, Terraform</code> | <code>Cloud & DevOps Infrastructure Lead<br>Deep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.<br>Own container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.<br>Required skills: Kubernetes, Docker, AWS, Terraform, CI/CD</code> |
  | <code>Senior Backend Engineer · Backend Engineering focus<br>Imani Okafor<br>Senior Backend Engineer<br>London, United Kingdom \| imani.okafor@jobrec.test<br><br>Backend engineer focused on steady services, clear contracts, and short feedback loops.<br><br>SKILLS: Python, FastAPI, PostgreSQL, Docker, Git, REST, Redis, Flask<br><br>EXPERIENCE<br>Northstar Systems — Senior Backend Engineer \| Jan 2014 - Feb 2017<br>- wrote Python services, designed FastAPI endpoints for internal tools.<br>- mo<br>Profile skills: Docker, FastAPI, Flask, Git, PostgreSQL, Python, REST APIs, Redis</code> | <code>Senior Data Platform Engineer<br>Solid experience with SQL, PostgreSQL, Redis caches, event streaming, and distributed data pipelines.<br>Build high-throughput ingestion pipelines and feature stores supporting near real-time recommendation updates and analytical modeling.<br>Required skills: PostgreSQL, Python, Redis, SQL, System Design</code>          |
  | <code>Lead Data Analyst · Data Science focus<br>Jonas Haddad<br>Lead Data Analyst<br>Sydney, Australia \| jonas.haddad@jobrec.test<br><br>Data analyst who turns messy event streams into clear, checked reporting.<br><br>SKILLS: SQL, Pandas, NumPy, Spark, Kafka<br><br>EXPERIENCE<br>Northstar Systems — Lead Data Analyst \| Jan 2015 - Feb 2018<br>- queried warehouses with SQL, shaped datasets with Pandas for internal tools.<br>- vectorised maths with NumPy with steady release cadenc<br>Profile skills: Kafka, NumPy, Pandas, SQL, Spark</code>                                               | <code>Lead Machine Learning & Backend Engineer<br>Proficiency with Python, FastAPI, and vector embeddings.<br>Architect candidate matching and two-stage ranking pipeline.<br>Required skills: Python, Machine Learning, FastAPI</code>                                                                                                                                  |
* Loss: [<code>MultipleNegativesRankingLoss</code>](https://sbert.net/docs/package_reference/sentence_transformer/losses.html#multiplenegativesrankingloss) with these parameters:
  ```json
  {
      "scale": 20.0,
      "similarity_fct": "cos_sim",
      "gather_across_devices": false,
      "directions": [
          "query_to_doc"
      ],
      "partition_mode": "joint",
      "hardness_mode": null,
      "hardness_strength": 0.0
  }
  ```

### Training Hyperparameters
#### Non-Default Hyperparameters

- `per_device_train_batch_size`: 16
- `learning_rate`: 2e-05
- `warmup_steps`: 1
- `per_device_eval_batch_size`: 16
- `data_seed`: 42
- `dataloader_pin_memory`: False
- `remove_unused_columns`: False

#### All Hyperparameters
<details><summary>Click to expand</summary>

- `per_device_train_batch_size`: 16
- `num_train_epochs`: 3.0
- `max_steps`: -1
- `learning_rate`: 2e-05
- `lr_scheduler_type`: linear
- `lr_scheduler_kwargs`: None
- `warmup_steps`: 1
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
| 0.3333 | 1    | 2.6264        | -               |
| 0.6667 | 2    | 2.5813        | -               |
| 1.0    | 3    | 1.1778        | 1.6297          |
| 1.3333 | 4    | 2.3230        | -               |
| 1.6667 | 5    | 2.5227        | -               |
| 2.0    | 6    | 1.0067        | 1.8326          |
| 2.3333 | 7    | 2.2065        | -               |
| 2.6667 | 8    | 2.1472        | -               |
| 3.0    | 9    | 1.6877        | 1.9182          |


### Training Time
- **Training**: 2.8 minutes
- **Evaluation**: 12.6 seconds
- **Total**: 3.0 minutes

### Framework Versions
- Python: 3.13.5
- Sentence Transformers: 6.0.1
- Transformers: 5.7.0
- PyTorch: 2.11.0+cpu
- Accelerate: 1.15.0
- Datasets: 4.8.5
- Tokenizers: 0.22.2

## Additional Resources

- [Training and Finetuning Embedding Models with Sentence Transformers](https://huggingface.co/blog/train-sentence-transformers): the end-to-end guide for training or finetuning Sentence Transformer models.
- [Introduction to Matryoshka Embedding Models](https://huggingface.co/blog/matryoshka): variable-size embeddings that can be truncated with minimal quality loss.
- [Binary and Scalar Embedding Quantization for Significantly Faster & Cheaper Retrieval](https://huggingface.co/blog/embedding-quantization): post-training compression of embedding vectors.
- [Multimodal Embedding & Reranker Models with Sentence Transformers](https://huggingface.co/blog/multimodal-sentence-transformers): use text, image, audio, and video models through the same API.
- [Training and Finetuning Multimodal Embedding & Reranker Models with Sentence Transformers](https://huggingface.co/blog/train-multimodal-sentence-transformers): train multimodal embedding models, with a Visual Document Retrieval walkthrough.

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

#### MultipleNegativesRankingLoss
```bibtex
@misc{oord2019representationlearningcontrastivepredictive,
      title={Representation Learning with Contrastive Predictive Coding},
      author={Aaron van den Oord and Yazhe Li and Oriol Vinyals},
      year={2019},
      eprint={1807.03748},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/1807.03748},
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