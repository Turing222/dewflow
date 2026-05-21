import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { Mock } from 'vitest';
import { streamChatQuery, type StreamCallbacks } from './chat-stream';

vi.mock('../api/chat', () => ({
    sendQueryStreamAPI: vi.fn(),
}));

import { sendQueryStreamAPI } from '../api/chat';

const mockSendQueryStreamAPI = vi.mocked(sendQueryStreamAPI);

function createFakeSSEResponse(chunks: string[]): Response {
    const encoder = new TextEncoder();
    let chunkIndex = 0;
    const stream = new ReadableStream({
        pull(controller) {
            if (chunkIndex < chunks.length) {
                controller.enqueue(encoder.encode(chunks[chunkIndex]));
                chunkIndex++;
            } else {
                controller.close();
            }
        },
    });
    return new Response(stream);
}

type MockCallbacks = StreamCallbacks & {
    onMeta: Mock<StreamCallbacks['onMeta']>;
    onChunk: Mock<StreamCallbacks['onChunk']>;
    onDone: Mock<StreamCallbacks['onDone']>;
    onError: Mock<StreamCallbacks['onError']>;
};

function createCallbacks(): MockCallbacks {
    return {
        onMeta: vi.fn(),
        onChunk: vi.fn(),
        onDone: vi.fn(),
        onError: vi.fn(),
    };
}

beforeEach(() => {
    vi.restoreAllMocks();
});

describe('streamChatQuery', () => {
    it('invokes onMeta for meta event', async () => {
        const sseData = 'data: {"type":"meta","session_id":"s1","session_title":"Hello"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onMeta).toHaveBeenCalledOnce();
        });
        expect(callbacks.onMeta).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'meta', session_id: 's1', session_title: 'Hello' }),
        );
    });

    it('invokes onChunk for chunk event', async () => {
        const sseData = 'data: {"type":"chunk","content":"hello"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onChunk).toHaveBeenCalledOnce();
        });
        expect(callbacks.onChunk).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'chunk', content: 'hello' }),
        );
    });

    it('invokes onError for error event', async () => {
        const sseData = 'data: {"type":"error","message":"LLM error"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError).toHaveBeenCalledWith(expect.any(Error));
        expect(callbacks.onError.mock.calls[0][0].message).toBe('LLM error');
    });

    it('invokes onDone when [DONE] received', async () => {
        const sseData = 'data: [DONE]\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onDone).toHaveBeenCalledOnce();
        });
    });

    it('calls onDone when stream ends without [DONE]', async () => {
        const sseData = 'data: {"type":"chunk","content":"x"}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onDone).toHaveBeenCalledOnce();
        });
        expect(callbacks.onChunk).toHaveBeenCalledOnce();
    });

    it('handles meta then chunk then [DONE] in order', async () => {
        const chunks = [
            'data: {"type":"meta","session_id":"s1","session_title":"T"}\n\n',
            'data: {"type":"chunk","content":"hi"}\n\n',
            'data: [DONE]\n\n',
        ];
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse(chunks));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onDone).toHaveBeenCalledOnce();
        });
        const callOrder = [
            callbacks.onMeta.mock.invocationCallOrder[0],
            callbacks.onChunk.mock.invocationCallOrder[0],
            callbacks.onDone.mock.invocationCallOrder[0],
        ];
        expect(callOrder).toEqual([...callOrder].sort((a, b) => a - b));
    });

    it('buffers partial SSE events across reads', async () => {
        const chunks = [
            'data: {"type":"me',
            'ta","session_id":"s1","session_title":"T"}\n\n',
        ];
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse(chunks));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onMeta).toHaveBeenCalledOnce();
        });
        expect(callbacks.onMeta).toHaveBeenCalledWith(
            expect.objectContaining({ type: 'meta', session_id: 's1' }),
        );
    });

    it('silently warns on parse errors without calling onError', async () => {
        const sseData = 'data: {invalid json}\n\n';
        mockSendQueryStreamAPI.mockResolvedValue(createFakeSSEResponse([sseData]));
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(warnSpy).toHaveBeenCalled();
        });
        expect(callbacks.onError).not.toHaveBeenCalled();
    });

    it('calls onError when no reader available', async () => {
        mockSendQueryStreamAPI.mockResolvedValue(new Response(null, { status: 200 }));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError.mock.calls[0][0].message).toBe('无法获取响应流');
    });

    it('calls onError for unexpected exceptions', async () => {
        mockSendQueryStreamAPI.mockRejectedValue(new Error('network fail'));
        const callbacks = createCallbacks();

        streamChatQuery({ query: 'test' }, callbacks);

        await vi.waitFor(() => {
            expect(callbacks.onError).toHaveBeenCalledOnce();
        });
        expect(callbacks.onError.mock.calls[0][0].message).toBe('network fail');
    });

    it('silently returns on abort', async () => {
        const stream = new ReadableStream({
            pull() {
                // never resolves — stream stays open
            },
        });
        mockSendQueryStreamAPI.mockResolvedValue(new Response(stream));
        const callbacks = createCallbacks();

        const controller = streamChatQuery({ query: 'test' }, callbacks);
        controller.abort();

        await new Promise((r) => setTimeout(r, 50));
        expect(callbacks.onDone).not.toHaveBeenCalled();
        expect(callbacks.onError).not.toHaveBeenCalled();
    });
});
