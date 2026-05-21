import React from 'react';
import { Avatar, Button, Popconfirm, Space, Table, Tag, Tooltip } from 'antd';
import type { TableColumnsType } from 'antd';
import { Edit, Trash2, Search } from 'lucide-react';
import type { User } from '../../../types/user';
import './UserTable.css';

type UserTableProps = {
    users: User[];
    loading: boolean;
    onEdit: (record: User) => void;
    onDeactivate: (record: User) => Promise<void>;
};

const UserTable: React.FC<UserTableProps> = ({ users, loading, onEdit, onDeactivate }) => {
    const columns: TableColumnsType<User> = [
        {
            title: '用户',
            dataIndex: 'username',
            key: 'username',
            render: (text: string) => (
                <div className="user-cell">
                    <Avatar className="user-cell-avatar" size={32}>
                        {text?.[0]?.toUpperCase()}
                    </Avatar>
                    <span>{text}</span>
                </div>
            ),
        },
        {
            title: '邮箱',
            dataIndex: 'email',
            key: 'email',
        },
        {
            title: '状态',
            dataIndex: 'is_active',
            key: 'is_active',
            render: (active: boolean) => (
                <Tag color={active ? 'green' : 'red'}>{active ? '活跃' : '已停用'}</Tag>
            ),
        },
        {
            title: '角色',
            dataIndex: 'is_superuser',
            key: 'is_superuser',
            render: (su: boolean) => (
                <Tag color={su ? 'purple' : 'default'}>{su ? '超级管理员' : '普通用户'}</Tag>
            ),
        },
        {
            title: 'Token 消耗',
            key: 'tokens',
            render: (_value: unknown, record: User) => {
                const used = record.used_tokens || 0;
                const max = record.max_tokens || 0;
                const percent = max > 0 ? Math.min(100, (used / max) * 100) : 0;
                let level = 'low';
                if (percent > 90) level = 'high';
                else if (percent > 70) level = 'mid';

                return (
                    <div className="token-cell">
                        <div className="token-cell-header">
                            <span>{used} / {max}</span>
                            <span>{Math.round(percent)}%</span>
                        </div>
                        <div className="token-cell-track">
                            <div
                                className={`token-cell-fill level-${level}`}
                                style={{ width: `${percent}%` }}
                            />
                        </div>
                    </div>
                );
            },
        },
        {
            title: '创建时间',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (t: string) => t ? new Date(t).toLocaleDateString('zh-CN') : '-',
        },
        {
            title: '操作',
            key: 'action',
            render: (_value: unknown, record: User) => (
                <Space>
                    <Tooltip title="编辑">
                        <Button type="text" icon={<Edit size={14} />} onClick={() => onEdit(record)} />
                    </Tooltip>
                    <Popconfirm title="确定停用该用户？" onConfirm={() => onDeactivate(record)}>
                        <Tooltip title="停用">
                            <Button type="text" danger icon={<Trash2 size={14} />} />
                        </Tooltip>
                    </Popconfirm>
                </Space>
            ),
        },
    ];

    return (
        <Table
            columns={columns}
            dataSource={users}
            rowKey="id"
            loading={loading}
            pagination={false}
            locale={{
                emptyText: (
                    <div className="user-table-empty">
                        <Search size={32} className="user-table-empty-icon" />
                        <div className="user-table-empty-text">搜索用户以查看结果</div>
                    </div>
                ),
            }}
        />
    );
};

export default UserTable;
