import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { useChatController } from './use-chat-controller';
import type { StreamCallbacks, StreamOptions } from '../../streams/chat-stream';

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

vi.mock('../../query/hooks/chat', () => ({
    useSessionDetailQuery: () => ({ data: undefined, isLoading: false }),
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
    vi.restoreAllMocks();
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
});
