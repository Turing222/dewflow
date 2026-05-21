import React from 'react';
import { Button, Layout } from 'antd';
import { ArrowLeft, Shield, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/useAuth';
import { useAdminUsers } from '../../features/admin/users/use-admin-users';
import UserSearchBar from '../../features/admin/users/UserSearchBar';
import UserTable from '../../features/admin/users/UserTable';
import CreateUserModal from '../../features/admin/users/CreateUserModal';
import EditUserModal from '../../features/admin/users/EditUserModal';
import './AdminDashboard.css';

const { Header, Content } = Layout;

const AdminDashboard: React.FC = () => {
    const { user } = useAuth();
    const navigate = useNavigate();
    const admin = useAdminUsers();

    return (
        <Layout className="admin-layout">
            <Header className="admin-header">
                <div className="header-left">
                    <Button
                        type="text"
                        icon={<ArrowLeft size={18} />}
                        onClick={() => navigate('/')}
                        className="back-btn"
                    />
                    <Shield size={22} color="#1677ff" />
                    <span className="header-title">管理后台</span>
                </div>
                <div className="header-right">
                    <span className="header-user">{user?.username}</span>
                </div>
            </Header>
            <Content className="admin-content">
                <div className="content-card">
                    <div className="card-header">
                        <h2><Users size={20} /> 用户管理</h2>
                        <UserSearchBar
                            searchValue={admin.searchValue}
                            onSearchValueChange={admin.setSearchValue}
                            onSearch={admin.handleSearch}
                            onCreateClick={() => admin.setCreateModalOpen(true)}
                            onUpload={admin.handleUpload}
                        />
                    </div>
                    <UserTable
                        users={admin.users}
                        loading={admin.loading}
                        onEdit={admin.handleEdit}
                        onDeactivate={admin.handleDeactivate}
                    />
                </div>
            </Content>

            <CreateUserModal
                open={admin.createModalOpen}
                onSubmit={admin.handleCreate}
                onCancel={admin.closeCreateModal}
            />

            <EditUserModal
                open={admin.editModalOpen}
                editingUser={admin.editingUser}
                onSubmit={admin.handleUpdate}
                onCancel={admin.closeEditModal}
            />
        </Layout>
    );
};

export default AdminDashboard;
