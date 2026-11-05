# Parallel production in the evaluation workbench

SpatialForge delegates independent scene design, annotation adapters and question
generator preparation to fresh native DSH subagents. Three simultaneous workers
is the default batch size, not a global host limit. Each worker receives the
frozen plan and its own output directory. This avoids carrying the parent's long
conversation into every edit and keeps file ownership clear.

The parent reads the completed handoffs, validates their outputs and merges them.
Only the parent submits scene programs, applies user plan edits, opens stage
review windows and packages the final dataset. A single Isaac device retains its
capture queue. Question shards prepare S4 outputs; the parent reviews the whole
S4 result before the single S5 package operation.

The runner aggregates all declared artifacts of a stage, including nested
recipes, before opening one five-minute user window for that stage and run.
Resuming a reviewed run preserves submitted jobs and completed artifacts.
Editing the active plan stops subsequent dependent work.

The workbench obtains child identities from DSH's parent catalog and verifies
their immutable parent headers. It reads only the listed children, without
scanning session history. Active-turn timing indicates running work; an inactive
child or an accepted spawn request does not establish successful production.
Products continue to use saved, session-owned artifacts and native acceptance.

Live progress changes update the meters. They do not reload plans, datasets or
movies; completed steps and product revisions trigger those heavier reads.
Measurements with different units are shown separately.

Plan preflight reports all independent omissions together. Native capture,
public answerability, physical support and allocation checks remain required.
Formatting or unrelated scoring edits do not invalidate an unchanged scene
design. A changed layout, hard requirement or geometry exception still requires
appropriate new scene acceptance. Revision notes need useful text and actual
image/physics references, without an arbitrary character quota.
The parent continues repairs that show evidence of improvement within the user's
budget. Repeated unchanged failures stop automatic retries and report the
missing input, rather than ending every scene after a fixed two attempts.

The external preset contains the default delegation policy. DSH keeps an active
session's preset revision locked; existing sessions need explicit steering,
while new sessions receive the updated worker configuration.
