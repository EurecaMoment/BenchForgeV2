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

Independent preparation uses the public `spatialforge_prepare` tool or the
authenticated workbench's shared trusted synthesis adapter. Before creating a
worker, the adapter resolves the exact provider/model route inherited from the
parent's latest request and reads its advertised reasoning efforts. Medium is a
preference only when supported; otherwise it selects an offered lower effort
such as low, minimal, none or off. A model offering only high/max uses high and
records that fallback. If those preferred levels are absent, an advertised max
or another provider-owned effort remains valid: the receipt names the selected
value and explains that no preferred or lighter level is available. When no
reasoning control is exposed, the adapter omits the effort override and records
why the inherited/default behavior applies. The provider/model route, parent
reasoning and host defaults remain unchanged, and no worker output-token cap is
added.

The startup receipt records the supported efforts, actual selection and reason
for each task. A raw native delegate retains the parent's default effort unless
an explicitly supported override is permitted; it does not automatically become
a medium worker. Older sessions may reject explicit model-selection parameters,
so they use the trusted preparation adapter rather than retrying that parameter.
The adapter resolves tool restrictions against registered canonical names and
preserves durable batch identities. An optional saved plan path must resolve to
an existing workspace file; that real path binds the batch and appears in every
initial worker prompt. Reusing the batch key with a different plan path is
rejected. A receipt proves inbox admission; verify an actual model request,
readable handoff files and parent acceptance before reporting successful
production. See [constraint-policy.md](constraint-policy.md).
