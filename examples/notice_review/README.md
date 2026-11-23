# Notice before termination

This fictional closed matter covers two shipments and a disputed receipt. The first production contains a sent notice, an identical copy, testimony, a record for a different shipment and the termination notice. The supplement supplies one additional document.

1. Copy the contents of `first-production/` to an authorized matter folder. In Configure, use that folder as the legal documents folder and this example's `matter.json` as the separate counsel intake. Run the co-worker. Keep the same matter and folder for the second run.
2. Ask the first reviewer to use co-worker Chat to investigate receipt for shipment A before termination. Have them record the cutoff and its source, capture the competing accounts in the report, prepare a witness question and assign any missing record. Include the question with the owner working copy in the team's authorized handoff.
3. Have the second reviewer independently reopen each citation, identify the contrary passage, and say which shipment each exhibit addresses. Record elapsed time and each wrong document, version, page or passage.
4. Export review decisions. Copy `supplement/acknowledgment.txt` into the same working matter folder. Configure the exported JSON as **Previous review decisions** and run the same co-worker again. Have the second reviewer ask the same question in Chat about the new run, inspect the affected draft, and decide whether to close the assigned discovery item.
5. To measure the improvement, have a second pair perform the same tasks in the earlier report, or counterbalance the order with an equivalent matter. Record time to answer and time to verify separately. Report the citation error counts and unresolved questions alongside the timings.

The first production's email asks for acknowledgment. The witness denies receipt of A, and the signed record in that production concerns B. The supplement includes a signed statement about A dated April 25, 2024. The termination record gives May 10, 2024. The contrary testimony remains part of the record.

For an automated run, use the blueprint's Python environment with its declared dependencies, a Node environment with Playwright and its Chromium browser, and a disposable directory:

```sh
python tests/test_casework.py /tmp/notice-pilot/first
PILOT_PYTHON="$(command -v python)" node tests/review_pilot.cjs /tmp/notice-pilot
```

The browser opens the actual HTML report, creates and exports the first review, republishes with the supplement, and verifies the handoff, passages, Word and CSV outputs offline.

