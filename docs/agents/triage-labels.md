# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## Scope labels

Every open issue also carries one scope label. These sit alongside the triage labels: triage says how ready an issue is, and scope says whether it matters yet.

| Label   | Meaning                                                                   |
| ------- | ------------------------------------------------------------------------- |
| `core`  | Needed for a usable base product: the core loop working and checked in game |
| `later` | An improvement or addition. Don't build it until the `core` queue is empty |

New issues default to `later`. An issue is `core` only if the Addon or Brain is broken or unusable without it; the user decides the borderline cases.
