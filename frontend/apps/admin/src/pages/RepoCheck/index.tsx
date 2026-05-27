import React from 'react';
import { useNavigate } from 'react-router-dom';
import { message as antdMessage, Spin } from 'antd';
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  Download,
  FileJson,
  Github,
  Loader2,
  ShieldCheck,
} from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import {
  useRepoAnalysisRunQuery,
  useSubmitRepoReadmeCheckMutation,
} from '../../query/hooks/repo-analysis';
import type { EvidenceItem, RepoAnalysisStatus } from '../../schemas/repo-analysis';
import styles from './RepoCheckPage.module.css';

const steps: Array<{ id: RepoAnalysisStatus | 'submit'; label: string }> = [
  { id: 'submit', label: '提交任务' },
  { id: 'pending', label: '等待调度' },
  { id: 'running', label: '分析 README' },
  { id: 'succeeded', label: '生成报告' },
];

const statusLabel: Record<RepoAnalysisStatus, string> = {
  pending: '等待调度',
  running: '分析中',
  succeeded: '已完成',
  failed: '失败',
};

const riskLabel: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  unknown: '未知',
};

const typeLabel: Record<string, string> = {
  demo_wrapper: 'Demo 包装',
  framework_assembly: '框架组合',
  research_prototype: '研究原型',
  product_candidate: '产品候选',
  unclear: '暂不明确',
};

const RepoCheckPage: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated, setShowAuthModal } = useAuth();
  const [repoUrl, setRepoUrl] = React.useState('');
  const [runId, setRunId] = React.useState<string | null>(null);
  const [showEvidenceJson, setShowEvidenceJson] = React.useState(false);
  const submitMutation = useSubmitRepoReadmeCheckMutation();
  const runQuery = useRepoAnalysisRunQuery(runId);
  const runData = runQuery.data;
  const report = runData?.report;
  const assessment = report?.structured;
  const evidenceItems = React.useMemo(() => {
    const evidence = runData?.evidence;
    if (!evidence) return new Map<string, EvidenceItem>();
    return new Map(
      [
        ...evidence.readme_claims,
        ...evidence.metadata_signals,
        ...evidence.missing_signals,
      ].map((item) => [item.id, item]),
    );
  }, [runData?.evidence]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!isAuthenticated) {
      setShowAuthModal(true);
      return;
    }
    if (!repoUrl.trim()) {
      antdMessage.warning('请输入 GitHub 仓库 URL');
      return;
    }
    const response = await submitMutation.mutateAsync(repoUrl.trim());
    setRunId(response.run_id);
    setShowEvidenceJson(false);
  };

  const downloadMarkdown = () => {
    if (!report?.markdown) return;
    const blob = new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${assessment?.project_name || 'repo-report'}-readme-check.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const currentStatus = runData?.run.status ?? (runId ? 'pending' : null);

  return (
    <div className={styles.page}>
      <div className={styles.shell}>
        <button className={styles.backButton} onClick={() => navigate('/')}>
          <ArrowLeft size={16} />
          返回
        </button>

        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <div className={styles.eyebrow}>
              <ShieldCheck size={16} />
              README Credibility Check
            </div>
            <h1>AI 项目可信度初筛</h1>
            <p>输入公开 GitHub 仓库，生成一份基于 README 和元信息的非技术判断报告。</p>
          </div>
          <form className={styles.inputBar} onSubmit={handleSubmit}>
            <Github size={20} />
            <input
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              placeholder="https://github.com/owner/repo"
              aria-label="GitHub repository URL"
            />
            <button type="submit" disabled={submitMutation.isPending}>
              {submitMutation.isPending ? <Loader2 size={18} /> : <ClipboardList size={18} />}
              Analyze
            </button>
          </form>
        </section>

        {runId && (
          <section className={styles.timeline}>
            {steps.map((step, index) => {
              const state = stepState(step.id, currentStatus);
              return (
                <div key={step.id} className={`${styles.step} ${styles[state]}`}>
                  <div className={styles.stepIcon}>
                    {state === 'done' ? <CheckCircle2 size={16} /> : index === 0 ? <Github size={16} /> : <Loader2 size={16} />}
                  </div>
                  <span>{step.label}</span>
                </div>
              );
            })}
          </section>
        )}

        {runQuery.isLoading && (
          <div className={styles.loadingPanel}>
            <Spin />
            <span>正在同步分析状态</span>
          </div>
        )}

        {runData?.run.status === 'failed' && (
          <div className={styles.errorPanel}>
            <AlertCircle size={20} />
            <span>{runData.run.error_message || '仓库分析失败，请稍后重试'}</span>
          </div>
        )}

        {assessment && runData?.subject && (
          <section className={styles.reportGrid}>
            <div className={styles.verdictPanel}>
              <div className={styles.panelHeader}>
                <div>
                  <span className={styles.kicker}>Verdict</span>
                  <h2>{assessment.project_name}</h2>
                </div>
                <span className={`${styles.statusBadge} ${styles[runData.run.status]}`}>
                  {statusLabel[runData.run.status]}
                </span>
              </div>
              <p className={styles.summary}>{assessment.one_sentence_summary}</p>
              <p className={styles.verdict}>{assessment.non_technical_verdict}</p>
              <div className={styles.metrics}>
                <Metric label="项目类型" value={typeLabel[assessment.likely_project_type]} />
                <Metric label="夸大风险" value={riskLabel[assessment.hype_risk]} />
                <Metric label="证据强度" value={assessment.evidence_strength} />
                <Metric label="生成方式" value={report?.generated_by || '-'} />
              </div>
              <div className={styles.actions}>
                <button onClick={downloadMarkdown}>
                  <Download size={16} />
                  Markdown
                </button>
                <button onClick={() => setShowEvidenceJson((value) => !value)}>
                  <FileJson size={16} />
                  Evidence JSON
                </button>
              </div>
            </div>

            <div className={styles.sidePanel}>
              <h3>可信信号</h3>
              <SignalList items={assessment.credibility_signals} />
              <h3>缺失信号</h3>
              <SignalList items={assessment.missing_signals} />
            </div>

            <div className={styles.findingsPanel}>
              <h3>关键发现</h3>
              <div className={styles.findingsList}>
                {assessment.findings.map((finding) => (
                  <details key={finding.title} className={styles.finding}>
                    <summary>
                      <span>{finding.title}</span>
                      <b className={styles[finding.severity]}>{finding.severity}</b>
                    </summary>
                    <p>{finding.non_technical_explanation}</p>
                    <div className={styles.evidenceRefs}>
                      {finding.evidence_refs.map((ref) => {
                        const item = evidenceItems.get(ref);
                        return (
                          <div key={ref} className={styles.evidenceRef}>
                            <code>{ref}</code>
                            <span>{item?.detail || '未找到证据详情'}</span>
                          </div>
                        );
                      })}
                    </div>
                  </details>
                ))}
              </div>
            </div>

            <div className={styles.markdownPanel}>
              <h3>Markdown 报告</h3>
              <pre>{report?.markdown}</pre>
            </div>

            {showEvidenceJson && (
              <div className={styles.jsonPanel}>
                <h3>Evidence JSON</h3>
                <pre>{JSON.stringify(runData.evidence, null, 2)}</pre>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
};

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metric}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SignalList({ items }: { items: string[] }) {
  if (!items.length) return <p className={styles.emptyText}>暂无</p>;
  return (
    <ul className={styles.signalList}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function stepState(
  step: RepoAnalysisStatus | 'submit',
  status: RepoAnalysisStatus | null,
): 'idle' | 'running' | 'done' | 'error' {
  if (!status) return step === 'submit' ? 'running' : 'idle';
  if (status === 'failed') return step === 'succeeded' ? 'error' : 'done';
  const order = ['submit', 'pending', 'running', 'succeeded'];
  const currentIndex = order.indexOf(status);
  const stepIndex = order.indexOf(step);
  if (stepIndex < currentIndex) return 'done';
  if (stepIndex === currentIndex) return status === 'succeeded' ? 'done' : 'running';
  return 'idle';
}

export default RepoCheckPage;
