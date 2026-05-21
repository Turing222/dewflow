import { useState, useCallback, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../context/useAuth';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatKeys } from '../../query/keys/chat';
import { useSessionDetailQuery } from '../../query/hooks/chat';
import { getSessionDetailAPI } from '../../api/chat';
import { streamChatQuery } from '../../streams/chat-stream';
import { getDefaultKBAPI } from '../../api/knowledge';
import type { ChatMessage, ChatSession } from '../../types/chat';
import {
    createInitialTraceSteps,
    parseCitations,
    TRACE_STEP_DEFS,
} from '../../types/agent-trace';
import type {
    AgentTraceStep,
    CitationItem,
} from '../../types/agent-trace';

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

export type ChatMode = 'normal' | 'rag';

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
    traceSteps: AgentTraceStep[];
    citations: CitationItem[];
    chatMode: ChatMode;
    setChatMode: (mode: ChatMode) => void;
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
    const [traceSteps, setTraceSteps] = useState<AgentTraceStep[]>([]);
    const [citations, setCitations] = useState<CitationItem[]>([]);
    const [chatMode, setChatMode] = useState<ChatMode>('normal');

    const defaultKbIdRef = useRef<string | null>(null);

    const fetchDefaultKbId = useCallback(async (): Promise<string | null> => {
        if (defaultKbIdRef.current) return defaultKbIdRef.current;
        try {
            const kb = await getDefaultKBAPI();
            defaultKbIdRef.current = kb.id;
            return kb.id;
        } catch (err) {
            console.error('获取默认知识库失败:', err);
            return null;
        }
    }, []);

    const abortControllerRef = useRef<AbortController | null>(null);
    const retryCacheRef = useRef<Map<string, RetryCacheEntry>>(new Map());

    const detailSessionId = isSessionFromHistory ? activeSessionId : null;
    const { data: sessionDetailData, isLoading: detailLoading } =
        useSessionDetailQuery(detailSessionId);

    const isLoadingHistory = detailLoading && isSessionFromHistory;

    useEffect(() => {
        if (!isSessionFromHistory || !sessionDetailData) return;
        setMessages(sessionDetailData.messages || []);
        if (sessionDetailData.session) {
            setChatMode(sessionDetailData.session.kb_id ? 'rag' : 'normal');
        }
        const lastAssistantMsg = [...(sessionDetailData.messages || [])]
            .reverse()
            .find((m) => m.role === 'assistant');
        if (lastAssistantMsg?.search_context) {
            setCitations(parseCitations(lastAssistantMsg.search_context));
        }
    }, [isSessionFromHistory, sessionDetailData]);

    const pruneRetryCache = useCallback(() => {
        const now = Date.now();
        for (const [messageId, entry] of retryCacheRef.current.entries()) {
            if (now - entry.createdAt > RETRY_CACHE_TTL_MS) {
                retryCacheRef.current.delete(messageId);
            }
        }
    }, []);

    const advanceToStep = useCallback((targetStepId: string) => {
        const targetIdx = TRACE_STEP_DEFS.findIndex((d) => d.id === targetStepId);
        if (targetIdx === -1) {
            if (import.meta.env.DEV) {
                console.warn(`[advanceToStep] Unknown step id: "${targetStepId}"`);
            }
            return;
        }

        setTraceSteps((prev) => {
            const now = Date.now();
            return prev.map((step, idx) => {
                if (
                    idx < targetIdx &&
                    step.status !== 'done' &&
                    step.status !== 'error' &&
                    step.status !== 'skipped'
                ) {
                    return { ...step, status: 'done' as const, finishedAt: now };
                }
                if (
                    idx === targetIdx &&
                    step.status !== 'done' &&
                    step.status !== 'error'
                ) {
                    return {
                        ...step,
                        status: 'running' as const,
                        startedAt: step.startedAt ?? now,
                    };
                }
                return step;
            });
        });
    }, []);

    const sendQuery = useCallback(async (text: string, options?: SendMessageOptions) => {
        const normalizedText = text.trim();
        if (!normalizedText) return;

        // Abort any in-flight stream before starting a new one
        abortControllerRef.current?.abort();

        const newController = new AbortController();
        abortControllerRef.current = newController;

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
        setTraceSteps(createInitialTraceSteps());
        setCitations([]);

        let targetKbId: string | undefined = undefined;
        if (!activeSessionId && chatMode === 'rag') {
            const kbId = await fetchDefaultKbId();
            if (kbId) {
                targetKbId = kbId;
            } else {
                setIsStreaming(false);
                const failedMessageId = `temp-err-${Date.now()}`;
                const errorMsg: ChatMessage = {
                    id: failedMessageId,
                    session_id: '',
                    role: 'assistant',
                    content: '无法获取默认知识库，请确保系统已配置知识库后再试。',
                    status: 'failed',
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                };
                setMessages((prev) => [...prev, errorMsg]);
                return;
            }
        }

        let runtimeSessionId: string | null = activeSessionId;
        let metaReceived = false;
        let firstChunkReceived = false;
        let messageId = '';
        let accumulatedContent = '';

        streamChatQuery(
            {
                query: normalizedText,
                sessionId: activeSessionId || undefined,
                kbId: targetKbId,
                clientRequestId,
                signal: newController.signal,
            },
            {
                onMeta(event) {
                    if (newController.signal.aborted) return;
                    if (metaReceived) return;
                    metaReceived = true;
                    messageId = event.message_id || '';
                    runtimeSessionId = event.session_id || runtimeSessionId;
                    advanceToStep('retrieve-docs');
                    if (!activeSessionId) {
                        setActiveSessionId(event.session_id);
                        setActiveSession({
                            id: event.session_id,
                            title: event.session_title,
                            user_id: String(user?.id ?? ''),
                            kb_id: targetKbId || null,
                            created_at: new Date().toISOString(),
                            updated_at: new Date().toISOString(),
                            total_tokens: 0,
                        });
                        queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                    }
                },
                onChunk(event) {
                    if (newController.signal.aborted) return;
                    if (!firstChunkReceived) {
                        firstChunkReceived = true;
                        advanceToStep('generate-answer');
                    }
                    accumulatedContent += event.content;
                    setStreamingText((prev) => prev + event.content);
                },
                onDone() {
                    if (newController.signal.aborted) return;
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
                    setTraceSteps((prev) => {
                        const now = Date.now();
                        return prev.map((step) => {
                            if (
                                step.status !== 'done' &&
                                step.status !== 'error' &&
                                step.status !== 'skipped'
                            ) {
                                return {
                                    ...step,
                                    status: 'done' as const,
                                    finishedAt: now,
                                };
                            }
                            return step;
                        });
                    });
                    refreshUser().catch(() => {});
                    if (runtimeSessionId) {
                        queryClient.invalidateQueries({ queryKey: chatKeys.sessionDetail(runtimeSessionId) });
                        getSessionDetailAPI(runtimeSessionId)
                            .then((detail) => {
                                if (!newController.signal.aborted) {
                                    setActiveSession(detail.session);
                                    const lastAssistantMsg = [
                                        ...detail.messages,
                                    ]
                                        .reverse()
                                        .find((m) => m.role === 'assistant');
                                    if (lastAssistantMsg?.search_context) {
                                        setCitations(
                                            parseCitations(
                                                lastAssistantMsg.search_context,
                                            ),
                                        );
                                    }
                                }
                            })
                            .catch(() => {});
                    }
                    queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                },
                onError(err) {
                    if (newController.signal.aborted) return;
                    setIsStreaming(false);
                    setStreamingText('');
                    setTraceSteps((prev) => {
                        const now = Date.now();
                        const runningIdx = prev.findIndex(
                            (s) => s.status === 'running',
                        );
                        return prev.map((step, idx) => {
                            if (idx === runningIdx)
                                return {
                                    ...step,
                                    status: 'error' as const,
                                    finishedAt: now,
                                };
                            if (idx > runningIdx && step.status === 'idle')
                                return { ...step, status: 'skipped' as const };
                            return step;
                        });
                    });
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
    }, [activeSessionId, pruneRetryCache, refreshUser, user?.id, queryClient, chatMode, fetchDefaultKbId]);

    const retryFailedMessage = useCallback((messageId: string) => {
        if (isStreaming) return;
        pruneRetryCache();
        const entry = retryCacheRef.current.get(messageId);
        if (!entry) return;
        setMessages((prev) => prev.filter((msg) => msg.id !== messageId));
        void sendQuery(entry.query, {
            clientRequestId: undefined,
            addUserMessage: false,
            retryMessageId: messageId,
        });
    }, [sendQuery, isStreaming, pruneRetryCache]);

    const selectSession = useCallback((session: ChatSession) => {
        setIsSessionFromHistory(true);
        setActiveSessionId(session.id);
        setActiveSession(session);
        setChatMode(session.kb_id ? 'rag' : 'normal');
        retryCacheRef.current.clear();
        setMessages([]);
        setTraceSteps([]);
        setCitations([]);
    }, []);

    const startNewChat = useCallback(() => {
        abortControllerRef.current?.abort();
        retryCacheRef.current.clear();
        setIsSessionFromHistory(false);
        setActiveSessionId(null);
        setActiveSession(null);
        setChatMode('normal');
        setMessages([]);
        setStreamingText('');
        setIsStreaming(false);
        setTraceSteps([]);
        setCitations([]);
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
        traceSteps,
        citations,
        chatMode,
        setChatMode,
    };
}
