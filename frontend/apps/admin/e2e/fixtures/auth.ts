import type { Page } from '@playwright/test';
import { mockAuthResponse, mockUser } from './api-mocks';

const AUTH_STORAGE_KEY = 'auth-storage';

export async function mockLoginRoute(
  page: Page,
  userOverrides: Record<string, unknown> = {},
  authOverrides: Record<string, unknown> = {},
) {
  const user = mockUser(userOverrides);
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockAuthResponse(authOverrides)),
    });
  });
  await page.route('**/api/v1/users/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(user),
    });
  });
  return user;
}

export async function mockAdminLoginRoute(
  page: Page,
  overrides: Record<string, unknown> = {},
) {
  return mockLoginRoute(page, {
    id: 'admin-1',
    username: 'admin',
    email: 'admin@example.com',
    role: 'admin',
    is_superuser: true,
    ...overrides,
  });
}

/**
 * Seeds the Zustand auth store in localStorage so the app boots already authenticated.
 * Navigates to the app first (localStorage needs an origin), writes the token, then reloads.
 */
export async function seedAuthState(page: Page, token = 'mock-jwt-token-abc123') {
  await page.goto('/');
  await page.evaluate(({ key, val }) => {
    localStorage.setItem(key, JSON.stringify({ state: { token: val }, version: 0 }));
  }, { key: AUTH_STORAGE_KEY, val: token });
  await page.reload();
}

export async function performLogin(
  page: Page,
  username = 'testuser',
  password = 'password123',
) {
  await page.getByTestId('user-menu-btn').click();
  await page.getByRole('menuitem', { name: '登录' }).click();
  await page.locator('.auth-modal').getByPlaceholder('用户名').fill(username);
  await page.locator('.auth-modal').getByPlaceholder('密码').fill(password);
  await page.locator('.auth-modal').locator('button[type="submit"]').click();
}
