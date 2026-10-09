import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { CiState, PrChip, PrState } from '../types'

const pr = atom({ plugin: 'pr-band', key: 'pr' } as const, null)
const isHidden = atom({ plugin: 'pr-band', key: 'isHidden' } as const, false)

type Check = { conclusion?: string; status?: string; state?: string }

type GhPrView = {
  number: number
  title: string
  url: string
  headRefName: string
  author: { login: string }
  createdAt: string
  additions: number
  deletions: number
  changedFiles: number
  state: 'OPEN' | 'CLOSED' | 'MERGED'
  statusCheckRollup?: Check[]
}

const FAILED = new Set([
  'FAILURE',
  'ERROR',
  'CANCELLED',
  'TIMED_OUT',
  'ACTION_REQUIRED',
  'STARTUP_FAILURE',
])
const PENDING_STATES = new Set(['PENDING', 'EXPECTED'])

const CI_COLOR: Record<CiState, string> = {
  pass: 'green',
  fail: 'red',
  pending: 'yellow',
  none: 'gray',
}
const PILL_BG = '#2a2a2a'
const TOOLTIP_BG = '#1e1e1e'
const REFRESH_MS = 5 * 60_000
// No polling once the session has been idle this long (overnight, say); the
// next prompt refreshes and wakes it.
const IDLE_STOP_MS = 30 * 60_000

const GH_STATE: Record<GhPrView['state'], PrState> = {
  OPEN: 'open',
  MERGED: 'merged',
  CLOSED: 'closed',
}

/** Lucide icons (ISC): git-pull-request, git-merge, git-pull-request-closed. */
const ICON_PATHS: Record<PrState, string> = {
  open:
    '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/>' +
    '<path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" x2="6" y1="9" y2="21"/>',
  merged:
    '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/>' +
    '<path d="M6 21V9a9 9 0 0 0 9 9"/>',
  closed:
    '<circle cx="6" cy="6" r="3"/><path d="M6 9v12"/><path d="m21 3-6 6"/>' +
    '<path d="m21 9-6-6"/><path d="M18 11.5V15"/><circle cx="18" cy="18" r="3"/>',
}

/** The app popup's state pill: label, terminal colour, SVG stroke, pill tint. */
const STATE_STYLE: Record<PrState, { label: string; text: string; stroke: string; bg: string }> = {
  open: { label: 'Open', text: 'green', stroke: '#3fb950', bg: '#1d3b2a' },
  merged: { label: 'Merged', text: 'magenta', stroke: '#a371f7', bg: '#2e2347' },
  closed: { label: 'Closed', text: 'red', stroke: '#f85149', bg: '#3b1d1d' },
}

function iconSvg(state: PrState): string {
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
    `stroke="${STATE_STYLE[state].stroke}" stroke-width="2" stroke-linecap="round" ` +
    `stroke-linejoin="round">${ICON_PATHS[state]}</svg>`
  )
}

const DEMO: PrChip = {
  number: 42,
  title: 'feat(search): filter results by date range',
  url: 'https://github.com/octo-org/octo-repo/pull/42',
  state: 'open',
  owner: 'octo-org',
  repo: 'octo-repo',
  branch: 'feature/search-date-filter',
  author: 'octocat',
  createdAt: '2026-10-05T12:00:00Z',
  additions: 8542,
  deletions: 132,
  changedFiles: 33,
  ci: 'pass',
}

function ciState(checks: Check[]): CiState {
  if (checks.length === 0) return 'none'
  const results = checks.map(c => (c.conclusion || c.state || '').toUpperCase())
  if (results.some(r => FAILED.has(r))) return 'fail'
  const isRunning = checks.some(
    c =>
      (c.status !== undefined && c.status !== 'COMPLETED') ||
      PENDING_STATES.has((c.state || '').toUpperCase()),
  )
  return isRunning ? 'pending' : 'pass'
}

/** `https://github.com/<owner>/<repo>/pull/<n>` -> `{ owner, repo }`. */
function ownerRepoFromPrUrl(url: string): { owner: string; repo: string } {
  const [, , , owner, repo] = url.split('/')
  return { owner: owner ?? '', repo: repo ?? '' }
}

/** `19h ago`, the largest whole unit, like the app's PR popup. */
function ago(iso: string, nowMs: number): string {
  const seconds = Math.max(0, Math.round((nowMs - Date.parse(iso)) / 1000))
  const units: [string, number][] = [['d', 86400], ['h', 3600], ['m', 60]]
  for (const [unit, size] of units) {
    if (seconds >= size) return `${Math.floor(seconds / size)}${unit} ago`
  }
  return 'just now'
}

function toChip(view: GhPrView): PrChip {
  return {
    number: view.number,
    title: view.title,
    url: view.url,
    state: GH_STATE[view.state],
    ...ownerRepoFromPrUrl(view.url),
    branch: view.headRefName,
    author: view.author.login,
    createdAt: view.createdAt,
    additions: view.additions,
    deletions: view.deletions,
    changedFiles: view.changedFiles,
    ci: ciState(view.statusCheckRollup ?? []),
  }
}

let latestRefresh = 0
let isRefreshing = false
// /pr-band-demo pins sample data until /pr-band; refreshes leave it alone.
let isDemo = false
let poll: Timer | null = null
let lastActiveMs = 0

/** Re-reads the branch's PR. Never rejects (callers fire and forget): "no PR"
 * clears the chip, any other failure keeps the last one, and a newer call wins. */
async function refresh($: EngineInterface): Promise<void> {
  if (isDemo) return
  const mine = ++latestRefresh
  isRefreshing = true
  try {
    const { exitCode, stdout, stderr } = await $.process.run([
      'gh', 'pr', 'view', '--json',
      'number,title,url,headRefName,author,createdAt,additions,deletions,'
        + 'changedFiles,state,statusCheckRollup',
    ])
    if (mine !== latestRefresh) return
    if (exitCode !== 0) {
      if (/no (open )?pull requests? found/i.test(stderr)) {
        await update($, pr, () => null)
      }
      return
    }
    const chip = toChip(JSON.parse(stdout) as GhPrView)
    // A merged/closed PR stays only if it is the one already shown: a reused
    // branch name must not resurface an old PR.
    const shown = await read($, pr)
    const isKept = chip.state === 'open' || shown?.number === chip.number
    await update($, pr, () => (isKept ? chip : null))
  } catch {
    // gh missing or unreadable output: keep whatever the chip last showed.
  } finally {
    if (mine === latestRefresh) isRefreshing = false
  }
}

/** The periodic tick: skipped while a refresh runs, for a demo, hidden or
 * merged/closed chip, and after IDLE_STOP_MS without activity. */
async function tick($: EngineInterface): Promise<void> {
  if (isRefreshing || isDemo || (await read($, isHidden))) return
  if ((await $.clock.now()) - lastActiveMs > IDLE_STOP_MS) return
  const shown = await read($, pr)
  if (shown !== null && shown.state !== 'open') return
  await refresh($)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    lastActiveMs = await $.clock.now()
    await $.command.register({
      name: 'pr-band',
      description: "Show this branch's PR chip again and refresh it",
    })
    await $.command.register({
      name: 'pr-band-demo',
      description: 'Fill the PR chip with demo data',
    })
    void refresh($)
    // Between turns too, so a merge or new CI result shows without a message.
    poll?.cancel()
    poll = $.clock.every(REFRESH_MS, () => {
      void tick($)
    })
    return started
  })

  on('prompt.submit', async ($, e, next) => {
    lastActiveMs = await $.clock.now()
    return next(e)
  })

  on('command.run', { command: 'pr-band' }, async $ => {
    lastActiveMs = await $.clock.now()
    isDemo = false
    await update($, isHidden, () => false)
    await refresh($)
    return { text: (await read($, pr)) ? 'PR chip refreshed.' : 'No PR on this branch.' }
  })

  on('command.run', { command: 'pr-band-demo' }, async $ => {
    isDemo = true
    await update($, isHidden, () => false)
    await update($, pr, () => DEMO)
    return { text: 'PR chip showing demo data; /pr-band restores the real PR.' }
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    lastActiveMs = await $.clock.now()
    void refresh($)
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const chip = await read($, pr)
    if (e.props.hasSurvey || chip === null || (await read($, isHidden))) {
      return next(e)
    }

    const { Box, Button, Link, Svg, Text } = $.ui.resolve(e)
    const age = ago(chip.createdAt, await $.clock.now())
    // Svg exists on the desktop, editor and mobile surfaces; the terminal
    // refuses a tree that uses it, so it keeps the glyph.
    const style = STATE_STYLE[chip.state]
    const prIcon =
      e.surface === 'terminal' ? (
        <Text color={style.text}>⎇</Text>
      ) : (
        <Svg source={iconSvg(chip.state)} alt={`${style.label} pull request`} width={14} height={14} />
      )

    return (
      <Box
        key="pr-chip"
        position="relative"
        flexDirection="row"
        alignItems="center"
        justifyContent="space-between"
        paddingX={1}
        gap={1}
      >
        <Box flexDirection="row" alignItems="center" gap={1} flexShrink={1}>
          {prIcon}
          <Link href={chip.url} label={`#${chip.number}`} />
          <Text dimColor>{chip.repo}</Text>
          <Box backgroundColor={PILL_BG} paddingX={1} flexShrink={1}>
            <Text wrap="truncate-end">{chip.branch}</Text>
          </Box>
        </Box>
        <Box flexDirection="row" alignItems="center" gap={1}>
          <Box backgroundColor={PILL_BG} paddingX={1}>
            <Text color="green">+{chip.additions.toLocaleString('en-US')}</Text>
            <Text> </Text>
            <Text color="red">−{chip.deletions.toLocaleString('en-US')}</Text>
          </Box>
          <Box backgroundColor={PILL_BG} paddingX={1}>
            <Text color={CI_COLOR[chip.ci]}>●</Text>
            <Text> CI</Text>
          </Box>
          <Button key="hide" label="×" onPress={() => update($, isHidden, () => true)} />
        </Box>
        <Box
          position="absolute"
          bottom={3}
          left={2}
          width={60}
          display="none"
          hover={{ display: 'flex' }}
          flexDirection="column"
          gap={1}
          borderStyle="round"
          borderColor="gray"
          backgroundColor={TOOLTIP_BG}
          paddingX={1}
        >
          <Box flexDirection="row" alignItems="center" justifyContent="space-between" gap={1}>
            <Box flexDirection="row" alignItems="center" gap={1} flexShrink={1}>
              <Box
                backgroundColor={style.bg}
                paddingX={1}
                flexDirection="row"
                alignItems="center"
                gap={1}
                flexShrink={0}
              >
                {prIcon}
                <Text color={style.text}>{style.label}</Text>
              </Box>
              <Text dimColor wrap="truncate-end">
                {chip.owner}/{chip.repo} #{chip.number}
              </Text>
            </Box>
            <Box flexDirection="row" alignItems="center" gap={1} flexShrink={0}>
              <Text dimColor>{age}</Text>
              <Button key="refresh" label="↻" onPress={() => refresh($)} />
            </Box>
          </Box>
          <Text>{chip.title}</Text>
          <Box flexDirection="row" justifyContent="space-between" gap={1}>
            <Text dimColor>{chip.author}</Text>
            <Box flexDirection="row" gap={1}>
              <Box backgroundColor={PILL_BG} paddingX={1}>
                <Text color="green">+{chip.additions.toLocaleString('en-US')}</Text>
                <Text color="red">−{chip.deletions.toLocaleString('en-US')}</Text>
              </Box>
              <Box backgroundColor={PILL_BG} paddingX={1}>
                <Text dimColor>{chip.changedFiles} files</Text>
              </Box>
            </Box>
          </Box>
        </Box>
      </Box>
    )
  })
}
