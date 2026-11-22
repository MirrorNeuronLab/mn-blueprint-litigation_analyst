# Litigation Analyst user manual

## Getting started and reviewing work

I organize approved matter documents into draft findings, timelines and competing explanations so counsel can inspect the evidence and decide what to investigate next.

Choose an authorized legal-document or email folder, or the offered public sample. A clear question, handling scope and exclusions help focus the review. Counsel matter intake and prior review decisions are optional existing inputs; they are not required just to try the first pass. Do not paste privileged documents into ordinary conversation.

Expect final_report.md, source-linked findings and an audit trail; a published offline investigation view helps inspect support, contradictions, relationships and chronology. All findings are drafts for human legal review. A relationship or co-occurrence is an investigation lead, not proof of intent, delivery, knowledge, wrongdoing or liability.

Begin with the question the draft addresses and its actual coverage. For one important finding, inspect exact support, the strongest contrary account, dates and missing sources. Separate when an event occurred from when it became known. First-pass omissions remain omissions. Choose a source check or wording decision for counsel; saving or reviewing a draft does not file it or authorize external sharing.

See [the conversation guide](conversation_guide.md) for the sample or walkthrough, expected handoff and useful follow-up questions. Examples are not current findings. Ask one missing question at a time, keep confirmed answers, and answer side questions without changing settings or issuing actions.

Make sense of a large collection of case documents. Find important facts, timelines, connections, and conflicting evidence, with links to the original sources. Get draft findings for legal review.

## Work a disputed fact

1. Open **Full report → Questions → Proof chart**. Add the claim or defense
   and the fact to establish. Start a distinct element for receipt even if
   the chart already includes dispatch.
2. Under **Evidence**, open the document, highlight the passage and choose
   **Capture fact**. Enter wording, evidence role, reviewer and optional witness.
   Add a Bates or transcript reference after checking it against the original.
   Choose **Open passage** to verify the citation.
3. Choose **Ask the graph** in Questions. Ask which records address receipt,
   then which of those predate termination. Open the cutoff source and a
   matching record. **Save question** retains the refinements.
4. In **People & events → Witness preparation**, choose the witness and element.
   Pair the witness's statement with another exhibit. Save counsel's neutral
   question and any explanation, then download the editable outline. Use
   **Identities** to confirm or reverse an alias from a passage.
5. Open **Timeline** to distinguish the record date from the event described.
   Choose **Add event from a fact** to enter a source-supported interval.
   In **Questions → Discovery**, assign a record, owner, internal target and
   closure test. Close the item with a current supporting fact and explanation.
6. For a handoff, choose **Save copy**. For the next production, use **Actions
   → Export review decisions** and attach that file in Configure before the next
   run of the same matter. Under **Review history → Changes**, compare the older
   passage with candidates in the new record. Revisit the linked proof, witness
   question and draft paragraph. Rerun saved questions under **Ask the graph**.
7. Under **Reports → Reviewed briefing**, download the numbered Word statement
   and the separate counsel review sheet. Select a linked exhibit in Word to read
   the quoted passage and locator. Open `case/privilege_log.html` in the owner's
   confidential archive for privilege review. Choose export fields, check the
   preview, and download the CSV. Save a counsel working copy to retain log edits.

## Inputs

- input_folder: Folder of legal sources. Omit to download the pinned public EMC2 sample automatically.
- goal: Neutral investigation objective; a default review goal is supplied.
- output_folder: Destination for review drafts and audit files.
- review_file: Optional exported human review decisions from this matter. Imported as analysis history, never instructions or evidence.

## Outputs and review

For real-data desktop setup, choose the authorized folder and state the question
the review should help answer. The synthetic sample supplies its question.
Optional counsel intake and previous decisions stay in Configure. Set handling restrictions
before work; Chat cannot clear excluded material.

Start with **Your next review** in the draft or offline overview. It explains one
question, why it matters now, when to decide and the source passages to inspect.
Chat shows a compact saved handoff. View full report opens the evidence workspace;
Discuss next step fills a draft message without sending it. Record wording
decisions through the existing finding review, then save or export to retain them.
No discussion starts further work, grants approval or authorizes sharing.

Use **Case graph** in the report to follow links between questions, findings,
email addresses, documents, and transaction records. Select a connection to see
its source passage. Chat can answer from the saved graph appendix when Membrane
retrieves the relevant section. The audit archive includes a queryable graph
database for direct lookup with the blueprint's `ask_case.py` tool.


Consult the published run results and their evidence before making decisions. Missing evidence does not establish that an event or condition did not occur.


## Supervision

Use `get_capabilities` for the current tools and their availability. Common MCP actions are implemented by the SDK. `start_run` starts new work, `pause_run` preserves a resumable run, `resume_run` continues it, and `stop_run` terminates it. Domain stop actions affect their named resource only. Accepted actions are not evidence of completion; use `get_operation_status`.

External mutations require a caller-generated `request_id`. Tool results use `mn.mcp.tool_result.v1` in `structuredContent`; keep workflow state inside `data` and poll a returned `operation_id` with `get_operation_status`. The runtime also publishes this installed manual through its MCP Skills manifest.


## Stage-aware conversation

OtterDesk reads `payloads/prompts/conversation.json` as optional app-owned guidance. It combines this role and stage policy with the pending question, confirmed non-secret setup answers, recent dialogue, selected report and fresh Job state. Short follow-ups retain their topic; a correction does not silently change saved configuration.

Use Memory or explicitly ask to remember, edit or forget an explanation preference. This affects Chat wording only; working rules and evidence keep their existing domain controls. The optional `inputs.payload.supervisor_instructions` array is app-managed, never a required setup answer or a new workflow permission.

Use existing Membrane prepared sources and claim provenance. Separate event time from when evidence became known; preserve contradictory and superseded facts. Draft research only; no legal advice, filing, witness contact or privileged-source disclosure. User statements and saved preferences are not evidence. Matter handling rules and scope stay in their existing configuration and review files. Existing submitted runs retain their configuration, evidence and approvals. An idle prepared Job may refresh through the existing conditional API without rehiring, resetting memory or mutating an active run.
