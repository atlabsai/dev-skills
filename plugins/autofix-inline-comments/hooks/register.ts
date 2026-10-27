import type { EngineInterface, Register } from 'claude-code'
import {
  type Monitor,
  type PullRequest,
  type ReviewThread,
  type SurfaceRules,
  REVIEW_THREADS_QUERY,
  describeThreads,
  parseIgnoreAuthors,
  parseMonitorStatus,
  threadsWithNewComments,
  unresolvedThreads,
} from './threads'
import { CLAUDE_SIGNATURE, SIGNATURE_LINE, planSigning, signJsonPayload, signTextBody, type BodyFile } from './signing'

const COMMAND = 'inline-review'
const CI_MONITOR_EVENT = /<ci-monitor-event\b/
const MAX_PAGES = 10
// How long a prompt waits on the scan before it goes on without the threads.
const PROMPT_SCAN_MS = 4_000
const NEW_COMMENTS = 'New inline review comments that Auto-fix did not deliver'

type Config = Omit<SurfaceRules, 'viewer'>

type Scan = { pr: PullRequest; unresolved: ReviewThread[]; fresh: ReviewThread[] }

type GraphqlPage = {
  data?: {
    viewer: { login: string }
    repository: {
      pullRequest: {
        state: string
        reviewThreads: { pageInfo: { hasNextPage: boolean; endCursor: string | null }; nodes: ReviewThread[] }
      } | null
    } | null
  }
}

// One scan at a time: a poll and an Auto-fix wake landing together would
// otherwise both read the seen list before either writes it.
let inFlight: Promise<Scan | undefined> = Promise.resolve(undefined)
function scanOnce($: EngineInterface, config: Config): Promise<Scan | undefined> {
  inFlight = inFlight.catch(() => undefined).then(() => scan($, config))
  return inFlight
}

// The scan, or undefined once `ms` pass first; the scan itself runs on.
function within<T>($: EngineInterface, ms: number, work: Promise<T>): Promise<T | undefined> {
  return new Promise(resolve => {
    const timer = $.clock.after(ms, () => resolve(undefined))
    const settle = (value: T | undefined) => {
      timer.cancel()
      resolve(value)
    }
    work.then(settle, () => settle(undefined))
  })
}

// Sends the threads with new comments as a turn of their own.
async function deliver($: EngineInterface, found: Scan | undefined): Promise<void> {
  if (!found || found.fresh.length === 0) return
  await $.prompt.submit({ text: describeThreads(found.pr, found.fresh, NEW_COMMENTS) })
}

const UNSIGNABLE = `This command posts a GitHub comment from the user's account without Claude Code's footer, in a form the autofix-inline-comments guard cannot sign itself (the body comes from a variable, a pipe, a GraphQL query string, or a file this same command writes). End every comment body with this line and run it again: ${SIGNATURE_LINE}`
const SIGNED_NOTE = `The autofix-inline-comments guard appended Claude Code's footer (${SIGNATURE_LINE}) to the comment this command posted.`

// A CI job (a review bot in GitHub Actions) posts as its own bot account,
// never under the person's login: neither the guard nor the poller is for it.
async function isCi($: EngineInterface): Promise<boolean> {
  return (await $.env.get('GITHUB_ACTIONS')) === 'true'
}

// Appends the footer to a body file the post reads; false when it cannot.
async function signBodyFile($: EngineInterface, file: BodyFile): Promise<boolean> {
  const text = await $.fs.read(file.path)
  if (CLAUDE_SIGNATURE.test(text)) return true
  if (file.format === 'text') {
    await $.fs.write(file.path, signTextBody(text))
    return true
  }
  const signed = signJsonPayload(text)
  if (signed === undefined) return false
  await $.fs.write(file.path, signed)
  return true
}

async function readMonitor($: EngineInterface): Promise<Monitor | undefined> {
  const ran = await $.tool.call({ tool: 'mcp__ccd_pr__get_status' })
  if (ran.deny !== undefined || ran.isError === true) return undefined
  return parseMonitorStatus(ran.text ?? JSON.stringify(ran.result))
}

async function fetchThreads(
  $: EngineInterface,
  pr: PullRequest,
): Promise<{ state: string; viewer: string; threads: ReviewThread[] } | undefined> {
  const threads: ReviewThread[] = []
  let after: string | null = null
  for (let page = 0; page < MAX_PAGES; page++) {
    const argv = [
      'gh', 'api', 'graphql',
      '-f', `query=${REVIEW_THREADS_QUERY}`,
      '-f', `owner=${pr.owner}`,
      '-f', `repo=${pr.repo}`,
      '-F', `number=${pr.number}`,
      ...(after === null ? [] : ['-f', `after=${after}`]),
    ]
    const { exitCode, stdout, stderr } = await $.process.run(argv, { timeoutMs: 60_000 })
    if (exitCode !== 0) {
      $.ui.log(`${$.plugin.name}: gh api graphql failed: ${stderr.trim().slice(0, 300)}`)
      return undefined
    }
    const data = (JSON.parse(stdout) as GraphqlPage).data
    const pullRequest = data?.repository?.pullRequest
    if (!data || !pullRequest) return undefined
    threads.push(...pullRequest.reviewThreads.nodes)
    const { hasNextPage, endCursor } = pullRequest.reviewThreads.pageInfo
    if (!hasNextPage || endCursor === null) return { state: pullRequest.state, viewer: data.viewer.login, threads }
    after = endCursor
  }
  return undefined
}

// Reads the monitor, fetches the threads and marks every comment of the
// unresolved ones seen. Undefined when Auto-fix is off or the PR is closed.
async function scan($: EngineInterface, config: Config): Promise<Scan | undefined> {
  const monitor = await readMonitor($)
  if (!monitor?.isAutoFixOn) {
    $.ui.status(undefined)
    return undefined
  }
  const { pr } = monitor
  const seenKey = `seen:${pr.owner}/${pr.repo}#${pr.number}`
  const fetched = await fetchThreads($, pr)
  if (!fetched) return undefined
  if (fetched.state !== 'OPEN') {
    await $.store.delete(seenKey)
    $.ui.status(undefined)
    return undefined
  }

  const rules: SurfaceRules = { ...config, viewer: fetched.viewer }
  const seen = new Set(((await $.store.get(seenKey)) as number[] | undefined) ?? [])
  const unresolved = unresolvedThreads(fetched.threads, rules)
  const fresh = threadsWithNewComments(unresolved, seen, rules)

  // Only ids still on an unresolved thread are kept, so the list stays small.
  const stillOpen = unresolved.flatMap(thread => thread.comments.nodes.map(comment => comment.databaseId))
  await $.store.set(seenKey, stillOpen)
  $.ui.status(unresolved.length > 0 ? `inline review: ${unresolved.length} unresolved` : undefined)
  return { pr, unresolved, fresh }
}

export const register: Register = (on, options) => {
  const pollMs = Math.max(1, Number(options.pollMinutes ?? 3)) * 60_000
  const config: Config = {
    ignoreAuthors: parseIgnoreAuthors(String(options.ignoreAuthors ?? '')),
  }

  // Every comment Claude (or a subagent) posts from the person's account
  // through gh carries Claude Code's footer: added to the command or the
  // body file where the command's shape allows, the command refused where not.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const plan = planSigning(e.command)
    if (plan.kind === 'pass' || (await isCi($))) return next(e)
    if (plan.kind === 'block') return { deny: UNSIGNABLE }
    for (const file of plan.files) {
      if (!(await signBodyFile($, file))) return { deny: UNSIGNABLE }
    }
    const ran = await next(plan.command === undefined ? e : { ...e, command: plan.command })
    if (ran.deny !== undefined) return ran
    return { ...ran, context: [...(ran.context ?? []), SIGNED_NOTE] }
  }).catch(($, e, next) => (next.called ? next(e) : { deny: UNSIGNABLE }))

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    if (await isCi($)) return started
    await $.command.register({
      name: COMMAND,
      description: 'Fetch the unresolved inline review threads on this session\'s PR now.',
    })
    // A session the app paused and resumed polls at once, not a period later.
    const poll = async () => deliver($, await scanOnce($, config))
    $.clock.after(0, poll)
    $.clock.every(pollMs, poll)
    return started
  })

  // Whatever prompt starts a turn carries the inline comments that landed
  // since the last scan, so a session resumed by any message sees them before
  // it answers. Every Auto-fix wake carries all the unresolved threads, so the
  // turn that answers CI or a conflict sees them too. A scan slower than
  // PROMPT_SCAN_MS lets the prompt through bare and delivers on its own.
  on('prompt.submit', async ($, e, next) => {
    if (e.origin.kind === 'plugin' && e.origin.name === $.plugin.name) return next(e)
    const scanning = scanOnce($, config)
    const found = await within($, PROMPT_SCAN_MS, scanning)
    if (!found) {
      void scanning.then(late => deliver($, late)).catch(() => undefined)
      return next(e)
    }
    const isWake = CI_MONITOR_EVENT.test(e.text)
    const threads = isWake ? found.unresolved : found.fresh
    if (threads.length === 0) return next(e)
    const context = describeThreads(found.pr, threads, isWake ? 'Unresolved inline review threads' : NEW_COMMENTS)
    return next({ ...e, context: [...(e.context ?? []), context] })
  }).catch(($, e, next) => next(e))

  on('command.run', { command: COMMAND }, async $ => {
    const found = await scanOnce($, config)
    if (!found) return { text: 'Auto-fix is off, no PR is bound to this session, or its PR is closed.' }
    if (found.unresolved.length === 0) return { text: `No unresolved inline review threads on ${found.pr.url}.` }
    return { text: describeThreads(found.pr, found.unresolved, 'Unresolved inline review threads') }
  })
}
