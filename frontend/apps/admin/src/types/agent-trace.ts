import {
    chatMessageMetricsSchema,
    ragMetricsSchema,
    searchContextSchema,
} from '../schemas/chat';
import type { ChatMessageMetrics, RagMetrics } from '../schemas/chat';

export type AgentTraceStepStatus = 'idle' | 'running' | 'done' | 'skipped' | 'error';

export interface AgentTraceStep {
    id: string;
    status: AgentTraceStepStatus;
    description: string;
    startedAt: number | null;
    finishedAt: number | null;
    durationMs?: number;
    metricDetails?: Record<string, number | string | boolean>;
}

export interface CitationItem {
    documentName: string;
    chunkId: string;
    relevanceScore: number;
    summarySnippet: string;
}

export interface AgentTraceState {
    steps: AgentTraceStep[];
    citations: CitationItem[];
    isComplete: boolean;
}

export const TRACE_STEP_DEFS = [
    { id: 'receive-query' },
    { id: 'router-judge' },
    { id: 'knowledge-path' },
    { id: 'retrieve-docs' },
    { id: 'generate-answer' },
    { id: 'organize-citations' },
    { id: 'complete' },
] as const;

export function createInitialTraceSteps(): AgentTraceStep[] {
    const now = Date.now();
    return TRACE_STEP_DEFS.map((def, index) => ({
        id: def.id,
        status: index === 0 ? ('running' as const) : ('idle' as const),
        description: '',
        startedAt: index === 0 ? now : null,
        finishedAt: null,
    }));
}

export const INGESTION_TRACE_STEP_DEFS = [
    { id: 'file-upload' },
    { id: 'content-audit' },
    { id: 'semantic-chunk' },
    { id: 'vector-index' },
    { id: 'ingestion-complete' },
] as const;

export function createInitialIngestionSteps(): AgentTraceStep[] {
    return INGESTION_TRACE_STEP_DEFS.map((def) => ({
        id: def.id,
        status: 'idle' as const,
        description: '',
        startedAt: null,
        finishedAt: null,
    }));
}

function parseMetrics<T>(
    payload: Record<string, unknown> | null | undefined,
    parser: { safeParse: (value: unknown) => { success: true; data: T } | { success: false } },
): T | undefined {
    const metrics = payload?.metrics;
    if (!metrics || typeof metrics !== 'object') return undefined;
    const result = parser.safeParse(metrics);
    return result.success ? result.data : undefined;
}

export function parseChatMessageMetrics(
    messageMetadata: Record<string, unknown> | null | undefined,
): ChatMessageMetrics | undefined {
    return parseMetrics(messageMetadata, chatMessageMetricsSchema);
}

export function parseRagMetrics(
    searchContext: Record<string, unknown> | null | undefined,
): RagMetrics | undefined {
    return parseMetrics(searchContext, ragMetricsSchema);
}

function hasAnyMetric(
    messageMetrics?: ChatMessageMetrics,
    ragMetrics?: RagMetrics,
): boolean {
    return Boolean(
        (messageMetrics && Object.keys(messageMetrics).length > 0) ||
        (ragMetrics && Object.keys(ragMetrics).length > 0),
    );
}

export function applyTraceMetricsToSteps(
    steps: AgentTraceStep[],
    messageMetrics?: ChatMessageMetrics,
    ragMetrics?: RagMetrics,
): AgentTraceStep[] {
    if (!hasAnyMetric(messageMetrics, ragMetrics)) return steps;

    const baseSteps = steps.length > 0
        ? steps
        : createInitialTraceSteps().map((step) => ({
            ...step,
            status: 'done' as const,
            finishedAt: Date.now(),
        }));

    return baseSteps.map((step) => {
        if (step.id === 'router-judge' && ragMetrics?.planner_ms !== undefined) {
            return { ...step, durationMs: ragMetrics.planner_ms };
        }
        if (step.id === 'retrieve-docs') {
            const metricDetails: Record<string, number | string | boolean> = {};
            if (ragMetrics?.candidate_count !== undefined) {
                metricDetails.candidate_count = ragMetrics.candidate_count;
            }
            if (ragMetrics?.hit_count !== undefined) {
                metricDetails.hit_count = ragMetrics.hit_count;
            }
            if (ragMetrics?.retrieval_mode !== undefined) {
                metricDetails.retrieval_mode = ragMetrics.retrieval_mode;
            }
            if (ragMetrics?.rerank_used !== undefined) {
                metricDetails.rerank_used = ragMetrics.rerank_used;
            }
            return {
                ...step,
                durationMs: ragMetrics?.retrieve_ms,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        if (step.id === 'generate-answer') {
            const metricDetails: Record<string, number | string | boolean> = {};
            // Prefer Web-observed e2e latency when available; fall back to the
            // Worker-local first token latency for older/completed records.
            const firstToken = messageMetrics?.e2e_first_token_ms ?? messageMetrics?.first_token_latency_ms;
            if (firstToken !== undefined) metricDetails.first_token_latency_ms = firstToken;
            if (messageMetrics?.llm_first_token_ms !== undefined) {
                metricDetails.llm_first_token_ms = messageMetrics.llm_first_token_ms;
            }
            return {
                ...step,
                durationMs: messageMetrics?.llm_generate_ms,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        if (step.id === 'organize-citations' && ragMetrics?.citation_validate_ms !== undefined) {
            return { ...step, durationMs: ragMetrics.citation_validate_ms };
        }
        if (step.id === 'complete') {
            const metricDetails: Record<string, number | string | boolean> = {};
            if (messageMetrics?.tokens_per_second !== undefined) {
                metricDetails.tokens_per_second = messageMetrics.tokens_per_second;
            }
            if (messageMetrics?.queue_wait_ms !== undefined) {
                metricDetails.queue_wait_ms = messageMetrics.queue_wait_ms;
            }
            return {
                ...step,
                durationMs: messageMetrics?.worker_total_latency_ms,
                metricDetails: Object.keys(metricDetails).length > 0 ? metricDetails : step.metricDetails,
            };
        }
        return step;
    });
}

export function parseCitations(
    searchContext: Record<string, unknown> | undefined,
): CitationItem[] {
    if (!searchContext || typeof searchContext !== 'object') return [];

    const result = searchContextSchema.safeParse(searchContext);
    if (!result.success) {
        if (import.meta.env.DEV) {
            console.warn(
                '[parseCitations] search_context does not match expected schema',
                result.error.flatten(),
            );
        }
        return [];
    }

    return result.data.citations
        .map((raw): CitationItem => ({
            documentName: raw.document_name,
            chunkId: raw.chunk_id,
            relevanceScore: raw.score,
            summarySnippet: raw.summary,
        }))
        .filter((c) => c.documentName || c.summarySnippet);
}
