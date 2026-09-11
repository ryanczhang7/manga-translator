---
description: Show the backlog, the active story and the last gate result
allowed-tools: Bash(bash scripts/phase.sh:*), Bash(git status:*), Bash(git branch:*), Read
---

Board:
!`bash scripts/phase.sh board`

Active:
!`bash scripts/phase.sh show`

Give the user a short read on where the project stands: what is in flight, what
phase it is in, what is blocked and on what, and the single next command to run.
If the last gate run failed, say so and name the gate. Keep it to a few lines —
this is a glance, not a report.
