import React, { useState } from 'react';
import { Button, Dropdown, message as antdMessage, Tooltip } from 'antd';
import { LogOut, LogIn, UserPlus, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/useAuth';
import { useChatController } from '../../features/chat/use-chat-controller';
import Sidebar from './Sidebar';
import MessageList from './MessageList';
import AuthModal from '../Auth/AuthModal';
import './ChatPage.css';

const ChatPage: React.FC = () => {
    const { user, isAuthenticated, logout, setShowAuthModal, setAuthTab } = useAuth();
    const navigate = useNavigate();
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

    const controller = useChatController();

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
                activeSessionId={controller.activeSessionId}
                onSelectSession={controller.selectSession}
                onNewChat={controller.startNewChat}
                collapsed={sidebarCollapsed}
                onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
            />
            <div className="chat-main">
                <div className="chat-header">
                    <div className="chat-header-title-container">
                        <div className="chat-header-title">
                            {controller.activeSession?.title || 'AI 助手'}
                        </div>
                        {controller.activeSession && controller.activeSession.total_tokens !== undefined && (
                            <div className="chat-header-tokens">
                                本次对话已消耗 {controller.activeSession.total_tokens} tokens
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
                                data-testid="user-menu-btn"
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
                    messages={controller.messages}
                    streamingText={controller.streamingText}
                    isStreaming={controller.isStreaming}
                    isLoading={controller.isLoadingHistory}
                    onSend={controller.sendQuery}
                    onRetryFailedMessage={controller.retryFailedMessage}
                />
            </div>
            <AuthModal />
        </div>
    );
};

export default ChatPage;
