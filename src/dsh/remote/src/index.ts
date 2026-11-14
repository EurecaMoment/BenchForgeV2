import {Service, type Context} from '@deepseek-ai/cordis';
import type {} from '@deepseek-ai/dsh-api-gateway';
import {Remote, RemoteError, bindTypertRemote} from '@deepseek-ai/dsh-typert-protocol';
import type {JsonValue, ReadQuery, WriteQuery} from './types.js';

type WorkbenchDispatch = (url: URL, input: {
  method: 'GET' | 'POST';
  signal: AbortSignal;
  headers: Headers;
  text: () => Promise<string>;
}) => Promise<JsonValue>;

declare module '@deepseek-ai/cordis' {
  interface Context {
    benchforgeWorkbench: WorkbenchRemote;
  }
}

export class WorkbenchRemote {
  readonly typertRemote = bindTypertRemote(this, 'benchforgeWorkbench');

  // Cordis binds the invocation Context when the Gateway gets the service.
  private readonly [Service.tracker] = {property: 'ctx'};
  declare private readonly ctx: Context;

  constructor(private readonly dispatch: WorkbenchDispatch) {}

  @Remote
  read(query: ReadQuery, signal: AbortSignal): Promise<JsonValue> {
    return this.call('GET', query, undefined, signal);
  }

  @Remote
  write(query: WriteQuery, body: JsonValue, signal: AbortSignal): Promise<JsonValue> {
    return this.call('POST', query, body, signal);
  }

  private async call(method: 'GET' | 'POST', query: Record<string, string>, body: JsonValue | undefined, signal: AbortSignal) {
    if (this.ctx.invocation?.peer.principal.kind !== 'owner') {
      throw new RemoteError('gateway/bad-request', 'Workbench access requires the host owner', {});
    }
    const url = new URL('http://benchforge.invalid');
    url.search = new URLSearchParams(query).toString();
    return this.dispatch(url, {
      method, signal, headers: new Headers(), text: async () => JSON.stringify(body),
    });
  }
}
