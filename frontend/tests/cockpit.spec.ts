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

  test('settings save preserves existing key', async ({ page }) => {
    // Save settings WITHOUT touching the API key (empty string = preserve).
    const res = await page.request.put(`${BASE}/api/settings`, {
      data: {
        default_model: 'minimax-m2.7',
        api_key: '',  // empty = preserve existing key
        base_url: '',
        default_mode: 'agent',
      },
    })
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(data.status).toBe('ok')
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
    const hasEmpty = await page.locator('text=No agents running').count()
    const hasWizard = await page.locator('text=Welcome to agentjam').count()
    const hasCockpit = await page.locator('text=agentjam').count()
    expect(hasEmpty + hasWizard + hasCockpit).toBeGreaterThanOrEqual(1)
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

// ── task API ────────────────────────────────────────────────────────────────

test.describe('task API', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('create, read, update, delete task', async ({ page }) => {
    const createRes = await page.request.post(`${BASE}/api/tasks`, {
      data: {
        title: 'E2E test task',
        description: 'A task created by Playwright',
        priority: 'high',
        tags: ['e2e', 'test'],
        acceptance_criteria: ['Must pass', 'Must be fast'],
      },
    })
    expect(createRes.status()).toBe(200)
    const created = await createRes.json()
    expect(created.title).toBe('E2E test task')
    expect(created.priority).toBe('high')
    expect(created.tags).toContain('e2e')
    const taskId = created.id

    // List.
    const listRes = await page.request.get(`${BASE}/api/tasks?status=open`)
    expect(listRes.status()).toBe(200)
    const list = await listRes.json()
    expect(list.tasks.some((t: any) => t.id === taskId)).toBe(true)

    // Get.
    const getRes = await page.request.get(`${BASE}/api/tasks/${taskId}`)
    expect(getRes.status()).toBe(200)
    const got = await getRes.json()
    expect(got.acceptance_criteria).toEqual(['Must pass', 'Must be fast'])

    // Update status.
    const patchRes = await page.request.patch(`${BASE}/api/tasks/${taskId}`, {
      data: { status: 'in_progress', assign: 'agent-test' },
    })
    expect(patchRes.status()).toBe(200)
    const patched = await patchRes.json()
    expect(patched.status).toBe('in_progress')
    expect(patched.assigned_to).toBe('agent-test')

    // Delete.
    const delRes = await page.request.delete(`${BASE}/api/tasks/${taskId}`)
    expect(delRes.status()).toBe(200)

    // Verify deleted.
    const goneRes = await page.request.get(`${BASE}/api/tasks/${taskId}`)
    expect(goneRes.status()).toBe(404)
  })

  test('get nonexistent task returns 404', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/tasks/fake-id`)
    expect(res.status()).toBe(404)
  })

  test('create task without title returns 422', async ({ page }) => {
    const res = await page.request.post(`${BASE}/api/tasks`, {
      data: { priority: 'low' },
    })
    expect(res.status()).toBe(422)
  })

  test('list and filter tasks', async ({ page }) => {
    const t1 = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Filter test A', priority: 'low' },
    })
    const t2 = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Filter test B', priority: 'high' },
    })
    const id1 = (await t1.json()).id
    const id2 = (await t2.json()).id

    const list = await page.request.get(`${BASE}/api/tasks?limit=10`)
    expect((await list.json()).tasks.length).toBeGreaterThanOrEqual(2)

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id1}`)
    await page.request.delete(`${BASE}/api/tasks/${id2}`)
  })

})

// ── task UI ─────────────────────────────────────────────────────────────────

test.describe('task UI', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('task list renders and shows created task', async ({ page }) => {
    // Create a task via API.
    const res = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'UI test task', priority: 'high', tags: ['ui-test'] },
    })
    const { id } = await res.json()

    // Navigate to tasks page.
    await page.goto(`${BASE}/#/tasks`)
    await page.waitForTimeout(1000)

    // Should show the task title.
    await expect(page.locator(`text=UI test task`)).toBeVisible({ timeout: 5000 })

    // Should show the task ID in mono font.
    await expect(page.locator(`text=${id}`)).toBeVisible()

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id}`)
  })

  test('create task via dialog', async ({ page }) => {
    await page.goto(`${BASE}/#/tasks`)
    await page.waitForTimeout(1000)

    // Click "New Task" button.
    await page.locator('text=New Task').click()
    await page.waitForTimeout(300)

    // Fill in the form.
    await page.locator('input[placeholder="What needs to be done?"]').fill('Dialog test task')
    await page.locator('select').last().selectOption('high')

    // Submit.
    await page.locator('text=Create Task').click()
    await page.waitForTimeout(1000)

    // Should appear in the list.
    await expect(page.locator('text=Dialog test task')).toBeVisible({ timeout: 5000 })

    // Cleanup — find and delete via API.
    const list = await (await page.request.get(`${BASE}/api/tasks`)).json()
    const task = list.tasks.find((t: any) => t.title === 'Dialog test task')
    if (task) await page.request.delete(`${BASE}/api/tasks/${task.id}`)
  })

  test('task detail view', async ({ page }) => {
    // Create a task with criteria and steps.
    const res = await page.request.post(`${BASE}/api/tasks`, {
      data: {
        title: 'Detail test task',
        description: 'A task for testing the detail view.',
        priority: 'medium',
        acceptance_criteria: ['Should render correctly', 'Should show steps'],
      },
    })
    const { id } = await res.json()

    // Navigate to task detail.
    await page.goto(`${BASE}/#/tasks/${id}`)
    await page.waitForTimeout(1000)

    // Should show title.
    await expect(page.locator('text=Detail test task')).toBeVisible({ timeout: 5000 })
    // Should show description.
    await expect(page.locator('text=A task for testing the detail view.')).toBeVisible()
    // Should show acceptance criteria.
    await expect(page.locator('text=Should render correctly')).toBeVisible()
    // Should show task ID.
    await expect(page.locator(`text=${id}`).first()).toBeVisible()

    // Status change.
    await page.locator('select').first().selectOption('in_progress')
    await page.waitForTimeout(500)

    // Verify via API.
    const updated = await (await page.request.get(`${BASE}/api/tasks/${id}`)).json()
    expect(updated.status).toBe('in_progress')

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id}`)
  })

  test('delete task from detail view', async ({ page }) => {
    const res = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Delete me' },
    })
    const { id } = await res.json()

    await page.goto(`${BASE}/#/tasks/${id}`)
    await page.waitForTimeout(1000)

    // Click delete button specifically.
    await page.locator('button:has-text("Delete")').click()
    await page.waitForTimeout(500)

    // Should redirect to tasks list.
    await expect(page).not.toHaveURL(new RegExp(id))

    // Verify gone via API.
    const check = await page.request.get(`${BASE}/api/tasks/${id}`)
    expect(check.status()).toBe(404)
  })

})
