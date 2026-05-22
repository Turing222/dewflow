import { test, expect } from '@playwright/test';

test.skip(() => !process.env.E2E_SMOKE, 'Requires running backend (set E2E_SMOKE=1)');

test.describe('Real backend: login + profile', () => {
  test('login with real credentials and fetch /users/me', async ({ page }) => {
    const username = process.env.E2E_SMOKE_USER!;
    const password = process.env.E2E_SMOKE_PASS!;

    await page.goto('/');

    await page.getByTestId('user-menu-btn').click();
    await page.getByRole('menuitem', { name: '登录' }).click();

    await page.locator('.auth-modal').getByPlaceholder('用户名').fill(username);
    await page.locator('.auth-modal').getByPlaceholder('密码').fill(password);
    await page.locator('.auth-modal').locator('button[type="submit"]').click();

    await expect(page.locator('.avatar-badge:not(.guest)')).toBeVisible();

    await expect(page.locator('.sidebar-hint, [data-testid="session-item"]').first()).toBeVisible({
      timeout: 15000,
    });
  });
});
