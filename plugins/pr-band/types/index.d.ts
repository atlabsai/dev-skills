export type CiState = 'pass' | 'fail' | 'pending' | 'none'

export type PrState = 'open' | 'merged' | 'closed'

export type PrChip = {
  number: number
  title: string
  url: string
  state: PrState
  owner: string
  repo: string
  branch: string
  author: string
  createdAt: string
  additions: number
  deletions: number
  changedFiles: number
  ci: CiState
}

declare module 'claude-code' {
  interface PluginState {
    'pr-band': { pr: PrChip | null; isHidden: boolean }
  }
}
