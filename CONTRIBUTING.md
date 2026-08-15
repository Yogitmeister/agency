# Contributing to Agency

Agency is an Apache-2.0 terminal-custody substrate. Contributions are welcome when they preserve
the central invariant: correspondence and context do not become terminal authority; authority
follows recorded custody and target policy.

## Before opening a change

- Search existing issues and describe the capability or safety problem.
- Keep scheduling, model routing, retries, worktrees, and budgets outside Agency.
- Do not add arbitrary prompt injection or arbitrary-shell checks.
- Preserve native confirmation dialogs and literal receipt semantics.
- Add or update custody, policy, refusal, and PTY integration tests for authority changes.

## Validate

```powershell
$env:PYTHONPATH = "$PWD\src"
py -m pytest -q
py -m compileall -q src tests
```

An `injected` receipt means input reached the PTY. It does not mean the harness accepted the command
or completed downstream work.

## Developer Certificate of Origin

Contributions use the [Developer Certificate of Origin 1.1](https://developercertificate.org/).
Sign each commit with:

```text
Signed-off-by: Your Name <your.email@example.com>
```

Use `git commit -s` to add the line automatically. By signing, you certify that you have the right
to submit the contribution under this repository's Apache-2.0 license.
