export function mockUser(overrides: Record<string, unknown> = {}) {
  return {
    id: 'user-1',
    username: 'testuser',
    email: 'test@example.com',
    role: 'user',
    is_superuser: false,
    is_active: true,
    max_tokens: 10000,
    used_tokens: 500,
    created_at: '2025-01-15T10:00:00Z',
    updated_at: '2025-01-20T12:00:00Z',
    ...overrides,
  };
}

export function mockSuperuser(overrides: Record<string, unknown> = {}) {
  return mockUser({
    id: 'admin-1',
    username: 'admin',
    email: 'admin@example.com',
    role: 'admin',
    is_superuser: true,
    is_active: true,
    ...overrides,
  });
}

export function mockAuthResponse(overrides: Record<string, unknown> = {}) {
  return {
    access_token: 'mock-jwt-token-abc123',
    token_type: 'bearer',
    ...overrides,
  };
}

export function mockSession(overrides: Record<string, unknown> = {}) {
  return {
    id: 'session-1',
    title: 'Test Session',
    user_id: 'user-1',
    total_tokens: 150,
    created_at: '2025-01-20T12:00:00Z',
    updated_at: '2025-01-20T12:30:00Z',
    ...overrides,
  };
}

export function mockSessionList(sessions: Record<string, unknown>[] = [mockSession()]) {
  return {
    items: sessions,
    total: sessions.length,
    skip: 0,
    limit: 50,
  };
}

export function metaEvent(overrides: Record<string, unknown> = {}) {
  return {
    type: 'meta',
    session_id: 'session-1',
    session_title: 'New Chat',
    message_id: 'msg-1',
    ...overrides,
  };
}

export function chunkEvent(content: string) {
  return { type: 'chunk', content };
}
