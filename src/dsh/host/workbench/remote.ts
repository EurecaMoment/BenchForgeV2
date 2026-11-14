import type {Context} from '@deepseek-ai/cordis';
import type {} from '@deepseek-ai/dsh-api-gateway';
import type {} from '@deepseek-ai/dsh-api-remote-access';
import type * as Typert from '@deepseek-ai/dsh-typert-protocol';
import type {JSONType} from 'zod/v4/core';

type Query = Record<string, string>;
type WorkbenchDispatch = (url: URL, input: {
  method: 'GET' | 'POST';
  signal: AbortSignal;
  headers: Headers;
  text: () => Promise<string>;
}) => Promise<JSONType>;

export function registerWorkbenchRemote(ctx: Context, typert: typeof Typert, dispatch: WorkbenchDispatch) {
  const {Remote, RemoteError, TypertRemoteService} = typert;

  class WorkbenchRemote extends TypertRemoteService {
    constructor(ctx: Context) {
      super(ctx, 'benchforgeWorkbench');
    }

    @Remote
    read(query: Query, signal: AbortSignal): Promise<JSONType> {
      return this.call('read', query, undefined, signal);
    }

    @Remote
    write(query: Query, body: JSONType, signal: AbortSignal): Promise<JSONType> {
      return this.call('write', query, body, signal);
    }

    private async call(method: 'read' | 'write', query: Query, body: JSONType | undefined, signal: AbortSignal) {
      if (this.ctx.invocation?.peer.principal.kind !== 'owner') {
        throw new RemoteError('remote-access/denied', 'Workbench access requires the host owner', {
          action: 'benchforgeWorkbench/' + method, reason: 'no-allow',
        });
      }
      const url = new URL('http://benchforge.invalid');
      url.search = new URLSearchParams(query).toString();
      return dispatch(url, {
        method: method === 'read' ? 'GET' : 'POST', signal,
        headers: new Headers(), text: async () => JSON.stringify(body),
      });
    }
  }

  new WorkbenchRemote(ctx);
}
