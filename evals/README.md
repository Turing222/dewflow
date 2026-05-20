# RAG Eval

RAG 链路评测分三层，各层独立打分，最后通过 snapshot 对比观察改动效果：

- **Planner 评测**（`eval_rag_planner.py`）：评估 `should_use_rag` / `retrieval_mode` / `use_rerank` 决策是否符合预期
- **检索评测**（`eval_retrieval.py`）：评估 hit@k / recall@k / MRR，离线可跑，无需 Ragas
- **回答评测**（`eval_answer.py` / `eval_api_answer.py`）：评估最终答案质量，使用 Ragas LLM-as-Judge

Ragas 只用于回答后的离线批量评测，不挂主请求链路，也不直接评估 planner 决策。
性能压测不放在 `evals/`；标准化压测入口在 `perf/`，避免 Ragas 或
LLM-as-Judge 污染延迟、吞吐和错误率指标。

## 1. 数据集格式（JSONL）

每行一条样本，字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | str | 问题文本（必填） |
| `kb_id` | uuid\|null | 知识库 ID |
| `category` | str | 分类标签，默认 `general` |
| `retrieval_mode` | str\|null | `vector` / `fulltext` / `hybrid`，优先级高于 CLI 参数 |
| `expected_chunk_ids` | list[str] | 期望命中的 chunk ID（强监督） |
| `expected_keywords` | list[str] | 期望关键词（弱监督） |
| `expected_plan` | object\|null | Planner 期望决策，可含 `should_use_rag` / `retrieval_mode` / `use_rerank` |
| `reference_answer` | str\|null | 参考答案，用于 AnswerCorrectness |
| `must_refuse` | bool | 期望拒答 |
| `notes` | str\|null | 备注 |

示例：`evals/dataset.sample.jsonl`

## 2. Planner 评测

```bash
python -m evals.eval_rag_planner \
  --dataset evals/dataset.sample.jsonl \
  --output evals/reports/rag_planner_report.json
```

可用 `--planner-provider` 覆盖 planner LLM provider；默认沿用服务配置。

指标：`planner_accuracy`, `should_use_rag_accuracy`, `retrieval_mode_accuracy`,
`rerank_decision_accuracy`, `avg_plan_latency_ms`, `fallback_rate`, `per_category`

## 3. 检索评测

```bash
# 单模式
python -m evals.eval_retrieval \
  --dataset evals/dataset.sample.jsonl \
  --retrieval-mode hybrid \
  --output evals/reports/retrieval_report.json

# 带 rerank
python -m evals.eval_retrieval \
  --dataset evals/dataset.sample.jsonl \
  --rerank --candidate-count 20 --rerank-top-k 4 \
  --output evals/reports/retrieval_report.json

# 对比模式：vector vs hybrid vs rerank 三合一
python -m evals.eval_retrieval \
  --dataset evals/dataset.sample.jsonl \
  --compare \
  --output evals/reports/retrieval_compare.json

# 使用 planner 输出驱动检索
python -m evals.eval_retrieval \
  --dataset evals/dataset.sample.jsonl \
  --use-planner \
  --output evals/reports/retrieval_planner_report.json
```

指标：`hit_at_k`, `recall_at_k`, `mrr`, `avg_retrieved_count`, `avg_top_score`, `per_category`

## 4. 回答评测（Ragas）

需要 LLM API Key 用于评估（生成回答用项目自身的 LLMService）：

```bash
# 设置评估 LLM
export OPENAI_API_KEY="sk-..."          # 或 EVAL_LLM_API_KEY
export EVAL_LLM_MODEL="gpt-4o"          # 可选，默认 gpt-4o
export EVAL_LLM_BASE_URL="..."          # 可选，OpenAI 兼容 API 地址

# 运行
python -m evals.eval_answer \
  --dataset evals/dataset.sample.jsonl \
  --retrieval-mode hybrid \
  --output evals/reports/answer_report.json

# 带 rerank
python -m evals.eval_answer \
  --dataset evals/dataset.sample.jsonl \
  --rerank \
  --output evals/reports/answer_report.json

# 使用 planner 输出驱动 service-level RAG 链路
python -m evals.eval_answer \
  --dataset evals/dataset.sample.jsonl \
  --use-planner \
  --output evals/reports/answer_planner_report.json
```

Ragas 指标：

| 指标 | 说明 |
|------|------|
| `faithfulness` | 回答是否忠实于检索到的上下文（核心指标） |
| `answer_relevancy` | 回答是否切题 |
| `answer_correctness` | 与参考答案的语义一致性（需 `reference_answer`） |

工程指标：`retrieval_hit_rate`, `avg_llm_latency_ms`, `avg_completion_tokens`, `per_category`

## 5. API 回答评测

API 评测复用同一份 JSONL 数据集，但通过运行中的 smoke HTTP stack 调用
`/api/v1/chat/query_sent`：

```bash
make qa-eval-api EVAL_DATASET=evals/dataset.sample.jsonl
```

可用 `SMOKE_BASE_URL` 覆盖目标环境。该入口属于 L3，不进入 `make check` 或
smoke pytest。

API 评测会注册临时用户，密码默认 `Password123`，可用 `EVAL_API_PASSWORD`
覆盖以匹配目标环境的密码策略。

## 6. Snapshot 与对比

每次完整跑完一整个评测集会生成一份 run snapshot。报告顶层包含：

- `run`：`id`, `kind`, `created_at`, `dataset_path`, `dataset_hash`, `git_commit`, `config`
- `summary`：聚合指标
- `details`：逐样本结果

推荐工作流：

```bash
uv run python -m evals.eval_answer \
  --dataset evals/dataset.sample.jsonl \
  --output evals/reports/baseline.json

uv run python -m evals.eval_answer \
  --dataset evals/dataset.sample.jsonl \
  --use-planner \
  --output evals/reports/candidate.json

uv run python -m evals.compare_reports \
  --baseline evals/reports/baseline.json \
  --candidate evals/reports/candidate.json
```

`evals/reports/` 是本地产物目录，被 `.gitignore` 忽略。

## 7. 常见问题

- **评估 LLM 和生成 LLM 要分开吗？** 建议用不同的模型：生成用项目配置的 LLM，评估用 GPT-4o 或同级模型（更稳定）。
- **没有 reference_answer 能跑吗？** 可以，Faithfulness 和 AnswerRelevancy 不需要参考答案，AnswerCorrectness 会自动跳过。
- **检索评测需要 LLM 吗？** 不需要，检索评测只测检索质量，不涉及 LLM 调用。
- **Planner 评测和 Ragas 是一回事吗？** 不是。Planner 评策略决策，Ragas 评最终答案质量。
- **性能压测放在哪里？** 放在 `perf/`。`evals/` 只负责效果评测和 snapshot 对比。
- **产物目录**：报告输出到 `evals/reports/`，该目录会被 `.gitignore` 忽略。
