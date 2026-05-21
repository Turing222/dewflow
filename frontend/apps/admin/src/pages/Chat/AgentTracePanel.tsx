import React, { useState } from 'react';
import { Check, Loader, AlertCircle, Minus, ChevronDown, ChevronLeft, ChevronRight, Activity } from 'lucide-react';
import { Button, Tooltip } from 'antd';
import { useTranslation } from 'react-i18next';
import type { AgentTraceStep, CitationItem } from '../../types/agent-trace';
import styles from './AgentTracePanel.module.css';

interface AgentTracePanelProps {
    traceSteps: AgentTraceStep[];
    citations: CitationItem[];
    collapsed?: boolean;
    onToggle?: () => void;
}

const AgentTracePanel: React.FC<AgentTracePanelProps> = ({
    traceSteps,
    citations,
    collapsed = false,
    onToggle,
}) => {
    const [citationsExpanded, setCitationsExpanded] = useState(false);
    const { t } = useTranslation();

    const hasTrace = traceSteps.length > 0;
    const summaryMetrics = getSummaryMetrics(traceSteps);

    if (collapsed) {
        return (
            <div className={`${styles['trace-panel']} ${styles['collapsed-trace-panel']}`} data-testid="trace-panel-collapsed">
                <Tooltip title={t('trace.expand')} placement="left">
                    <Button
                        className={styles['toggle-btn']}
                        type="text"
                        icon={<ChevronLeft size={18} />}
                        aria-label={t('trace.expand')}
                        onClick={onToggle}
                        data-testid="trace-panel-expand-btn"
                    />
                </Tooltip>
                <div className={styles['collapsed-icon-btn']}>
                    <Activity size={20} className={styles['spin-slow']} style={{ animationDuration: '3s' }} />
                </div>
                <div className={styles['collapsed-vertical-title']}>
                    {t('trace.title')}
                </div>
            </div>
        );
    }

    return (
        <div className={styles['trace-panel']}>
            <div className={styles['trace-panel-header']}>
                {onToggle && (
                    <Tooltip title={t('trace.collapse')} placement="left">
                        <Button
                            className={styles['toggle-btn']}
                            type="text"
                            icon={<ChevronRight size={18} />}
                            aria-label={t('trace.collapse')}
                            onClick={onToggle}
                            data-testid="trace-panel-collapse-btn"
                        />
                    </Tooltip>
                )}
                <span className={styles['trace-panel-title']}>
                    {t('trace.title')}
                </span>
            </div>

            <div className={styles['trace-panel-body']}>
                {!hasTrace ? (
                    <div className={styles['trace-panel-empty']} data-testid="trace-panel-empty">
                        {t('trace.empty_hint')}
                    </div>
                ) : (
                    <>
                        {summaryMetrics.length > 0 && (
                            <div className={styles['trace-metrics-summary']} data-testid="trace-metrics-summary">
                                {summaryMetrics.map((item) => (
                                    <div key={item.key} className={styles['trace-metric-item']}>
                                        <span className={styles['trace-metric-label']}>{t(`trace.summary.${item.key}`)}</span>
                                        <span className={styles['trace-metric-value']}>{item.value}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className={styles['trace-timeline']}>
                            {traceSteps.map((step, index) => (
                                <div
                                    key={step.id}
                                    className={`${styles['trace-step']} ${styles[`trace-step-${step.status}`]}`}
                                    data-testid={`trace-step-${step.id}`}
                                    style={{
                                        animationDelay: `${index * 60}ms`,
                                    }}
                                >
                                    <div
                                        className={
                                            styles['trace-step-indicator']
                                        }
                                    >
                                        <div
                                            className={styles['trace-step-dot']}
                                        />
                                        {index < traceSteps.length - 1 && (
                                            <div
                                                className={
                                                    styles['trace-step-line']
                                                }
                                            />
                                        )}
                                    </div>
                                    <div
                                        className={styles['trace-step-content']}
                                    >
                                        <div
                                            className={
                                                styles['trace-step-title']
                                            }
                                        >
                                            {t(`trace.steps.${step.id}`)}
                                        </div>
                                        {step.description && (
                                            <div
                                                className={
                                                    styles['trace-step-desc']
                                                }
                                            >
                                                {step.description}
                                            </div>
                                        )}
                                        {step.metricDetails && Object.keys(step.metricDetails).length > 0 && (
                                            <div className={styles['trace-step-details']}>
                                                {Object.entries(step.metricDetails).map(([key, value]) => (
                                                    <span key={key}>
                                                        {t(`trace.metrics.${key}`, key)}: {formatMetricValue(key, value)}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    {step.durationMs !== undefined && (
                                        <div className={styles['trace-step-duration']} data-testid={`trace-step-duration-${step.id}`}>
                                            {formatDuration(step.durationMs)}
                                        </div>
                                    )}
                                    <div className={styles['trace-step-icon']}>
                                        {step.status === 'done' && (
                                            <Check size={14} />
                                        )}
                                        {step.status === 'running' && (
                                            <Loader
                                                size={14}
                                                className={styles['spin']}
                                            />
                                        )}
                                        {step.status === 'error' && (
                                            <AlertCircle size={14} />
                                        )}
                                        {step.status === 'skipped' && (
                                            <Minus size={14} />
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className={styles['trace-citations']}>
                            <div
                                className={
                                    styles['trace-citations-header']
                                }
                                data-testid="trace-citations-header"
                                onClick={() =>
                                    setCitationsExpanded(!citationsExpanded)
                                }
                                role="button"
                                tabIndex={0}
                                onKeyDown={(e) => {
                                    if (
                                        e.key === 'Enter' ||
                                        e.key === ' '
                                    ) {
                                        setCitationsExpanded(
                                            !citationsExpanded,
                                        );
                                    }
                                }}
                            >
                                <span>
                                    {t('trace.citations_count', {
                                        count: citations.length,
                                    })}
                                </span>
                                <ChevronDown
                                    size={14}
                                    className={
                                        citationsExpanded
                                            ? styles['rotated']
                                            : ''
                                    }
                                />
                            </div>
                            {citationsExpanded && (
                                <div
                                    className={
                                        styles['trace-citations-list']
                                    }
                                    data-testid="trace-citations-list"
                                >
                                    {citations.length === 0 ? (
                                        <div
                                            className={
                                                styles[
                                                    'trace-citations-empty'
                                                ]
                                            }
                                            data-testid="trace-citations-empty"
                                        >
                                            {t('trace.no_citations')}
                                        </div>
                                    ) : (
                                        citations.map((cit) => (
                                            <div
                                                key={cit.chunkId}
                                                data-testid="citation-card"
                                                className={
                                                    styles['citation-card']
                                                }
                                            >
                                                <div
                                                    className={
                                                        styles[
                                                            'citation-card-name'
                                                        ]
                                                    }
                                                >
                                                    {cit.documentName}
                                                </div>
                                                <div
                                                    className={
                                                        styles[
                                                            'citation-card-meta'
                                                        ]
                                                    }
                                                >
                                                    {cit.chunkId && (
                                                        <span>
                                                            {t(
                                                                'trace.chunk_id',
                                                            )}
                                                            : {cit.chunkId}
                                                        </span>
                                                    )}
                                                    {cit.relevanceScore >
                                                        0 && (
                                                        <span>
                                                            {t('trace.score')}
                                                            :{' '}
                                                            {(
                                                                cit.relevanceScore *
                                                                100
                                                            ).toFixed(0)}
                                                            %
                                                        </span>
                                                    )}
                                                </div>
                                                {cit.summarySnippet && (
                                                    <div
                                                        className={
                                                            styles[
                                                                'citation-card-snippet'
                                                            ]
                                                        }
                                                    >
                                                        {cit.summarySnippet}
                                                    </div>
                                                )}
                                            </div>
                                        ))
                                    )}
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default AgentTracePanel;

function formatDuration(value: number): string {
    if (value < 1000) return `${Math.round(value)} ms`;
    return `${(value / 1000).toFixed(1)} s`;
}

function formatMetricValue(key: string, value: number | string | boolean): string {
    if (typeof value === 'boolean') return value ? 'yes' : 'no';
    if (typeof value === 'number') {
        if (key.endsWith('_ms')) return formatDuration(value);
        return String(value);
    }
    return value;
}

function getSummaryMetrics(traceSteps: AgentTraceStep[]) {
    const generateStep = traceSteps.find((step) => step.id === 'generate-answer');
    const completeStep = traceSteps.find((step) => step.id === 'complete');
    const firstToken = generateStep?.metricDetails?.first_token_latency_ms;
    const tokensPerSecond = completeStep?.metricDetails?.tokens_per_second;
    const items: Array<{ key: string; value: string }> = [];
    if (typeof firstToken === 'number') {
        items.push({ key: 'first_token', value: formatDuration(firstToken) });
    }
    if (completeStep?.durationMs !== undefined) {
        items.push({ key: 'total', value: formatDuration(completeStep.durationMs) });
    }
    if (typeof tokensPerSecond === 'number') {
        items.push({ key: 'tokens_per_second', value: tokensPerSecond.toFixed(2) });
    }
    return items;
}
