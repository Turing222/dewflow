import request, { createAuthorizedHeaders } from '../lib/http/client';
import { createFetchHttpError, notifyHttpError } from '../lib/http/errors';
import { handleUnauthorized } from '../lib/http/auth';
import { resolveIdempotencyKey, IDEMPOTENCY_KEY_HEADER } from '../lib/http/idempotency';
import { getRequestIdFromHeaders } from '../lib/http/trace';
import {
    chatQueryRequestSchema,
    chatQueryResponseSchema,
    sessionDetailResponseSchema,
    sessionListResponseSchema,
} from '../schemas/chat';
import { parseWithSchema } from '../schemas/parse';
import { API_URLS } from './urls';

export const sendQueryAPI = (
    query: string,
    sessionId?: string,
    kbId?: string,
    clientRequestId?: string,
) => {
    const resolvedClientRequestId = resolveIdempotencyKey(clientRequestId);
    const payload = chatQueryRequestSchema.parse({
        query,
        session_id: sessionId || null,
        kb_id: kbId || null,
        client_request_id: resolvedClientRequestId,
    });
    return request
        .post<unknown, unknown>(API_URLS.CHAT.QUERY, payload, {
            headers: { [IDEMPOTENCY_KEY_HEADER]: resolvedClientRequestId },
        })
        .then((response) => parseWithSchema(chatQueryResponseSchema, response, '聊天响应格式无效'));
};

/**
 * SSE 流式查询 — 使用原生 fetch 读取 text/event-stream
 * 返回 Response 对象，调用方通过 body.getReader() 逐 chunk 读取
 */
export const sendQueryStreamAPI = async (
    query: string,
    sessionId?: string,
    kbId?: string,
    clientRequestId?: string,
    signal?: AbortSignal,
): Promise<Response> => {
    const resolvedClientRequestId = resolveIdempotencyKey(clientRequestId);
    const payload = chatQueryRequestSchema.parse({
        query,
        session_id: sessionId || null,
        kb_id: kbId || null,
        client_request_id: resolvedClientRequestId,
    });
    const res = await fetch(API_URLS.CHAT.QUERY_STREAM, {
        method: 'POST',
        headers: createAuthorizedHeaders({
            'Content-Type': 'application/json',
        }, { idempotencyKey: resolvedClientRequestId }),
        body: JSON.stringify(payload),
        signal,
    });

    if (!res.ok) {
        const error = createFetchHttpError({
            status: res.status,
            statusText: res.statusText,
            requestId: getRequestIdFromHeaders(res.headers),
            url: API_URLS.CHAT.QUERY_STREAM,
            method: 'POST',
        });

        if (error.code === 'unauthorized') {
            handleUnauthorized();
            notifyHttpError(error);
        }

        throw error;
    }
    return res;
};

export const getSessionsAPI = (skip = 0, limit = 20) => {
    return request
        .get<unknown, unknown>(API_URLS.CHAT.SESSIONS, {
            params: { skip, limit },
        })
        .then((response) => parseWithSchema(sessionListResponseSchema, response, '会话列表响应格式无效'));
};

export const getSessionDetailAPI = (sessionId: string, skip = 0, limit = 100) => {
    return request
        .get<unknown, unknown>(API_URLS.CHAT.SESSION_DETAIL(sessionId), {
            params: { skip, limit },
        })
        .then((response) => parseWithSchema(sessionDetailResponseSchema, response, '会话详情响应格式无效'));
};
