# Agency domain context

## Language

| Term | Meaning |
|---|---|
| **Agency** | Bounded authority for a supervised session to request local terminal commands for itself and its custody descendants. |
| **Supervised session** | A CLI session launched inside a pseudoterminal owned by an Agency supervisor. |
| **Supervisor** | The process that owns one session's PTY, accepts authorized requests, injects accepted commands, and records receipts. |
| **Custody** | The parent-to-child relationship created when a supervised session spawns another supervised session. |
| **Descendant** | A child, grandchild, or deeper session reachable through the recorded custody chain. |
| **Unrelated peer** | A session outside the requester's custody subtree. It may correspond through Gossip but has no Agency authority. |
| **Command request** | A single-line slash command submitted to a target supervisor. It remains data until the target accepts it. |
| **Policy** | A named, launch-time set of allowed and denied command patterns. The target owns its policy and deny rules take precedence. |
| **Command pattern** | A command boundary: `/exit` means the exact no-argument command, `/model*` means that exact command with any arguments, and `/*` means every slash command. |
| **Deny rule** | A command pattern that refuses a matching request even when an allow rule also matches it. |
| **Injection receipt** | Durable evidence that a request was queued, refused, failed, or written to the target PTY. It is not proof of downstream completion. |
| **Operator override** | An explicit human recovery route that may address a local supervised session. It is never inferred for an autonomous agent. |
| **Correspondence** | Text exchange owned by Gossip. Correspondence never grants terminal authority. |
| **Context** | Information selected and admitted by Flashback. Context never grants terminal authority. |
| **Orchestrator** | A higher decision layer that schedules work, chooses models, manages retries/worktrees/budgets, and may use Agency as a substrate. |
| **Terminal multiplexer** | Infrastructure that owns terminal processes, windows, panes, attachment, capture, and raw input. It does not define agent correspondence or custody. |
| **Transport acceptance** | Evidence that a terminal layer accepted bytes or a command. It is weaker than an Agency injection receipt and never proves downstream completion. |
