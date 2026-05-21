import React from 'react';
import { Button, Spin, Tooltip } from 'antd';
import { Plus, MessageSquare, Clock, ChevronLeft, ChevronRight, Inbox, Sun, Moon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatSession } from '../../types/chat';
import { useChatSessionsQuery } from '../../query/hooks/chat';
import { useAuth } from '../../context/useAuth';
import { useThemeStore } from '../../stores/theme-store';
import { changeAppLanguage } from '../../lib/i18n';
import styles from './Sidebar.module.css';

interface SidebarProps {
    activeSessionId: string | null;
    onSelectSession: (session: ChatSession) => void;
    onNewChat: () => void;
    collapsed: boolean;
    onToggle: () => void;
}

const BRAND_PRESETS = [
    { key: 'blue', value: '#1677ff' },
    { key: 'indigo', value: '#4f46e5' },
    { key: 'purple', value: '#722ed1' },
    { key: 'teal', value: '#0d9488' },
    { key: 'orange', value: '#ea580c' },
];

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
    const { theme, brandColor, setTheme, setBrandColor } = useThemeStore();
    const { t, i18n } = useTranslation();

    const formatTime = (dateStr: string) => {
        const d = new Date(dateStr);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
        const locale = i18n.language === 'en-US' ? 'en-US' : 'zh-CN';
        if (diffDays === 0) return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
        if (diffDays === 1) return t('sidebar.time.yesterday');
        if (diffDays < 7) return t('sidebar.time.days_ago', { count: diffDays });
        return d.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
    };

    const toggleLanguage = () => {
        const targetLng = i18n.language === 'zh-CN' ? 'en-US' : 'zh-CN';
        void changeAppLanguage(targetLng);
    };

    const renderLanguageSwitch = (isCollapsed: boolean) => {
        const text = i18n.language === 'zh-CN' ? 'EN' : (isCollapsed ? '中' : '中文');
        const tooltipTitle = i18n.language === 'zh-CN' ? 'English' : '中文';
        
        const btn = (
            <Button
                type="text"
                size={isCollapsed ? undefined : "small"}
                className={isCollapsed ? styles['collapsed-action-btn'] : styles['sidebar-text-btn']}
                style={isCollapsed ? { fontSize: '11px', fontWeight: 700 } : { fontSize: '12px', fontWeight: 700 }}
                onClick={toggleLanguage}
            >
                {text}
            </Button>
        );

        if (isCollapsed) {
            return (
                <Tooltip title={tooltipTitle} placement="right">
                    {btn}
                </Tooltip>
            );
        }
        return btn;
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
                <Tooltip title={t('sidebar.new_chat')} placement="right">
                    <Button
                        className={styles['collapsed-action-btn']}
                        type="text"
                        icon={<Plus size={20} />}
                        onClick={onNewChat}
                    />
                </Tooltip>
                
                <div style={{ flex: 1 }} />

                {renderLanguageSwitch(true)}
                
                <Tooltip title={theme === 'dark' ? t('sidebar.light_mode') : t('sidebar.dark_mode')} placement="right">
                    <Button
                        className={styles['collapsed-action-btn']}
                        type="text"
                        icon={theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
                        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
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
                    {t('sidebar.new_chat')}
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
                <span>{t('sidebar.history')}</span>
            </div>

            <div className={styles['session-list']}>
                {!isAuthenticated ? (
                    <div className={`${styles['sidebar-hint']} sidebar-hint`}>
                        {t('sidebar.login_hint')}
                    </div>
                ) : loading ? (
                    <div className={styles['sidebar-loading']}><Spin size="small" /></div>
                ) : sessions.length === 0 ? (
                    <div className={`${styles['sidebar-hint']} sidebar-hint`}>
                        <Inbox size={20} className={styles['sidebar-hint-icon']} />
                        {t('sidebar.empty_hint')}
                    </div>
                ) : (
                    sessions.map((s) => (
                        <div
                            key={s.id}
                            className={`${styles['session-item']} session-item ${s.id === activeSessionId ? `${styles.active} active` : ''}`}
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

            {/* 底部主题与品牌色定制面板 */}
            <div className={styles['sidebar-footer']}>
                <div className={styles['theme-toggle-row']}>
                    <span className={styles['theme-label']}>
                        {theme === 'dark' ? t('sidebar.dark_mode') : t('sidebar.light_mode')}
                    </span>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        {renderLanguageSwitch(false)}
                        <Button
                            className={styles['sidebar-icon-btn']}
                            type="text"
                            size="small"
                            icon={theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
                            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                        />
                    </div>
                </div>
                <div className={styles['brand-colors-row']}>
                    {BRAND_PRESETS.map((color) => (
                        <button
                            key={color.value}
                            className={`${styles['color-preset-btn']} ${brandColor === color.value ? styles['color-preset-active'] : ''}`}
                            style={{ backgroundColor: color.value }}
                            title={t(`sidebar.brand_colors.${color.key}`)}
                            onClick={() => setBrandColor(color.value)}
                        />
                    ))}
                </div>
            </div>
        </div>
    );
};

export default Sidebar;
