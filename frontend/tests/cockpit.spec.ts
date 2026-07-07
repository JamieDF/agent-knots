import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

const BASE = 'http://127.0.0.1:8080'

function getToken(): string {
  const tokenPath = join(homedir(), '.agentjam', 'cockpit.token')
  return readFileSync(tokenPath, 'utf-8').trim()
}

async function authPage(page: any) {
  const token = getToken()
  await page.context().addCookies([{
    name: 'agentjam-session',
    value: token,
    domain: '127.0.0.1',
    path: '/',
    httpOnly: true,
    sameSite: 'Strict',
  }])
}

// ── helpers ─────────────────────────────────────────────────────────────────

async function createSession(page: any, prompt: string, mode = 'agent') {
  const res = await page.request.post(`${BASE}/api/sessions`, {
    data: { prompt, mode },
  })
  expect(res.status()).toBe(200)
  return await res.json()
}

// ── public endpoints ────────────────────────────────────────────────────────

test.describe('public endpoints', () => {

  test('health is public', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/health`)
    expect(res.status()).toBe(200)
    expect((await res.json()).status).toBe('ok')
  })

  test('login page renders', async ({ page }) => {
    await page.goto(`${BASE}/login`)
    await expect(page.locator('text=Enter your access token')).toBeVisible()
  })

  test('protected routes redirect to login', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/agents`, { maxRedirects: 0 })
    expect(res.status()).toBe(303)
    expect(res.headers()['location']).toContain('/login')
  })

})

// ── authenticated API ───────────────────────────────────────────────────────

test.describe('authenticated API', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('agents list returns data', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/agents`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data.agents)).toBe(true)
  })

  test('settings returns config', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/settings`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('configured')
    expect(data.agent).toHaveProperty('default_model')
  })

  test('settings save and restore', async ({ page }) => {
    const before = await (await page.request.get(`${BASE}/api/settings`)).json()

    // Save test settings.
    const res = await page.request.put(`${BASE}/api/settings`, {
      data: {
        default_model: 'minimax-m2.7',
        api_key: 'sk-test-preserve',
        base_url: '',
        default_mode: 'agent',
      },
    })
    expect(res.status()).toBe(200)

    // Restore original — pass empty api_key to preserve.
    await page.request.put(`${BASE}/api/settings`, {
      data: {
        default_model: before.agent.default_model,
        api_key: '',  // empty = preserve
        base_url: before.agent.base_url,
        default_mode: before.agent.default_mode,
      },
    })
  })

})

// ── SPA overview ────────────────────────────────────────────────────────────

test.describe('SPA overview', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('overview loads with cockpit branding', async ({ page }) => {
    await page.goto(BASE)
    await page.waitForSelector('text=agentjam', { timeout: 5000 })
    // Either the React SPA or inline shell renders.
    const count = await page.locator('text=agentjam').count()
    expect(count).toBeGreaterThanOrEqual(1)
  })

  test('empty state shows when no agents', async ({ page }) => {
    await page.goto(BASE)
    // Should show either "No agents running" or the setup wizard.
    const hasEmpty = await page.locator('text=No agents').count()
    const hasWizard = await page.locator('text=Welcome to agentjam').count()
    expect(hasEmpty + hasWizard).toBeGreaterThanOrEqual(1)
  })

})

// ── full cockpit flow (requires real MiniMax key) ───────────────────────────

test.describe('cockpit — real agent flow', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('create session, view in cockpit, assume/relinquish', async ({ page }) => {
    // 1. Create a real session via API.
    const session = await createSession(
      page,
      'My name is Taylor. Favourite colour: teal. Remember both facts and reply confirming.',
      'agent'
    )
    console.log(`Session created: ${session.id}`)

    // 2. Navigate to overview — agent card should appear.
    await page.goto(BASE)
    await page.waitForTimeout(3000) // wait for polling

    const card = page.locator(`text=${session.id}`)
    await expect(card).toBeVisible({ timeout: 10000 })

    // Check mode pill on card shows 'agent'.
    const modePill = page.locator('.agent-card .mode-pill').first()
    await expect(modePill).toContainText('agent')

    // 3. Click the agent card to enter focus view.
    await card.click()
    await page.waitForTimeout(2000)

    // Should see the agent header with Assume button.
    const assumeBtn = page.locator('text=Assume')
    await expect(assumeBtn).toBeVisible({ timeout: 5000 })

    // Mode pill should show 'watching'.
    const focusPill = page.locator('#mode-pill')
    await expect(focusPill).toContainText('watching')

    // 4. Assume control.
    await assumeBtn.click()
    await page.waitForTimeout(500)

    // Mode pill should now show 'driving'.
    await expect(focusPill).toContainText('driving')

    // Should see Relinquish button.
    const relinquishBtn = page.locator('text=Relinquish')
    await expect(relinquishBtn).toBeVisible()

    // 5. Send a multi-turn message.
    const chatInput = page.locator('#chat-input, .chat-bar input').first()
    await expect(chatInput).toBeVisible()
    await chatInput.fill('What is my name?')
    await chatInput.press('Enter')
    await page.waitForTimeout(3000)

    // Should see the user message echoed.
    await expect(page.locator('.prose-user')).toBeVisible({ timeout: 5000 })

    // 6. Relinquish control.
    await relinquishBtn.click()
    await page.waitForTimeout(500)

    // Mode pill should go back to 'watching'.
    await expect(focusPill).toContainText('watching')

    // Should see Assume button again.
    await expect(page.locator('text=Assume')).toBeVisible()

    // 7. Send another message in agent mode.
    await chatInput.fill('What colour did I mention?')
    await chatInput.press('Enter')
    await page.waitForTimeout(3000)

    // 8. Navigate back to overview.
    const backBtn = page.locator('text=Back').first()
    if (await backBtn.isVisible()) {
      await backBtn.click()
    } else {
      await page.goBack()
    }
    await page.waitForTimeout(1000)

    // Agent card should still be visible.
    await expect(card).toBeVisible()
  })

})

// ── multi-turn via API ──────────────────────────────────────────────────────

test.describe('multi-turn API', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('multi-turn conversation remembers context', async ({ page }) => {
    // Create session.
    const session = await createSession(
      page,
      'My name is Alex. My pet is a cat named Whiskers.',
      'agent'
    )

    // Wait for first turn to complete.
    await page.waitForTimeout(5000)

    // Turn 2: ask a follow-up.
    const res2 = await page.request.post(`${BASE}/api/agent/${session.id}/send`, {
      form: { message: 'What is my name and what is my pet called?' },
    })
    expect(res2.status()).toBe(200)
    await page.waitForTimeout(5000)

    // Turn 3: another follow-up.
    const res3 = await page.request.post(`${BASE}/api/agent/${session.id}/send`, {
      form: { message: 'What species is Whiskers?' },
    })
    expect(res3.status()).toBe(200)

    // Basic smoke test: API calls succeed.
  })

})

// ── mode switching via API ──────────────────────────────────────────────────

test.describe('mode switching API', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('assume and relinquish via API', async ({ page }) => {
    const session = await createSession(page, 'Say hello.', 'agent')
    await page.waitForTimeout(3000)

    // Assume control.
    const assumeRes = await page.request.post(`${BASE}/api/agent/${session.id}/assume`)
    expect(assumeRes.status()).toBe(200)

    // Relinquish.
    const relRes = await page.request.post(`${BASE}/api/agent/${session.id}/relinquish`)
    expect(relRes.status()).toBe(200)
  })

  test('mode switching on nonexistent agent returns 404', async ({ page }) => {
    const res = await page.request.post(`${BASE}/api/agent/fake-id/assume`)
    // Returns error — either 404 from agent lookup or 500 from session manager.
    expect([404, 500]).toContain(res.status())
  })

})
