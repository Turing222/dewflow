import React, { useState } from 'react';
import { Button, Dropdown, message as antdMessage, Tooltip } from 'antd';
import { LogOut, LogIn, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/useAuth';
import { useChatController } from '../../features/chat/use-chat-controller';
import Sidebar from './Sidebar';
import MessageList from './MessageList';
import AgentTracePanel from './AgentTracePanel';
import AuthModal from '../Auth/AuthModal';
import styles from './ChatPage.module.css';

const ChatPage: React.FC = () => {
    const { user, isAuthenticated, logout, setShowAuthModal } = useAuth();
    const navigate = useNavigate();
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
    const [tracePanelCollapsed, setTracePanelCollapsed] = useState(false);
    const { t } = useTranslation();

    const controller = useChatController();

    const userMenuItems = isAuthenticated
        ? [
            { key: 'user', label: user?.username || 'User', disabled: true },
            ...(user?.is_superuser ? [{ key: 'admin', label: t('chat.user_menu.admin_panel'), icon: <Shield size={14} /> }] : []),
            { key: 'logout', label: t('chat.user_menu.logout'), icon: <LogOut size={14} />, danger: true },
        ]
        : [
            { key: 'login', label: t('chat.user_menu.login'), icon: <LogIn size={14} /> },
        ];

    const handleMenuClick = ({ key }: { key: string }) => {
        if (key === 'logout') {
            logout();
            antdMessage.success(t('chat.user_menu.logout'));
        }
        if (key === 'login') { setShowAuthModal(true); }
        if (key === 'admin') navigate('/admin');
    };

    return (
        <div className={`${styles['chat-page']} chat-page`}>
            <Sidebar
                activeSessionId={controller.activeSessionId}
                onSelectSession={controller.selectSession}
                onNewChat={controller.startNewChat}
                collapsed={sidebarCollapsed}
                onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
            />
            <div className={styles['chat-workspace']}>
                <div className={styles['chat-main']}>
                    <div className={styles['chat-header']}>
                        <div className={styles['chat-header-title-container']}>
                            <div className={`${styles['chat-header-title']} chat-header-title`}>
                                {controller.activeSession?.title || t('chat.default_title')}
                            </div>
                            {controller.activeSession && (
                                <div className={`${styles['chat-header-badge']} ${controller.activeSession.kb_id ? styles['rag'] : styles['normal']}`}>
                                    {controller.activeSession.kb_id ? t('chat.mode_rag', '知识库问答 RAG') : t('chat.mode_normal', '普通对话')}
                                </div>
                            )}
                            {controller.activeSession && controller.activeSession.total_tokens !== undefined && (
                                <div className={styles['chat-header-tokens']}>
                                    {t('chat.tokens_consumed', { tokens: controller.activeSession.total_tokens })}
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
                                    <div className={styles['token-tooltip']}>
                                        <div className={styles['token-tooltip-title']}>{t('chat.user_menu.token_quota')}</div>
                                        <div className={styles['token-usage-text']}>
                                            <span>{t('chat.user_menu.used')}</span>
                                            <span>{user?.used_tokens || 0} / {user?.max_tokens || 0}</span>
                                        </div>
                                        <div className={styles['token-progress-bar']}>
                                            <div
                                                className={styles['token-progress-fill']}
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
                                    className={styles['user-menu-btn']}
                                    data-testid="user-menu-btn"
                                    icon={
                                        isAuthenticated
                                            ? <div className={`${styles['avatar-badge']} avatar-badge`}>{user?.username?.[0]?.toUpperCase()}</div>
                                            : <div className={`${styles['avatar-badge']} avatar-badge ${styles['guest']} guest`}><LogIn size={18} /></div>
                                    }
                                />
                            </Tooltip>
                        </Dropdown>
                    </div>
                    <MessageList
                        messages={controller.messages}
                        streamingText={controller.streamingText}
                        isStreaming={controller.isStreaming}
                        isLoading={controller.isLoadingHistory}
                        onSend={controller.sendQuery}
                        onRetryFailedMessage={controller.retryFailedMessage}
                        chatMode={controller.chatMode}
                        setChatMode={controller.setChatMode}
                    />
                </div>
                <AgentTracePanel
                    traceSteps={controller.traceSteps}
                    citations={controller.citations}
                    collapsed={tracePanelCollapsed}
                    onToggle={() => setTracePanelCollapsed(!tracePanelCollapsed)}
                />
            </div>
            <AuthModal />
        </div>
    );
};

export default ChatPage;
