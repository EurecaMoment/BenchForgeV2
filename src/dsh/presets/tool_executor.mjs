import {RUN_CODE_NAME, ToolBatchExecutionError} from '@deepseek-ai/dsh-tools';
import {NativeToolExecutor} from '@deepseek-ai/dsh-tool-executor-native';
import {PtcExecutor} from '@deepseek-ai/dsh-tool-executor-ptc';

export const name = 'benchforge-tool-executor';
export const inject = ['tools', 'systemPrompt', 'ptcRuntime'];

class BenchForgeToolExecutor extends PtcExecutor {
  constructor(ctx) {
    super(ctx);
    this.native = new NativeToolExecutor(ctx);
    this.sections = this.sections.filter(section => section.name !== 'tools:ptc-only');
  }

  describe(tools) {
    const native = this.native.describe(tools);
    const ptc = super.describe(tools);
    return {
      schemas: [...native.schemas, ...ptc.schemas],
      knownNames: [...tools.map(tool => tool.name), ...ptc.knownNames],
    };
  }

  async execute(input) {
    const combined = {results: [], additionalContexts: [], concluded: false};
    const append = result => {
      combined.results.push(...result.results);
      combined.additionalContexts.push(...result.additionalContexts);
      combined.concluded ||= result.concluded;
    };

    // A program is an exclusive barrier between runs of direct calls.
    for (let start = 0; start < input.calls.length;) {
      const program = input.calls[start].name === RUN_CODE_NAME;
      let end = start + 1;
      while (!program && end < input.calls.length && input.calls[end].name !== RUN_CODE_NAME) end++;
      const batch = {...input, calls: input.calls.slice(start, end)};
      try {
        append(await (program ? super.execute(batch) : this.native.execute(batch)));
      } catch (error) {
        if (error instanceof ToolBatchExecutionError) append(error.partial);
        throw new ToolBatchExecutionError(error, combined);
      }
      start = end;
    }
    return combined;
  }
}

export function apply(ctx) {
  ctx.tools.setExecutor(new BenchForgeToolExecutor(ctx));
}
