import { searchContextSchema } from '../schemas/chat';

export type AgentTraceStepStatus = 'idle' | 'running' | 'done' | 'skipped' | 'error';

export interface AgentTraceStep {
    id: string;
    status: AgentTraceStepStatus;
    description: string;
    startedAt: number | null;
    finishedAt: number | null;
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
