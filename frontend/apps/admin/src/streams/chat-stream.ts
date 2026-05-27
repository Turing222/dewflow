import { sendQueryStreamAPI } from '../api/chat';
import { chatStreamEventSchema } from '../schemas/chat';
import type { ChatStreamEvent } from '../schemas/chat';

type StartedEvent = Extract<ChatStreamEvent, { type: 'started' }>;
type MetaEvent = Extract<ChatStreamEvent, { type: 'meta' }>;
type ChunkEvent = Extract<ChatStreamEvent, { type: 'chunk' }>;

export type StreamCallbacks = {
    onStarted?: (event: StartedEvent) => void;
    onMeta: (event: MetaEvent) => void;
    onChunk: (event: ChunkEvent) => void;
    onDone: () => void;
    onError: (error: Error) => void;
    onAbort?: () => void;
};

export type StreamOptions = {
    query: string;
    sessionId?: string;
    kbId?: string;
    clientRequestId?: string;
    enableExternalContext?: boolean;
    signal?: AbortSignal;
};

export function streamChatQuery(
    options: StreamOptions,
    callbacks: StreamCallbacks,
): AbortController {
    const abortController = new AbortController();

    if (options.signal?.aborted) {
        abortController.abort();
        return abortController;
    }

    let parentAbortHandler: (() => void) | null = null;

    if (options.signal) {
        parentAbortHandler = () => abortController.abort();
        options.signal.addEventListener('abort', parentAbortHandler, { once: true });
    }

    (async () => {
        try {
            const response = await sendQueryStreamAPI({
                query: options.query,
                sessionId: options.sessionId,
                kbId: options.kbId,
                clientRequestId: options.clientRequestId,
                enableExternalContext: options.enableExternalContext,
                signal: abortController.signal,
            });

            const reader = response.body?.getReader();
            if (!reader) {
                callbacks.onError(new Error('无法获取响应流'));
                return;
            }

            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                if (abortController.signal.aborted) {
                    reader.cancel().catch(() => {});
                    callbacks.onAbort?.();
                    return;
                }
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                const events = buffer.split('\n\n');
                buffer = events.pop() || '';

                for (const event of events) {
                    const line = event.trim();
                    if (!line.startsWith('data: ')) continue;

                    const data = line.slice(6);

                    if (data === '[DONE]') {
                        callbacks.onDone();
                        return;
                    }

                    try {
                        const parsed = chatStreamEventSchema.parse(JSON.parse(data));

                        if (parsed.type === 'started') {
                            callbacks.onStarted?.(parsed);
                        } else if (parsed.type === 'meta') {
                            callbacks.onMeta(parsed);
                        } else if (parsed.type === 'chunk') {
                            callbacks.onChunk(parsed);
                        } else if (parsed.type === 'error') {
                            callbacks.onError(new Error(parsed.message || 'LLM 服务错误'));
                            return;
                        }
                    } catch (parseErr) {
                        console.warn('SSE 解析警告:', parseErr);
                    }
                }
            }

            // Stream ended without [DONE] — treat as error
            callbacks.onError(new Error('流式响应异常结束'));
        } catch (err: unknown) {
            if (abortController.signal.aborted) return;
            callbacks.onError(err instanceof Error ? err : new Error('请求处理失败，请稍后重试'));
        } finally {
            if (parentAbortHandler && options.signal) {
                options.signal.removeEventListener('abort', parentAbortHandler);
            }
        }
    })();

    return abortController;
}
