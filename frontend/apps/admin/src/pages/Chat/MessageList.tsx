import React, { useEffect, useState, useRef } from 'react';
import { Input, Button, Spin, Avatar, Upload, message as antdMessage } from 'antd';
import { Send, Bot, User as UserIcon, Paperclip, AlertCircle, RotateCcw, MessageSquare, Database } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatMessage } from '../../types/chat';
import type { ChatMode } from '../../features/chat/use-chat-controller';
import { uploadCSVAPI } from '../../api/upload';
import styles from './MessageList.module.css';

const { TextArea } = Input;

interface MessageListProps {
    messages: ChatMessage[];
    streamingText: string;
    isStreaming: boolean;
    isLoading: boolean;
    onSend: (text: string) => void;
    onRetryFailedMessage?: (messageId: string) => void;
    chatMode: ChatMode;
    setChatMode: (mode: ChatMode) => void;
}

const MessageList: React.FC<MessageListProps> = ({
    messages,
    streamingText,
    isStreaming,
    isLoading,
    onSend,
    onRetryFailedMessage,
    chatMode,
    setChatMode,
}) => {
    const [inputValue, setInputValue] = useState('');
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const { t } = useTranslation();

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, streamingText]);

    const handleSend = () => {
        const text = inputValue.trim();
        if (!text || isStreaming) return;
        onSend(text);
        setInputValue('');
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleUpload = async (file: File) => {
        try {
            await uploadCSVAPI(file);
            antdMessage.success(t('chat.upload_success', { name: file.name }));
        } catch {
            // error handled by interceptor
        }
        return false; // prevent default upload
    };

    const renderMessage = (msg: ChatMessage) => {
        const isUser = msg.role === 'user';
        return (
            <div key={msg.id} className={`${styles['chat-message']} chat-message ${isUser ? `${styles.user} user` : `${styles.assistant} assistant`}`}>
                <Avatar
                    className={styles['chat-avatar']}
                    style={{ backgroundColor: isUser ? 'var(--color-bg-subtle)' : 'var(--color-bg-container)', flexShrink: 0 }}
                    icon={isUser ? <UserIcon size={18} color="var(--color-primary)" /> : <Bot size={18} color="var(--color-primary-gradient-end)" />}
                />
                <div className={`${styles['chat-bubble']} ${isUser ? styles['user-bubble'] : styles['assistant-bubble']}`}>
                    {msg.status === 'failed' ? (
                        <>
                            <div className={styles['error-content']}>
                                <AlertCircle size={14} />
                                <span>{msg.content || t('chat.request_failed')}</span>
                            </div>
                            {!isUser && onRetryFailedMessage && (
                                <div className={styles['error-actions']}>
                                    <Button
                                        type="link"
                                        className={styles['retry-btn']}
                                        icon={<RotateCcw size={14} />}
                                        onClick={() => onRetryFailedMessage(msg.id)}
                                        disabled={isStreaming}
                                    >
                                        {t('chat.retry')}
                                    </Button>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className={`${styles['message-text']} message-text`}>{msg.content}</div>
                    )}
                    {msg.latency_ms && (
                        <div className={styles['message-meta']}>{msg.latency_ms}ms</div>
                    )}
                </div>
            </div>
        );
    };

    return (
        <div className={styles['message-list-container']}>
            <div className={styles['messages-scroll']}>
                {isLoading ? (
                    <div className={styles['messages-loading']}>
                        <Spin size="large" />
                        <span className={styles['loading-label']}>{t('chat.loading_history')}</span>
                    </div>
                ) : messages.length === 0 && !isStreaming ? (
                    <div className={styles['messages-empty']}>
                        <div className={styles['empty-hint']}>
                            <Bot size={40} className={styles['empty-hint-icon']} />
                            <h3>{t('chat.empty_title')}</h3>
                            <p>{t('chat.empty_desc1')}</p>
                            <p className={styles['empty-sub-prompt']}>{t('chat.empty_desc2')}</p>
                        </div>
                        <div className={styles['mode-selector-container']}>
                            <div
                                className={`${styles['mode-card']} ${chatMode === 'normal' ? styles.active : ''}`}
                                onClick={() => setChatMode('normal')}
                            >
                                <div className={styles['mode-card-icon-container']}>
                                    <MessageSquare size={20} className={styles['mode-icon']} />
                                </div>
                                <div className={styles['mode-card-content']}>
                                    <h4>{t('chat.mode_normal_title', '普通对话')}</h4>
                                    <p>{t('chat.mode_normal_desc', '纯粹的大语言模型对话，速度极快，不绑定任何特定文档。')}</p>
                                </div>
                            </div>

                            <div
                                className={`${styles['mode-card']} ${chatMode === 'rag' ? styles.active : ''}`}
                                onClick={() => setChatMode('rag')}
                            >
                                <div className={styles['mode-card-icon-container']}>
                                    <Database size={20} className={styles['mode-icon']} />
                                </div>
                                <div className={styles['mode-card-content']}>
                                    <h4>{t('chat.mode_rag_title', '知识库问答 RAG')}</h4>
                                    <p>{t('chat.mode_rag_desc', '关联您的默认个人知识库文档，回答更有针对性与专业性。')}</p>
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <>
                        {messages.map(renderMessage)}
                        {isStreaming && streamingText && (
                            <div className={`${styles['chat-message']} chat-message ${styles.assistant} assistant`}>
                                <Avatar
                                    className={styles['chat-avatar']}
                                    style={{ backgroundColor: 'var(--color-bg-container)', flexShrink: 0 }}
                                    icon={<Bot size={18} color="var(--color-primary-gradient-end)" />}
                                />
                                <div className={`${styles['chat-bubble']} ${styles['assistant-bubble']}`}>
                                    <div className={`${styles['message-text']} message-text`}>
                                        {streamingText}
                                        <span className={styles['cursor-blink']}>|</span>
                                    </div>
                                </div>
                            </div>
                        )}
                        {isStreaming && !streamingText && (
                            <div className={`${styles['chat-message']} chat-message ${styles.assistant} assistant`}>
                                <Avatar
                                    className={styles['chat-avatar']}
                                    style={{ backgroundColor: 'var(--color-bg-container)', flexShrink: 0 }}
                                    icon={<Bot size={18} color="var(--color-primary-gradient-end)" />}
                                />
                                <div className={`${styles['chat-bubble']} ${styles['assistant-bubble']}`}>
                                    <div className={styles['thinking-dots']}>
                                        <span></span><span></span><span></span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                )}
                <div ref={messagesEndRef} />
            </div>

            <div className={styles['input-area']}>
                <div className={`${styles['input-row']} ${isStreaming ? styles['input-disabled'] : ''}`}>
                    <Upload
                        showUploadList={false}
                        beforeUpload={handleUpload}
                        accept=".csv,.xlsx,.xls"
                        disabled={isStreaming}
                    >
                        <Button
                            className={styles['upload-btn']}
                            icon={<Paperclip size={18} />}
                            type="text"
                            title={t('chat.upload_file')}
                            disabled={isStreaming}
                        />
                    </Upload>
                    <TextArea
                        className={styles['chat-input']}
                        data-testid="chat-input"
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={t('chat.input_tip')}
                        autoSize={{ minRows: 1, maxRows: 4 }}
                        disabled={isStreaming}
                    />
                    <Button
                        className={styles['send-btn']}
                        type="primary"
                        data-testid="send-btn"
                        icon={<Send size={18} />}
                        onClick={handleSend}
                        disabled={!inputValue.trim() || isStreaming}
                        loading={isStreaming}
                    />
                </div>
            </div>
        </div>
    );
};

export default MessageList;
