---
description: Work your Unizo review queue - Investigations awaiting review, mine or unclaimed (W1)
argument-hint: "[mine | unclaimed] [crown] [kev] [INV-id]"
---

Work the user's review queue with the `unizo-review-queue` skill.

Arguments: `$ARGUMENTS`

- `mine` (default) or `unclaimed` picks whose Investigations to list. With neither, list mine, then unclaimed.
- `crown` keeps only Investigations whose Exposure reaches a crown jewel.
- `kev` keeps only those whose Exposure's CVE is on the CISA KEV list.
- An Investigation ID (e.g. `INV-2214`) skips the queue and goes straight to reading that one.

Follow the skill's steps in order: queue, read, take, weigh, re-draft if none fits, choose, check and commit.
Read before claiming, and claim only when the user decides to work it. Confirm with the user before every
write, and never commit an action until `preview_commit` has been shown for it.
