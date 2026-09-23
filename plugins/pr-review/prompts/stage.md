Read the file `__SPEC__` — that file is your complete task
specification. Do that task yourself, directly, exactly as it
describes. You do not have the Agent tool; there is nothing to
spawn or delegate to, and nothing will resume you later. Finish the
whole task in this session.

The working directory is the repository under review, checked out
at the PR head. The full unified diff for this PR is at
__SCRATCH__/pr-context/diff.txt (read it with the Read tool; page
through with offset/limit if it is large). The PR title and body are
in __SCRATCH__/pr-context/meta.json.

__EXTRA__

The specification describes what to return (a JSON array, a JSON
object, or prose). As your LAST action, write exactly that output to
__OUT__ using the Write tool. That file is what the next pipeline
stage reads; your final chat response is discarded.
