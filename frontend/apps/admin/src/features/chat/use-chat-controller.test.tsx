import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { useChatController } from './use-chat-controller';
import type { StreamCallbacks, StreamOptions } from '../../streams/chat-stream';
import { TRACE_STEP_DEFS } from '../../types/agent-trace';

vi.mock('../../api/chat', () => ({
    sendQueryAPI: vi.fn(),
    sendQueryStreamAPI: vi.fn(),
    getSessionsAPI: vi.fn(),
    getSessionDetailAPI: vi.fn().mockResolvedValue({
        session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
        messages: [],
        total_messages: 0,
    }),
}));

vi.mock('../../streams/chat-stream', () => ({
    streamChatQuery: vi.fn(),
}));

vi.mock('../../context/useAuth', () => ({
    useAuth: () => ({
        user: { id: '1', is_superuser: false },
        refreshUser: vi.fn().mockResolvedValue(undefined),
    }),
}));

vi.mock('../../query/keys/chat', () => ({
    chatKeys: {
        sessions: () => ['chat', 'sessions'],
        sessionDetail: (id: string) => ['chat', 'session', id],
    },
}));

// Factory lets individual tests control what useSessionDetailQuery returns.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockSessionDetailData: any = { data: undefined, isLoading: false };

vi.mock('../../query/hooks/chat', () => ({
    useSessionDetailQuery: () => mockSessionDetailData,
}));

import { streamChatQuery } from '../../streams/chat-stream';
import { getSessionDetailAPI } from '../../api/chat';

const mockStreamChatQuery = vi.mocked(streamChatQuery);
const mockGetSessionDetailAPI = vi.mocked(getSessionDetailAPI);

function createWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false, gcTime: 0 },
            mutations: { retry: false },
        },
    });
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    // Reset per-test session detail mock to "no data" default
    mockSessionDetailData = { data: undefined, isLoading: false } as any;
    mockGetSessionDetailAPI.mockResolvedValue({
        session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
        messages: [],
        total_messages: 0,
    });
});

describe('useChatController', () => {
    it('aborts previous stream signal when sending a new query', async () => {
        let firstSignal: AbortSignal | undefined;

        mockStreamChatQuery.mockImplementation((options: StreamOptions) => {
            if (!firstSignal) {
                firstSignal = options.signal;
            }
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('first query');
        });

        expect(firstSignal).toBeDefined();
        expect(firstSignal!.aborted).toBe(false);

        await act(async () => {
            result.current.sendQuery('second query');
        });

        // The first signal should now be aborted
        expect(firstSignal!.aborted).toBe(true);
    });

    it('does not commit state in onDone if controller was aborted', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};
        let capturedSignal: AbortSignal | undefined;

        mockStreamChatQuery.mockImplementation((options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            capturedSignal = options.signal;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        // Abort the signal after sendQuery returns
        expect(capturedSignal).toBeDefined();
        // Manually abort to simulate the race condition
        // We need to abort the newController from the hook — but it's internal.
        // Instead, test by calling startNewChat which aborts it.
        act(() => {
            result.current.startNewChat();
        });

        // Now call onDone — the guard should prevent state commit
        const messageCountBefore = result.current.messages.length;
        act(() => {
            capturedCallbacks.onDone!();
        });

        // No new assistant message should be added
        expect(result.current.messages.length).toBe(messageCountBefore);
    });

    it('does not commit state in onError if controller was aborted', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        // Abort via startNewChat
        act(() => {
            result.current.startNewChat();
        });

        const messageCountBefore = result.current.messages.length;
        act(() => {
            capturedCallbacks.onError!(new Error('test error'));
        });

        // No error message should be appended
        expect(result.current.messages.length).toBe(messageCountBefore);
    });

    it('handles getSessionDetailAPI rejection without unhandled promise rejection', async () => {
        mockGetSessionDetailAPI.mockRejectedValue(new Error('network fail'));

        let capturedCallbacks: Partial<StreamCallbacks> = {};
        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        // Calling onDone should not throw unhandled rejection even if getSessionDetailAPI fails
        await act(async () => {
            capturedCallbacks.onDone!();
        });

        // .catch(() => {}) prevents unhandled rejection
        expect(true).toBe(true);
    });

    // --- Trace step tests ---

    it('initializes trace steps on sendQuery', async () => {
        mockStreamChatQuery.mockReturnValue(new AbortController());

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        expect(result.current.traceSteps).toHaveLength(0);

        await act(async () => {
            result.current.sendQuery('test');
        });

        expect(result.current.traceSteps).toHaveLength(TRACE_STEP_DEFS.length);
        expect(result.current.traceSteps[0].status).toBe('running');
        expect(result.current.traceSteps[0].id).toBe('receive-query');
        for (let i = 1; i < result.current.traceSteps.length; i++) {
            expect(result.current.traceSteps[i].status).toBe('idle');
        }
    });

    it('advances trace steps on onMeta', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
        });

        // Steps 0-2 should be done, step 3 (retrieve-docs) running
        expect(result.current.traceSteps[0].status).toBe('done');
        expect(result.current.traceSteps[1].status).toBe('done');
        expect(result.current.traceSteps[2].status).toBe('done');
        expect(result.current.traceSteps[3].status).toBe('running');
        expect(result.current.traceSteps[3].id).toBe('retrieve-docs');
    });

    it('advances trace steps on first onChunk', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
        });

        act(() => {
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'Hello' });
        });

        expect(result.current.traceSteps[4].status).toBe('running');
        expect(result.current.traceSteps[4].id).toBe('generate-answer');
    });

    it('marks all remaining steps done on onDone', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'Hello' });
        });

        await act(async () => {
            capturedCallbacks.onDone!();
        });

        for (const step of result.current.traceSteps) {
            expect(step.status).toBe('done');
        }
    });

    it('marks running step as error and later steps as skipped on onError', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
        });

        // Step 3 (retrieve-docs) is running at this point
        act(() => {
            capturedCallbacks.onError!(new Error('fail'));
        });

        const runningIdx = result.current.traceSteps.findIndex((s) => s.status === 'error');
        expect(runningIdx).toBe(3);

        for (let i = runningIdx + 1; i < result.current.traceSteps.length; i++) {
            expect(result.current.traceSteps[i].status).toBe('skipped');
        }
    });

    it('clears trace on startNewChat', async () => {
        mockStreamChatQuery.mockReturnValue(new AbortController());

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        expect(result.current.traceSteps.length).toBeGreaterThan(0);

        act(() => {
            result.current.startNewChat();
        });

        expect(result.current.traceSteps).toHaveLength(0);
        expect(result.current.citations).toHaveLength(0);
    });

    it('parses citations from search_context after onDone', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        mockGetSessionDetailAPI.mockResolvedValue({
            session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
            messages: [{
                id: 'm1',
                session_id: 's1',
                role: 'assistant',
                content: 'answer',
                status: 'success',
                search_context: {
                    citations: [
                        { document_name: 'doc1.pdf', chunk_id: 'c1', score: 0.92, summary: 'Passage one.' },
                        { document_name: 'report.docx', chunk_id: 'c2', score: 0.78, summary: 'Passage two.' },
                    ],
                },
                created_at: '',
                updated_at: '',
            }],
            total_messages: 1,
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'answer' });
        });

        await act(async () => {
            capturedCallbacks.onDone!();
        });

        expect(result.current.citations).toHaveLength(2);
        expect(result.current.citations[0].documentName).toBe('doc1.pdf');
        expect(result.current.citations[1].documentName).toBe('report.docx');
    });

    it('handles empty or malformed search_context gracefully', async () => {
        let capturedCallbacks: Partial<StreamCallbacks> = {};

        mockStreamChatQuery.mockImplementation((_options: StreamOptions, callbacks: StreamCallbacks) => {
            capturedCallbacks = callbacks;
            return new AbortController();
        });

        mockGetSessionDetailAPI.mockResolvedValue({
            session: { id: 's1', title: 'Test', user_id: '1', created_at: '', updated_at: '', total_tokens: 0 },
            messages: [{
                id: 'm1',
                session_id: 's1',
                role: 'assistant',
                content: 'answer',
                status: 'success',
                created_at: '',
                updated_at: '',
            }],
            total_messages: 1,
        });

        const { result } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            result.current.sendQuery('test');
        });

        act(() => {
            capturedCallbacks.onMeta!({ type: 'meta', session_id: 's1', session_title: 'Test', message_id: 'm1' });
            capturedCallbacks.onChunk!({ type: 'chunk', content: 'answer' });
        });

        await act(async () => {
            capturedCallbacks.onDone!();
        });

        expect(result.current.citations).toHaveLength(0);
    });

    // P2-9 — historical session: citations derived from useEffect watching sessionDetailData
    it('derives citations from historical session via useSessionDetailQuery', async () => {
        // Simulate useSessionDetailQuery returning a session with search_context
        const historicalDetail = {
            session: { id: 'hist-1', title: 'History', user_id: '1', created_at: '', updated_at: '', total_tokens: 50 },
            messages: [
                {
                    id: 'h-m1',
                    session_id: 'hist-1',
                    role: 'user' as const,
                    content: 'question',
                    status: 'success' as const,
                    created_at: '',
                    updated_at: '',
                },
                {
                    id: 'h-m2',
                    session_id: 'hist-1',
                    role: 'assistant' as const,
                    content: 'historical answer',
                    status: 'success' as const,
                    search_context: {
                        citations: [
                            { document_name: 'hist-doc.pdf', chunk_id: 'hc1', score: 0.85, summary: 'Historical passage.' },
                        ],
                    },
                    created_at: '',
                    updated_at: '',
                },
            ],
            total_messages: 2,
        };

        const { result, rerender } = renderHook(() => useChatController(), {
            wrapper: createWrapper(),
        });

        // Citations should be empty before any session is selected
        expect(result.current.citations).toHaveLength(0);

        // Step 1: selectSession switches to history mode
        act(() => {
            result.current.selectSession({
                id: 'hist-1',
                title: 'History',
                user_id: '1',
                created_at: '',
                updated_at: '',
                total_tokens: 50,
            });
        });

        // Step 2: simulate useSessionDetailQuery resolving with data.
        // Wrapped in act() so React flushes the useEffect before assertions run.
        act(() => {
            mockSessionDetailData = { data: historicalDetail, isLoading: false };
            rerender();
        });

        // useEffect should have fired and populated citations from the last assistant message
        expect(result.current.citations).toHaveLength(1);
        expect(result.current.citations[0].documentName).toBe('hist-doc.pdf');
        expect(result.current.citations[0].relevanceScore).toBe(0.85);
    });
});
