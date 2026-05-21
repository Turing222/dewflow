import { test, expect } from '@playwright/test';

test.skip(() => !process.env.E2E_SMOKE, 'Requires running backend (set E2E_SMOKE=1)');

test.describe('Real backend: minimal chat chain', () => {
  test('send a short question, receive a streamed response', async ({ page }) => {
    const username = process.env.E2E_SMOKE_USER!;
    const password = process.env.E2E_SMOKE_PASS!;

    await page.goto('/');

    await page.getByTestId('user-menu-btn').click();
    await page.getByRole('menuitem', { name: '登录' }).click();
    await page.locator('.auth-modal').getByPlaceholder('用户名').fill(username);
    await page.locator('.auth-modal').getByPlaceholder('密码').fill(password);
    await page.locator('.auth-modal').locator('button[type="submit"]').click();
    await expect(page.locator('.avatar-badge:not(.guest)')).toBeVisible();

    await page.getByTestId('chat-input').fill('你好');
    await page.getByTestId('send-btn').click();

    await expect(
      page.locator('.thinking-dots').or(page.locator('.cursor-blink')),
    ).toBeVisible({ timeout: 15000 });

    await expect(page.locator('.chat-message.assistant .message-text')).toBeVisible({
      timeout: 30000,
    });

    const responseText = await page.locator('.chat-message.assistant .message-text').textContent();
    expect(responseText!.length).toBeGreaterThan(0);
  });
});
