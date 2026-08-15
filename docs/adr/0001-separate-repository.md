# ADR 0001: Keep Agency independent from Gossip and Flashback

- Status: accepted
- Date: 2026-08-15

## Context

The three products protect different trust boundaries:

- Gossip transports correspondence between independently launched sessions and harnesses.
- Flashback selects, checks, and times context admitted to a session.
- Agency writes commands into PTY-supervised terminals under explicit custody.

Terminal input is the highest-authority boundary. Combining it with peer messaging or context
retrieval in one default package would make a bridge bug capable of turning text or memory into
operator-like input. It would also add platform PTY dependencies to otherwise portable products.

## Decision

Ship Agency as an independent Apache-2.0 repository, distribution, install, and release stream.

Agency authority covers the supervised session itself and descendants recorded in its custody
chain. It never covers arbitrary Gossip peers. Gossip messages, Flashback context records, and
Agency command requests use separate code paths. No automatic bridge may upgrade one capability
into another.

Agency owns terminal mechanics, custody policy, and input receipts. It does not choose work, models,
worktrees, retries, credentials, or budgets; those decisions belong to an orchestrator.

## Consequences

### Positive

- Correspondence, context, and custody remain separately inspectable and replaceable.
- Users opt into terminal authority explicitly.
- Platform-specific PTY dependencies and tests remain isolated.
- Orchestrators can adopt Agency without adopting the sibling products.

### Negative

- The complementary stack has three repositories and install surfaces.
- Identity and lifecycle adapters require small versioned contracts.
- Collateral must distinguish Agency from a full orchestrator.

## Rejected alternatives

### Put Agency inside Gossip behind a flag

Rejected because a runtime flag is a weak boundary for a capability that can impersonate terminal
input.

### Let Flashback records or Gossip senders trigger commands automatically

Rejected because relevant information is not authorization. Custody and target policy—not address
knowledge or context relevance—govern terminal input.

### Build scheduling and model routing into Agency

Rejected because that duplicates orchestrators such as Outsourcerer and erodes Agency's small,
composable substrate position.
