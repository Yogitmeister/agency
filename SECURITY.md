# Security model

Agency controls terminal input. Treat it as a local privileged tool.

## Trust boundary

- Agency runs as the same OS user as the supervised sessions.
- It is designed to prevent accidental cross-session control and prompt-origin confusion, not to
  isolate mutually hostile processes running as the same OS account.
- A session can act on itself and descendants in its recorded custody chain.
- An unrelated Gossip peer has no terminal authority.
- `--operator` is an explicit human override and must never be added to autonomous agent defaults.

## Command boundary

- Only one-line slash commands are accepted.
- The bundled JSON `context` policy allows read-only context/usage commands and `/compact`.
- `self-manage` also allows `/model*`, `/effort*`, `/fast*`, `/plan*`, `/rename*`, `/tasks*`,
  `/reload-skills`, and `/exit`. Selecting it grants authority to change runtime cost, capability,
  mode, identity, and lifecycle within the harness's own confirmation rules.
- `all-slash` must be selected at target launch and exposes every local slash command supported by
  that harness.
- `/command*` means that exact command with any arguments; it does not match another command whose
  name shares the prefix. `/*` matches every normalized slash command.
- Each JSON profile has `allow` and `deny` arrays. Deny rules win, including over `/*`.
- Agency does not define allowed model names or `/model` arguments. Operators may replace the
  bundled profiles with `--policy-file` and their own command boundary.
- `--operator` is refused inside a supervised session. It is a local-console escape hatch, not an
  autonomous-session capability.
- Arbitrary prompt text is rejected.
- A target supervisor enforces its own policy. The requester cannot widen it.

Some slash commands may change configuration, permissions, authentication, external connectivity,
spend, or process state. The `all-slash` policy is therefore equivalent to granting the session
access to the harness's full local command surface. It does not manufacture human authorization for
those actions; the session's instructions and native confirmation dialogs still apply.

## Receipts

An `injected` receipt means the supervisor wrote the command and Enter to the target PTY. It does
not prove the TUI accepted the command, that a confirmation dialog completed, or that downstream
work succeeded. Consumers must not upgrade that receipt into a stronger claim.

## Reporting

Open a GitHub issue without secrets, tokens, private transcripts, or command payloads that disclose
sensitive data. This Apache-2.0 project has no security SLA.
