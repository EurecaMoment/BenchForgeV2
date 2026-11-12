export function requestKeyFor(args, exec) {
  return args.request_key ?? `dsh:${exec.agent.session.id}:${exec.callId}`;
}
