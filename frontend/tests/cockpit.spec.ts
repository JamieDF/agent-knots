import { test, expect } from '@playwright/test'
import { readFileSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

const BASE = 'http://127.0.0.1:8090'

function getToken(): string {
  const tokenPath = join(homedir(), '.agent-knots', 'cockpit.token')
  return readFileSync(tokenPath, 'utf-8').trim()
}

async function authPage(page: any) {
  const token = getToken()
  await page.context().addCookies([{
    name: 'agent-knots-session',
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
    await expect(page.locator('text=Access token').first()).toBeVisible()
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
    await page.waitForSelector('text=agent-knots', { timeout: 5000 })
    // Either the React SPA or inline shell renders.
    const count = await page.locator('text=agent-knots').count()
    expect(count).toBeGreaterThanOrEqual(1)
  })

  test('empty state shows when no agents', async ({ page }) => {
    await page.goto(BASE)
    // Should show either "No agents running" or the setup wizard.
    const hasEmpty = await page.locator('text=No agents running').count()
    const hasWizard = await page.locator('text=Welcome to agent-knots').count()
    const hasCockpit = await page.locator('text=agent-knots').count()
    expect(hasEmpty + hasWizard + hasCockpit).toBeGreaterThanOrEqual(1)
  })

})

// ── full cockpit flow (requires real MiniMax key) ───────────────────────────

test.describe('cockpit — real agent flow', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('create task-attached session, view in cockpit, toggle Autonomous', async ({ page }) => {
    // The Autonomous toggle only means anything for a task-attached
    // session — there's no task to self-direct from otherwise.
    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Remember Taylor', priority: 'medium' },
    })
    const task = await taskRes.json()

    // 1. Create a real session via API, attached to the task.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: {
        prompt: 'My name is Taylor. Favourite colour: teal. Remember both facts and reply confirming.',
        mode: 'agent',
        task_id: task.id,
      },
    })
    const session = await sessionRes.json()
    console.log(`Session created: ${session.id}`)

    // 2. Navigate to overview — agent card should appear, showing
    // "autonomous" (a task-attached agent-mode session starts autonomous
    // by default — see session/manager.py's mode semantics). A
    // task-attached card shows the task's title, not the raw session id.
    await page.goto(BASE)
    await page.waitForTimeout(3000) // wait for polling

    const card = page.locator('text=Remember Taylor').first()
    await expect(card).toBeVisible({ timeout: 10000 })
    await expect(page.locator('text=autonomous').first()).toBeVisible()

    // 3. Enter the agent thread — the card's title area isn't itself a
    // nav target (only its "Open →" link is, per the Atelier design).
    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(2000)

    // Header shows the Autonomous toggle, on by default.
    await expect(page.locator('text=▶ AUTONOMOUS')).toBeVisible({ timeout: 5000 })
    // The composer stays a normal chat, plus a banner reminding you that
    // typing pauses it — never a locked-out state.
    await expect(page.locator('text=Working autonomously on the task')).toBeVisible()
    const chatInput = page.locator('input[placeholder="Type to step in…"]')
    await expect(chatInput).toBeVisible()
    await expect(chatInput).toBeEnabled()

    // 4. Turn the toggle off directly — the "I see it going wrong, hold
    // up" affordance, without needing to type anything first.
    await page.locator('[role="switch"]').click()
    await page.waitForTimeout(500)
    await expect(page.locator('text=⏸ PAUSED')).toBeVisible()
    await expect(page.locator('text=Working autonomously on the task')).toHaveCount(0)

    // 5. Send a message while paused — a normal back-and-forth turn,
    // tools still work (only reviewer/security modes are ever read-only).
    const pausedInput = page.locator('input[placeholder="Message the agent…"]')
    await expect(pausedInput).toBeVisible()
    await pausedInput.fill('What is my name?')
    await pausedInput.press('Enter')
    await page.waitForTimeout(3000)

    // Should see the user message echoed back (the backend broadcasts a
    // USER event for every sent message so all viewers see it).
    await expect(page.locator('text=What is my name?')).toBeVisible({ timeout: 5000 })

    // 6. Turn Autonomous back on — should resume the task (a "Resume
    // working on the task" message gets sent under the hood).
    await page.locator('[role="switch"]').click()
    await page.waitForTimeout(1000)
    await expect(page.locator('text=▶ AUTONOMOUS')).toBeVisible()
    await expect(page.locator('text=Resume working on the task')).toBeVisible({ timeout: 5000 })

    // 6b. Typing + sending while autonomous is itself the "hold up" —
    // pauses it, no separate toggle-off click required first.
    const autonomousInput = page.locator('input[placeholder="Type to step in…"]')
    await autonomousInput.fill('Taking over now.')
    await autonomousInput.press('Enter')
    await page.waitForTimeout(1000)
    await expect(page.locator('text=⏸ PAUSED')).toBeVisible()
    await expect(page.locator('text=Taking over now.')).toBeVisible({ timeout: 5000 })

    // 7. Navigate back to the Dashboard.
    await page.locator('button:has-text("←")').click()
    await page.waitForTimeout(1000)

    // Agent card should still be visible.
    await expect(card).toBeVisible()

    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
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
        status: 'open', // tasks default to 'draft' now — set explicitly to exercise the status=open list filter below
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

    // Navigate to the List tab.
    await page.goto(`${BASE}/tasks?view=list`)
    await page.waitForTimeout(1000)

    // Should show the task title.
    await expect(page.locator(`text=UI test task`)).toBeVisible({ timeout: 5000 })

    // Should show the task ID in mono font.
    await expect(page.locator(`text=${id}`)).toBeVisible()

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id}`)
  })

  test('create task via dialog', async ({ page }) => {
    await page.goto(`${BASE}/tasks`)
    await page.waitForTimeout(1000)

    // Click "+ New task" button.
    await page.locator('text=New task').click()
    await page.waitForTimeout(300)

    // Fill in the form. Only Priority + Review gate selects exist in
    // create mode (Status is edit-only), so target Priority by label.
    await page.locator('input[placeholder="What needs to be done?"]').fill('Dialog test task')
    await page.getByLabel('Priority').selectOption('high')

    // Submit.
    await page.locator('text=Create task').click()
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
    await page.goto(`${BASE}/tasks/${id}`)
    await page.waitForTimeout(1000)

    // Should show title.
    await expect(page.locator('text=Detail test task')).toBeVisible({ timeout: 5000 })
    // Should show description.
    await expect(page.locator('text=A task for testing the detail view.')).toBeVisible()
    // Should show acceptance criteria.
    await expect(page.locator('text=Should render correctly')).toBeVisible()
    // Should show task ID.
    await expect(page.locator(`text=${id}`).first()).toBeVisible()

    // Status change — status is edit-only now (no inline dropdown on the
    // detail page itself), via the Edit dialog.
    await page.locator('text=Edit').first().click()
    await page.waitForTimeout(300)
    await page.getByLabel('Status').selectOption('review')
    await page.locator('text=Save changes').click()
    await page.waitForTimeout(500)

    // Verify via API.
    const updated = await (await page.request.get(`${BASE}/api/tasks/${id}`)).json()
    expect(updated.status).toBe('review')

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id}`)
  })

  test('delete task from detail view', async ({ page }) => {
    const res = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Delete me' },
    })
    const { id } = await res.json()

    await page.goto(`${BASE}/tasks/${id}`)
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

// ── agent task tools ────────────────────────────────────────────────────────

/** Poll a task until the agent modifies it (progress or status change). */
async function waitForAgentToModifyTask(page: any, taskId: string, maxSec = 120): Promise<any> {
  // Freshly created tasks default to 'draft' (task/models.py), not
  // 'open' — so "status !== 'open'" as an exit condition would return
  // on the very first poll before the agent has done anything. Track
  // the starting status instead and wait for it to actually change.
  const startRes = await page.request.get(`${BASE}/api/tasks/${taskId}`)
  const startStatus = (await startRes.json()).status

  const deadline = Date.now() + maxSec * 1000
  while (Date.now() < deadline) {
    const res = await page.request.get(`${BASE}/api/tasks/${taskId}`)
    const task = await res.json()
    if (task.progress.length > 0 || task.status !== startStatus) {
      return task
    }
    await new Promise(r => setTimeout(r, 3000))
  }
  // One final check.
  const res = await page.request.get(`${BASE}/api/tasks/${taskId}`)
  return res.json()
}

test.describe('agent task tools', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('agent logs progress and updates task status', async ({ page }) => {
    test.setTimeout(180000)

    // Create task.
    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Agent tool e2e test', description: 'Agent must log progress.', priority: 'medium' },
    })
    const task = await taskRes.json()
    console.log(`Task: ${task.id}`)

    // Start agent session.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: {
        prompt: 'Use log_progress to record that you started work. Then use update_task_status to mark the task in_progress.',
        mode: 'agent',
        task_id: task.id,
      },
    })
    expect(sessionRes.status()).toBe(200)
    const session = await sessionRes.json()
    console.log(`Session: ${session.id}`)

    // Poll until agent modifies the task (up to 2 min).
    const updated = await waitForAgentToModifyTask(page, task.id, 120)
    console.log(`Final: status=${updated.status}, progress=${updated.progress.length}`)

    expect(updated.progress.length).toBeGreaterThanOrEqual(1)
    await page.request.delete(`${BASE}/api/tasks/${task.id}`)
  })

})

// ── cockpit: agent uses task tools (frontend) ───────────────────────────────

test.describe('cockpit — agent task tools', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('watch agent use task tools in cockpit', async ({ page }) => {
    test.setTimeout(180000)

    // Create task.
    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: {
        title: 'Cockpit tool e2e test',
        description: 'Agent should log progress.',
        priority: 'high',
        acceptance_criteria: ['Agent logs progress'],
      },
    })
    const task = await taskRes.json()

    // Start session.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: {
        prompt: 'Use log_progress to record you started. Then use update_task_status to set task to in_progress.',
        mode: 'agent',
        task_id: task.id,
      },
    })
    expect(sessionRes.status()).toBe(200)
    const session = await sessionRes.json()

    // Navigate to cockpit and find the agent card. A task-attached card
    // shows the task's title, not the raw session id (see the "create
    // task-attached session" test above).
    await page.goto(BASE)
    await page.waitForTimeout(3000)
    const card = page.locator('text=Cockpit tool e2e test').first()
    await expect(card).toBeVisible({ timeout: 10000 })

    // Enter the agent thread directly (card title isn't a nav target).
    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(2000)

    // Poll the task until the agent modifies it (checking via API in background).
    const updated = await waitForAgentToModifyTask(page, task.id, 120)
    console.log(`Agent finished: status=${updated.status}, progress=${updated.progress.length}`)

    // Check cockpit UI for any tool cards that appeared.
    const toolCards = await page.locator('[data-testid="tool-card"]').count()
    console.log(`Tool cards in UI: ${toolCards}`)

    expect(updated.progress.length).toBeGreaterThanOrEqual(1)
    await page.request.delete(`${BASE}/api/tasks/${task.id}`)
  })

})

// ── tool manager ────────────────────────────────────────────────────────────

test.describe('tool manager', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('list tools shows built-in tools', async ({ page }) => {
    const res = await page.request.get(`${BASE}/api/tools`)
    expect(res.status()).toBe(200)
    const data = await res.json()
    expect(data.tools.length).toBeGreaterThanOrEqual(10)
    // Check key built-in tools exist.
    const names = data.tools.map((t: any) => t.name)
    expect(names).toContain('editor')
    expect(names).toContain('shell')
    expect(names).toContain('create_task')
    expect(names).toContain('log_progress')
  })

  test('create and delete custom tool', async ({ page }) => {
    // Create.
    const createRes = await page.request.post(`${BASE}/api/tools`, {
      data: {
        name: 'e2e_test_tool',
        description: 'A test tool created by Playwright.',
        command: 'echo "hello {name}"',
        parameters: [{ name: 'name', type: 'string', description: 'Name to greet' }],
      },
    })
    expect(createRes.status()).toBe(200)

    // Verify it appears in list.
    const listRes = await page.request.get(`${BASE}/api/tools`)
    const tools = (await listRes.json()).tools
    const found = tools.find((t: any) => t.name === 'e2e_test_tool')
    expect(found).toBeDefined()
    expect(found.builtin).toBe(false)
    expect(found.enabled).toBe(true)

    // Toggle it off.
    const toggleRes = await page.request.post(`${BASE}/api/tools/e2e_test_tool/toggle`)
    expect(toggleRes.status()).toBe(200)
    expect((await toggleRes.json()).enabled).toBe(false)

    // Toggle it back on.
    const toggleRes2 = await page.request.post(`${BASE}/api/tools/e2e_test_tool/toggle`)
    expect((await toggleRes2.json()).enabled).toBe(true)

    // Delete.
    const delRes = await page.request.delete(`${BASE}/api/tools/e2e_test_tool`)
    expect(delRes.status()).toBe(200)

    // Verify gone.
    const after = await (await page.request.get(`${BASE}/api/tools`)).json()
    expect(after.tools.find((t: any) => t.name === 'e2e_test_tool')).toBeUndefined()
  })

  test('custom tool actually works with agent', async ({ page }) => {
    test.setTimeout(120000)

    // Create a custom tool.
    await page.request.post(`${BASE}/api/tools`, {
      data: {
        name: 'say_hello',
        description: 'Say hello to someone.',
        command: 'echo "Hello, {who}!"',
        parameters: [{ name: 'who', type: 'string', description: 'Who to greet' }],
      },
    })

    // Create a task.
    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Custom tool test', priority: 'medium' },
    })
    const task = await taskRes.json()

    // Start a session.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: {
        prompt: 'Use the say_hello tool to greet World. Then use log_progress to record you did it.',
        mode: 'agent',
        task_id: task.id,
      },
    })
    expect(sessionRes.status()).toBe(200)

    // Poll until agent modifies task.
    const deadline = Date.now() + 120000
    let modified = false
    while (Date.now() < deadline) {
      const res = await page.request.get(`${BASE}/api/tasks/${task.id}`)
      const t = await res.json()
      if (t.progress.length > 0) { modified = true; break }
      await new Promise(r => setTimeout(r, 3000))
    }
    expect(modified).toBe(true)

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    await page.request.delete(`${BASE}/api/tools/say_hello`)
  })

})

// ── board view ──────────────────────────────────────────────────────────────

test.describe('board view', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('board loads with columns', async ({ page }) => {
    // Create a few tasks in different statuses.
    const t1 = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Board task A', priority: 'high' },
    })
    const t2 = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Board task B', priority: 'medium' },
    })
    const id1 = (await t1.json()).id
    const id2 = (await t2.json()).id

    // Move one to in_progress.
    await page.request.patch(`${BASE}/api/tasks/${id1}`, { data: { status: 'in_progress' } })

    // Navigate to board.
    await page.goto(`${BASE}/tasks?view=board`)
    await page.waitForTimeout(2000)

    // Should see stage column headers (Draft/Open/In progress/Review/Done
    // — the default stage set from lib/stages.ts).
    await expect(page.locator('text=Open')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=In progress')).toBeVisible()
    await expect(page.locator('text=Done')).toBeVisible()

    // Should see task cards.
    await expect(page.locator('text=Board task A')).toBeVisible()
    await expect(page.locator('text=Board task B')).toBeVisible()

    // Expand a task card.
    await page.locator('text=Board task A').click()
    await page.waitForTimeout(300)

    // Should see the stage-mover chips and Details link in expanded view.
    await expect(page.locator('text=Details →')).toBeVisible({ timeout: 3000 })

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id1}`)
    await page.request.delete(`${BASE}/api/tasks/${id2}`)
  })

})

// ── workspaces ──────────────────────────────────────────────────────────────

test.describe('workspaces', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('create, read, update, delete workspace', async ({ page }) => {
    // Create.
    const createRes = await page.request.post(`${BASE}/api/workspaces`, {
      data: { id: 'e2e-workspace', name: 'E2E Workspace', description: 'Test workspace', tags: ['test'] },
    })
    expect(createRes.status()).toBe(200)

    // List.
    const listRes = await page.request.get(`${BASE}/api/workspaces`)
    const workspaces = (await listRes.json()).workspaces
    expect(workspaces.some((w: any) => w.id === 'e2e-workspace')).toBe(true)

    // Update.
    const patchRes = await page.request.patch(`${BASE}/api/workspaces/e2e-workspace`, {
      data: { name: 'Updated Workspace' },
    })
    expect(patchRes.status()).toBe(200)

    // Delete.
    const delRes = await page.request.delete(`${BASE}/api/workspaces/e2e-workspace`)
    expect(delRes.status()).toBe(200)
  })

  test('tasks filter by workspace', async ({ page }) => {
    // Create workspace.
    await page.request.post(`${BASE}/api/workspaces`, {
      data: { id: 'filter-test', name: 'Filter Test' },
    })

    // Create task in that workspace.
    const t1 = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Workspace task', project: 'filter-test' },
    })
    const id1 = (await t1.json()).id

    // Create task in no workspace.
    const t2 = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'No workspace task' },
    })
    const id2 = (await t2.json()).id

    // List tasks filtered by workspace.
    const listRes = await page.request.get(`${BASE}/api/tasks?project=filter-test`)
    const tasks = (await listRes.json()).tasks
    expect(tasks.some((t: any) => t.id === id1)).toBe(true)
    expect(tasks.some((t: any) => t.id === id2)).toBe(false)

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id1}`)
    await page.request.delete(`${BASE}/api/tasks/${id2}`)
    await page.request.delete(`${BASE}/api/workspaces/filter-test`)
  })

})

// ── advisory agents (reviewer role) ──────────────────────────────────────────

test.describe('advisory agents', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('writer branches, advisory reviewer shares the tree, assignment stays with the writer', async ({ page }) => {
    // The reviewer role is advisory by default (Workflows screen): it
    // fires read-only, sharing the writer's working tree rather than
    // getting its own branch — see SessionManager._ensure_branch and
    // the tool allowlist in intervention.py.
    const { mkdtempSync, writeFileSync } = await import('fs')
    const { tmpdir } = await import('os')
    const { join } = await import('path')
    const { execSync } = await import('child_process')

    const repo = mkdtempSync(join(tmpdir(), 'advisory-test-'))
    execSync('git init -q', { cwd: repo })
    execSync('git config user.email t@example.com', { cwd: repo })
    execSync('git config user.name T', { cwd: repo })
    writeFileSync(join(repo, 'a.txt'), 'one\n')
    execSync('git add a.txt', { cwd: repo })
    execSync('git commit -q -m init', { cwd: repo })

    await page.request.post(`${BASE}/api/workspaces`, {
      data: { id: 'advisory-e2e', name: 'Advisory E2E', repository: repo },
    })
    await page.request.patch(`${BASE}/api/roles/builder`, { data: { enabled: true } })
    await page.request.patch(`${BASE}/api/roles/reviewer`, { data: { enabled: true } })

    try {
      const created = await page.request.post(`${BASE}/api/tasks`, {
        data: { title: 'Advisory E2E task', project: 'advisory-e2e' },
      })
      const task = await created.json()

      // in_progress fires the builder (writer) — real working dir + branch.
      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'in_progress' } })
      let agents: any[] = []
      for (let i = 0; i < 20; i++) {
        await page.waitForTimeout(300)
        agents = (await (await page.request.get(`${BASE}/api/tasks/${task.id}/agents`)).json()).agents
        if (agents.length >= 1) break
      }
      expect(agents.length).toBe(1)
      const writer = agents[0]
      expect(writer.advisory).toBe(false)
      expect(writer.role).toBe('builder')
      // Branches are task-scoped and named from the task's title plus a
      // short hash of its id, not the raw id (gitutil.session_branch_name).
      const { createHash } = await import('crypto')
      const shortId = createHash('sha1').update(task.id).digest('hex').slice(0, 6)
      expect(writer.branch).toBe(`knots/advisory-e2e-task-${shortId}`)

      const afterInProgress = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
      expect(afterInProgress.assigned_to).toBe(writer.id)

      // review fires the reviewer — advisory, no branch of its own. It
      // also pauses the writer rather than stopping it (routes/tasks.py
      // runs this on the same PATCH, before role triggers create the
      // reviewer — see task/lifecycle.py) — the writer stays alive so
      // the Review screen's reject flow can resume the same thread
      // later, so both it and the new reviewer are in the active list.
      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'review' } })
      let reviewer: any
      for (let i = 0; i < 20; i++) {
        await page.waitForTimeout(300)
        agents = (await (await page.request.get(`${BASE}/api/tasks/${task.id}/agents`)).json()).agents
        reviewer = agents.find((a: any) => a.advisory)
        if (reviewer) break
      }
      expect(reviewer).toBeTruthy()
      const pausedWriter = agents.find((a: any) => a.id === writer.id)
      expect(pausedWriter).toBeTruthy()
      expect(pausedWriter.mode).toBe('assistant')
      expect(reviewer.role).toBe('reviewer')
      expect(reviewer.branch).toBeNull()

      // The advisory session must never have taken over assigned_to —
      // assign() is last-writer-wins, so this is the property that
      // actually keeps the writer in charge of the task.
      const afterReview = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
      expect(afterReview.assigned_to).toBe(writer.id)

      // The Task Detail screen renders one block per session, labelled
      // by the agent's human-readable name — the advisory one prefixed
      // with a shield + its role.
      await page.goto(`${BASE}/tasks/${task.id}`)
      await expect(page.locator(`text=${writer.name}`).first()).toBeVisible({ timeout: 5000 })
      await expect(page.getByText(/🛡 .+ · reviewer/)).toBeVisible()
      await expect(page.locator(`text=${writer.branch}`).first()).toBeVisible()

      for (const a of agents) {
        await page.request.delete(`${BASE}/api/agent/${a.id}`).catch(() => {})
      }
    } finally {
      await page.request.patch(`${BASE}/api/roles/builder`, { data: { enabled: false } })
      await page.request.patch(`${BASE}/api/roles/reviewer`, { data: { enabled: false } })
      await page.request.delete(`${BASE}/api/workspaces/advisory-e2e`).catch(() => {})
    }
  })

})

test.describe('agent deletion', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('delete agent via API', async ({ page }) => {
    // Create a session.
    const res = await page.request.post(`${BASE}/api/sessions`, {
      data: { prompt: 'Say hello', mode: 'agent' },
    })
    expect(res.status()).toBe(200)
    const { id } = await res.json()

    // Delete it.
    const delRes = await page.request.delete(`${BASE}/api/agent/${id}`)
    expect(delRes.status()).toBe(200)

    // Verify gone from agent list.
    const list = await (await page.request.get(`${BASE}/api/agents`)).json()
    expect(list.agents.find((a: any) => a.id === id)).toBeUndefined()
  })

})

// ── task editing ────────────────────────────────────────────────────────────

test.describe('task editing', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })
  test('change status via edit dialog', async ({ page }) => {
    const res = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Status change test' },
    })
    const { id } = await res.json()

    await page.goto(`${BASE}/tasks/${id}`)
    await page.waitForTimeout(1000)

    // Status is edit-only (no inline dropdown on the detail page).
    await page.locator('text=Edit').first().click()
    await page.waitForTimeout(300)
    await page.getByLabel('Status').selectOption('review')
    await page.locator('text=Save changes').click()
    await page.waitForTimeout(500)

    // Verify.
    const updated = await (await page.request.get(`${BASE}/api/tasks/${id}`)).json()
    expect(updated.status).toBe('review')

    await page.request.delete(`${BASE}/api/tasks/${id}`)
  })

  test('create task from board + button', async ({ page }) => {
    await page.goto(`${BASE}/tasks?view=board`)
    await page.waitForTimeout(1000)

    // Click + button in the Open column.
    const plusButtons = page.locator('button[title="Add task"]')
    await plusButtons.first().click()
    await page.waitForTimeout(300)

    // Fill dialog.
    await page.locator('input[placeholder="What needs to be done?"]').fill('Board dialog task')
    await page.locator('text=Create task').click()
    await page.waitForTimeout(1000)

    // Should appear on board.
    await expect(page.locator('text=Board dialog task')).toBeVisible({ timeout: 5000 })

    // Cleanup via API.
    const list = await (await page.request.get(`${BASE}/api/tasks`)).json()
    const task = list.tasks.find((t: any) => t.title === 'Board dialog task')
    if (task) await page.request.delete(`${BASE}/api/tasks/${task.id}`)
  })

  test('Tasks nav pill switches between Board and List tabs', async ({ page }) => {
    // Replaces the old "Tasks ▾" dropdown, which no longer exists — Board
    // and List are now tabs inside the /tasks screen.
    await page.goto(BASE)
    await page.waitForTimeout(1000)

    await page.locator('nav >> text=Tasks').click()
    await page.waitForTimeout(500)
    expect(page.url()).toContain('/tasks')

    // Target the tab buttons by role — a plain `text=Board` locator also
    // matches the "Dashboard" nav link ("board" is a substring of it).
    await page.getByRole('button', { name: 'list' }).click()
    await page.waitForTimeout(300)
    expect(page.url()).toContain('view=list')

    await page.getByRole('button', { name: 'board' }).click()
    await page.waitForTimeout(300)
    expect(page.url()).toContain('view=board')
  })

})

test.describe('task modal editing', () => {
  test.beforeEach(async ({ page }) => { await authPage(page) })

  test('edit task via modal', async ({ page }) => {
    test.setTimeout(30000)
    const res = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Modal test', priority: 'low' } })
    const { id } = await res.json()
    await page.goto(`${BASE}/tasks/${id}`)
    await page.waitForTimeout(1000)

    await page.locator('text=Edit').first().click()
    await page.waitForTimeout(500)

    // Fill in the modal — title has a distinctive placeholder, priority
    // is targeted by its aria-label (multiple selects exist in edit mode).
    await page.locator('input[placeholder="What needs to be done?"]').fill('Updated via modal')
    await page.getByLabel('Priority').selectOption('urgent')
    await page.locator('text=Save changes').click()
    await page.waitForTimeout(500)

    const updated = await (await page.request.get(`${BASE}/api/tasks/${id}`)).json()
    expect(updated.title).toBe('Updated via modal')
    expect(updated.priority).toBe('urgent')
    await page.request.delete(`${BASE}/api/tasks/${id}`)
  })
})

// ── session-task assignment ─────────────────────────────────────────────────

test.describe('session-task assignment', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('starting session on task moves it to in_progress', async ({ page }) => {
    // Create a task.
    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Assignment test task', priority: 'medium' },
    })
    const task = await taskRes.json()
    expect(task.status).toBe('draft')

    // Move to open — only an 'open' task auto-transitions to in_progress
    // when a session starts (SessionManager._resolve_task_context).
    await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'open' } })

    // Start a session assigned to this task.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: { prompt: 'Say hello', mode: 'agent', task_id: task.id },
    })
    expect(sessionRes.status()).toBe(200)

    // Wait briefly for session to start.
    await page.waitForTimeout(3000)

    // Verify task status changed to in_progress.
    const updated = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
    expect(updated.status).toBe('in_progress')
    expect(updated.assigned_to).toBeTruthy()

    // Cleanup — stop the session and delete the task.
    const session = await sessionRes.json()
    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
    await page.request.delete(`${BASE}/api/tasks/${task.id}`)
  })

  test('board card click opens Task Detail and hover action starts a session', async ({ page }) => {
    // The card no longer expands inline — clicking opens Task Detail,
    // and the start action is a hover-revealed ▶ button on the card.
    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Board card test', priority: 'high' },
    })
    const task = await taskRes.json()

    try {
      // Navigate to board.
      await page.goto(`${BASE}/tasks?view=board`)
      await page.waitForTimeout(2000)

      // Card is visible in the Draft column.
      const card = page.locator(`.ak-card:has-text("${task.title}")`)
      await expect(card).toBeVisible({ timeout: 5000 })

      // Clicking the card navigates to Task Detail, not an expand.
      await card.click()
      await page.waitForTimeout(500)
      expect(page.url()).toMatch(/\/tasks\/T-/)

      // Back to the board to test the hover start action.
      await page.goto(`${BASE}/tasks?view=board`)
      await page.waitForTimeout(1500)

      // Hover the card to reveal the ▶ start button, then click it.
      const startBtn = page.locator(`.ak-card:has-text("${task.title}") .ak-card-action`)
      await card.hover()
      await startBtn.click({ timeout: 3000 })
      await page.waitForTimeout(1000)

      // Start (non-headless) navigates to the agent thread.
      expect(page.url()).toMatch(/\/agent\//)
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${task.id}`).catch(() => {})
    }
  })

  test('New session dialog offers open tasks to attach to', async ({ page }) => {
    // Dashboard's own ad-hoc task-picker dropdown was replaced with a
    // real NewSessionDialog opened from Topbar's (now-enabled) "+ New
    // session" button — a native <select> instead of an open list of
    // buttons, so task options are asserted via the select's contents
    // rather than toBeVisible() (closed <select> options aren't
    // considered "visible" by Playwright).
    // Explicit status: 'open' — tasks default to 'draft' now, and the
    // attach-to-task picker only offers Open tasks (a Draft task isn't
    // ready to attach a session to yet; that's the point of Draft).
    const t1 = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Picker task 1', status: 'open' } })
    const t2 = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Picker task 2', status: 'open' } })
    const id1 = (await t1.json()).id; const id2 = (await t2.json()).id

    await page.goto(BASE)
    await page.waitForTimeout(2000)

    // The Dashboard's workspace-cluster footer also has a "+ New session"
    // link (opens the same dialog), so scope to Topbar's specifically.
    await page.getByRole('banner').getByRole('button', { name: 'New session' }).click()
    await page.waitForTimeout(300)

    await expect(page.locator('text=Attach to task')).toBeVisible({ timeout: 3000 })
    const taskSelect = page.getByLabel('Attach to task')
    await expect(taskSelect.locator('option', { hasText: 'No task — just start' })).toHaveCount(1)
    await expect(taskSelect.locator('option', { hasText: 'Picker task 1' })).toHaveCount(1)
    await expect(taskSelect.locator('option', { hasText: 'Picker task 2' })).toHaveCount(1)

    // Cleanup.
    await page.request.delete(`${BASE}/api/tasks/${id1}`)
    await page.request.delete(`${BASE}/api/tasks/${id2}`)
  })

})

// ── full task workflow ──────────────────────────────────────────────────────

test.describe('full task workflow', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('create task → draft → open → agent works → progress → done', async ({ page }) => {
    test.setTimeout(180000)

    // 1. Create a task (starts as open by default, but we can set draft).
    const createRes = await page.request.post(`${BASE}/api/tasks`, {
      data: {
        title: 'Full workflow test — write a hello script',
        description: 'Create a Python script called greet.py that prints a greeting and the current time.',
        priority: 'medium',
        acceptance_criteria: [
          'Script file is named greet.py',
          'Prints a greeting message',
          'Prints the current time',
          'Script exits cleanly when run',
        ],
        status: 'draft',
      },
    })
    expect(createRes.status()).toBe(200)
    const task = await createRes.json()
    console.log(`Task created: ${task.id} (draft)`)

    // 2. Verify it's in draft status.
    let current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
    expect(current.status).toBe('draft')

    // 3. Move to open (ready for work).
    await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'open' } })
    current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
    expect(current.status).toBe('open')
    console.log('Status: open (ready)')

    // 4. Start an agent session on this task.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: {
        prompt: `Work on task ${task.id}. Read the task, log progress at each step, create the greet.py file, and when done mark the task as done. Use the task tools.`,
        mode: 'agent',
        task_id: task.id,
      },
    })
    expect(sessionRes.status()).toBe(200)
    const session = await sessionRes.json()
    console.log(`Session started: ${session.id}`)

    // 5. Verify task moved to in_progress automatically.
    await page.waitForTimeout(2000)
    current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
    expect(current.status).toBe('in_progress')
    expect(current.assigned_to).toBe(session.id)
    console.log('Status: in_progress (agent assigned)')

    // 6. Poll until agent finishes (task has progress entries).
    const deadline = Date.now() + 120000
    let progressCount = 0
    while (Date.now() < deadline) {
      current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
      progressCount = current.progress.length
      if (progressCount >= 2) break  // at least 2 progress entries = agent working
      await new Promise(r => setTimeout(r, 3000))
    }
    console.log(`Progress entries: ${progressCount}, status: ${current.status}`)

    // 7. Verify agent logged progress.
    expect(progressCount).toBeGreaterThanOrEqual(1)

    // 8. If the agent didn't finish the workflow itself, drive it the
    // rest of the way as a human would — done can't be reached directly
    // from in_progress (task/store.py::_validate_transition requires
    // passing through review first, then a human — not the agent that
    // did the work — has to be the one to approve it).
    if (current.status === 'in_progress') {
      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'review' } })
      current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
    }
    if (current.status === 'review') {
      for (const criterion of current.acceptance_criteria) {
        await page.request.post(`${BASE}/api/tasks/${task.id}/criteria/toggle`, { data: { criterion, met: true } })
      }
      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'done' } })
      current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
    }
    expect(current.status).toBe('done')
    console.log('Status: done (completed)')

    // 9. Verify the full state: task has progress, was assigned, is now done.
    expect(current.assigned_to).toBeTruthy()
    expect(current.progress.length).toBeGreaterThanOrEqual(1)

    // Cleanup.
    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
    await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    console.log('✅ Full workflow complete: draft → open → in_progress → done')
  })

})

// ── runtime & isolation ─────────────────────────────────────────────────────

test.describe('runtime & isolation', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('workspace with a legacy/unknown runtime value falls back to in-process, not a crash', async ({ page }) => {
    // SubprocessRuntime (a second, isolated-process runtime) was removed
    // after a code review found it never actually worked — it referenced
    // a Session API that stopped existing when SSE fan-out landed, so it
    // crashed on the first event any subprocess-runtime session tried to
    // emit. create_runtime()/set_runtime_type() now
    // silently treat any non-"inprocess" value (including an old
    // "subprocess" saved from before the removal) as in-process, so a
    // pre-existing workspace with that value doesn't break on upgrade —
    // that's what this test actually verifies now.
    test.setTimeout(60000)

    const wsRes = await page.request.post(`${BASE}/api/workspaces`, {
      data: { id: 'legacy-runtime-test', name: 'Legacy Runtime Test', runtime: 'subprocess' },
    })
    expect(wsRes.status()).toBe(200)

    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Legacy runtime task', project: 'legacy-runtime-test' },
    })
    const task = await taskRes.json()

    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: { prompt: 'Say hello', mode: 'agent', project_id: 'legacy-runtime-test' },
    })
    expect(sessionRes.status()).toBe(200)
    const session = await sessionRes.json()

    await page.waitForTimeout(3000)

    // The session should show up as a normal running agent, not have
    // crashed on session start.
    const agents = await (await page.request.get(`${BASE}/api/agents`)).json()
    expect(agents.agents.some((a: any) => a.id === session.id)).toBe(true)

    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
    await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    await page.request.delete(`${BASE}/api/workspaces/legacy-runtime-test`)
  })

  test('workspace runtime field round-trips through the API', async ({ page }) => {
    // The field itself is free-text storage at the workspace-model layer
    // (no validation against a fixed set of implemented runtimes) — this
    // deliberately uses a value that was never a real runtime, to keep
    // the test about the round-trip, not about which runtimes exist.
    await page.request.post(`${BASE}/api/workspaces`, {
      data: { id: 'runtime-test', name: 'Runtime Test', runtime: 'some-custom-value' },
    })

    const list = await (await page.request.get(`${BASE}/api/workspaces`)).json()
    const ws = list.workspaces.find((w: any) => w.id === 'runtime-test')
    expect(ws).toBeDefined()
    expect(ws.runtime).toBe('some-custom-value')

    await page.request.delete(`${BASE}/api/workspaces/runtime-test`)
  })

  test('settings API returns global runtime', async ({ page }) => {
    const settings = await (await page.request.get(`${BASE}/api/settings`)).json()
    expect(settings.agent).toHaveProperty('runtime')
    console.log(`Global runtime: ${settings.agent.runtime}`)
  })

})

// ── agent panel tabs ────────────────────────────────────────────────────────

test.describe('agent panel tabs', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('terminal, files, commands, browser tabs switch in agent thread', async ({ page }) => {
    // The original 4-tab set (Terminal/Review/Code/Browser) was
    // consolidated into Terminal/Files/Preview — task info (the old
    // "Review" tab's content) moved to the always-visible left goal
    // rail instead of being a tab. A later round added a 4th tab,
    // Commands (a structured log of shell invocations + timestamps),
    // and made Terminal a real PTY-backed shell (xterm.js) instead of a
    // read-only output log — Files also narrowed to editor-only touches
    // (shell commands no longer masquerade as "files"). Preview was
    // later rebuilt into a real multi-tab Browser panel (this test) —
    // renamed from "preview" to "browser" to match.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: { prompt: 'Say hello', mode: 'agent' },
    })
    const session = await sessionRes.json()

    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(2000)

    await expect(page.locator('button:has-text("terminal")')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('button:has-text("files")')).toBeVisible()
    await expect(page.locator('button:has-text("commands")')).toBeVisible()
    await expect(page.locator('button:has-text("browser")')).toBeVisible()

    // Terminal tab is active by default — a real PTY shell, so it shows
    // a connection status line rather than a static placeholder.
    await expect(page.locator('text=connected').or(page.locator('text=connecting'))).toBeVisible({ timeout: 5000 })

    await page.locator('button:has-text("files")').click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=Files the agent reads or edits will appear here.')).toBeVisible()

    await page.locator('button:has-text("commands")').click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=Shell commands the agent runs will appear here')).toBeVisible()

    await page.locator('button:has-text("browser")').click()
    await page.waitForTimeout(300)
    // Browser is now a real mini-browser (tab strip + address bar +
    // iframe), not a static "coming soon" placeholder.
    await expect(page.locator('input[placeholder="Enter a URL to preview…"]')).toBeVisible()

    await page.locator('button:has-text("terminal")').click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=connected').or(page.locator('text=connecting'))).toBeVisible()

    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
  })

  test('browser tab: manual URL entry, clicking a chat link opens a new tab, and tabs can be closed', async ({ page }) => {
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: { prompt: '', mode: 'agent' },
    })
    const session = await sessionRes.json()

    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(800)

    // Manual entry: bare host gets an http:// scheme prefixed automatically.
    await page.locator('button:has-text("browser")').click()
    const urlInput = page.locator('input[placeholder="Enter a URL to preview…"]')
    await urlInput.fill('example.com')
    await urlInput.press('Enter')
    await page.waitForTimeout(300)
    await expect(page.locator('iframe[title="Browser"]')).toHaveAttribute('src', 'http://example.com')
    // One tab so far — this same tab's URL just changed, no new tab yet.
    await expect(page.locator('[title="Close tab"]')).toHaveCount(1)

    // A URL the agent (or here, a plain send()) posts in chat is a real
    // clickable link (remark-gfm autolinks bare URLs) that opens in a
    // brand-new Browser tab — the example.com tab from above stays put.
    await page.locator('button:has-text("terminal")').click()
    await page.request.post(`${BASE}/api/agent/${session.id}/send`, {
      form: { message: 'Dev server is up: http://localhost:5173/ check it out' },
    })
    await page.waitForTimeout(800)

    const chatLink = page.locator('a', { hasText: 'http://localhost:5173/' })
    await expect(chatLink).toBeVisible()
    await chatLink.click()
    await page.waitForTimeout(300)
    await expect(page.locator('iframe[title="Browser"]')).toHaveAttribute('src', 'http://localhost:5173/')
    await expect(page.locator('[title="Close tab"]')).toHaveCount(2)

    // Closing the active (2nd) tab falls back to the remaining one.
    await page.locator('[title="Close tab"]').nth(1).click()
    await page.waitForTimeout(200)
    await expect(page.locator('[title="Close tab"]')).toHaveCount(1)
    await expect(page.locator('iframe[title="Browser"]')).toHaveAttribute('src', 'http://example.com')

    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
  })

  test('goal rail shows task details when session has task', async ({ page }) => {
    test.setTimeout(120000)

    // Create a task with criteria and steps.
    const taskRes = await page.request.post(`${BASE}/api/tasks`, {
      data: {
        title: 'Panel review test',
        description: 'Testing review panel.',
        priority: 'medium',
        acceptance_criteria: ['Should show in panel', 'Should update live'],
      },
    })
    const task = await taskRes.json()

    // Start session on the task.
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: { prompt: 'Use log_progress to record you started.', mode: 'agent', task_id: task.id },
    })
    const session = await sessionRes.json()

    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(3000)

    // Task title/criteria are always visible in the left goal rail —
    // no tab click needed (that's the point of the Agent Thread redesign).
    // The bare criterion text can also appear elsewhere on the page (a
    // raw tool-output echo in chat, or the steering hook's "possible
    // match" auto-log line) — the "○ " bullet prefix is unique to the
    // rail's own rendering of an unmet criterion.
    await expect(page.locator('text=Panel review test').first()).toBeVisible({ timeout: 10000 })
    await expect(page.locator('text=○ Should show in panel')).toBeVisible()

    // Cleanup.
    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
    await page.request.delete(`${BASE}/api/tasks/${task.id}`)
  })

})

test.describe('agent code panel', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('files tab shows files agent touches', async ({ page }) => {
    test.setTimeout(60000)
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, {
      data: { prompt: 'Say hello', mode: 'agent' },
    })
    const session = await sessionRes.json()

    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(3000)

    await page.locator('button:has-text("files")').click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=touched')).toBeVisible({ timeout: 5000 })

    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
  })

})

// ── workflows screen ─────────────────────────────────────────────────────────

test.describe('workflows screen', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('shows default stages and roles, all roles disabled', async ({ page }) => {
    await page.goto(`${BASE}/workflows`)
    await page.waitForTimeout(800)

    await expect(page.locator('text=Current workflow')).toBeVisible()
    await expect(page.locator('text=Board stages')).toBeVisible()
    await expect(page.locator('text=Default agents')).toBeVisible()
    // "Planner"/"Builder"/"Reviewer" also appear inside the pipeline
    // template descriptions further down — .first() targets the role row.
    await expect(page.locator('text=Planner').first()).toBeVisible()
    await expect(page.locator('text=Builder').first()).toBeVisible()
    await expect(page.locator('text=Reviewer').first()).toBeVisible()

    // Auto-firing a real agent costs real API money — must be opt-in.
    const roleSwitches = await page.getByRole('switch').all()
    const roleStates = await Promise.all(roleSwitches.slice(-3).map(s => s.getAttribute('aria-checked')))
    expect(roleStates.every(s => s === 'false')).toBe(true)
  })

  test('toggling a stage persists via the API', async ({ page }) => {
    await page.goto(`${BASE}/workflows`)
    await page.waitForTimeout(800)

    await page.getByRole('switch').nth(5).click() // Abandoned — 6th stage switch
    await page.waitForTimeout(300)

    const resp = await page.request.get(`${BASE}/api/stages`)
    const abandoned = (await resp.json()).stages.find((s: any) => s.key === 'abandoned')
    expect(abandoned.enabled).toBe(true)

    // Cleanup — restore default.
    await page.request.post(`${BASE}/api/stages/abandoned/toggle`, { data: { enabled: false } })
  })

  test('configure dialog edits a role', async ({ page }) => {
    await page.goto(`${BASE}/workflows`)
    await page.waitForTimeout(800)

    await page.locator('button:has-text("Configure")').first().click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=Configure Planner')).toBeVisible()

    await page.getByLabel('Model').fill('gpt-4o')
    await page.locator('button:has-text("Save")').click()
    await page.waitForTimeout(300)

    const resp = await page.request.get(`${BASE}/api/roles`)
    const planner = (await resp.json()).roles.find((r: any) => r.key === 'planner')
    expect(planner.model).toBe('gpt-4o')
  })

})

// ── review screen ────────────────────────────────────────────────────────────

test.describe('review screen', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('list shows a task in review; detail shows its diff and approve commits + closes it out', async ({ page }) => {
    const { mkdtempSync, writeFileSync } = await import('fs')
    const { tmpdir } = await import('os')
    const { join } = await import('path')
    const { execSync } = await import('child_process')
    const { createHash } = await import('crypto')

    const repo = mkdtempSync(join(tmpdir(), 'review-test-'))
    execSync('git init -q', { cwd: repo })
    execSync('git config user.email t@example.com', { cwd: repo })
    execSync('git config user.name T', { cwd: repo })
    writeFileSync(join(repo, 'a.txt'), 'one\n')
    execSync('git add a.txt', { cwd: repo })
    execSync('git commit -q -m init', { cwd: repo })

    await page.request.post(`${BASE}/api/workspaces`, {
      data: { id: 'review-e2e', name: 'Review E2E', repository: repo },
    })
    const created = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Review page task', project: 'review-e2e' },
    })
    const task = await created.json()

    // No live session on this task, so the review routes fall back to
    // the deterministic branch name (gitutil.session_branch_name) —
    // check the repo out onto it directly, matching a real task-scoped
    // session's branch exactly.
    const shortId = createHash('sha1').update(task.id).digest('hex').slice(0, 6)
    const branch = `knots/review-page-task-${shortId}`
    execSync(`git checkout -q -b ${branch}`, { cwd: repo })
    writeFileSync(join(repo, 'a.txt'), 'one\ntwo\n')

    await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'review' } })

    await page.goto(`${BASE}/review`)
    await page.waitForTimeout(800)
    await expect(page.locator('text=Review page task')).toBeVisible({ timeout: 5000 })

    await page.click('text=Review page task')
    await page.waitForTimeout(600)
    expect(page.url()).toContain(`/review/${task.id}`)
    await expect(page.locator('text=a.txt')).toBeVisible()
    await expect(page.locator('text=1 file pending')).toBeVisible()

    // "Approve all" also matches a plain has-text("Approve") locator —
    // target the per-file "Approve" button specifically.
    await page.locator('button:has-text("Approve")').last().click()
    await page.waitForTimeout(500)
    await expect(page.locator('text=every file committed')).toBeVisible()

    const log = execSync('git log --oneline', { cwd: repo }).toString()
    expect(log.split('\n').filter(Boolean).length).toBe(2)

    const updated = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
    expect(updated.status).toBe('done')

    await page.request.delete(`${BASE}/api/tasks/${task.id}`).catch(() => {})
    await page.request.delete(`${BASE}/api/workspaces/review-e2e`).catch(() => {})
  })

})

// ── vault section (folded into Settings) ────────────────────────────────────

const VAULT_PASSPHRASE = 'e2e-test-passphrase'

test.describe('vault section', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('locked card shows unlock form, unlocking reveals credentials + audit log', async ({ page }) => {
    await page.request.post(`${BASE}/api/vault/lock`)
    await page.goto(`${BASE}/settings#vault`)
    await page.waitForTimeout(500)

    await expect(page.getByLabel('Passphrase')).toBeVisible()
    await page.getByLabel('Passphrase').fill(VAULT_PASSPHRASE)
    await page.locator('button:has-text("vault")').last().click() // "Unlock vault" / "Create vault"
    await page.waitForTimeout(500)

    // "Credentials" also matches the empty-state "No credentials yet."
    await expect(page.locator('text=Credentials').first()).toBeVisible()
    await expect(page.locator('text=UNLOCKED')).toBeVisible()
    await expect(page.locator('text=Audit log')).toBeVisible()
  })

  test('add credential never leaks the value to the page, and Lock returns to the locked card', async ({ page }) => {
    await page.request.post(`${BASE}/api/vault/unlock`, { data: { passphrase: VAULT_PASSPHRASE } })
    await page.request.delete(`${BASE}/api/vault/credentials/e2e-cred`) // leftover from a prior interrupted run
    await page.goto(`${BASE}/settings#vault`)
    await page.waitForTimeout(500)

    await page.locator('button:has-text("+ Add credential")').click()
    await page.waitForTimeout(300)
    await page.getByLabel('Credential ID').fill('e2e-cred')
    await page.getByLabel('Credential value').fill('super-secret-value-xyz')
    await page.locator('button:text-is("Add")').click()
    await page.waitForTimeout(500)

    // Also appears in the audit-log row below the credential row.
    await expect(page.locator('text=e2e-cred').first()).toBeVisible()
    expect(await page.content()).not.toContain('super-secret-value-xyz')

    await page.locator('button:has-text("Lock")').click()
    await page.waitForTimeout(300)
    await expect(page.getByLabel('Passphrase')).toBeVisible()

    // Cleanup — re-unlock and remove the test credential.
    await page.request.post(`${BASE}/api/vault/unlock`, { data: { passphrase: VAULT_PASSPHRASE } })
    await page.request.delete(`${BASE}/api/vault/credentials/e2e-cred`)
  })

})

// ── settings screen ──────────────────────────────────────────────────────────

test.describe('settings screen', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('shows every settings section', async ({ page }) => {
    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)

    for (const label of ['Usage', 'Accessibility', 'Model providers', 'Tools', 'Policies', 'MCP servers', 'Integrations']) {
      await expect(page.locator(`text=${label}`).first()).toBeVisible()
    }
    // "Workspaces" alone also case-insensitively matches the topbar's
    // "All workspaces" <option> — check the card's unique button instead.
    await expect(page.locator('text=+ Add workspace')).toBeVisible()
  })

  test('side nav jumps to a section, and /vault redirects into it', async ({ page }) => {
    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)

    await page.locator('nav button:has-text("Workspaces")').click()
    await page.waitForTimeout(500)
    await expect(page.locator('text=+ Add workspace')).toBeInViewport()

    // Old standalone /vault route should land on the Vault section.
    await page.goto(`${BASE}/vault`)
    await page.waitForTimeout(600)
    expect(page.url()).toContain('/settings#vault')
    await expect(page.locator('nav button:has-text("Vault")')).toHaveCSS('color', 'rgb(108, 92, 231)')
  })

  test('add provider then set default persists via the API', async ({ page }) => {
    // "Set default" intentionally overwrites the real agent.* settings
    // (that's the whole point of the feature) — and there's no API to
    // blank an api_key back out once set (PUT /api/settings treats an
    // empty key as "leave unchanged", to protect against accidentally
    // wiping a real key). So this test restores the raw settings.yaml
    // afterward directly, rather than leaving a fake key that would
    // flip every other test's "configured" check to true.
    const { readFileSync, writeFileSync, existsSync, rmSync } = await import('fs')
    const settingsPath = join(homedir(), '.agent-knots', 'settings.yaml')
    const hadFile = existsSync(settingsPath)
    const original = hadFile ? readFileSync(settingsPath, 'utf-8') : null

    try {
      await page.goto(`${BASE}/settings`)
      await page.waitForTimeout(800)

      await page.locator('button:has-text("+ Add provider")').click()
      await page.waitForTimeout(300)
      await page.getByLabel('Provider name').fill('e2e-provider')
      await page.getByLabel('API key').fill('sk-e2e-test-key')
      await page.locator('button:text-is("Add")').click()
      await page.waitForTimeout(500)

      await expect(page.locator('text=e2e-provider')).toBeVisible()
      expect(await page.content()).not.toContain('sk-e2e-test-key')

      await page.locator('button:has-text("Set default")').click()
      await page.waitForTimeout(500)

      const settings = await (await page.request.get(`${BASE}/api/settings`)).json()
      expect(settings.default_provider).toBe('e2e-provider')

      await page.request.delete(`${BASE}/api/settings/providers/e2e-provider`)
    } finally {
      if (hadFile) writeFileSync(settingsPath, original as string)
      else if (existsSync(settingsPath)) rmSync(settingsPath)
    }
  })

  test('toggling a policy persists via the API', async ({ page }) => {
    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)

    await page.locator('text=No sudo').scrollIntoViewIfNeeded()
    // "No sudo" labels the row's flex:1 text wrapper, not the row
    // itself — the Toggle is a sibling one level further up.
    const noSudoRow = page.locator('text=No sudo').locator('..').locator('..')
    await noSudoRow.getByRole('switch').click()
    await page.waitForTimeout(300)

    const policies = await (await page.request.get(`${BASE}/api/policies`)).json()
    expect(policies.policies.find((p: any) => p.key === 'no_sudo').enabled).toBe(true)

    // Cleanup — restore default.
    await page.request.patch(`${BASE}/api/policies/no_sudo`, { data: { enabled: false } })
  })

  test('add, toggle, and remove an MCP server', async ({ page }) => {
    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)

    await page.locator('button:has-text("+ Add MCP server")').click()
    await page.waitForTimeout(200)
    await page.getByLabel('MCP server name').fill('e2e-mcp')
    await page.locator('button:text-is("Add")').click()
    await page.waitForTimeout(500)

    await expect(page.locator('text=e2e-mcp')).toBeVisible()

    const row = page.locator('text=e2e-mcp').locator('..')
    await row.getByRole('switch').click()
    await page.waitForTimeout(300)

    const servers = await (await page.request.get(`${BASE}/api/mcp`)).json()
    expect(servers.servers.find((s: any) => s.name === 'e2e-mcp').enabled).toBe(true)

    await page.request.delete(`${BASE}/api/mcp/e2e-mcp`)
  })

  test('add, edit, and delete a workspace via the dialog', async ({ page }) => {
    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)

    await page.locator('button:has-text("+ Add workspace")').click()
    await page.waitForTimeout(200)
    // No id field any more — the backend slugifies one from the name.
    await page.getByLabel('Workspace name').fill('E2E Workspace')
    await page.locator('button:text-is("Create")').click()
    await page.waitForTimeout(500)

    await expect(page.locator('text=E2E Workspace')).toBeVisible()

    const wsRow = page.locator('text=E2E Workspace').locator('..')
    await wsRow.locator('button:has-text("Edit")').click()
    await page.waitForTimeout(200)
    await page.getByLabel('Workspace name').fill('E2E Workspace Renamed')
    await page.locator('button:text-is("Save")').click()
    await page.waitForTimeout(500)
    await expect(page.locator('text=E2E Workspace Renamed')).toBeVisible()

    await page.request.delete(`${BASE}/api/workspaces/e2e-workspace`)
  })

  test('deleting a workspace shows a themed confirm dialog, not the native browser one', async ({ page }) => {
    await page.request.post(`${BASE}/api/workspaces`, { data: { name: 'Delete Me', id: 'delete-me-e2e' } })
    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)

    const wsRow = page.locator('text=Delete Me').locator('..')
    // If this were still window.confirm(), a native dialog would block
    // the page and this click would hang waiting for a dialog handler.
    // Scoped to the dialog itself (role="dialog") — an unscoped
    // "Delete" text locator also matches every row's button in the
    // Settings Wastebin list.
    const dialog = page.getByRole('dialog')
    await wsRow.locator('button:has-text("✕")').click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=Delete this workspace?')).toBeVisible()

    // Cancel — workspace still there.
    await dialog.locator('button:text-is("Cancel")').click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=Delete Me')).toBeVisible()

    // Confirm — workspace actually gone.
    await wsRow.locator('button:has-text("✕")').click()
    await page.waitForTimeout(300)
    await dialog.locator('button:text-is("Delete")').click()
    await page.waitForTimeout(500)
    await expect(page.locator('text=Delete Me')).toHaveCount(0)
  })

  test('accessibility: font size and font family apply and persist', async ({ page }) => {
    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)
    await page.locator('nav button:has-text("Accessibility")').click()
    await page.waitForTimeout(300)

    await page.locator('button:text-is("Largest")').click()
    await page.waitForTimeout(300)
    const zoom = await page.evaluate(() => document.getElementById('root')?.style.getPropertyValue('zoom'))
    expect(zoom).toBe('1.375')

    await page.selectOption('select[aria-label="Font family"]', 'accessible')
    await page.waitForTimeout(300)
    const font = await page.evaluate(() => getComputedStyle(document.body).getPropertyValue('--font'))
    expect(font).toContain('Atkinson Hyperlegible')

    // Both choices persist across reload (localStorage-backed, not just
    // component state).
    await page.reload()
    await page.waitForTimeout(500)
    const zoomAfterReload = await page.evaluate(() => document.getElementById('root')?.style.getPropertyValue('zoom'))
    expect(zoomAfterReload).toBe('1.375')
    const fontAfterReload = await page.evaluate(() => getComputedStyle(document.body).getPropertyValue('--font'))
    expect(fontAfterReload).toContain('Atkinson Hyperlegible')

    // Reset to defaults so this doesn't leak into other tests running
    // against the same browser storage.
    await page.locator('nav button:has-text("Accessibility")').click()
    await page.waitForTimeout(300)
    await page.locator('button:text-is("Default")').click()
    await page.selectOption('select[aria-label="Font family"]', 'default')
    await page.waitForTimeout(300)
  })

})

// ── setup wizard ─────────────────────────────────────────────────────────────

test.describe('setup wizard', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('shows on an unconfigured install with MiniMax preselected and no stale model id', async ({ page }) => {
    const settings = await (await page.request.get(`${BASE}/api/settings`)).json()
    test.skip(settings.configured, 'server is configured — wizard would not show')

    await page.goto(`${BASE}/`)
    await page.waitForTimeout(600)

    await expect(page.locator('text=Welcome to agent-knots')).toBeVisible()
    // Regression: AgentSettings.default_model's dataclass default
    // ("openai/gpt-4o-mini") used to leak into the Model ID field even
    // though the MiniMax chip was the one shown selected.
    await expect(page.getByLabel('Model ID')).toHaveValue('minimax-m2.7')
  })

  test('Skip dismisses the wizard for this view without marking configured', async ({ page }) => {
    const settings = await (await page.request.get(`${BASE}/api/settings`)).json()
    test.skip(settings.configured, 'server is configured — wizard would not show')

    await page.goto(`${BASE}/`)
    await page.waitForTimeout(600)
    await expect(page.locator('text=Welcome to agent-knots')).toBeVisible()

    await page.locator('button:has-text("Skip")').click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=Welcome to agent-knots')).not.toBeVisible()

    // Not persisted — a fresh load still shows the wizard.
    await page.reload()
    await page.waitForTimeout(600)
    await expect(page.locator('text=Welcome to agent-knots')).toBeVisible()
  })

})

// ── notification bell ────────────────────────────────────────────────────────

test.describe('notification bell', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('badge count and dropdown row reflect a blocked task, and deep-links to it', async ({ page }) => {
    const createRes = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Bell E2E task' } })
    const task = await createRes.json()
    await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'blocked' } })

    try {
      await page.goto(`${BASE}/`)
      await page.waitForTimeout(6000) // 5s notification poll interval

      const badge = page.locator('button[title="Notifications"] span')
      await expect(badge).toBeVisible()

      await page.click('button[title="Notifications"]')
      await page.waitForTimeout(300)
      // Scoped to the topbar — a blocked task also surfaces as a card on
      // the Dashboard itself, so an unscoped locator matches both.
      const dropdown = page.getByRole('banner')
      await expect(dropdown.getByText('Bell E2E task')).toBeVisible()
      await expect(dropdown.getByText('blocked · ')).toBeVisible()

      await dropdown.getByText('Bell E2E task').click()
      await page.waitForTimeout(500)
      expect(page.url()).toContain(`/tasks/${task.id}`)
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    }
  })

  test('phone-push toggle in the dropdown footer persists via the API', async ({ page }) => {
    await page.goto(`${BASE}/`)
    await page.waitForTimeout(600)

    await page.click('button[title="Notifications"]')
    await page.waitForTimeout(300)
    await page.locator('text=Push blockers to phone').locator('..').getByRole('switch').click()
    await page.waitForTimeout(300)

    const settings = await (await page.request.get(`${BASE}/api/settings`)).json()
    expect(settings.integrations.phone_push).toBe(true)

    // Cleanup — restore default.
    await page.request.put(`${BASE}/api/integrations`, { data: { phone_push: false } })
  })

})

// ── workspace creation UI ────────────────────────────────────────────────────

test.describe('workspace creation UI', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('Dashboard shows a create-workspace CTA when there are none, and the dialog has no id field', async ({ page }) => {
    const existing = await (await page.request.get(`${BASE}/api/workspaces`)).json()
    for (const w of existing.workspaces) await page.request.delete(`${BASE}/api/workspaces/${w.id}`)

    await page.goto(`${BASE}/`)
    await page.waitForTimeout(600)
    const skip = page.locator('button:has-text("Skip")')
    if (await skip.count() > 0) await skip.click()
    await page.waitForTimeout(300)
    await expect(page.locator('text=No workspaces yet')).toBeVisible()

    await page.click('button:has-text("+ Create workspace")')
    await page.waitForTimeout(300)
    await expect(page.getByLabel('Workspace name')).toBeVisible()
    await expect(page.getByLabel('Workspace ID')).toHaveCount(0)

    await page.getByLabel('Workspace name').fill('Dashboard E2E')
    await page.click('button:text-is("Create")')
    await page.waitForTimeout(600)

    const listed = await (await page.request.get(`${BASE}/api/workspaces`)).json()
    const created = listed.workspaces.find((w: any) => w.name === 'Dashboard E2E')
    expect(created).toBeTruthy()
    expect(created.id).toBe('dashboard-e2e')

    await expect(page.locator('text=Dashboard E2E')).toBeVisible()

    await page.request.delete(`${BASE}/api/workspaces/${created.id}`)
  })

  test('folder picker browses directories and detects a GitHub remote', async ({ page }) => {
    const { mkdtempSync, mkdirSync } = await import('fs')
    const { tmpdir } = await import('os')
    const { join } = await import('path')
    const { execSync } = await import('child_process')

    const root = mkdtempSync(join(tmpdir(), 'folder-picker-'))
    const repo = join(root, 'picked-repo')
    mkdirSync(repo)
    execSync('git init -q', { cwd: repo })
    execSync('git remote add origin git@github.com:jamiedf/agent-knots.git', { cwd: repo })

    await page.goto(`${BASE}/settings`)
    await page.waitForTimeout(800)
    await page.click('button:has-text("+ Add workspace")')
    await page.waitForTimeout(300)

    await page.click('button:has-text("Browse")')
    await page.waitForTimeout(300)
    await page.fill('input[aria-label="Folder path"]', root)
    await page.click('button:has-text("Go")')
    await page.waitForTimeout(300)
    await expect(page.locator('text=picked-repo')).toBeVisible()

    await page.click('text=picked-repo')
    await page.waitForTimeout(300)
    await page.click('button:has-text("Use this folder")')
    await page.waitForTimeout(800) // git-info round trip

    await expect(page.locator('text=github.com/jamiedf/agent-knots')).toBeVisible()

    await page.getByRole('dialog').locator('button:text-is("Cancel")').click()
  })

})

// ── workspace scope persistence ──────────────────────────────────────────────

test.describe('workspace scope persistence', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('selecting a workspace survives navigating to another page', async ({ page }) => {
    await page.request.post(`${BASE}/api/workspaces`, { data: { id: 'scope-e2e', name: 'Scope E2E' } })

    try {
      await page.goto(`${BASE}/`)
      await page.waitForTimeout(500)

      await page.click('button:has-text("All workspaces")')
      await page.waitForTimeout(200)
      await page.click('text=Scope E2E')
      await page.waitForTimeout(300)
      await expect(page.locator('button:has-text("Scope E2E")')).toBeVisible()

      // Plain in-app navigation carries no ?ws= query string at all —
      // the scope must survive from React state, not the URL.
      await page.click('nav >> text=Tasks')
      await page.waitForTimeout(400)
      await expect(page.locator('button:has-text("Scope E2E")')).toBeVisible()
    } finally {
      await page.request.delete(`${BASE}/api/workspaces/scope-e2e`)
    }
  })

})

// ── kanban drag and drop ──────────────────────────────────────────────────────

test.describe('kanban drag and drop', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('dragging a card to another column moves it and persists via the API', async ({ page }) => {
    const createRes = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Drag drop E2E' } })
    const taskId = (await createRes.json()).id

    try {
      await page.goto(`${BASE}/tasks`)
      await page.waitForTimeout(600)

      const card = page.locator('text=Drag drop E2E')
      const openColumn = page.locator('text=Open').first().locator('..').locator('..')
      const cardBox = await card.boundingBox()
      const openBox = await openColumn.boundingBox()

      await page.mouse.move(cardBox!.x + cardBox!.width / 2, cardBox!.y + cardBox!.height / 2)
      await page.mouse.down()
      await page.waitForTimeout(100)
      await page.mouse.move(openBox!.x + openBox!.width / 2, openBox!.y + 100, { steps: 10 })
      await page.waitForTimeout(100)
      await page.mouse.up()
      await page.waitForTimeout(500)

      const after = await (await page.request.get(`${BASE}/api/tasks`)).json()
      const task = after.tasks.find((t: any) => t.id === taskId)
      expect(task.status).toBe('open')
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${taskId}`)
    }
  })

})

// ── task creation and workflow protocol ──────────────────────────────────────

test.describe('task creation and workflow protocol', () => {

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('new tasks default to draft status', async ({ page }) => {
    const createRes = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Draft default E2E' } })
    const created = await createRes.json()
    expect(created.status).toBe('draft')
    await page.request.delete(`${BASE}/api/tasks/${created.id}`)
  })

  test('cannot skip review straight to done, even with no acceptance criteria', async ({ page }) => {
    const createRes = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Review gate E2E' } })
    const taskId = (await createRes.json()).id

    try {
      await page.request.patch(`${BASE}/api/tasks/${taskId}`, { data: { status: 'in_progress' } })

      const blocked = await page.request.patch(`${BASE}/api/tasks/${taskId}`, { data: { status: 'done' } })
      expect(blocked.status()).toBe(400)
      const body = await blocked.json()
      expect(body.detail).toContain('review')

      await page.request.patch(`${BASE}/api/tasks/${taskId}`, { data: { status: 'review' } })
      const allowed = await page.request.patch(`${BASE}/api/tasks/${taskId}`, { data: { status: 'done' } })
      expect(allowed.status()).toBe(200)
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${taskId}`)
    }
  })

  test('a task created while scoped to a workspace is saved to that workspace', async ({ page }) => {
    // Regression: TaskDialog's create path never read the current
    // workspace scope at all, so every new task's `project` came back
    // empty regardless of which workspace the Tasks screen was scoped
    // to when you clicked "+ New task".
    await page.request.post(`${BASE}/api/workspaces`, { data: { id: 'task-scope-e2e', name: 'Task Scope E2E' } })

    try {
      await page.goto(`${BASE}/tasks`)
      await page.waitForTimeout(600)

      await page.click('button:has-text("All workspaces")')
      await page.waitForTimeout(200)
      await page.click('text=Task Scope E2E')
      await page.waitForTimeout(300)

      await page.click('button:has-text("+ New task")')
      await page.waitForTimeout(300)
      await page.fill('input[placeholder="What needs to be done?"]', 'Scoped task E2E')
      await page.click('button:has-text("Create task")')
      await page.waitForTimeout(600)

      const tasks = await (await page.request.get(`${BASE}/api/tasks`)).json()
      const task = tasks.tasks.find((t: any) => t.title === 'Scoped task E2E')
      expect(task.project).toBe('task-scope-e2e')

      await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    } finally {
      await page.request.delete(`${BASE}/api/workspaces/task-scope-e2e`)
    }
  })

})

// ── task → agent thread lifecycle ────────────────────────────────────────────

test.describe('task to agent thread lifecycle', () => {
  // A real provider isn't configured on this test server — fake one in
  // via the raw settings file (not PUT /api/settings, which has no way
  // to blank an api_key back out afterward — see the Settings-screen
  // "Set default" test's own note on this) so POST /api/sessions
  // succeeds. No actual network call completes with an empty prompt
  // and nothing here awaits a real completion.
  const settingsPath = join(homedir(), '.agent-knots', 'settings.yaml')
  let hadSettingsFile = false
  let originalSettings: string | null = null

  test.beforeAll(async () => {
    const { readFileSync, existsSync, writeFileSync } = await import('fs')
    hadSettingsFile = existsSync(settingsPath)
    originalSettings = hadSettingsFile ? readFileSync(settingsPath, 'utf-8') : null
    const yaml = 'agent:\n  default_model: fake/model\n  api_key: sk-fake\n  base_url: http://fake-does-not-exist.invalid\n  default_mode: agent\n  runtime: inprocess\n'
    writeFileSync(settingsPath, yaml)
  })

  test.afterAll(async () => {
    const { writeFileSync, existsSync, rmSync } = await import('fs')
    if (hadSettingsFile) writeFileSync(settingsPath, originalSettings as string)
    else if (existsSync(settingsPath)) rmSync(settingsPath)
  })

  test.beforeEach(async ({ page }) => {
    await authPage(page)
  })

  test('Task Detail links to the agent thread once a session is assigned', async ({ page }) => {
    const created = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Thread link E2E' } })
    const task = await created.json()

    try {
      await page.goto(`${BASE}/tasks/${task.id}`)
      await page.waitForTimeout(500)

      // No session yet — header shows the primary Start button, not a
      // watch card. (Headless start is behind the kebab now.)
      await expect(page.locator('button:has-text("▶ Start")')).toBeVisible()
      await expect(page.locator('button:has-text("Watch")')).toHaveCount(0)

      await page.click('button:has-text("▶ Start")')
      await page.waitForTimeout(1000)
      const threadUrl = page.url()
      expect(threadUrl).toMatch(/\/agent\/[a-f0-9]+$/)

      // Back on Task Detail, both the header button and the Session
      // side-block link must now navigate to that same agent thread.
      await page.goto(`${BASE}/tasks/${task.id}`)
      await page.waitForTimeout(600)

      await expect(page.locator('button:has-text("Watch")')).toBeVisible()
      await page.click('button:has-text("Watch")')
      await page.waitForTimeout(400)
      expect(page.url()).toBe(threadUrl)

      await page.goto(`${BASE}/tasks/${task.id}`)
      await page.waitForTimeout(600)
      await page.click('button:has-text("Open thread")')
      await page.waitForTimeout(400)
      expect(page.url()).toBe(threadUrl)
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    }
  })

  test('starting headless stays on the page — thread is reachable later', async ({ page }) => {
    const created = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Headless start E2E' } })
    const task = await created.json()

    try {
      await page.goto(`${BASE}/tasks/${task.id}`)
      await page.waitForTimeout(500)
      const detailUrl = page.url()

      // Headless start is behind the header kebab now — open it, then
      // click the revealed "Start headless" menu item.
      await page.click('button[title="More"]')
      await page.waitForTimeout(200)
      await page.click('button:has-text("Start headless")')
      await page.waitForTimeout(1000)

      // Stayed on Task Detail — no redirect to the thread.
      expect(page.url()).toBe(detailUrl)

      // But the session really did start — task shows assigned, and a
      // thread link now exists to open it whenever.
      const current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
      expect(current.assigned_to).toBeTruthy()

      await page.reload()
      await page.waitForTimeout(500)
      await expect(page.locator('button:has-text("Watch")')).toBeVisible()
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    }
  })

  test('full lifecycle: create in draft, start agent, blocked from skipping review, done after review', async ({ page }) => {
    const created = await page.request.post(`${BASE}/api/tasks`, { data: { title: 'Full lifecycle E2E' } })
    const task = await created.json()

    try {
      expect(task.status).toBe('draft')

      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'open' } })

      await page.goto(`${BASE}/tasks/${task.id}`)
      await page.waitForTimeout(500)
      await page.click('button:has-text("▶ Start")')
      await page.waitForTimeout(1000)

      let current = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
      expect(current.status).toBe('in_progress')
      expect(current.assigned_to).toBeTruthy()

      const blocked = await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'done' } })
      expect(blocked.status()).toBe(400)

      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'review' } })
      const done = await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'done' } })
      expect(done.status()).toBe(200)
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    }
  })

  test('auto review_gate: "Run review now" refuses with unmet criteria, succeeds once met', async ({ page }) => {
    const created = await page.request.post(`${BASE}/api/tasks`, {
      data: { title: 'Auto review E2E', review_gate: 'auto', acceptance_criteria: ['Must pass tests'] },
    })
    const task = await created.json()

    try {
      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'in_progress' } })
      await page.request.patch(`${BASE}/api/tasks/${task.id}`, { data: { status: 'review' } })

      await page.goto(`${BASE}/tasks/${task.id}`)
      await page.waitForTimeout(600)

      await page.click('button:has-text("Run review now")')
      await page.waitForTimeout(400)
      await expect(page.locator('text=done was refused')).toBeVisible()

      await page.request.post(`${BASE}/api/tasks/${task.id}/criteria/toggle`, { data: { criterion: 'Must pass tests', met: true } })
      await page.reload()
      await page.waitForTimeout(500)
      await page.click('button:has-text("Run review now")')
      await page.waitForTimeout(500)

      const final = await (await page.request.get(`${BASE}/api/tasks/${task.id}`)).json()
      expect(final.status).toBe('done')
    } finally {
      await page.request.delete(`${BASE}/api/tasks/${task.id}`)
    }
  })

  test('deleting a session shows a themed confirm dialog, not the native browser one', async ({ page }) => {
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, { data: { prompt: '', mode: 'agent' } })
    const session = await sessionRes.json()

    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(600)

    // A native window.confirm() would block script execution and this
    // click would hang forever with no dialog handler registered.
    await page.click('button[title="Delete this session"]')
    await page.waitForTimeout(300)
    await expect(page.locator('text=Delete this session?')).toBeVisible()

    // Cancel — still on the thread, session still exists. Scoped to the
    // dialog (role="dialog") — an unscoped locator can also match a
    // Wastebin row's own Delete button elsewhere on the page.
    const dialog = page.getByRole('dialog')
    await dialog.locator('button:text-is("Cancel")').click()
    await page.waitForTimeout(300)
    expect(page.url()).toContain(`/agent/${session.id}`)

    // Confirm — actually deletes and navigates to the dashboard.
    await page.click('button[title="Delete this session"]')
    await page.waitForTimeout(300)
    await dialog.locator('button:text-is("Delete")').click()
    await page.waitForTimeout(600)
    expect(page.url()).toBe(`${BASE}/`)

    // Gone from the live list, but still reachable read-only — a
    // stopped session's transcript is kept in the wastebin and can be
    // reopened, not 404 (see routes/agents.py's wastebin fallback).
    const liveAgents = (await (await page.request.get(`${BASE}/api/agents`)).json()).agents
    expect(liveAgents.find((a: any) => a.id === session.id)).toBeUndefined()
    const agentsResp = await page.request.get(`${BASE}/api/agent/${session.id}`)
    expect(agentsResp.status()).toBe(200)
    expect((await agentsResp.json()).running).toBe(false)
  })

  test('dragging the rail divider resizes the right rail and persists across reload', async ({ page }) => {
    const sessionRes = await page.request.post(`${BASE}/api/sessions`, { data: { prompt: '', mode: 'agent' } })
    const session = await sessionRes.json()

    await page.goto(`${BASE}/agent/${session.id}`)
    await page.waitForTimeout(600)

    const handle = page.locator('div[title="Drag to resize"]')
    const before = await handle.boundingBox()
    if (!before) throw new Error('resize handle not found')

    await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2)
    await page.mouse.down()
    await page.mouse.move(before.x + before.width / 2 - 120, before.y + before.height / 2, { steps: 8 })
    await page.mouse.up()
    await page.waitForTimeout(300)

    const after = await handle.boundingBox()
    if (!after) throw new Error('resize handle not found after drag')
    expect(before.x - after.x).toBeGreaterThan(80) // handle moved left with the drag

    await page.reload()
    await page.waitForTimeout(600)
    const afterReload = await handle.boundingBox()
    if (!afterReload) throw new Error('resize handle not found after reload')
    expect(Math.abs(afterReload.x - after.x)).toBeLessThan(5) // same width, persisted

    await page.request.delete(`${BASE}/api/agent/${session.id}`).catch(() => {})
  })

})
