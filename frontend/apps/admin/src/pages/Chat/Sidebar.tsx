import React from 'react';
import { Button, Spin, Tooltip } from 'antd';
import { Plus, MessageSquare, Clock, ChevronLeft, ChevronRight, Inbox, LogIn } from 'lucide-react';
import type { ChatSession } from '../../types/chat';
import { useChatSessionsQuery } from '../../query/hooks/chat';
import { useAuth } from '../../context/useAuth';
import styles from './Sidebar.module.css';

interface SidebarProps {
    activeSessionId: string | null;
    onSelectSession: (session: ChatSession) => void;
    onNewChat: () => void;
    collapsed: boolean;
    onToggle: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({
    activeSessionId,
    onSelectSession,
    onNewChat,
    collapsed,
    onToggle,
}) => {
    const { isAuthenticated } = useAuth();
    const { data, isLoading: loading } = useChatSessionsQuery();
    const sessions = data?.items || [];

    const formatTime = (dateStr: string) => {
        const d = new Date(dateStr);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
        if (diffDays === 0) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        if (diffDays === 1) return '昨天';
        if (diffDays < 7) return `${diffDays}天前`;
        return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    };

    if (collapsed) {
        return (
            <div className={`${styles.sidebar} ${styles['collapsed-sidebar']}`}>
                <Button
                    className={styles['toggle-btn']}
                    type="text"
                    icon={<ChevronRight size={18} />}
                    onClick={onToggle}
                />
                <Tooltip title="新对话" placement="right">
                    <Button
                        className={styles['collapsed-action-btn']}
                        type="text"
                        icon={<Plus size={20} />}
                        onClick={onNewChat}
                    />
                </Tooltip>
            </div>
        );
    }

    return (
        <div className={styles.sidebar}>
            <div className={styles['sidebar-header']}>
                <Button
                    className={styles['new-chat-btn']}
                    type="primary"
                    icon={<Plus size={16} />}
                    onClick={onNewChat}
                    block
                >
                    新对话
                </Button>
                <Button
                    className={styles['toggle-btn']}
                    type="text"
                    icon={<ChevronLeft size={18} />}
                    onClick={onToggle}
                />
            </div>

            <div className={styles['sidebar-section-title']}>
                <Clock size={14} />
                <span>历史记录</span>
            </div>

            <div className={styles['session-list']}>
                {!isAuthenticated ? (
                    <div className={styles['sidebar-hint']}>
                        <LogIn size={20} className={styles['sidebar-hint-icon']} />
                        登录后可查看历史记录
                    </div>
                ) : loading ? (
                    <div className={styles['sidebar-loading']}><Spin size="small" /></div>
                ) : sessions.length === 0 ? (
                    <div className={styles['sidebar-hint']}>
                        <Inbox size={20} className={styles['sidebar-hint-icon']} />
                        暂无对话记录
                    </div>
                ) : (
                    sessions.map((s) => (
                        <div
                            key={s.id}
                            className={`${styles['session-item']} ${s.id === activeSessionId ? styles.active : ''}`}
                            data-testid="session-item"
                            onClick={() => onSelectSession(s)}
                        >
                            <MessageSquare size={14} className={styles['session-icon']} />
                            <div className={styles['session-info']}>
                                <div className={styles['session-title']}>{s.title}</div>
                                <div className={styles['session-time']}>{formatTime(s.updated_at)}</div>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default Sidebar;
