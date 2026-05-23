import { useState, useCallback, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { message } from 'antd';
import { useAuth } from '../../context/useAuth';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatKeys } from '../../query/keys/chat';
import { useSessionDetailQuery } from '../../query/hooks/chat';
import { getSessionDetailAPI } from '../../api/chat';
import { streamChatQuery } from '../../streams/chat-stream';
import { getDefaultKBAPI, uploadKBFileAPI, getKBTaskStatusAPI } from '../../api/knowledge';
import type { ChatMessage, ChatSession } from '../../types/chat';
import {
    applyTraceMetricsToSteps,
    createInitialTraceSteps,
    createInitialIngestionSteps,
    parseCitations,
    parseChatMessageMetrics,
    parseRagMetrics,
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
    activeTraceTab: 'rag' | 'ingestion';
    setActiveTraceTab: (tab: 'rag' | 'ingestion') => void;
    ingestionSteps: AgentTraceStep[];
    uploadKBFile: (file: File) => Promise<void>;
    isIngesting: boolean;
    isIngestionSidebarOpen: boolean;
    setIsIngestionSidebarOpen: (open: boolean) => void;
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
    const [activeTraceTab, setActiveTraceTab] = useState<'rag' | 'ingestion'>('rag');
    const [ingestionSteps, setIngestionSteps] = useState<AgentTraceStep[]>(createInitialIngestionSteps());
    const [isIngesting, setIsIngesting] = useState(false);
    const [isIngestionSidebarOpen, setIsIngestionSidebarOpen] = useState(false);

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
    const pollIntervalRef = useRef<any>(null);
    const tabSwitchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        return () => {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            if (tabSwitchTimerRef.current) clearTimeout(tabSwitchTimerRef.current);
        };
    }, []);

    const detailSessionId = isSessionFromHistory ? activeSessionId : null;
    const { data: sessionDetailData, isLoading: detailLoading } =
        useSessionDetailQuery(detailSessionId);

    const isLoadingHistory = detailLoading && isSessionFromHistory;

    const displayedActiveSession = isSessionFromHistory && sessionDetailData
        ? sessionDetailData.session
        : activeSession;
    const displayedMessages = isSessionFromHistory && sessionDetailData
        ? sessionDetailData.messages || []
        : messages;

    useEffect(() => {
        if (!isSessionFromHistory || !sessionDetailData) return;
        // Historical session selection hydrates local chat state from query data.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setMessages(sessionDetailData.messages || []);
        if (sessionDetailData.session) {
            setChatMode(sessionDetailData.session.kb_id ? 'rag' : 'normal');
        }
        const lastAssistantMsg = [...(sessionDetailData.messages || [])]
            .reverse()
            .find((m) => m.role === 'assistant');
        if (lastAssistantMsg?.search_context) {
            setCitations(parseCitations(lastAssistantMsg.search_context));
        } else {
            setCitations([]);
        }
        setTraceSteps((prev) => applyTraceMetricsToSteps(
            prev,
            parseChatMessageMetrics(lastAssistantMsg?.message_metadata),
            parseRagMetrics(lastAssistantMsg?.search_context),
        ));
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
                retryCacheRef.current.set(failedMessageId, {
                    clientRequestId,
                    query: normalizedText,
                    createdAt: Date.now(),
                });
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
                                    } else {
                                        setCitations([]);
                                    }
                                    setTraceSteps((prev) => applyTraceMetricsToSteps(
                                        prev,
                                        parseChatMessageMetrics(lastAssistantMsg?.message_metadata),
                                        parseRagMetrics(lastAssistantMsg?.search_context),
                                    ));
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
    }, [activeSessionId, pruneRetryCache, refreshUser, user?.id, queryClient, chatMode, fetchDefaultKbId, advanceToStep]);

    const retryFailedMessage = useCallback((messageId: string) => {
        console.log('[retry] 点击重试, messageId=', messageId, 'isStreaming=', isStreaming);
        console.log('[retry] 当前缓存 keys=', [...retryCacheRef.current.keys()]);
        if (isStreaming) {
            console.log('[retry] 放弃：正在流式中');
            return;
        }
        pruneRetryCache();

        let queryText = '';
        let clientRequestId: string | undefined = undefined;

        const entry = retryCacheRef.current.get(messageId);
        if (entry) {
            queryText = entry.query;
            clientRequestId = entry.clientRequestId;
            console.log('[retry] 命中缓存，queryText=', queryText);
        } else {
            console.log('[retry] 缓存未命中，尝试从消息历史查找');
            const msgIndex = displayedMessages.findIndex((msg) => msg.id === messageId);
            if (msgIndex > 0) {
                const prevMsg = displayedMessages[msgIndex - 1];
                if (prevMsg && prevMsg.role === 'user') {
                    queryText = prevMsg.content;
                    console.log('[retry] 从消息历史中找到前一条用户提问作为重试内容:', queryText);
                }
            }
        }

        if (!queryText) {
            console.log('[retry] 放弃：缓存里找不到该 messageId，且在消息列表中找不到对应的用户提问');
            return;
        }

        if (entry) {
            retryCacheRef.current.delete(messageId);
        }

        setMessages(() => {
            const baseMessages = isSessionFromHistory && sessionDetailData
                ? sessionDetailData.messages || []
                : messages;
            return baseMessages.filter((msg) => msg.id !== messageId);
        });

        void sendQuery(queryText, {
            clientRequestId,
            addUserMessage: false,
            retryMessageId: messageId,
        });
    }, [sendQuery, isStreaming, pruneRetryCache, displayedMessages, isSessionFromHistory, sessionDetailData, messages]);

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



    const uploadKBFile = useCallback(async (file: File) => {
        const suffix = file.name.split('.').pop()?.toLowerCase();
        if (suffix !== 'md' && suffix !== 'markdown') {
            message.error('仅支持上传 .md 或 .markdown 格式的文件！');
            return;
        }
        if (file.size > 20 * 1024 * 1024) {
            message.error('文件大小不能超过 20MB！');
            return;
        }

        if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
        }

        setIsIngesting(true);
        setActiveTraceTab('ingestion');
        setIsIngestionSidebarOpen(true);

        const now = Date.now();
        setIngestionSteps([
            { id: 'file-upload', status: 'running', description: `正在上传: ${file.name}`, startedAt: now, finishedAt: null },
            { id: 'content-audit', status: 'idle', description: '等待文件解析提取', startedAt: null, finishedAt: null },
            { id: 'semantic-chunk', status: 'idle', description: '等待分块处理', startedAt: null, finishedAt: null },
            { id: 'vector-index', status: 'idle', description: '等待构建向量索引', startedAt: null, finishedAt: null },
            { id: 'ingestion-complete', status: 'idle', description: '等待入库完成', startedAt: null, finishedAt: null },
        ]);

        try {
            const uploadRes = await uploadKBFileAPI(file);
            const uploadFinishedAt = Date.now();

            setIngestionSteps((prev) =>
                prev.map((step) =>
                    step.id === 'file-upload'
                        ? {
                              ...step,
                              status: 'done',
                              finishedAt: uploadFinishedAt,
                              durationMs: uploadFinishedAt - now,
                              description: `已成功上传: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`,
                          }
                        : step
                )
            );

            if (uploadRes.deduplicated || uploadRes.task_status === 'completed') {
                const completeTime = Date.now();
                setIngestionSteps((prev) =>
                    prev.map((step) => {
                        if (step.id === 'file-upload') return step;
                        return {
                            ...step,
                            status: 'done',
                            startedAt: step.startedAt ?? uploadFinishedAt,
                            finishedAt: completeTime,
                            description: step.id === 'ingestion-complete' 
                                ? '知识库文档秒传匹配成功，入库完成！' 
                                : '已完成(秒传缓存)',
                        };
                    })
                );
                setIsIngesting(false);
                message.success('文件入库成功 (秒传匹配)！');

                tabSwitchTimerRef.current = setTimeout(() => {
                    setActiveTraceTab('rag');
                }, 4000);
                return;
            }

            const taskId = uploadRes.task_id;
            let pollAttempts = 0;
            const maxPollAttempts = 120;

            setIngestionSteps((prev) =>
                prev.map((step) =>
                    step.id === 'content-audit'
                        ? { ...step, status: 'running', startedAt: Date.now() }
                        : step
                )
            );

            pollIntervalRef.current = setInterval(async () => {
                if (!pollIntervalRef.current) return;
                pollAttempts++;
                if (pollAttempts > maxPollAttempts) {
                    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
                    setIsIngesting(false);
                    setIngestionSteps((prev) =>
                        prev.map((step) =>
                            step.status === 'running' || step.status === 'idle'
                                ? { ...step, status: 'error', finishedAt: Date.now(), description: '入库任务查询超时' }
                                : step
                        )
                    );
                    message.error('文件入库超时，请前往后台查看任务状态。');
                    return;
                }

                try {
                    const taskRes = await getKBTaskStatusAPI(taskId);
                    const currentStatus = taskRes.status.toLowerCase();
                    const progress = taskRes.progress;

                    setIngestionSteps((prev) => {
                        const tickTime = Date.now();
                        return prev.map((step) => {
                            if (step.id === 'file-upload') return step;

                            if (currentStatus === 'completed') {
                                return {
                                    ...step,
                                    status: 'done',
                                    startedAt: step.startedAt ?? tickTime,
                                    finishedAt: step.finishedAt ?? tickTime,
                                    description: step.id === 'ingestion-complete' ? '文档已成功解析、切片并建索入库！' : step.description || '已完成',
                                    metricDetails: step.id === 'vector-index' ? { '入库进度': '100%' } : step.metricDetails,
                                };
                            }

                            if (currentStatus === 'failed') {
                                if (step.id === 'ingestion-complete') {
                                    return {
                                        ...step,
                                        status: 'error',
                                        finishedAt: tickTime,
                                        description: taskRes.error_log || '知识文件入库失败，详细信息见错误日志',
                                    };
                                }
                                if (step.status === 'running' || step.status === 'idle') {
                                    return {
                                        ...step,
                                        status: 'error',
                                        finishedAt: tickTime,
                                        description: '处理中断',
                                    };
                                }
                                return step;
                            }

                            const fileStatusFromPayload = (taskRes.payload?.file_status as string | undefined)?.toUpperCase();

                            if (step.id === 'content-audit') {
                                if (fileStatusFromPayload === 'PARSING' || progress < 30) {
                                    return {
                                        ...step,
                                        status: 'running',
                                        startedAt: step.startedAt ?? tickTime,
                                        description: '正在解析提取文档文本内容...',
                                    };
                                } else {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: step.finishedAt ?? tickTime,
                                        description: '文档文本内容已成功提取',
                                    };
                                }
                            }

                            if (step.id === 'semantic-chunk') {
                                if (fileStatusFromPayload === 'CHUNKING' || (progress >= 30 && progress < 60)) {
                                    return {
                                        ...step,
                                        status: 'running',
                                        startedAt: step.startedAt ?? tickTime,
                                        description: '正在进行智能文本切片与安全扫描...',
                                    };
                                } else if (progress >= 60 || fileStatusFromPayload === 'READY') {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: step.finishedAt ?? tickTime,
                                        description: '文本切片及分块安全扫描已完成',
                                    };
                                } else {
                                    return step;
                                }
                            }

                            if (step.id === 'vector-index') {
                                if (progress >= 60 && progress < 100) {
                                    return {
                                        ...step,
                                        status: 'running',
                                        startedAt: step.startedAt ?? tickTime,
                                        description: '正在计算向量嵌入并写入向量数据库...',
                                        metricDetails: { '入库进度': `${progress}%` },
                                    };
                                } else if (progress >= 100 || fileStatusFromPayload === 'READY') {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: step.finishedAt ?? tickTime,
                                        description: '向量索引构建完成',
                                        metricDetails: { '入库进度': '100%' },
                                    };
                                } else {
                                    return step;
                                }
                            }

                            if (step.id === 'ingestion-complete') {
                                if (progress >= 100 || fileStatusFromPayload === 'READY') {
                                    return {
                                        ...step,
                                        status: 'done',
                                        startedAt: step.startedAt ?? tickTime,
                                        finishedAt: tickTime,
                                        description: '文档入库全生命周期执行完成！',
                                    };
                                } else {
                                    return step;
                                }
                            }

                            return step;
                        });
                    });

                    if (currentStatus === 'completed') {
                        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
                        setIsIngesting(false);
                        message.success('文件入库成功！');
                        tabSwitchTimerRef.current = setTimeout(() => {
                            setActiveTraceTab('rag');
                        }, 4000);
                    } else if (currentStatus === 'failed') {
                        if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
                        setIsIngesting(false);
                        message.error(taskRes.error_log || '文件入库失败，请查看右侧诊断！');
                    }

                } catch (err) {
                    console.error('轮询入库任务状态失败:', err);
                }
            }, 1000);

        } catch (err: unknown) {
            console.error('上传文件失败:', err);
            const errMsg = err instanceof Error ? err.message : '文件上传失败';
            setIsIngesting(false);
            setIngestionSteps((prev) =>
                prev.map((step) => {
                    if (step.id === 'file-upload') {
                        return { ...step, status: 'error', finishedAt: Date.now(), description: `上传失败: ${errMsg}` };
                    }
                    if (step.id === 'ingestion-complete') {
                        return { ...step, status: 'error', finishedAt: Date.now(), description: '处理中断' };
                    }
                    return step;
                })
            );
            message.error(errMsg);
        }
    }, []);

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
        activeTraceTab,
        setActiveTraceTab,
        ingestionSteps,
        uploadKBFile,
        isIngesting,
        isIngestionSidebarOpen,
        setIsIngestionSidebarOpen,
    };
}
