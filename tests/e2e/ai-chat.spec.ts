/**
 * AI Chat Panel — end-to-end tests
 *
 * Covers:
 *  - Panel hidden when Ollama unavailable
 *  - Floating AI button appears when Ollama is available
 *  - Clicking button opens the panel
 *  - Panel shows "AI Assistant" header
 *  - Panel shows current stock symbol chip
 *  - Suggested prompts are visible
 *  - Typing and sending a message
 *  - Streaming response appears in chat
 *  - Close (chevron down) button hides the panel
 *  - Clear button clears the conversation
 *  - Enter key sends the message
 *  - Empty message is not sent
 *  - When Ollama unavailable (available=false) panel is null-rendered
 */
import { test, expect, type Page } from '@playwright/test';
import { mockStockAPIs, mockAIChat, MOCK_AI_MODELS } from './helpers/mocks';

// bd:deps-2026-09 iter1 (Q-7) — was `setupWithAI(page: any)`, a raw Page
// param. `test.beforeEach(setupWithAI)` (used 3x below) calls its
// handler with Playwright's own fixtures OBJECT as the first arg
// ({page, ...}), not a bare Page — current Playwright enforces
// destructuring at collection time for that call shape, so the whole
// file (12 tests) couldn't even collect. Confirmed pre-existing/
// zero-diff-from-baseline: `git diff 73fac00..HEAD -- tests/e2e/ai-chat
// .spec.ts` -> empty (Quinn's review, Finding Q-7).
async function setupWithAI({ page }: { page: Page }) {
  await page.addInitScript(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  });
  await mockStockAPIs(page);  // already mocks /api/ai/models as available
  await mockAIChat(page);
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  // Wait for models check to complete (3s backend timeout mocked instantly)
  await page.waitForTimeout(500);
}

test.describe('AI Chat Panel — availability', () => {
  test('AI button is visible when Ollama is available', async ({ page }) => {
    await setupWithAI({ page });
    // The floating AI button appears bottom-right
    const aiBtn = page.locator('button[title="AI Assistant"]');
    await expect(aiBtn).toBeVisible({ timeout: 5_000 });
  });

  test('AI button is hidden when Ollama is not available', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    // Override models to return unavailable
    await page.route('**/api/ai/models', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ models: [], available: false }),
      }),
    );
    await mockAIChat(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);

    const aiBtn = page.locator('button[title="AI Assistant"]');
    await expect(aiBtn).not.toBeVisible();
  });
});

test.describe('AI Chat Panel — open/close', () => {
  test.beforeEach(setupWithAI);

  test('clicking AI button opens the chat panel', async ({ page }) => {
    const aiBtn = page.locator('button[title="AI Assistant"]');
    await aiBtn.click();
    await expect(page.getByText('AI Assistant').first()).toBeVisible({ timeout: 3_000 });
  });

  test('chat panel shows header with AI Assistant text', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    await expect(page.getByText('AI Assistant').first()).toBeVisible();
  });

  test('clicking chevron-down closes the panel', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    await expect(page.getByText('AI Assistant').first()).toBeVisible();

    // The close button has ChevronDown icon
    const closeBtn = page.locator('button[title!="AI Assistant"]').filter({
      has: page.locator('svg'),
    }).last();
    // Click the collapse button (last button in header area)
    const headerBtns = page.locator('button').filter({ hasText: '' });
    // Use the panel header's close button
    await page.locator('[style*="bottom: 52"]').locator('button').last().click();

    // Panel should close — floating button returns
    await expect(page.locator('button[title="AI Assistant"]')).toBeVisible({ timeout: 3_000 });
  });
});

test.describe('AI Chat Panel — message sending', () => {
  test.beforeEach(setupWithAI);

  test('suggested prompts are visible on empty chat', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    // SUGGESTED_PROMPTS includes "วิเคราะห์หุ้นตัวนี้ให้หน่อย"
    await expect(page.getByText(/วิเคราะห์หุ้นตัวนี้ให้หน่อย/).first()).toBeVisible({ timeout: 3_000 });
  });

  test('clicking a suggested prompt sends it as a message', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    const prompt = page.getByText(/วิเคราะห์หุ้นตัวนี้ให้หน่อย/).first();
    await expect(prompt).toBeVisible({ timeout: 3_000 });
    await prompt.click();

    // User message should appear in chat
    await expect(page.getByText('วิเคราะห์หุ้นตัวนี้ให้หน่อย').first()).toBeVisible({ timeout: 3_000 });
  });

  test('typing a message and pressing Enter sends it', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    const input = page.locator('input[type="text"]').last();
    await input.fill('วิเคราะห์ PTT.BK ให้หน่อย');
    await input.press('Enter');

    // Message should appear in the chat thread
    await expect(page.getByText('วิเคราะห์ PTT.BK ให้หน่อย').first()).toBeVisible({ timeout: 3_000 });
  });

  test('AI response text appears after sending', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    const input = page.locator('input[type="text"]').last();
    await input.fill('สวัสดี');
    await input.press('Enter');

    // Wait for streaming response — mock returns the preset text
    await expect(page.getByText(/วิเคราะห์หุ้นนี้/).first()).toBeVisible({ timeout: 8_000 });
  });

  test('empty message is NOT sent', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    const input = page.locator('input[type="text"]').last();
    await input.fill('');
    await input.press('Enter');

    // No message should appear in the chat (still shows suggested prompts)
    await expect(page.getByText(/วิเคราะห์หุ้นตัวนี้ให้หน่อย/).first()).toBeVisible();
  });

  test('Send button triggers message send', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    const input = page.locator('input[type="text"]').last();
    await input.fill('ทดสอบ');
    // Click the Send button (has Send icon)
    const sendBtn = page.locator('button[type="submit"], button').filter({ has: page.locator('svg[data-lucide="send"], svg') }).last();
    await page.locator('[style*="bottom: 52"]').locator('button').filter({ has: page.locator('svg') }).last().click();

    await expect(page.getByText('ทดสอบ').first()).toBeVisible({ timeout: 3_000 });
  });
});

test.describe('AI Chat Panel — clear conversation', () => {
  test.beforeEach(setupWithAI);

  test('clear button resets conversation to suggested prompts', async ({ page }) => {
    await page.locator('button[title="AI Assistant"]').click();
    const input = page.locator('input[type="text"]').last();
    await input.fill('test message');
    await input.press('Enter');
    await expect(page.getByText('test message').first()).toBeVisible({ timeout: 3_000 });

    // Click the clear/refresh button (RefreshCw icon)
    const clearBtn = page.locator('button[title="ล้างการสนทนา"]');
    await clearBtn.click();

    // Should be back to empty state with suggested prompts
    await expect(page.getByText(/วิเคราะห์หุ้นตัวนี้ให้หน่อย/).first()).toBeVisible({ timeout: 3_000 });
    // Old message should be gone
    await expect(page.getByText('test message')).not.toBeVisible();
  });
});

test.describe('AI Chat Panel — Ollama error handling', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
  });

  test('503 from /ai/chat shows error message gracefully', async ({ page }) => {
    await page.route('**/api/ai/chat', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `data: ${JSON.stringify({ error: 'Ollama ยังไม่พร้อม', done: true })}\n\n`,
      }),
    );
    await page.goto('/');
    await page.waitForTimeout(500);
    await page.locator('button[title="AI Assistant"]').click();
    const input = page.locator('input[type="text"]').last();
    await input.fill('test');
    await input.press('Enter');

    await expect(page.getByText(/Ollama ยังไม่พร้อม|ยังไม่พร้อม|error/i).first()).toBeVisible({ timeout: 8_000 });
  });

  test('network error on /ai/chat shows error in chat', async ({ page }) => {
    await page.route('**/api/ai/chat', (route) => route.abort('failed'));
    await page.goto('/');
    await page.waitForTimeout(500);
    await page.locator('button[title="AI Assistant"]').click();
    const input = page.locator('input[type="text"]').last();
    await input.fill('ทดสอบ network error');
    await input.press('Enter');

    // Should show some error in chat (not crash)
    await expect(page.getByText(/เกิดข้อผิดพลาด|error|ไม่พร้อม/i).first()).toBeVisible({ timeout: 8_000 });
  });
});
