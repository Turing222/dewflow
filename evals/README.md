# RAG Eval

RAG 链路评测，分两档：

- **检索评测**（`eval_retrieval.py`）：hit@k / recall@k / MRR，离线可跑，无需 LLM
- **回答评测**（`eval_answer.py`）：端到端 + Ragas LLM-as-Judge（Faithfulness, AnswerRelevancy, AnswerCorrectness）

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
| `reference_answer` | str\|null | 参考答案，用于 AnswerCorrectness |
| `must_refuse` | bool | 期望拒答 |
| `notes` | str\|null | 备注 |

示例：`evals/dataset.sample.jsonl`

## 2. 检索评测

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
```

指标：`hit_at_k`, `recall_at_k`, `mrr`, `avg_retrieved_count`, `avg_top_score`, `per_category`

## 3. 回答评测（Ragas）

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
```

Ragas 指标：

| 指标 | 说明 |
|------|------|
| `faithfulness` | 回答是否忠实于检索到的上下文（核心指标） |
| `answer_relevancy` | 回答是否切题 |
| `answer_correctness` | 与参考答案的语义一致性（需 `reference_answer`） |

工程指标：`retrieval_hit_rate`, `avg_llm_latency_ms`, `avg_completion_tokens`, `per_category`

## 4. 常见问题

- **评估 LLM 和生成 LLM 要分开吗？** 建议用不同的模型：生成用项目配置的 LLM，评估用 GPT-4o 或同级模型（更稳定）。
- **没有 reference_answer 能跑吗？** 可以，Faithfulness 和 AnswerRelevancy 不需要参考答案，AnswerCorrectness 会自动跳过。
- **检索评测需要 LLM 吗？** 不需要，检索评测只测检索质量，不涉及 LLM 调用。
- **产物目录**：报告输出到 `evals/reports/`，该目录会被 `.gitignore` 忽略。
