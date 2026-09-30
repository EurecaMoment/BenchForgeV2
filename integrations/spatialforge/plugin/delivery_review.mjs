// A capture receipt closes a rendering job, not the user's scene request.
// Review a new capture, or the latest one explicitly resumed in a later turn.
export const sourceKind = 'spatialforge-delivery-review';
const captureTools = new Set(['spatialforge_capture', 'spatialforge_refine', 'spatialforge_status', 'spatialforge_wait', 'spatialforge_evidence']);

// PTC stores settled inner calls separately from the outer run_code result.
function captureEvents(events) {
  return events.flatMap(event => event.type === 'tool/ptc-dispatch' ? [
    {type:'tool/call',data:{name:event.data.name,callId:event.data.subCallId,arguments:JSON.stringify(event.data.arguments)}},
    {type:'tool/result',data:{message:{toolCallId:event.data.subCallId,isError:event.data.isError,content:event.data.content}}},
  ] : [event]);
}

export function pendingCapture(events, turn) {
  events = captureEvents(events);
  const start = events.findLastIndex(e => e.type === 'turn/start' && e.data.turn === turn);
  const submissions = new Set(['spatialforge_capture', 'spatialforge_refine']);
  const observations = new Set(['spatialforge_status', 'spatialforge_wait', 'spatialforge_evidence']);
  const calls = new Map();
  const reviewed = new Set();
  const reviewedTasks = new Set();
  const revisited = new Set();
  let latest, received;
  let submittedHere = false;
  if (start < 0) return;
  for (const [index, event] of events.entries()) {
    const data = event.data;
    if (event.type === 'tool/call' && (submissions.has(data.name) || observations.has(data.name))) {
      calls.set(data.callId, { ...data, index });
    }
    if (event.type === 'user/message' && data.source?.kind === sourceKind) {
      reviewed.add(data.source.capture_call_id);
      reviewedTasks.add(data.source.task_id);
    }
    if (event.type !== 'tool/result' || data.message.isError || !calls.has(data.message.toolCallId)) continue;
    const call = calls.get(data.message.toolCallId);
    if (submissions.has(call.name)) {
      const value = JSON.parse(data.message.content.find(block => block.type === 'text').text);
      latest = { callId: data.message.toolCallId, runId: value.run_id, taskId: value.task_id ?? value.run_id + '.scene0' };
      submittedHere = call.index > start;
    } else if (call.index > start) {
      const args = JSON.parse(call.arguments);
      revisited.add(args.run_id ?? args.task_id);
      if (call.name !== 'spatialforge_evidence' && args.run_id) {
        received = { callId: data.message.toolCallId, runId: args.run_id, taskId: args.run_id + '.scene0' };
      }
    }
  }
  // An unrelated follow-up does not reopen old work; reminders deduplicate
  // across the whole session, including after replay or reconnection.
  // A receiving agent has no submission event: explicitly observing a run
  // supplies that identity. The inspect result below decides whether it is
  // a completed capture, rather than a generation or dataset operation.
  if (!latest) return received && !reviewedTasks.has(received.taskId) ? received : undefined;
  return latest && !reviewed.has(latest.callId)
    && (submittedHere || revisited.has(latest.runId) || revisited.has(latest.taskId)) ? latest : undefined;
}

export function createDeliveryReview({ api, createMessage, visuals = async () => [] }) {
  return async ({ agent, turn, signal }, deliver = message => agent.steer(message)) => {
    signal.throwIfAborted();
    const capture = pendingCapture(agent.session.snapshotEvents(), turn);
    if (!capture) return;
    const run = await api('/inspect', { run_id: capture.runId }, signal);
    const task = run.tasks.find(task => task.id === capture.taskId);
    // Active or failed jobs retain their normal wait/repair/blocker decisions.
    if (!task || task.state !== 'SUCCEEDED' || task.result.operation !== 'capture_only') return;
    const { report, scene_quality_assessed, data_exported } = task.result;
    const facts = {
      task_id: task.id, revision: task.unit.revision,
      capture_status: report.status, scene_quality_assessed, data_exported,
      render_qa: report.render_qa,
      capture_scope: report.capture_scope,
      scene_export: {
        entry: report.scene_file, payload: report.scene_payload,
        resource_scope: report.scene_resource_scope,
        unresolved_resources: report.scene_resources_unresolved,
        runtime_requirements: report.scene_runtime_requirements,
      },
      interaction_kind: report.interaction?.test_kind,
      actions: (report.interaction?.action_results ?? []).map(action => ({
        id: action.id, object_id: action.object_id, success: action.success,
        translation_m: action.translation_m, checks: action.checks,
        before_position_m: action.before?.position, after_position_m: action.after?.position,
        before_image: action.before_image, after_image: action.after_image,
        recording: action.recording,
        object_contacts: action.object_contacts,
        before_visibility: action.visual_evidence?.before, after_visibility: action.visual_evidence?.after,
      })),
      reference: task.unit.intent.layout,
      capture_directory: task.result.directory + '/capture',
    };
    const text = `Review the requested delivery before finishing this SpatialForge turn.
Latest capture receipt: ${JSON.stringify(facts)}
capture_scope records the outputs selected for this run. Omitted views and a skipped scene export are not new delivery evidence; reuse earlier evidence where it still applies and request additional outputs only as needed.
SUCCEEDED here means capture completed. scene_quality_assessed=false means the capture service did not assess scene quality; it does not invalidate a visual review you already performed.
Reconcile the user's actual request with the reference, rendered views, declared action traces and delivered files. Reuse evidence already inspected. For reference-based scenes, address visible layout, material and lighting gaps; a checked TODO or successful render is not evidence that those gaps are resolved. For requested scene files, verify the delivered entry point, referenced assets and image/metadata links in the intended loading environment.
For a reference-based scene, compare the actual pixels together. The first capture camera may look in a different direction: use the existing view that best matches the reference, or adjust the camera if the required composition is not observable. Check recognizable shapes, object states, materials and lighting, not just object names. Listing a visible, fixable mismatch as an honest limitation does not fulfill that requirement; distinguish such unfinished work from intrinsic uncertainty such as unmeasured reflectance. Keep that comparison tied to the original request rather than adding unrelated requirements.
Source asset paths describe the construction inputs, not necessarily dependencies of the exported USD. Use the export receipt and actual delivered USD resolution to describe portability; an empty unresolved_resources list alone is not a verification of the final copied package.
An action's success records its physical checks, not whether it occurred at the requested location or is visible in the demonstration. Use the recorded positions and before/after visibility to assess those requirements. A requested tabletop object that settled on the floor, or a target with zero visible pixels in both demonstration frames, still needs correction even if displacement checks passed. Preserve the original simulation measurements.
If a requested result is still missing or visibly wrong and the available tools can fix it, continue that work now: revise the SceneProgram, submit a new capture, inspect the changed pixels, and only then prepare the delivery response. Do not stop merely because capture succeeded, render QA passed, TODOs are checked, or the mismatch can be described in a README. A visible omission or mismatch is unfinished work, not an honest limitation. If a concrete external blocker prevents the next repair (for example an unavailable asset, desktop or required file), report that blocker and the exact evidence; do not present the incomplete scene as delivered.
Use only the user's requested scope: no extra robot, dataset, model review, prescribed tool sequence or fixed number of revisions is required.

When the requested work is complete, or an external blocker requires stopping, write the formal delivery response. While repair is possible, continue working; this review does not require an immediate final answer. Write a finished delivery note, not an audit log or a continuation of private reasoning. Start with one clear status sentence: "已完成交付" only when every requested result is supported; otherwise use "部分完成"、"未完成" or "阻塞" and name the missing result. Then give the useful artifact paths and the evidence that actually exists, followed by only concrete blockers or operational requirements that still matter. Do not write a generic "诚实局限" section. Keep capture completion, visual fidelity, physical interaction, and scene-file loadability as separate claims. "render_qa.passed", a successful capture, a checked TODO, or an honest limitation does not by itself prove visual restoration. Do not claim that all views were inspected unless you actually inspected those pixels; say which views were captured versus visually checked. Do not say there are no fixable gaps when a visible requested mismatch remains. Do not expose internal reasoning, review-round narration, TODO history, speculative explanations, or phrases such as "本轮新核验的一项" and "复审全部完成". Do not inflate an approximation into a complete restoration. Use concise user-facing Chinese with direct declarative sentences and normal Markdown links. This review is issued once for this capture submission; unchanged status polling does not issue it again.`;
    const visualContent = await visuals({ task, agent, signal });
    deliver(createMessage({ content: [{ type: 'text', text }, ...visualContent],
      source: { kind: sourceKind, capture_call_id: capture.callId, task_id: task.id, revision: task.unit.revision } }));
  };
}

// Put new observations before the next model decision (including update_goal),
// rather than waiting until the model has already announced completion.
export function createCaptureReviewStep(review) {
  return async (input, next) => {
    const decision = await next();
    if (decision.kind !== 'enter') return decision;
    const events = captureEvents(input.agent.session.snapshotEvents());
    const boundary = events.findLastIndex(e => e.type === 'step/start' || e.type === 'turn/start');
    const recent = events.slice(boundary + 1);
    const calls = new Set(recent.filter(e => e.type === 'tool/call' && captureTools.has(e.data.name)).map(e => e.data.callId));
    if (!recent.some(e => e.type === 'tool/result' && !e.data.message.isError && calls.has(e.data.message.toolCallId))) return decision;
    const messages = [];
    await review(input, message => messages.push(message));
    return messages.length ? {...decision, messages:[...decision.messages, ...messages]} : decision;
  };
}
