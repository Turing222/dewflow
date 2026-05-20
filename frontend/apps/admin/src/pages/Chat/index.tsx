import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Button, Dropdown, message as antdMessage, Tooltip } from 'antd';
import { LogOut, LogIn, UserPlus, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../context/useAuth';
import { resolveIdempotencyKey } from '../../lib/http/idempotency';
import { chatStreamEventSchema } from '../../schemas/chat';
import { chatKeys } from '../../query/keys/chat';
import { useSessionDetailQuery } from '../../query/hooks/chat';
import Sidebar from './Sidebar';
import MessageList from './MessageList';
import type { ChatMessage, ChatSession } from '../../types/chat';
import { sendQueryStreamAPI, getSessionDetailAPI } from '../../api/chat';
import AuthModal from '../Auth/AuthModal';
import './ChatPage.css';

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

const ChatPage: React.FC = () => {
    const { user, isAuthenticated, logout, setShowAuthModal, setAuthTab, refreshUser } = useAuth();
    const navigate = useNavigate();
    const queryClient = useQueryClient();

    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [activeSession, setActiveSession] = useState<ChatSession | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [streamingText, setStreamingText] = useState('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

    // Track whether the current session was entered by selecting history
    // vs. being created during streaming — prevents detail query from
    // overwriting optimistic/local messages mid-stream.
    const isSessionFromHistoryRef = useRef(false);

    // Only fetch session detail when selecting from history (not during/after streaming).
    // During streaming, messages are managed locally; after [DONE] we invalidate
    // but don't sync detail back to messages to avoid overwriting local state.
    const detailSessionId = isSessionFromHistoryRef.current ? activeSessionId : null;
    const { data: sessionDetailData, isLoading: detailLoading } =
        useSessionDetailQuery(detailSessionId);

    const isLoadingHistory = detailLoading && isSessionFromHistoryRef.current;

    const abortControllerRef = useRef<AbortController | null>(null);
    const retryCacheRef = useRef<Map<string, RetryCacheEntry>>(new Map());

    const pruneRetryCache = useCallback(() => {
        const now = Date.now();
        for (const [messageId, entry] of retryCacheRef.current.entries()) {
            if (now - entry.createdAt > RETRY_CACHE_TTL_MS) {
                retryCacheRef.current.delete(messageId);
            }
        }
    }, []);

    // Sync session detail data to local state — only for history selection path
    useEffect(() => {
        if (sessionDetailData && isSessionFromHistoryRef.current) {
            setActiveSession(sessionDetailData.session);
            setMessages(sessionDetailData.messages || []);
        }
    }, [sessionDetailData]);

    // 发送消息（SSE 真流式）
    const handleSend = useCallback(async (text: string, options?: SendMessageOptions) => {
        const normalizedText = text.trim();
        if (!normalizedText) {
            return;
        }

        pruneRetryCache();
        isSessionFromHistoryRef.current = false;
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

        try {
            let runtimeSessionId: string | null = activeSessionId;
            const response = await sendQueryStreamAPI(
                normalizedText,
                activeSessionId || undefined,
                undefined,
                clientRequestId,
            );
            const reader = response.body?.getReader();
            if (!reader) throw new Error('无法获取响应流');

            const decoder = new TextDecoder();
            let buffer = '';
            let accumulatedContent = '';
            let metaReceived = false;
            let messageId = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // 按 SSE 协议解析: 每条消息以 \n\n 分隔
                const events = buffer.split('\n\n');
                buffer = events.pop() || ''; // 最后一段可能不完整，留在 buffer

                for (const event of events) {
                    const line = event.trim();
                    if (!line.startsWith('data: ')) continue;

                    const data = line.slice(6); // 去掉 "data: "

                    if (data === '[DONE]') {
                        // 流结束，将累积内容作为完整消息添加
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
                        // Mark that this session is no longer from history selection
                        isSessionFromHistoryRef.current = false;
                        // Force-refresh user profile (token usage) and session detail
                        refreshUser();
                        if (runtimeSessionId) {
                            queryClient.invalidateQueries({ queryKey: chatKeys.sessionDetail(runtimeSessionId) });
                            // Fetch updated session metadata (e.g. token count) without
                            // overwriting local messages — only update activeSession.
                            getSessionDetailAPI(runtimeSessionId).then((detail) => {
                                setActiveSession(detail.session);
                            });
                        }
                        queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                        return;
                    }

                    try {
                        const parsed = chatStreamEventSchema.parse(JSON.parse(data));

                        if (parsed.type === 'meta' && !metaReceived) {
                            metaReceived = true;
                            messageId = parsed.message_id || '';
                            runtimeSessionId = parsed.session_id || runtimeSessionId;
                            if (!activeSessionId) {
                                setActiveSessionId(parsed.session_id);
                                setActiveSession({
                                    id: parsed.session_id,
                                    title: parsed.session_title,
                                    user_id: String(user?.id ?? ''),
                                    created_at: new Date().toISOString(),
                                    updated_at: new Date().toISOString(),
                                    total_tokens: 0
                                });
                                queryClient.invalidateQueries({ queryKey: chatKeys.sessions() });
                            }
                        } else if (parsed.type === 'chunk') {
                            accumulatedContent += parsed.content;
                            setStreamingText((prev) => prev + parsed.content);
                        } else if (parsed.type === 'error') {
                            throw new Error(parsed.message || 'LLM 服务错误');
                        }
                    } catch (parseErr) {
                        // JSON 解析失败的非 [DONE] 数据，忽略
                        if (data !== '[DONE]') {
                            console.warn('SSE 解析警告:', parseErr);
                        }
                    }
                }
            }

            // 如果流正常结束但没收到 [DONE]
            if (accumulatedContent) {
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
            }
            setStreamingText('');
            setIsStreaming(false);
        } catch (err: unknown) {
            setIsStreaming(false);
            setStreamingText('');
            const errorMessage = err instanceof Error ? err.message : '请求处理失败，请稍后重试';
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
        }
    }, [activeSessionId, pruneRetryCache, refreshUser, user?.id, queryClient]);

    const handleRetryFailedMessage = useCallback((messageId: string) => {
        if (isStreaming) {
            return;
        }
        pruneRetryCache();
        const entry = retryCacheRef.current.get(messageId);
        if (!entry) {
            antdMessage.warning('该重试记录已失效，请重新发送问题');
            return;
        }
        setMessages((prev) => prev.filter((msg) => msg.id !== messageId));
        void handleSend(entry.query, {
            clientRequestId: entry.clientRequestId,
            addUserMessage: false,
            retryMessageId: messageId,
        });
    }, [handleSend, isStreaming, pruneRetryCache]);

    // 选择历史会话
    const handleSelectSession = useCallback((session: ChatSession) => {
        isSessionFromHistoryRef.current = true;
        setActiveSessionId(session.id);
        retryCacheRef.current.clear();
        setMessages([]);
    }, []);

    // 新建对话
    const handleNewChat = useCallback(() => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        retryCacheRef.current.clear();
        isSessionFromHistoryRef.current = false;
        setActiveSessionId(null);
        setActiveSession(null);
        setMessages([]);
        setStreamingText('');
        setIsStreaming(false);
    }, []);

    const userMenuItems = isAuthenticated
        ? [
            { key: 'user', label: user?.username || '用户', disabled: true },
            ...(user?.is_superuser ? [{ key: 'admin', label: '后台管理', icon: <Shield size={14} /> }] : []),
            { key: 'logout', label: '退出登录', icon: <LogOut size={14} />, danger: true },
        ]
        : [
            { key: 'login', label: '登录', icon: <LogIn size={14} /> },
            { key: 'register', label: '注册', icon: <UserPlus size={14} /> },
        ];

    const handleMenuClick = ({ key }: { key: string }) => {
        if (key === 'logout') { logout(); antdMessage.success('已退出'); }
        if (key === 'login') { setAuthTab('login'); setShowAuthModal(true); }
        if (key === 'register') { setAuthTab('register'); setShowAuthModal(true); }
        if (key === 'admin') navigate('/admin');
    };

    return (
        <div className="chat-page">
            <Sidebar
                activeSessionId={activeSessionId}
                onSelectSession={handleSelectSession}
                onNewChat={handleNewChat}
                collapsed={sidebarCollapsed}
                onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
            />
            <div className="chat-main">
                <div className="chat-header">
                    <div className="chat-header-title-container">
                        <div className="chat-header-title">
                            {activeSession?.title || 'AI 助手'}
                        </div>
                        {activeSession && activeSession.total_tokens !== undefined && (
                            <div className="chat-header-tokens">
                                本次对话已消耗 {activeSession.total_tokens} tokens
                            </div>
                        )}
                    </div>

                    <Dropdown
                        menu={{ items: userMenuItems, onClick: handleMenuClick }}
                        placement="bottomRight"
                        trigger={['click']}
                    >
                        <Tooltip
                            placement="left"
                            title={isAuthenticated ? (
                                <div className="token-tooltip">
                                    <div className="token-tooltip-title">账号 Token 额度</div>
                                    <div className="token-usage-text">
                                        <span>已使用</span>
                                        <span>{user?.used_tokens || 0} / {user?.max_tokens || 0}</span>
                                    </div>
                                    <div className="token-progress-bar">
                                        <div
                                            className="token-progress-fill"
                                            style={{
                                                width: `${Math.min(100, ((user?.used_tokens || 0) / (user?.max_tokens || 1)) * 100)}%`
                                            }}
                                        />
                                    </div>
                                </div>
                            ) : null}
                        >
                            <Button
                                type="text"
                                className="user-menu-btn"
                                icon={
                                    isAuthenticated
                                        ? <div className="avatar-badge">{user?.username?.[0]?.toUpperCase()}</div>
                                        : <div className="avatar-badge guest"><LogIn size={18} /></div>
                                }
                            />
                        </Tooltip>
                    </Dropdown>
                </div>
                <MessageList
                    messages={messages}
                    streamingText={streamingText}
                    isStreaming={isStreaming}
                    isLoading={isLoadingHistory}
                    onSend={handleSend}
                    onRetryFailedMessage={handleRetryFailedMessage}
                />
            </div>
            <AuthModal />
        </div>
    );
};

export default ChatPage;
