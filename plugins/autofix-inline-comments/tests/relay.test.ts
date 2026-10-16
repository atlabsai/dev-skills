import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

const PR_URL = 'https://github.com/acme/app/pull/12'
const POLL_MS = 3 * 60_000
const SIGNED = '_🤖 Addressed by [Claude Code](https://claude.com/claude-code)_'

type FakeComment = { id: number; login: string; body: string }
type FakeThread = { id: string; isResolved?: boolean; comments: FakeComment[] }

function graphqlPage(threads: FakeThread[]): string {
  return JSON.stringify({
    data: {
      viewer: { login: 'me' },
      repository: {
        pullRequest: {
          state: 'OPEN',
          reviewThreads: {
            pageInfo: { hasNextPage: false, endCursor: null },
            nodes: threads.map(thread => ({
              id: thread.id,
              isResolved: thread.isResolved ?? false,
              isOutdated: false,
              path: 'src/app.ts',
              line: 7,
              originalLine: 7,
              comments: {
                nodes: thread.comments.map(comment => ({
                  databaseId: comment.id,
                  author: { login: comment.login },
                  body: comment.body,
                  url: `${PR_URL}#discussion_r${comment.id}`,
                })),
              },
            })),
          },
        },
      },
    },
  })
}

// The world beneath the plugin: the PR monitor, gh, and the session's sinks.
function world(on: On, state: { isAutoFixOn: boolean; threads: FakeThread[] }) {
  const submitted: string[] = []
  const ghCalls: string[][] = []
  const clock = mock.clock(on)
  mock.store(on)
  mock.env(on, {})
  on('tool.call', { tool: 'mcp__ccd_pr__get_status' }, () => {
    const text = JSON.stringify({ bound: true, pr: { url: PR_URL }, monitor: { auto_fix: state.isAutoFixOn } })
    return { result: text, text }
  })
  on('process.run', ($, e) => {
    ghCalls.push([...e.argv])
    return { value: { exitCode: 0, stdout: graphqlPage(state.threads), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('prompt.submit', ($, e) => {
    submitted.push(e.context ? `${e.text}\n---\n${e.context.join('\n')}` : e.text)
    return { text: e.text, context: e.context }
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  return { submitted, ghCalls, clock }
}

test('a poll surfaces new inline threads once, skipping ignored bots and resolved threads', async ($, on) => {
  const state = {
    isAutoFixOn: true,
    threads: [
      { id: 'T1', comments: [{ id: 1, login: 'reviewer', body: 'Rename this.' }] },
      { id: 'T2', comments: [{ id: 2, login: 'atlabs-ciel', body: 'Preview rebuilt.' }] },
      { id: 'T3', isResolved: true, comments: [{ id: 3, login: 'reviewer', body: 'Done already.' }] },
    ],
  }
  const { submitted, clock } = world(on, state)
  await $.session.start({ cwd: '/repo', surface: null, isInteractive: true })

  await clock.advance(POLL_MS)
  expect(submitted.length).toBe(1)
  expect(submitted[0]).toContain('Rename this.')
  expect(submitted[0]).not.toContain('Preview rebuilt.')
  expect(submitted[0]).not.toContain('Done already.')

  await clock.advance(POLL_MS)
  expect(submitted.length).toBe(1)

  // A reviewer's follow-up resurfaces the thread.
  state.threads[0]!.comments.push({ id: 5, login: 'reviewer', body: 'Also the test.' })
  await clock.advance(POLL_MS)
  expect(submitted.length).toBe(2)
  expect(submitted[1]).toContain('Also the test.')
})

test('your own comments surface; signed replies under your login do not', async ($, on) => {
  const state: { isAutoFixOn: boolean; threads: FakeThread[] } = {
    isAutoFixOn: true,
    threads: [{ id: 'T1', comments: [{ id: 1, login: 'me', body: 'Should these be typed?' }] }],
  }
  const { submitted, clock } = world(on, state)
  await $.session.start({ cwd: '/repo', surface: null, isInteractive: true })

  await clock.advance(POLL_MS)
  expect(submitted.length).toBe(1)
  expect(submitted[0]).toContain('Should these be typed?')

  state.threads[0]!.comments.push({ id: 7, login: 'me', body: `Done in def456.\n\n${SIGNED}` })
  await clock.advance(POLL_MS)
  expect(submitted.length).toBe(1)

  state.threads[0]!.comments.push({ id: 6, login: 'me', body: 'No, use a union.' })
  await clock.advance(POLL_MS)
  expect(submitted.length).toBe(2)
  expect(submitted[1]).toContain('No, use a union.')
})

test('nothing is fetched while Auto-fix is off', async ($, on) => {
  const state = { isAutoFixOn: false, threads: [{ id: 'T1', comments: [{ id: 1, login: 'reviewer', body: 'Hi.' }] }] }
  const { submitted, ghCalls, clock } = world(on, state)
  await $.session.start({ cwd: '/repo', surface: null, isInteractive: true })
  await clock.advance(POLL_MS)
  expect(ghCalls.length).toBe(0)
  expect(submitted.length).toBe(0)
})

test('an Auto-fix wake carries every unresolved inline thread as context', async ($, on) => {
  const state = { isAutoFixOn: true, threads: [{ id: 'T1', comments: [{ id: 1, login: 'reviewer', body: 'Null check here.' }] }] }
  const { submitted } = world(on, state)
  await $.prompt.submit({ text: '<ci-monitor-event>checks failed</ci-monitor-event>', wait: false, origin: { kind: 'composer' } })
  expect(submitted.length).toBe(1)
  expect(submitted[0]).toContain('checks failed')
  expect(submitted[0]).toContain('Null check here.')
})

// What reaches Bash, and the files the guard reads and writes, beneath it.
function shell(on: On, files: Record<string, string> = {}, env: Record<string, string> = {}) {
  const ran: string[] = []
  mock.env(on, env)
  on('tool.call', { tool: 'Bash' }, ($, e) => {
    ran.push(e.command)
    return { result: { stdout: '', stderr: '', interrupted: false }, text: '' }
  })
  on('fs.read', ($, e) => (e.path in files ? { value: files[e.path]! } : { deny: 'missing' }))
  on('fs.write', ($, e) => {
    files[e.path] = e.text
    return { value: undefined }
  })
  return { ran, files }
}

test('the guard signs an inline body, a heredoc and a body file, and blocks what it cannot sign', async ($, on) => {
  const { ran, files } = shell(on, { '/tmp/reply.md': 'Fixed in abc.\n' })

  await $.tool.call({ tool: 'Bash', command: "gh api repos/{owner}/{repo}/pulls/12/comments/1/replies -f body='Fixed, it'\\''s typed now.'" })
  expect(ran[0]).toBe(`'gh' 'api' 'repos/{owner}/{repo}/pulls/12/comments/1/replies' '-f' 'body=Fixed, it'\\''s typed now.\n\n${SIGNED}'`)

  await $.tool.call({ tool: 'Bash', command: `gh pr comment 12 --body "$(cat <<'EOF'\nDone.\nEOF\n)"` })
  expect(ran[1]).toBe(`gh pr comment 12 --body "$(cat <<'EOF'\nDone.\n\n${SIGNED}\nEOF\n)"`)

  await $.tool.call({ tool: 'Bash', command: 'gh api repos/acme/app/pulls/12/comments/1/replies -F body=@/tmp/reply.md' })
  expect(files['/tmp/reply.md']).toBe(`Fixed in abc.\n\n${SIGNED}\n`)
  expect(ran[2]).toBe('gh api repos/acme/app/pulls/12/comments/1/replies -F body=@/tmp/reply.md')

  const blocked = await $.tool.call({ tool: 'Bash', command: 'gh pr comment 12 --body "$BODY"' })
  expect(blocked.deny).toContain(SIGNED)
  expect(ran.length).toBe(3)

  await $.tool.call({ tool: 'Bash', command: 'gh api repos/acme/app/pulls/12/comments --paginate' })
  await $.tool.call({ tool: 'Bash', command: `gh pr comment 12 --body "Thanks.\n\n${SIGNED}"` })
  expect(ran.slice(3)).toEqual(['gh api repos/acme/app/pulls/12/comments --paginate', `gh pr comment 12 --body "Thanks.\n\n${SIGNED}"`])
})

test('in GitHub Actions the guard leaves a bot\'s comment posts alone', async ($, on) => {
  const { ran } = shell(on, {}, { GITHUB_ACTIONS: 'true' })
  await $.tool.call({ tool: 'Bash', command: 'gh pr comment 12 --body "$REVIEW"' })
  await $.tool.call({ tool: 'Bash', command: "gh pr comment 12 --body 'Review: looks fine.'" })
  expect(ran).toEqual(['gh pr comment 12 --body "$REVIEW"', "gh pr comment 12 --body 'Review: looks fine.'"])
})

test('a heredoc that only mentions gh in its text is not a post', async ($, on) => {
  const { ran } = shell(on)
  const command = `cat > notes.md <<'EOF'\nRun gh pr comment 12 --body "$X" to reply.\nEOF`
  await $.tool.call({ tool: 'Bash', command })
  expect(ran).toEqual([command])
})
