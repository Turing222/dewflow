import React from 'react';
import { Modal, Tabs, Form, Input, Button, message } from 'antd';
import { User, Lock, Mail } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/useAuth';
import { loginAPI } from '../../api/auth';
import { useRegisterUserMutation } from '../../query/hooks/users';
import type { LoginCredentials, UserRegistrationPayload } from '../../types/user';

type RegisterFormValues = Omit<UserRegistrationPayload, 'max_tokens'>;

const AuthModal: React.FC = () => {
    const { showAuthModal, setShowAuthModal, authTab, setAuthTab, login } = useAuth();
    const { t } = useTranslation();
    const [loginLoading, setLoginLoading] = React.useState(false);
    const registerMutation = useRegisterUserMutation();
    const registerLoading = registerMutation.isPending;
    const [loginForm] = Form.useForm<LoginCredentials>();
    const [registerForm] = Form.useForm<RegisterFormValues>();

    const handleLogin = async (values: LoginCredentials) => {
        setLoginLoading(true);
        try {
            const res = await loginAPI(values);
            await login(res.access_token);
            message.success(t('auth.login_success'));
            loginForm.resetFields();
        } catch {
            // 错误已在拦截器处理
        } finally {
            setLoginLoading(false);
        }
    };

    const handleRegister = async (values: RegisterFormValues) => {
        try {
            await registerMutation.mutateAsync({ ...values, confirm_password: values.password, max_tokens: undefined });
            message.success(t('auth.register_success'));
            registerForm.resetFields();
            setAuthTab('login');
        } catch (error) {
            console.error(error);
        }
    };

    const handleClose = () => {
        setShowAuthModal(false);
        loginForm.resetFields();
        registerForm.resetFields();
    };

    const tabItems = [
        {
            key: 'login',
            label: t('auth.login'),
            children: (
                <Form form={loginForm} name="modal-login" onFinish={handleLogin} style={{ marginTop: 16 }}>
                    <Form.Item name="username" rules={[{ required: true, message: t('auth.validation.username_required') }]}>
                        <Input
                            prefix={<User size={16} color="#999" />}
                            placeholder={t('auth.username')}
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item name="password" rules={[{ required: true, message: t('auth.validation.password_required') }]}>
                        <Input.Password
                            prefix={<Lock size={16} color="#999" />}
                            placeholder={t('auth.password')}
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                        <Button type="primary" htmlType="submit" block size="large" loading={loginLoading}>
                            {t('auth.login')}
                        </Button>
                    </Form.Item>
                </Form>
            ),
        },
        {
            key: 'register',
            label: t('auth.register'),
            children: (
                <Form form={registerForm} name="modal-register" onFinish={handleRegister} style={{ marginTop: 16 }}>
                    <Form.Item name="username" rules={[{ required: true, message: t('auth.validation.username_required') }]}>
                        <Input
                            prefix={<User size={16} color="#999" />}
                            placeholder={t('auth.username')}
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item
                        name="email"
                        rules={[
                            { required: true, message: t('auth.validation.email_required') },
                            { type: 'email', message: t('auth.validation.email_invalid') },
                        ]}
                    >
                        <Input
                            prefix={<Mail size={16} color="#999" />}
                            placeholder={t('auth.email')}
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item name="password" rules={[{ required: true, message: t('auth.validation.password_required') }]}>
                        <Input.Password
                            prefix={<Lock size={16} color="#999" />}
                            placeholder={t('auth.password')}
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item
                        name="confirm_password"
                        dependencies={['password']}
                        rules={[
                            { required: true, message: t('auth.validation.confirm_password_required') },
                            ({ getFieldValue }) => ({
                                validator(_, value) {
                                    if (!value || getFieldValue('password') === value) {
                                        return Promise.resolve();
                                    }
                                    return Promise.reject(new Error(t('auth.validation.password_mismatch')));
                                },
                            }),
                        ]}
                    >
                        <Input.Password
                            prefix={<Lock size={16} color="#999" />}
                            placeholder={t('auth.confirm_password')}
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                        <Button type="primary" htmlType="submit" block size="large" loading={registerLoading}>
                            {t('auth.register')}
                        </Button>
                    </Form.Item>
                </Form>
            ),
        },
    ];

    return (
        <Modal
            open={showAuthModal}
            onCancel={handleClose}
            footer={null}
            centered
            width={420}
            className="auth-modal"
            styles={{
                mask: {
                    backgroundColor: 'rgba(0, 0, 0, 0.45)',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                },
                body: {
                    padding: '24px',
                },
            }}
            style={{
                borderRadius: 16,
            }}
        >
            <div style={{ textAlign: 'center', marginBottom: 8 }}>
                <div style={{
                    fontSize: 28,
                    fontWeight: 700,
                    background: 'linear-gradient(135deg, var(--color-primary), var(--color-primary-gradient-end))',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                    marginBottom: 4,
                }}>
                    {t('auth.title')}
                </div>
                <div style={{ color: '#999', fontSize: 14 }}>{t('auth.subtitle')}</div>
            </div>
            <Tabs
                activeKey={authTab}
                onChange={(key) => setAuthTab(key as 'login' | 'register')}
                items={tabItems}
                centered
            />
        </Modal>
    );
};

export default AuthModal;
