import { useState, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../context/useAuth';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatKeys } from '../../query/keys/chat';
import { useSessionDetailQuery } from '../../query/hooks/chat';
import { getSessionDetailAPI } from '../../api/chat';
import { streamChatQuery } from '../../streams/chat-stream';
import type { ChatMessage, ChatSession } from '../../types/chat';

const RETRY_CACHE_TTL_MS = 5 * 60 * 1000;

type RetryCacheEntry = {
    clientRequestId: string;
    query: string;
    createdAt: number;
};

type SendMessageOptions = {
    clientRequestId?: string;
    addUserMessage?: boolean;
    retryMessageId?: string;
};

export type UseChatControllerReturn = {
    activeSessionId: string | null;
    activeSession: ChatSession | null;
    messages: ChatMessage[];
    streamingText: string;
    isStreaming: boolean;
    isLoadingHistory: boolean;
    sendQuery: (text: string, options?: SendMessageOptions) => Promise<void>;
    retryFailedMessage: (messageId: string) => void;
    selectSession: (session: ChatSession) => void;
    startNewChat: () => void;
};

export function useChatController(): UseChatControllerReturn {
    const { user, refreshUser } = useAuth();
    const queryClient = useQueryClient();

    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [streamingText, setStreamingText] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [isSessionFromHistory, setIsSessionFromHistory] = useState(false);

    const abortControllerRef = useRef<AbortController | null>(null);
    const retryCacheRef = useRef<Map<string, RetryCacheEntry>>(new Map());

    const detailSessionId = isSessionFromHistory ? activeSessionId : null;
    const { data: sessionDetailData, isLoading: detailLoading } =
        useSessionDetailQuery(detailSessionId);

    const isLoadingHistory = detailLoading && isSessionFromHistory;

    const pruneRetryCache = useCallback(() => {
        const now = Date.now();
        for (const [messageId, entry] of retryCacheRef.current.entries()) {
            if (now - entry.createdAt > RETRY_CACHE_TTL_MS) {
                retryCacheRef.current.delete(messageId);
            }
        }
    }, []);

    const sendQuery = useCallback(async (text: string, options?: SendMessageOptions) => {
        const normalizedText = text.trim();
        if (!normalizedText) return;

        pruneRetryCache();
        setIsSessionFromHistory(false);

        const addUserMessage = options?.addUserMessage ?? true;
        const clientRequestId = resolveIdempotencyKey(options?.clientRequestId);

        if (options?.retryMessageId) {
            retryCacheRef.current.delete(options.retryMessageId);
        }

        if (addUserMessage) {
            const userMsg: ChatMessage = {
                id: `temp-user-${Date.now()}`,
                session_id: activeSessionId || '',
                role: 'user',
                content: normalizedText,
                status: 'success',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };
            setMessages((prev) => [...prev, userMsg]);
        }
        setIsStreaming(true);
        setStreamingText('');

        let runtimeSessionId: string | null = activeSessionId;
        let metaReceived = false;
        let messageId = '';
        let accumulatedContent = '';

        const controller = streamChatQuery(
            {
                query: normalizedText,
                sessionId: activeSessionId || undefined,
                clientRequestId,
            },
            {
                onMeta(event) {
                    if (metaReceived) return;
                    metaReceived = true;
                    messageId = event.message_id || '';
                    runtimeSessionId = event.session_id || runtimeSessionId;
                    if (!activeSessionId) {
                        setActiveSessionId(event.session_id);
                        setActiveSession({
                            id: event.session_id,
                            title: event.session_title,
                            user_id: String(user?.id ?? ''),
                            created_at: new Date().toISOString(),
                            updated_at: new Date().toISOString(),
                            total_tokens: 0,
                        });
                        queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                    }
                },
                onChunk(event) {
                    accumulatedContent += event.content;
                    setStreamingText((prev) => prev + event.content);
                },
                onDone() {
                    const assistantMsg: ChatMessage = {
                        id: messageId || `msg-${Date.now()}`,
                        session_id: runtimeSessionId || '',
                        role: 'assistant',
                        content: accumulatedContent,
                        status: 'success',
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                    };
                    setMessages((prev) => [...prev, assistantMsg]);
                    setStreamingText('');
                    setIsStreaming(false);
                    setIsSessionFromHistory(false);
                    refreshUser();
                    if (runtimeSessionId) {
                        queryClient.invalidateQueries({ queryKey: chatKeys.sessionDetail(runtimeSessionId) });
                        getSessionDetailAPI(runtimeSessionId).then((detail) => {
                            setActiveSession(detail.session);
                        });
                    }
                    queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                },
                onError(err) {
                    setIsStreaming(false);
                    setStreamingText('');
                    const errorMessage = err.message || '请求处理失败，请稍后重试';
                    const failedMessageId = `temp-err-${Date.now()}`;
                    const errorMsg: ChatMessage = {
                        id: failedMessageId,
                        session_id: activeSessionId || '',
                        role: 'assistant',
                        content: errorMessage,
                        status: 'failed',
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                    };
                    setMessages((prev) => [...prev, errorMsg]);
                    retryCacheRef.current.set(failedMessageId, {
                        clientRequestId,
                        query: normalizedText,
                        createdAt: Date.now(),
                    });
                },
            },
        );

        abortControllerRef.current = controller;
    }, [activeSessionId, pruneRetryCache, refreshUser, user?.id, queryClient]);

    const retryFailedMessage = useCallback((messageId: string) => {
        if (isStreaming) return;
        pruneRetryCache();
        const entry = retryCacheRef.current.get(messageId);
        if (!entry) return;
        setMessages((prev) => prev.filter((msg) => msg.id !== messageId));
        void sendQuery(entry.query, {
            clientRequestId: entry.clientRequestId,
            addUserMessage: false,
            retryMessageId: messageId,
        });
    }, [sendQuery, isStreaming, pruneRetryCache]);

    const selectSession = useCallback((session: ChatSession) => {
        setIsSessionFromHistory(true);
        setActiveSessionId(session.id);
        setActiveSession(session);
        retryCacheRef.current.clear();
        setMessages([]);
    }, []);

    const startNewChat = useCallback(() => {
        abortControllerRef.current?.abort();
        retryCacheRef.current.clear();
        setIsSessionFromHistory(false);
        setActiveSessionId(null);
        setActiveSession(null);
        setMessages([]);
        setStreamingText('');
        setIsStreaming(false);
    }, []);

    const displayedActiveSession = isSessionFromHistory && sessionDetailData
        ? sessionDetailData.session
        : activeSession;
    const displayedMessages = isSessionFromHistory && sessionDetailData
        ? sessionDetailData.messages || []
        : messages;

    return {
        activeSessionId,
        activeSession: displayedActiveSession,
        messages: displayedMessages,
        streamingText,
        isStreaming,
        isLoadingHistory,
        sendQuery,
        retryFailedMessage,
        selectSession,
        startNewChat,
    };
}
