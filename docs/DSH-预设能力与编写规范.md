# DSH Agent 预设能力与编写规范

本文以 DeepSeek Harness（DSH）`0.2.2-rc.3` 为准，对应上游源码提交 `39163dd30f`。示例基于该版本的 Web profile，其他 profile 的依赖差异在下文标出。 [DSH 上游源码](https://github.com/deepseek-ai/deepseek-harness/tree/39163dd30f703a79079e2d2446545cff3c453738)

**一个预设可以组合 Agent 的提示词、上下文、工具及执行器、Skill、MCP、用户命令、事件策略、计划与压缩、子 Agent 和工作流，也能运行自定义的隔离服务。** 同一个 bundle 还可以贡献宿主服务和 Web 界面，再让界面根据会话使用的预设 ID 改变。预设的能力范围由插件接口决定，所以盘点以**挂载机制、内置预设实际装配、文档公开的扩展点**为边界。第三方插件用相同机制接入，依其服务和事件是否支持作用域判断放置位置。 [预设能力边界](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/compositions.md#L71) · [公开扩展点](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/architecture.zh.md#L149)

## 目录

- [能力与放置位置](#能力与放置位置)
- [声明、安装和更新预设](#声明安装和更新预设)
- [插件编写与作用域规范](#插件编写与作用域规范)
- [角色、提示词和上下文](#角色提示词和上下文)
- [Skill、MCP、记忆和人类命令](#skillmcp记忆和人类命令)
- [Tool 编写、可见性与执行策略](#tool-编写可见性与执行策略)
- [规划、长会话与持续目标](#规划长会话与持续目标)
- [子 Agent、Team 与工作流](#子-agentteam-与工作流)
- [官方扩展点的补充写法](#官方扩展点的补充写法)
- [会话状态和业务持久化](#会话状态和业务持久化)
- [Web 界面、业务 RPC 与会话状态](#web-界面业务-rpc-与会话状态)
- [Host 入口与共享基础设施](#host-入口与共享基础设施)
- [评测与训练预设的组合示例](#评测与训练预设的组合示例)
- [验收步骤](#验收步骤)
- [按包和接口查证](#按包和接口查证)
- [四套内置预设的全部装配行](#四套内置预设的全部装配行)

## 能力与放置位置

| 要做的事 | 放置位置 | 编写接口 |
|---|---|---|
| 新增或覆盖预设、配置显示名、默认项和排序 | profile/bundle patch | `@deepseek-ai/dsh-agent-preset`，默认项在注册表 `default` |
| 人设、提示词片段、模板变量、项目指令、时间和实时上下文 | 预设 | `dsh-persona`、`ctx.systemPrompt`、`dsh-agent-instructions`、`dsh-time-context`、`agent.inject()` |
| Skill 文件、内置 Skill、动态 Skill 提供方 | 预设贡献，宿主注册表 | `dsh-skill-filesystem`、`dsh-tool-skill`、`ctx.skills.registerProvider()` |
| 原生 Tool、步骤可见性、PTC、程序批量调用、工具呈现元数据 | 预设贡献，宿主注册表 | `defineTool()`、`ctx.tools.register()`、`restrict()`、`dsh-tool-executor-ptc` |
| 审批前判断、执行门禁、包装、结果检查、审计、取消 | 预设作用域的策略插件 | `tools/pre-execute`、`ctx.tools.guard()`、`tools/execute`、`tools/post-execute`、`tools/result` |
| 钩住 Agent 阶段、引导下一步、记录事件 | 预设监听，宿主提供循环和持久化 | `agent/*`、`agent.followup()`、`agent.steer()`、`session/event` |
| 人工斜杠命令、计划模式、压缩、目标 | 预设挂命令和策略，宿主提供共享目标、投影和计量 | `ctx.commands.register()`、`dsh-plan-mode`、`dsh-compaction-basic`、`dsh-command-goal` |
| 委派、并行工作流、结构化子任务、团队 | 预设配置模型入口和可隔离引擎，默认项在注册表、团队宿主服务和 provider 由 Host 挂载 | `dsh-tool-subagent`、`dsh-workflow-ptc`、`ctx.workflowEngine`、`ctx.agentTeams` |
| Shell、持久终端、文件读写/检索、待办、问答、Web 搜索、Office、产物展示 | 预设挂可见能力，按对应插件声明消费 Host 提供方 | 四套内置预设的 `plugins` 与工具目录 |
| 后台任务、定时投递 | 预设挂工具/控制器，Host 提供 jobs/schedule | `ctx.jobs.start()`、`dsh-tool-jobs`、`dsh-tool-schedule` |
| 预设专用 MCP 与资源 | 预设挂客户端，profile 负责全局管理 | `dsh-mcp-client`、`ctx.mcpResources` |
| 私有业务服务、资源释放、可替换实现 | 预设内同一隔离组装配提供者和消费方 | `Service` / `ctx.provide()`、`cordis:group`、`isolate`、`ctx.effect()` |
| 会话界面、右栏、主工作台、工具卡、聊天节点、用户设置 | Web profile 注册双面包，Client 按会话选择界面 | `dsh.client`、`ctx.slots`、`useProjection('agentPreset')` |
| 模型 provider/凭据、持久化、权限、Gateway、外部入口、Web Server | Host/profile，具体会话选择放在会话控制面 | `ctx.llm`、`SessionPersistence`、`ctx.permissionPresets`、`@Remote` |
| 业务状态、事件与 UI 投影 | 共享投影或业务 Host 服务，用 Session 或业务任务作为身份 | `sessionProjections`、领域存储与业务 Remote。改造 DSH 内置持久事件时另维护 `SessionEventMap` 和格式迁移。 |

参考 [扩展实操索引](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/extension-cookbook.zh.md#L145) · [Web 宿主与预设移交清单](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/cordis.patch.yml#L544)

表格中的 `SessionEventMap` 是仓库内置事件扩展机制。独立 bundle 使用现有事件的投影，或通过自己的业务存储和 Remote 保存领域状态。持久化章节给出两种写法的具体条件。 [外部插件持久化规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/practices.md#L17)

## 声明、安装和更新预设

### 新建预设

在 DSH 源码根目录下自行创建 `examples/training-preset/`，把本地 overlay 保存为其中的 `cordis.patch.yml`。顶层是 patch 数组，`insert` 下面是一组 Loader 条目。

```yaml
- insert:
    - id: preset-training-data
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: training-data
        name: 训练数据生产
        description: 生成并校验训练样本。
        order: 10
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config:
              prefix: |
                你是训练数据生产 Agent。
                汇报产物时附上数据版本、分区和质检回执。
```

| 位置 | 编写规范 |
|---|---|
| 声明行 `id` | Loader 地址，建议用 `preset-<id>`。覆盖该声明时按这个地址匹配。 |
| `config.id` | 会话保存的预设身份，全局注册表内唯一。源码校验非空，命名按小写字母、数字和连字符的项目约定。发布后保持稳定，让历史会话能恢复。 |
| `config.plugins` | 必填的插件条目数组。新预设按清单装配，并通过作用域链访问宿主的共享贡献。要保留官方 `standard` 当中的会话级能力，可复制该声明的完整清单再改。 |
| `config.name`、`description`、`order` | 可选展示名、说明和排序。 |
| 子条目 `name` | 插件包名、包的公开子路径或模块 URL。本地 Windows 示例使用 `file:///C:/.../plugin.ts`。 |
| 子条目 `id`、`config` | 给每行稳定 ID，便于定位和审计。配置按该插件的运行时 schema 编写。 |
| 子条目 `disabled` | 布尔值、`null` 或 Loader 的 `!!js` 条件。 |
| 子条目 `inject` | 为这一行增加服务依赖，插件还可在模块内导出自己的 `inject`。 |
| 子条目 `group`、`isolate`、`intercept` | `cordis:group` 配合 `group: true` 创建子树，`isolate` 按服务名重映射实例，`intercept` 是 Cordis 的局部服务拦截配置，具体值按服务约定写。 |

`!!js` 可用在 `disabled` 和插件 `config` 的值上。Windows 的模块 URL 可由 `[System.Uri]::new((Resolve-Path -LiteralPath $modulePath).Path).AbsoluteUri` 生成。overlay 对相对模块名的重定位遍历插入行和显式 Loader group，预设里的 `config.plugins` 另有挂载树，使用包名或绝对 URL 可以明确解析位置。Skill 目录路径另按文件系统路径传入。 [声明和校验](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/README.zh.md#L27) · [条目格式](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/composition-reference.md#L5) · [overlay 路径实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/boot/app-boot/src/index.ts#L550)

### 覆盖、默认项与 profile

覆盖现有定义时，用外层 `id` 定位，把含 `id`、`plugins` 和所需展示字段的**完整 config** 写进去。顶层 `insert` 追加新行，带目标 `id` 的 `insert` 只适用于显式 `group: true` 的 Loader group。当前源码中的预设声明有独立的挂载树，覆盖 `preset-standard` 时以完整的 `config.plugins` 提交新清单。常规配置层按 bundle、profile patch、home patch、命令行 overlay 的顺序应用。 [实际 patch 算法](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/vendor/include/src/patch.ts#L43) · [预设覆盖方式](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/compositions.md#L50) · [加载顺序](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/develop/basic/publish.zh.md#L123)

Web 已挂载 `agent-preset-registry`。可在 Web 的 Agent 预设设置里设为新任务默认。部署层也可覆盖下面这行，用户已经保存的 `selectedDefault` 有更高优先级。随附的 SDK、headless 和 ACP 使用各自的组合。要给这些入口使用预设，先在目标 profile 查清 Registry 和所用插件的 Host 依赖，并确认该入口的会话创建路径会绑定预设。Web overlay 里的 `preset-training-data` 会在 Web 的注册表中注册。 [Web 注册表](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/cordis.patch.yml#L622) · [注册表默认规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/README.zh.md#L35) · [profile 差异](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/architecture.zh.md#L15)

```yaml
- id: agent-preset-registry
  name: '@deepseek-ai/dsh-agent-preset-registry'
  config:
    default: training-data
```

### 本地运行和作为 bundle 分发

源码启动命令如下，先在 DSH 工作树根目录执行。把 `$patch` 指向实际写好的 overlay。配置变更可先用 `--dump-config` 查看合并结果，运行日志和 Web 预设列表用于检查插件是否真正激活。 [源码运行说明](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/README.zh.md#L33) · [CLI 参数](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/apps/cli/src/args.ts#L165)

```powershell
pnpm install --frozen-lockfile
pnpm run build
$patch = (Resolve-Path -LiteralPath 'examples/training-preset/cordis.patch.yml').Path
pnpm dsh web --dump-config --patch "$patch"
pnpm dsh web --patch "$patch"
```

生产分发时由安装包提供代码与资源，最小配置型 bundle 可以只有下面的 `package.json` 和上面的 `cordis.patch.yml`。有自编插件时，按需增加 `exports`、`files` 和依赖，并把插件行改成已安装包名或导出的子路径。避免在分发配置中嵌入某台机器的路径。与宿主共享注册表或作用域标记的依赖，按官方指南声明为 peer，开发环境再提供匹配的 devDependency。支持版本可以通过 `engines.dsh` 表达，示例使用已经核对的确切预发布版本。 [bundle 编写和安装](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/develop/basic/publish.zh.md#L12) · [源码包约束](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-package.zh.md#L7)

本手册的代码按能力给出独立模块或标注用途的片段。合并为业务包时按模块的 `import` 声明直接依赖，包括 `zod`、`@deepseek-ai/dsh-storage-domain` 和 `@deepseek-ai/dsh-working-directory` 等。`examples/training-preset/` 便于试跑简单 overlay，完整的业务模块建议放入自有 workspace 或 bundle 包。 [源码包结构和依赖声明](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-package.zh.md#L7)

```json
{
  "name": "@local/training-preset",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "engines": { "dsh": "0.2.2-rc.3" },
  "files": ["cordis.patch.yml"],
  "dsh": { "bundle": { "patch": "./cordis.patch.yml" } }
}
```

已初始化的 Web profile 可用 `dsh plugin --profile web add <bundle路径或包名>` 安装。源码环境用 `pnpm dsh plugin --profile web add <bundle路径或包名>`。只做本地迭代可以持续使用 `--patch`。插件依赖缺失时先看预设的加载诊断，确认插件为什么处于 pending 或 failed。 [安装方式](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/develop/basic/publish.zh.md#L74) · [审计机制](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/index.ts#L143)

## 插件编写与作用域规范

### 普通插件的入口和生命周期

下面是一段可在有相应依赖的源码工作区运行的 Host 插件。运行时 schema 和同名 TypeScript 接口定义配置，`inject` 定义必需服务，`apply` 负责注册，`ctx.effect()` 绑定资源清理。定时器随预设插件的活动版本创建和释放，业务运行状态应按会话或业务任务分配。

```ts
import type { Context } from '@deepseek-ai/cordis'
import Schema from '@deepseek-ai/schemastery'

export const name = 'example-heartbeat'
export const inject = ['logger']

export interface Config {
  label: string
  intervalMs: number
}

export const Config: Schema<Config> = Schema.object({
  label: Schema.string().required(),
  intervalMs: Schema.number().min(1000).default(60000),
})

export function apply(ctx: Context, config: Config) {
  const logger = ctx.logger(name)
  ctx.effect(() => {
    const timer = setInterval(() => {
      logger.info('%s', config.label)
    }, config.intervalMs)
    timer.unref()
    return () => clearInterval(timer)
  }, 'example-heartbeat.timer')
}
```

对于工具注册、事件监听等 Cordis API，通常由调用时的 `ctx` 持有清理责任。外部连接、计时器、进程和自己的订阅须显式归属到 effect，释放时终止已启动的工作。可选服务用 `ctx.get()` 探测。相关 API 消失后，声明了硬依赖的消费插件会随依赖卸载与恢复。 [插件入口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cordis-tutorial/01-first-plugin.zh.md) · [effect](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cordis-tutorial/02-lifecycle-and-effects.zh.md) · [配置 schema](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cordis-tutorial/05-config.zh.md#L12)

### 预设范围、单个 Agent 范围、服务隔离

| 机制 | 适用场景 | 生命周期规则 |
|---|---|---|
| 从预设插件的 `ctx` 注册 | 对选择该预设的会话贡献工具、提示词、命令及可作用域化的事件处理 | 同一活动版本的预设树可被多个 Agent 共享 |
| 从 `agent.ctx` 注册 | 只给特定 Agent 增加一个临时贡献 | 随那个 Agent 的作用域释放 |
| 荷载参数使用 Session ID/业务 run ID | 防止多个会话共用可变业务状态 | 每会话派生状态通过 Session 日志或投影持久化，长作业由业务存储持有 |
| `isolate` 服务 realm | 更换或私有化 Cordis 服务实例 | 提供方和消费方通过同一 realm 解析实例，组外依原来的 Host 查找路径 |

内置 Tool、提示词和 Skill 使用可感知作用域的注册表。自制注册表可沿用 `ScopedLayers`、`NamedEntries`、`AnonymousEntries` 与 `scopeTarget()`。已有 SDK 或框架服务是否支持作用域，要看实际的注册和事件路由方式。插件代码在 Host 进程内执行，进程、文件与网络权限沿用部署层实际权限和业务服务的访问控制。 [Scope API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/scope/README.zh.md#L24) · [服务泄漏审计和代际](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/README.zh.md#L54)

下面是自定义服务 `provider.ts` 和消费方 `consumer.ts`。将这些插件放在一个 group 下。需要在组外读取预设拥有的服务时，可以调用 `ctx.agentPresets.serviceFor(agent, name)`。传入 Agent 或具有 `ctx` 的对象，普通 `agent.ctx` 服务查找仍遵循 Host realm。

```ts
// provider.ts
import { Service, type Context } from '@deepseek-ai/cordis'

declare module '@deepseek-ai/cordis' {
  interface Context {
    datasetPolicy: DatasetPolicy
  }
}

export default class DatasetPolicy extends Service {
  constructor(ctx: Context) {
    super(ctx, 'datasetPolicy')
  }

  canSubmit(split: string, validated: boolean): boolean {
    return split === 'train' && validated
  }
}
```

```ts
// consumer.ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from './provider.ts'

export const name = 'dataset-policy-consumer'
export const inject = ['datasetPolicy', 'logger']

export function apply(ctx: Context) {
  const policy = ctx.datasetPolicy
  ctx.logger(name).debug('Training policy loaded: %s', policy.canSubmit('train', true))
}
```

```yaml
- id: dataset-policy
  name: cordis:group
  group: true
  isolate:
    datasetPolicy: true
  config:
    - id: provider
      name: 'file:///C:/path/to/deepseek-harness/examples/training-preset/provider.ts'
    - id: consumer
      name: 'file:///C:/path/to/deepseek-harness/examples/training-preset/consumer.ts'
```

两个模块只演示服务定义和解析。要执行训练门禁，在 consumer 中向共享工具链注册守卫，把它与 `canSubmit()` 对接。守卫需要的批次状态由可信任务记录提供。 [Cordis 服务教程](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cordis-tutorial/03-services.zh.md) · [原生预设隔离范例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/standard.patch.yml#L72) · [预设私有服务的读取实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/mount.ts#L87)

在 `agent/created` 中向 `agent.ctx` 注册单会话功能时，让 Agent lifecycle 持有注册，同时让注册插件保管对应 disposer。这样卸载插件时也能撤销已经装到 Agent 上的贡献。读取已完成轮次用持久 `turn/end`，实时文本用瞬态 `agent/assistant-stream`，等待整个 Agent 驱动空闲才用 `whenIdle()`。 [外部插件生命周期规范](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/practices.md#L11) · [运行时事件入口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/architecture.zh.md#L69)

### 会话什么时候应用预设

- 注册表在定义声明时预先挂载并审计插件，然后把创建的 Agent 绑定到对应作用域。预设可以在同一个已打开的空会话切换，首轮开始后会话锁定该选择。 [注册实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/index.ts#L93) · [锁定检查](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/index.ts#L355)
- 已运行的 Agent 与相应的进程内子 Agent 保有其原来的预设版本。停止 Host 后，会话按记录的 ID 恢复该预设的当前版本，ID 缺失会阻止恢复。要复现实验，在业务回执中另保存 bundle 版本、DSH 版本和配置版本。 [代际、子 Agent 与恢复](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/README.zh.md#L54)
- Web 或 API 创建会话时可明确传入 `agentPreset`。会话模型选择、推理强度和权限预设有各自的 API。模型供应商和适配器由 Host 配置。 [创建会话入参](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/session-controller/src/types.ts#L268) · [模型入口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/session-controller/src/index.ts#L307) · [权限预设](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/interaction/permission-presets/README.zh.md#L62)

## 角色、提示词和上下文

### 预设的人设和系统提示词

把 `dsh-persona` 加到 `config.plugins`。`prefix` 必填，`suffix` 默认空字符串。两者支持 `{{变量名}}`。`{{provider}}` 和 `{{model}}` 由 Agent 提供。下面保留默认拼装方式，方便同时使用工具指南、计划提示和其他已注册段落。 [Persona 字段和行为](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/persona/README.zh.md#L26-L53)

```yaml
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: |
      你是训练数据生产 Agent，当前模型是 {{model}}。
      汇报时引用数据版本、分区和真实的质检回执。
    suffix: |
      提交产物后给出可定位的产物 ID。
    complete: false
    includeRuntimeContext: true
```

- `complete: true` 让 `prefix` 成为唯一系统段落。同一次组装只能有一个有效的 `complete` 段。启用后应逐个复核原先依赖的系统提示词指导，工具 schema 仍由执行器装配。
- `includeRuntimeContext: false` 抑制可选的 `PromptContext`，标记 `required: true` 的操作性事实还会保留。文件指令、Skill 内容和插件直接写入的用户角色上下文各有自己的入口。
- `dsh-persona` 放在预设内。整个部署的人设由 Host 的 `dsh-system-prompt` 配置。

[Persona 实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/persona/src/index.ts#L24-L71) · [提示词的作用域规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/system-prompt/README.zh.md#L54-L89)

### 自己写提示词贡献插件

`section()` 用来注册稳定规则，`variable()` 给模板提供值，`context()` 提供随会话变化的事实。把下面模块作为一行加入 `config.plugins`。该例使用 `workingDirectory.get(agent.session)` 读取**会话的当前目录**。需要 `run_id` 或数据版本时，用同样的 `context()` 读取后文的领域服务。 [组装上下文与注册签名](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/system-prompt.zh.md#L9-L24) · [动态上下文与 Cordis API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/system-prompt.zh.md#L76-L179)

```ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-system-prompt'
import type {} from '@deepseek-ai/dsh-working-directory'

export const name = 'training-context'
export const inject = ['systemPrompt', 'workingDirectory']

export function apply(ctx: Context): void {
  ctx.systemPrompt.variable('training_pipeline', () => '训练数据生产')

  ctx.systemPrompt.section({
    name: 'training:protocol',
    order: 450,
    text: '本会话负责{{training_pipeline}}。提交产物时给出校验回执。',
  })

  ctx.systemPrompt.context({
    name: 'training:workspace',
    order: 300,
    interpolate: false,
    text: ({ agent }) => agent === undefined
      ? ''
      : `任务工作目录为 ${JSON.stringify(ctx.workingDirectory.get(agent.session))}。`,
  })
}
```

示例用于展示读取会话状态的写法。标准 Host 本身已经提供当前目录上下文，实际项目可以把这一条换成数据集版本等业务事实。`context()` 的文本函数是**同步读**，可在组装与准入刷新两个阶段被调用。外部查询结果由自己的服务提前更新，文本函数只读快照。会话日志会在快照变化或被压缩移除后记录当前值。 [提示词提供方约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/system-prompt/README.zh.md#L54-L89) · [工作目录服务](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/working-directory/README.zh.md#L26-L46)

| 接口 | 代码规范 |
|---|---|
| `section({ name, order, text, interpolate?, complete? })` | 名称在同一作用域唯一，顺序为有限数字。同序按名称排。相同名称的预设段落可以覆盖宿主段落。 |
| `variable(name, context => value)` | 名称匹配 `[a-z][a-z0-9_]*`。模板引用的变量必须有值。工作目录使用上下文服务。 |
| `context({ name, order, text, interpolate?, required? })` | 空文本跳过。外部内容设 `interpolate: false`。只给必须随请求提供的事实使用 `required: true`。 |
| `suppressRuntimeContext()` | 在本作用域抑制可选动态上下文。每个抑制器拥有独立的 disposer。 |
| `ctx.on('system-prompt/assemble', listener)` | 最后呈现阶段可加工段落、上下文和变量。先让下游组装，保留返回对象的其他字段。工具声明由 schema 提供方控制。 |
| `tools(context => ({ schemas, knownNames }))` | 底层工具 schema 提供器，供实现独立 transport 或执行器时使用。常规 Tool 注册后由既有执行器公布 schema。 |

[组装事件与接口定义](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/system-prompt.zh.md#L120-L242)

例如，将以下监听器放进声明了 `systemPrompt` 注入的 `apply(ctx)`，就能观测组装结果。添加提示词内容用 `section()`、`context()` 或 `agent.inject()`。底层 waterfall 能转换呈现，交付插件按官方约定优先使用这些独立的贡献接口。 [插件实践](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/practices.md#L11-L19)

```ts
ctx.on('system-prompt/assemble', async (_input, context, next) => {
  const result = await next()
  if (context.modelSelection !== undefined) {
    ctx.logger.debug(`已组装 ${result.sections.length} 个提示词段落。`)
  }
  return result
})
```

### 工作区指令、时间和其他内置上下文

把工作区约定放在工作区本身的 `AGENTS.md`，让指令插件发现它。以下两行都可加入预设。`maxBytes` 对用户指令链和项目指令链分别生效。初始加载及后续重新发现以作用中的会话工作目录和工具事件为准。 [工作区指令配置和刷新](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/context/agent-instructions/README.zh.md#L26-L68) · [时间上下文配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/context/time-context/README.zh.md#L24-L49)

```yaml
- id: agent-instructions
  name: '@deepseek-ai/dsh-agent-instructions'
  config:
    maxBytes: 65536
    instructionFileCandidates: [AGENTS.md, CLAUDE.md]
    localInstructionFileCandidates: [AGENTS.local.md, CLAUDE.local.md]
- id: time-context
  name: '@deepseek-ai/dsh-time-context'
  config:
    timeZone: Asia/Shanghai
    refreshIntervalMs: 600000
```

| 内置能力 | 接入方式和代码规范 |
|---|---|
| tmux 位置 | 可加预设行 `name: '@deepseek-ai/dsh-tmux-context'`，按需设 `config.refreshIntervalMs: 60000`。只有进程实际位于 tmux pane 内才记录位置与布局。 [tmux 上下文](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/context/tmux-context/README.zh.md#L26-L52) |
| 会话目录 | 注入 `workingDirectory`，用 `ctx.workingDirectory.get(agent.session)` 读，`await ctx.workingDirectory.set(agent, path, signal)` 改，`ensure(agent, signal)` 验证当前路径。Host 持有服务、文件系统验证和持久记录。 [工作目录实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/working-directory/src/index.ts#L135-L182) |
| `@` 文件补全 | Web Host 已装 `dsh-file-reference-local`。调用 `ctx.fileReferences.list(agent, query, signal)` 得到路径候选。候选路径与当前 Agent 的 `read` 命名空间应一致，读取文件需要实际的工具调用。 [文件引用接口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/context/file-reference/README.zh.md#L26-L44) |
| 引用另一会话 | Web Host 的 `dsh-session-reference` 支持 `@[标签](dsh-session:<编码后的-id>)`。插件用 `formatSessionReferenceMention({ sessionId, label })` 生成引用。`maxReferences`、`maxReferenceBytes`、`referenceContextFraction` 控制有界快照。 [会话引用协议](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/context/session-reference/README.zh.md#L26-L58) |
| DSH checkout / GUI 地址 | Web Host 已挂 `dsh-harness-dev-context`，从 `webApp` 等共享服务获取地址并注入动态上下文。要全局禁用，profile patch 按 `id: harness-dev-context` 设置 `disabled: true`。 [上下文配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/context/harness-dev-context/README.zh.md#L26-L32) |

### 给当前步骤追加上下文，或给下一步排队

系统段落适合稳定规则，`PromptContext` 适合最新状态。要在**已接纳的某一步**插入一条自己的用户角色消息，可以使用这个作用域内的 `agent/pre-step`。示例每轮首步添加一条快照，保留其他监听器的准入决策。 [事件形状和准入顺序](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent/src/runtime-types.ts#L338-L351) · [内置时间上下文的监听器](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/context/time-context/src/index.ts#L199-L243)

```ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-agent'
import { createUserMessage } from '@deepseek-ai/dsh-llm'

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap {
    'training-turn-context': {
      kind: 'training-turn-context'
      form: 'snapshot'
      sections: readonly { name: string; text: string }[]
    }
  }
}

export const name = 'training-turn-context'
export const inject = ['agents']

export function apply(ctx: Context): void {
  ctx.on('agent/pre-step', async ({ agent, step, signal }, next) => {
    const decision = await next()
    if (decision.kind !== 'enter' || signal.aborted || step !== 1) return decision

    const text = `当前会话 ID 为 ${JSON.stringify(agent.session.id)}。`
    const message = createUserMessage({
      content: [{ type: 'text', text }],
      source: {
        kind: 'training-turn-context',
        form: 'snapshot',
        sections: [{ name: 'training:session', text }],
      },
    })
    return { ...decision, messages: [...decision.messages, message] }
  }, { prepend: true })
}
```

`agent.inject(message)` 由外部生产方将消息排到下一个接纳步骤，**注入本身不会唤醒 Agent**。`agent.steer(message)` 追加下一步输入并唤醒，`agent.followup(message)` 排队开启下个轮次并唤醒。三者都可接收 `createUserMessage()` 建好的消息。`MessageSourceMap` 为来源声明独立的稳定 `kind`，快照记录 `sections`，单次通知可用 `form: 'notice'` 和 `summary`。触发器可能重试时，业务更新应自行用事件 ID 做幂等，耗时查询应接收 `signal`。 [Agent 收件箱](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent/README.zh.md#L56-L82) · [来源声明与消息建造器](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/llm/llm/src/message.ts#L45-L135)

## Skill、MCP、记忆和人类命令

### Skill 的三种来源

Web Host 提供 `ctx.skills`。把 `dsh-tool-skill` 放进预设，生成会话内可用目录，并允许模型通过 `skill({ name })` 加载正文。用户也能用 `/技能名` 显式加载可供用户调用的 Skill。Host、预设和 Agent 的 Skill 候选会合并，越近的层越优先，`rank` 只在同一层决定胜出。 [Skill 作用域和目录](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/skills.zh.md#L9-L16) · [Web profile 的 Skill 配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/cordis.patch.yml#L549-L562)

**磁盘或随包文件。** 在 `customSkillDirs` 下放 `dataset-check/SKILL.md`。也支持根目录下的 `dataset-check.md`，发现只扫根的直接子项。前置元数据至少有 `name` 和 `description`。`disable-model-invocation: true` 只留下用户或可信代码入口，`user-invocable: false` 取消用户入口，两者独立。`includeDefaultRoots: false` 只缩小这一提供方的扫描范围。 [文件格式和扫描配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/skill/skill-filesystem/README.zh.md#L30-L76)

```yaml
- id: dataset-skill-files
  name: '@deepseek-ai/dsh-skill-filesystem'
  config:
    providerName: dataset-files
    includeDefaultRoots: false
    customSkillDirs: ['C:/path/to/deepseek-harness/examples/training-preset/skills']
- id: tool-skill
  name: '@deepseek-ai/dsh-tool-skill'
```

```markdown
---
name: dataset-check
description: 根据已提供的产物清单检查训练数据覆盖情况。
---

先读取当前任务产物清单，再按验收协议调用质检工具。
回复引用被检查的产物、实际回执和缺失项。
```

**代码内置。** 在一个声明 `inject = ['skills']` 的预设插件的 `apply(ctx)` 中调用 `register()`，Skill 可以完全存在于内存。用 `resourceBase` 指明相对资源如何定位。`invocation` 未指定时两边均可调用。 [运行时 Skill 定义](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/skill/skill/src/index.ts#L94-L103) · [注册实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/skill/skill/src/index.ts#L437-L462)

```ts
ctx.skills.register({
  name: 'dataset-review',
  description: '核对采集回执、数据版本和分区。',
  source: 'runtime',
  invocation: { modelInvocable: true, userInvocable: true },
  content: '逐项核对采集回执与产物 ID，再报告可用数据的版本和分区。',
})
```

**远端、数据库或其他提供方。** 用 `registerProvider()` 同步注册，异步 I/O 放在 `list()` 和 `get()` 中。`list({ cwd, signal })` 提交目录候选，`get(candidate, { signal })` 加载获胜项的完整内容。以下是一个虚拟来源的完整注册模块，把静态对象替换为远端读即可。远端只成功了一部分时返回 `{ candidates, complete: false }`。收到版本变动时调用工厂参数 `control.invalidate()`，用 `control.signal` 回收订阅。 [提供方契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/skills.zh.md#L17-L62) · [候选与资源地址约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/skills.zh.md#L91-L185)

```ts
import type { Context } from '@deepseek-ai/cordis'
import type { SkillSummary } from '@deepseek-ai/dsh-skill'

export const name = 'dataset-skill-provider'
export const inject = ['skills']

export function apply(ctx: Context): void {
  const skill: SkillSummary = {
    name: 'dataset-acceptance',
    description: '应用训练产物的验收规则。',
    source: 'custom',
    provider: 'dataset-catalog',
    invocation: { modelInvocable: true, userInvocable: true },
  }

  ctx.skills.registerProvider(() => ({
    name: skill.provider,
    async list({ signal }) {
      signal?.throwIfAborted()
      return [{ ...skill, rank: 300, locator: skill.name }]
    },
    async get(candidate, { signal }) {
      signal?.throwIfAborted()
      if (candidate.locator !== skill.name) return undefined
      return { ...skill, content: '校验分区、样本数量、产物 ID 和完整回执。' }
    },
  }))
}
```

### MCP 连接和资源

把 `@deepseek-ai/dsh-mcp-client` 加进预设插件清单可做预设专用集成。外部服务器的工具名是 `mcp__<serverName>__<tool>`。服务器指令以字面文本进入系统提示词，资源通过 `list_mcp_resources`、`list_mcp_resource_templates`、`read_mcp_resource` 按当前 Agent 的可见服务器读取。`dsh-mcp-resources` 在 Host 统一安装即可。Web 设置里的 `dsh-mcp-manager` 管理全局列表。 [MCP 配置和模板](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/mcp/mcp-client/README.zh.md#L29-L117) · [资源发现与读取](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/mcp/mcp-resources/README.zh.md#L24-L60) · [全局管理器边界](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/mcp/mcp-manager/README.zh.md#L26-L32)

```yaml
- id: dataset-mcp
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: dataset
    transport: streamable-http
    url: 'http://127.0.0.1:3000/mcp'
    expandTemplates: true
    headers:
      Authorization: 'Bearer ${credential:DATASET_MCP_TOKEN}'
    startupTimeoutMs: 10000
    toolCallTimeoutMs: 60000
```

若服务是本机进程，`config` 使用 `serverName`、`transport: stdio`、`command` 和 `args`，可加 `cwd` 和显式 `env`。有鉴权时让宿主凭据服务解析模板。`serverName` 在注册层内唯一，需符合 `[A-Za-z0-9_-]{1,32}`。连不上时按实际需要选择后台重连或 `failOnStartupError: true`，验证时等待 `mcp__...` 工具完成发现。DSH 这条 MCP 连接支持 stdio 和 Streamable HTTP。如果仿真器本身提供 gRPC，可由自己注册的 Tool 或独立 MCP 服务调用 gRPC 客户端。 [连接生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/mcp/mcp-client/README.zh.md#L54-L110)

已有本地资源实现也可直接登记 `ctx.mcpResources.register(serverName, provider)`，无须为只读资源单独跑一条 MCP 连接。提供者遵守 MCP 的列表、模板与读取结果形状，并处理每次调用的取消。下面按构造的 `dataset://acceptance/protocol` 提供一份虚拟文本资源。 [资源注册接口与所有权](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/mcp/mcp-resources/src/index.ts#L19-L100) · [内置客户端的资源注册](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/mcp/mcp-client/src/server-context.ts#L28-L39)

```ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-mcp-resources'
import type { JsonValue } from '@deepseek-ai/dsh-util-values'

export const name = 'dataset-resources'
export const inject = ['mcpResources']

export function apply(ctx: Context): void {
  const resource = {
    uri: 'dataset://acceptance/protocol',
    name: '训练数据验收协议',
    mimeType: 'text/plain',
  }

  ctx.mcpResources.register('dataset-local', {
    async request(request, execution): Promise<JsonValue> {
      execution.signal.throwIfAborted()
      switch (request.method) {
        case 'resources/list':
          return { resources: request.cursor === undefined ? [resource] : [] }
        case 'resources/templates/list':
          return { resourceTemplates: [] }
        case 'resources/read':
          if (request.uri !== resource.uri) throw new Error('该验收协议 URI 不存在。')
          return { contents: [{ uri: resource.uri, mimeType: resource.mimeType, text: '保留分区标签和产物验收回执。' }] }
      }
    },
  })
}
```

### 跨会话记忆

当前发行组合默认没有长期记忆服务器。官方有 Memorix、MCP Reference Memory、Engram 的参考 overlay，可将其中的 `dsh-mcp-client` 行移入该预设的 `config.plugins`。独立记忆系统负责索引、权限和存储，DSH 提供连接、发现与调用。另一种实现是给预设的 Tool 注入你自己的记忆或检索服务，返回有界结果，用 `ctx.systemPrompt.context()` 提供同步快照，或用 `agent/pre-step` 在请求准入期间检索并附上来源。人工引用另一会话、检索记忆和自动提供上下文是三个不同的入口，分别按其数据范围授权。 [官方长期记忆接入示例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/guide/mcp-memory.zh.md#L1-L36) · [MCP Reference Memory overlay](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/apps/cli/config/examples/mcp-memory/mcp-reference-memory.cordis.yml)

### 新增给用户操作的斜杠命令

命令用 `ctx.commands.register()` 注册，按当前 Agent 的作用域发现与执行。下面的 `/task-status` 直接返回 UI 可读状态，用户执行它无需发起一次模型推理。真实查状态时可把 `rawInput` 按业务语法解析，并使用 `handler` 收到的 `signal` 调用业务 API。 [命令注册与调用](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/interaction/commands/README.zh.md#L25-L65) · [处理器和返回类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/interaction/commands/src/index.ts#L40-L79)

```ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-commands'
import type {} from '@deepseek-ai/dsh-working-directory'

export const name = 'task-commands'
export const inject = ['commands', 'workingDirectory']

export function apply(ctx: Context): void {
  ctx.commands.register({
    name: 'task-status',
    description: '查看当前会话及工作目录。',
    handler({ agent, rawInput, signal }) {
      if (rawInput.trim() !== '') {
        return { kind: 'error', text: '用法为 /task-status。' }
      }
      signal.throwIfAborted()
      const cwd = ctx.workingDirectory.get(agent.session)
      return { kind: 'success', text: `会话 ${agent.session.id}\n工作目录 ${cwd}` }
    },
  })
}
```

`name` 填不带 `/` 的小写名称。同层重名拒绝注册。命令可选 `input: { hint: '<run-id>', attachments: true }` 开启参数提示与附件能力。`handler` 负责消费 `attachments`、校验 `rawInput`，按语法返回 `{ kind: 'error', text }` 或 `{ kind: 'success', text }`。`command/run` 和 `command/done` 成对记录。原始参数由默认的 `recordInput: true` 写入日志，已有权威记录时可设为 `false`。Skill 的 `/技能名` 交给 Skill 加载机制，命令由 `ctx.commands` 执行业务代码，账户设置等操作仍由 Host 授权。 [命令生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/commands.zh.md) · [Skill 的用户调用](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/skill/tool-skill/README.zh.md#L52-L57)

## Tool 编写、可见性与执行策略

以下 YAML 片段中的条目放在预设的 `config.plugins` 下，标为 Host 的片段放在 Web profile 的补丁顶层。工具注册、执行器选择和事件监听都可以由预设贡献给 Host 注册表，注册会随插件的 Cordis 生命周期撤回。 [工具包参考](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/README.zh.md#L49) · [Host 与预设的插件位置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/compositions.md#L71)

### 写一个可以同时用于 Native 和 PTC 的业务 Tool

一个 Tool 插件可以注册多个定义。下面是可以直接加到自定义工具模块中的完整示例。它校验传入的采集清单，返回结构化计数，并通过可选的展示元数据支持 Web 卡片回放。

```ts
import type { Context } from '@deepseek-ai/cordis'
import { defineTool, ToolArgsError } from '@deepseek-ai/dsh-tools'

export const name = 'artifact-tools'
export const inject = ['tools']

export function apply(ctx: Context) {
  const countArtifacts = defineTool({
    name: 'count_artifacts',
    description: '统计指定采集清单的文件数，保留每个输入条目。',
    parameters: {
      items: {
        type: 'array',
        items: { type: 'string' },
        required: true,
        description: '相对于采集包的产物名称。',
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          count: { type: 'integer', required: true },
        },
      },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
      presentationMeta: (_args, value) => ({ count: value.count }),
    },
    async execute({ items }, exec) {
      exec.signal.throwIfAborted()
      if (items.some(item => item.trim() === '')) {
        throw new ToolArgsError(['items must contain only non-empty names'])
      }
      return { count: items.length }
    },
    isConcurrencySafe: () => true,
  })
  ctx.tools.register(countArtifacts)
}
```

| 接口 | 编写约定 |
|---|---|
| `name`、`description`、`parameters` | 名称在同一作用域唯一，选稳定的业务前缀。较近作用域可遮蔽同名定义。`run_code` 由框架保留。参数根是字段表，`required: true` 写在字段定义上。显式的对象节点声明 `additionalProperties`。输入 schema 无法表达的跨字段约束交给 `ToolArgsError(string[])`。 |
| `output.schema`、`execute(args, exec)` | 业务返回值符合 schema，可以是对象、数组、标量或 `null`。返回普通的无损 JSON 数据，字段中省略未定义项，数值保持有限。耗时 I/O 把 `exec.signal` 传给下游，直到本次调用启动的工作清理完毕再结算。预期的执行失败用带稳定 `code` 的 `HarnessError` 子类。领域结果由工具自己的 schema 表达。 |
| `output.render`、`output.presentationMeta` | `render` 从值投影模型可见内容块。`presentationMeta` 可将有限的结构化事实写入工具结果日志。`presentCall` 与 `presentResult` 是可选的 Host 展示投影，回放要求这些回调无 I/O、时间或随机数依赖。Web 专用卡片在 Client 用 `tool.call.toolview` 注册并读取原始事件与 `result.meta`。 |
| `isConcurrencySafe`、`timeoutMs` | 只有可并行安全的调用返回 `true`，省略时独占。`timeoutMs` 是正的毫秒预算，Host 或适用作用域挂载 `dsh-tool-call-timeout-policy` 后才执行。`maxParallelToolCalls` 属于 Agent loop，PTC 的程序内并发另外配置。 |
| `exec.deferContext()`、`exec.concludeTurn()` | 前者排队带有注册来源的 `UserMessage`，在工具结果之后交付。后者由成功结果标记结束当前轮次，适用于明确的协议终点。运行在当前 Tool 之外的通知可用 `agent.inject()`，交付到下次获准的请求。 |

直接注册原始 JSON Schema 的 `ToolDefinition` 时，自行校验输入。`defineTool` 使用仓库的 schema DSL 推导 TypeScript 类型并校验参数，输出规范值由共享流水线快照、校验和冻结。需要让 Tool 调仿真或训练服务时，保留这个接口，将 `execute` 接到业务 Client，把大产物写入业务存储，返回结构化 ID、状态和可定位的产物引用。 [工具编写参考](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-tool.zh.md) · [Tool 定义与执行上下文](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/contracts.ts#L245) · [无损输出校验](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/pipeline.ts#L557)

### 限制工具可用范围

- 静态组合通过添加或移除提供方条目控制预设贡献。若工具来自 Host 或上层作用域，预设插件可以调用 `ctx.tools.restrict({ deny: ['working_directory'] })`。这要求名称在调用作用域的继承工具中确实存在。`allow` 列表同样只写已知的继承工具名，并与其他限制取交集。对本层定义用行级装配或注册时的条件控制。 [作用域注册与限制源码](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/index.ts#L128) · [全局与 scoped 工具测试](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/tests/scoped.spec.ts#L125)
- 步骤级可用性通过 `register(definition, { when })`。函数接收 `agent`、`modelSelection` 与 `signal`。返回 `false` 时，该步的工具声明和分发都排除该工具。抛错会让步骤准备失败。一个步骤的重试和 PTC 内部调用复用已准入集合。条件只读取必要状态，可使用异步且要支持取消。示例用注册时已有的业务状态函数。 [条件工具协议](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/contracts.ts#L105) · [准入实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/index.ts#L239)

```ts
ctx.tools.register(countArtifacts, {
  when: ({ agent, signal }) => {
    signal.throwIfAborted()
    return hasActiveCaptureRun(agent.id)
  },
})
```

### 写权限门禁、派发包装和日志监听

下面的示例是一个单独的预设插件。它适用于存在 `start_training` 工具的预设。示例的核验规则是演示值，正式的数据包和权限检查使用你的业务服务。

```ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-tools'

export const name = 'training-policy'
export const inject = ['tools']

export function apply(ctx: Context) {
  ctx.on('tools/pre-execute', async (exec, next) => {
    if (exec.name !== 'start_training') return next()
    const decision = await next()
    if (decision.kind !== 'allow') return decision
    return {
      kind: 'ask',
      reason: 'Submit a dataset for training',
      displayReason: { en: 'Start the training run?', zh: '提交本次训练？' },
    }
  })

  ctx.tools.guard(exec => {
    if (exec.name !== 'start_training') return undefined
    const args = exec.arguments
    if (typeof args === 'object' && args !== null
      && 'manifestId' in args && typeof args.manifestId === 'string'
      && args.manifestId.trim().length > 0) {
      return undefined
    }
    return {
      reason: '提交训练需要 manifestId。',
      info: { name: 'TrainingAdmissionError', code: 'MANIFEST_REQUIRED' },
    }
  })

  ctx.on('tools/result', (exec, result) => {
    if (exec.name === 'start_training') {
      ctx.logger.info(JSON.stringify({
        tool: exec.name,
        callId: exec.callId,
        sessionId: exec.agent?.id,
        status: result.isError ? 'failed' : 'completed',
      }))
    }
    return undefined
  })
}
```

| 执行阶段 | 接口与约定 |
|---|---|
| 调用前 | `ctx.on('tools/pre-execute', async (exec, next) => …)`。`return next()` 交给下一层。可返回 `{ kind: 'deny', reason }`、`{ kind: 'ask', reason }` 或 `{ kind: 'cancel' }`。`ask` 使用 Host 审批。这里的 `exec.arguments` 已冻结。 |
| 最终门禁 | `ctx.tools.guard(exec => reasonOrUndefined)`。同步，从前置策略和审批通过后，到工具体执行前。拒绝理由不可由后续策略撤销。需查询外部信息的检查放在异步前置策略或业务服务，由实际改变训练状态的服务做最终核验。 |
| 分发环绕 | `ctx.on('tools/execute', async (exec, next) => …)`。通常用 `try { return await next() } finally { … }` 记录耗时。超时包装可以临时替换 `exec.signal`，在 `finally` 恢复并等待下游停稳。重试有副作用的动作前，依据业务幂等键和服务回执确认结果。 |
| 结果检查 | `ctx.on('tools/post-execute', async (exec, result, next) => …)`。可以 `return next()`，或返回 `{ kind: 'block', feedback: [{ type: 'text', text: reason }] }`。接受时可替换 `content` 或 `value` 并附带 `additionalContexts`。替换规范值会重新校验。已发生的业务副作用由业务服务自己回滚或补偿。 |
| 事后观测 | `tools/result` 读取冻结结果，回调返回 `undefined`。可收集 `callId`、`rootCallId`、操作名、会话和状态。`tools/change` 是注册变更通知，事件本身不按预设过滤。`tools/ptc-dispatch-log` 可处理程序子调用的日志内容。 |

Host 的默认组合已挂载工具超时、结果 spill 和会话持久化检查点。`spill-policy.config.maxInlineTokens` 影响行内展示，使用 Host 提供的 spill 存储。只改写展示内容时，PTC 仍可取得原规范值。需要控制程序可读的字段，在业务输出或结果策略中按值处理。调用前工具门禁适用于 DSH 分发，空间生产系统仍应在各个服务入口校验训练分区和可用产物。 [事件与返回值定义](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/events.ts#L6) · [前置与后置决策类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/contracts.ts#L365) · [Host 包装层](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/base/cordis.patch.yml#L418) · [结果处理](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/pipeline.ts#L505)

### 选择 Native、PTC 或单独的程序工具

二选一放进预设。Web 的宿主已有 Native 默认值，省略时由作用域继承。每个作用域只出现一个执行器。 [执行器装配](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/README.zh.md#L75)

```yaml
- id: native-executor
  name: '@deepseek-ai/dsh-tool-executor-native'
```

```yaml
- id: ptc-executor
  name: '@deepseek-ai/dsh-tool-executor-ptc'
  config:
    maxParallelSubCalls: 4
    maxSubCallsPerMinute: 120
```

Native 直接暴露可见工具的 schema。PTC 暴露 `run_code` 和 TypeScript SDK。程序中用 `await tools.count_artifacts({ items: ['rgb.png', 'depth.exr'] })` 取得 `{ count: 2 }`，用 `inspect(...)` 选择展示给模型的内容。内部调用仍走参数验证、审批、guard、日志和结果处理。PTC 需要宿主的 `ptcRuntime`、工具与提示词服务，以及调用时的工作目录。当前 Web 的基础组合提供 Node PTC 运行时。并发只作用于标为并行安全的子调用，实际调用总额按运行超时和 `maxSubCallsPerMinute` 计算。 [PTC 配置和调用规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tool-executor-ptc/README.zh.md#L26) · [基础运行时](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/base/cordis.patch.yml#L407) · [官方 PTC 预设](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/ptc.patch.yml#L127)

已有配置可能使用 `@deepseek-ai/dsh-agent-tool-presentation`，其 `config.mode` 必填，接受 `native` 或 `ptc`。这是仍可用的兼容入口，源码已经标记弃用。新预设直接挂执行器，两个入口使用相同作用域的执行器位置。兼容入口选 PTC 时，首次取得运行时之前保留继承的执行器。直接挂 PTC 时会等待必需注入，预设可用性检查也能指出这项依赖。 [兼容入口源码](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent-tool-presentation/src/index.ts#L19) · [兼容入口的加载时序](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent-tool-presentation/README.zh.md#L40)

自定义执行器用 `ctx.tools.setExecutor(executor)`，实现 `ToolExecutor.describe(definitions)` 和 `execute(batch)`。沿用 `@deepseek-ai/dsh-tools/pipeline` 的 `ToolExecutionPipeline` 与 `executeToolBatch` 可以共用策略和日志。结果按输入调用顺序交付，每个调用一个结算结果。尊重 `batch.signal`，等待已经开始的工作结束，按契约提交工具日志和后续上下文。原生执行器是最短的实现示例。 [执行器接口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/executor.ts#L60) · [原生执行器源码](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tool-executor-native/src/index.ts#L1)

如果只想让一个工具跑带私有能力的程序，在 Native 预设里可以注册具名程序工具。`privateDefinitions` 是代码提供的完整 `ToolDefinition[]`，无需向模型全局注册。依赖声明包含 `tools`、`ptcRuntime` 和运行时所需的 `workingDirectory`。 [工厂代码和类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tool-executor-ptc/src/run-code.ts#L13)

```ts
import { createRunCodeTool } from '@deepseek-ai/dsh-tool-executor-ptc/run-code'

ctx.tools.register(createRunCodeTool(ctx, {
  name: 'batch_quality_check',
  description: '使用获准的质检操作批量校验场景。',
  runtime: ctx.ptcRuntime,
  tools: privateDefinitions,
  limits: { maxParallelSubCalls: 4, maxSubCallsPerMinute: 120 },
}))
```

### 使用内置工具与持久 shell

直接挂载内置 Tool 时，按对应包的 `Config` 填写字段。Web 中的终端、文件系统、语言服务、检索、后台任务等工具依赖各自的 Host 服务。本表展示挂载行所需的包名后缀与常用配置，包的完整名称都以 `@deepseek-ai/dsh-` 开头，插件子路径照表填写。每一个模型参数和完整默认配置可查生成目录。 [工具名与服务依赖总表](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/tool-catalog.zh.md#L16) · [各包配置字段](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/config-catalog.zh.md)

| 能力 | `name` 后缀 | 编写规格 |
|---|---|---|
| 文件读写、图像读取 | `tool-fs` | `config: { applyPatch: false }` 省略 `apply_patch`。只挂指定操作可用 `read`、`readImage`、`write`、`edit` 四个布尔字段。参照内置 `minimal`。 |
| 文件和文本搜索 | `tool-fs-search` | `config: { sampleOverCapGlobResults: false }`。按 `glob` 和 `grep` 的参数 schema 使用。 |
| 单次 shell | `tool-bash`、`tool-pwsh` | Windows 选 PowerShell，其他平台选 Bash，与 Host shell/sandbox 后端配合。可按 `standard` 用 `disabled: !!js process.platform === 'win32'` 和反向条件。 |
| 持久 shell 与交互 PTY | `tool-bash-persistent`、`tool-pwsh-persistent`、`tool-terminal` | 持久 shell 维持同一 Agent 的目录、变量和函数。PTY 工具提供显式打开、读写、信号和关闭。两者都依赖 `terminals`。同名 `bash` 或 `pwsh` 在同一作用域只选一份实现。 |
| 用户问答 | `tool-ask-user` | 使用 Host `userQuestions`，需要 timed 模式时写 `config: { mode: timed }`。默认阻塞等答复，timed 支持前台超时。 |
| 会话待办 | `tool-todo` | `config.allowParallelInProgress` 必填。`todo_write` 写会话事件，各 Agent 自己的待办由相应会话投影读取。 |
| 搜索与取网页 | `tool-web` | `config: { fetch: true, searchTimeoutMs: 60000 }` 是 `standard` 采用的配置。Host `web` 注册实际提供方。 |
| 文档、表格、幻灯片 | `tool-office`、`tool-present` | 挂选用的包，使用其 Office 转换、渲染、重算或产物呈现工具。依赖和配置按目录逐包核对。 |
| 工作目录、LSP、会话查询 | `tool-working-directory`、`tool-lsp`、`tool-session-query` | 依赖已有工作目录、LSP 或会话查询服务。LSP 还需要 provider。会话查询工具是只读并带调用方授权。 |
| 插件管理、插件市场和 Cordis 检查 | `plugin-manager/tools`、`plugin-market/tools`、`tool-cordis` | 用明确依赖的 Host 服务加载。检查工具是内置 `cordis` 预设的用途之一。同类工具根据实际模型能力和 profile 选择。 |
| 工作流、定时任务、后台控制、团队 | `tool-workflow`、`tool-schedule`、`tool-jobs`、`tool-agent-team` | 下文给出工作流和任务的作用域。定时任务定义和调度服务由 Host 维护，模型入口可按预设挂载。 |

持久 PowerShell 可以复用 `minimal` 的隔离组。下面只装 Windows 分支，完整跨平台例子还会为非 Windows 配置 Bash 的后端与工具。组内提供者和消费者共同解析同一个 `terminals` realm。 [官方持久 shell 分组](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/minimal.patch.yml#L34) · [持久 PowerShell 配置定义](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/shell/tool-pwsh-persistent/src/index.ts#L455)

```yaml
- id: persistent-shell
  name: cordis:group
  group: true
  isolate:
    terminals: true
  config:
    - id: pty
      name: '@deepseek-ai/dsh-terminal'
    - id: terminal-pwsh
      name: '@deepseek-ai/dsh-terminal-bash'
      disabled: !!js process.platform !== 'win32'
      config:
        shellDialect: pwsh
        timeoutMs: 300000
    - id: persistent-pwsh
      name: '@deepseek-ai/dsh-tool-pwsh-persistent'
      disabled: !!js process.platform !== 'win32'
      config:
        timeoutMs: 300000
        maxOutputChars: 16000
```

### 后台任务和可查询的运行进度

预设含有 `dsh-tool-jobs` 且 Host 提供 `dsh-jobs-local` 时，可在工具中发布长期工作，得到 `jobId`，用户与 Agent 用 `job_list`、`job_output`、`job_kill` 控制它。默认 Web 把控制器条目交给各预设。`owner` 写调用 Agent 的 Session ID，`run(handle)` 同步返回 `cancel` 与 `done`，`done` 在清理后结算。业务侧远程训练可有自己的持久 `runId`，将它与当前进程的 `jobId` 一起返回即可。 [Job 生产者契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/jobs/jobs/src/types.ts#L139) · [Job 运行时](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/jobs/jobs/README.zh.md#L39) · [Web 的装配](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/cordis.patch.yml#L540)

```yaml
- id: tool-jobs
  name: '@deepseek-ai/dsh-tool-jobs'
  config:
    maxWaitTimeoutMs: 600000
    completionDelivery: quiet
```

下面是工具模块可以调用的生产者函数。该模块需要注入 `tools` 与 `jobs` 并给自己的包声明 `@deepseek-ai/dsh-jobs` 类型依赖。`prepare` 由项目实现，收到取消信号后要停止自己的 I/O 或经业务协议取消任务。

```ts
import type { Context } from '@deepseek-ai/cordis'
import type { JobOutcome } from '@deepseek-ai/dsh-jobs'
import { ToolContextUnavailableError, type ToolRunContext } from '@deepseek-ai/dsh-tools'

declare module '@deepseek-ai/dsh-jobs' {
  interface JobKindMap {
    'prepare-manifest': 'prepare-manifest'
  }
}

export function startPreparation(
  ctx: Context,
  exec: ToolRunContext,
  manifestId: string,
  prepare: (manifestId: string, signal: AbortSignal) => Promise<string>,
) {
  exec.signal.throwIfAborted()
  if (exec.agent === undefined) {
    throw new ToolContextUnavailableError('Preparing a manifest requires a calling Agent')
  }
  const jobId = ctx.jobs.start({
    kind: 'prepare-manifest',
    label: 'Prepare ' + manifestId,
    owner: exec.agent.id,
    toolCall: { callId: exec.callId, rootCallId: exec.rootCallId },
    run(job) {
      const controller = new AbortController()
      const done = Promise.resolve().then(async (): Promise<JobOutcome> => {
        try {
          job.updateProgress('Preparing manifest')
          const result = await prepare(manifestId, controller.signal)
          if (controller.signal.aborted) return { status: 'killed' }
          return { status: 'completed', result }
        } catch (error) {
          if (controller.signal.aborted) return { status: 'killed' }
          return { status: 'failed', detail: String(error) }
        }
      })
      return { cancel: reason => controller.abort(reason), done }
    },
  })
  return { kind: 'background' as const, jobId }
}
```

发布成功以后由 Job 自己的信号控制生命周期。取消当前工具等待与停止后台生产是两个不同操作。需要前台等待时，直接在 Tool 内用 `exec.signal` 驱动操作。生产承诺、读取游标和观测接口的参考分别是 `JobSpec` 和既有 Bash 后台生产代码。 [所有者与取消约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-tool.zh.md#L58) · [Bash 生产者实例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/shell/tool-bash/src/index.ts#L306)

### 验收 Tool 与策略

用同一个无副作用测试操作验证公开 schema、输入校验、规范结果、运行策略和作用域。Native 会话可在宿主测试中用下列调用进入真实分发。`agent` 来自测试创建的活跃会话，`signal` 属于本次调用。调用块中的 `arguments` 是原始 JSON 字符串。这里省略日志坐标，正式 Agent loop 会写入真实步骤日志。条件工具的测试需生成适用于该步骤的 `toolSet`，并在批次结算后释放它。 [批次 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/executor.ts#L20) · [作用域测试](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/tests/scoped.spec.ts#L125)

```ts
import { randomUUID } from 'node:crypto'
import { ToolCallId } from '@deepseek-ai/dsh-llm'

const batch = await ctx.tools.execute({
  agent,
  signal,
  calls: [{
    type: 'tool-call',
    id: ToolCallId(randomUUID()),
    name: 'count_artifacts',
    arguments: JSON.stringify({ items: ['rgb.png', 'depth.exr'] }),
  }],
})
```

期望 `batch.results[0]?.result` 成功且 `value` 为 `{ count: 2 }`。对应的 PTC 会话发送 `run_code`，把 `inspect(await tools.count_artifacts({ items: ['rgb.png', 'depth.exr'] }))` 作为 `code`，并附简短 `description`。试验无效输入、预先取消、guard 拒绝和其他预设的不可见性。涉及写入的工具，在测试后端中验证拒绝发生时业务接口调用次数为零。 [PTC 调用与输出](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tool-executor-ptc/README.zh.md#L105)

## 规划、长会话与持续目标

### 计划模式与用户评审

将 `dsh-plan-mode` 作为一个隔离组挂在预设里。`section` 是唯一必填配置。用户可以输入 `/plan`、`/plan <message>` 或 `/plan off`。模型通过 `exit_plan_mode({ plan })` 提交以一级 Markdown 标题 `# 标题` 开始的计划，评审需要交互式的 Host `userQuestions`。计划状态写入会话并可恢复。提示词提供规划指引，实际可执行的动作由工具策略、沙箱和审批控制。 [计划模式配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/plan/plan-mode/README.zh.md#L26) · [官方计划组装](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/standard.patch.yml#L51)

```yaml
- id: planning
  name: cordis:group
  group: true
  isolate:
    planMode: true
  config:
    - id: plan-mode
      name: '@deepseek-ai/dsh-plan-mode'
      config:
        section: |
          先记录数据来源、分区、采集参数和验收标准。
          使用 exit_plan_mode 将完整生产计划交给用户评审。
```

同一 realm 内的插件可以注入 `planMode` 并调用 `ctx.planMode.get(agent)` 与 `ctx.planMode.set(agent, active)`。`set` 在开放轮次期间可能返回 `queued`，选择到下一次获准步骤才提交。 [计划控制器 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/plan.zh.md#L51)

### 压缩上下文与修剪工具结果

按官方分组将后端、可选修剪器与 `/compact` 命令挂到同一预设。Host 保留共享 token 计量、LLM 和 Session 服务。`dsh-compaction-basic` 支持自动窗口压力与已确认溢出恢复。设定较小窗口的独立策略时，从实际路由填写 `provider` 和 `model`，配置正的摘要输出上限，并保证保留预算低于触发阈值。`retainRatio` 与 `retainTokens` 二选一，`summarizationProvider` 与 `summarizationModel` 成对。给可观测的训练规格和产物引用分配独立持久记录，压缩以后可以按 ID 找回。 [官方压缩分组](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/standard.patch.yml#L72) · [窗口与保留规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/compaction/compaction-basic/README.zh.md#L49)

```yaml
- id: compaction
  name: cordis:group
  group: true
  isolate:
    compaction: true
    toolResultPruner: true
  config:
    - id: compaction-basic
      name: '@deepseek-ai/dsh-compaction-basic'
      config:
        thresholdRatio: 0.8
        retainRatio: 0.16
        headroomTokens: 8192
        maxTokens: 4096
    - id: command-compact
      name: '@deepseek-ai/dsh-command-compact'
    - id: tool-result-pruner
      name: '@deepseek-ai/dsh-compaction-tool-result-pruner'
      config:
        thresholdChars: 8192
        headChars: 4096
        tailChars: 1024
```

`auto: false` 保留按需压缩。自定义后端实现 `CompactionEngine`，至少按抽象接口实现 `compactIfNeeded`、`compactNow`、范围压缩，并保留正确的调用／结果配对与检查点。消费方在同一 realm 内解析 `ctx.compaction`。修剪仅在触发压缩后发生，原始结果保留于会话日志。基础 Host 还使用 `dsh-compaction-image-offload` 处理模型的特定图片预算错误和重试。 [压缩后端接口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/compaction/compaction/src/index.ts#L110) · [工具结果修剪](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/compaction/compaction-tool-result-pruner/README.zh.md#L44) · [图片省略恢复](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/compaction/compaction-image-offload/README.zh.md#L28)

### 同会话持久目标与自动续行

Web 宿主已有 `dsh-goal` 和 `dsh-goal-round-driver`。预设只挂面向用户的命令及面向模型的工具。驱动器根据目标的状态、已启用的续行、空闲状态和轮次额度，决定是否排入下一轮。恢复会话后用户可用 `/goal resume` 授权续行。 [Web Goal 归属](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/cordis.patch.yml#L564) · [驱动器行为](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/goal/goal-round-driver/README.zh.md#L26)

```yaml
- id: command-goal
  name: '@deepseek-ai/dsh-command-goal'
- id: tool-goal
  name: '@deepseek-ai/dsh-tool-goal'
  config:
    blockedAfterConsecutiveRounds: 3
```

`/goal <objective>` 创建并启用续行，`/goal pause`、`/goal resume`、`/goal edit <objective>` 和 `/goal clear` 管理生命周期。模型用 `get_goal()` 读取当前版本，`create_goal({ objective, max_goal_rounds })` 创建，`update_goal({ goal_id, revision, action })` 按版本更新。`blocked` 需要 `blocked_reason`，模型在自主轮次报告阻塞还受配置的连续轮次阈值约束。训练应用可在可信 Host 代码中调用 `ctx.goals.create(agent, { objective, maxGoalRounds: 8 })`。更新时传该 Agent 的当前 `{ id, revision }`。模型侧创建与修改做了人类直接输入和根 Agent 权限检查。Goal 持久化的是会话目标和轮次进展，外部训练队列自己的作业状态由训练后端管理。 [命令语法](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/goal/command-goal/README.zh.md#L27) · [Goal 工具契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/goal/tool-goal/README.zh.md#L28) · [Goal 服务 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/goal.zh.md#L176)

## 子 Agent、Team 与工作流

### 发起子 Agent 并为它选预设

Web 的 Host 已注册 `subagents`、`spawn` 与 `fork`。预设挑选工具入口。下面演示把默认子 Agent 固定为 `dataset-qc`，该 ID 必须另有预设声明。`allowedAgentPresets` 是允许模型通过 `agent_preset` 选择的白名单，包含默认 ID。只配置 `agentPreset` 时选择固定。进程内 spawn 支持独立预设，fork 继承父预设和已完成轮次的历史。省略显式子预设时，本地子 Agent 加入父 Agent 的当前预设代际。 [Web 委派归属](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/cordis.patch.yml#L593) · [子级预设和配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/subagent/tool-subagent/README.zh.md#L42)

```yaml
- id: dataset-qc-child
  name: '@deepseek-ai/dsh-tool-subagent'
  config:
    provider: spawn
    toolName: check_dataset_quality
    agentPreset: dataset-qc
    allowedAgentPresets: [dataset-qc]
    maxDepth: 1

- id: subagent-fork
  name: '@deepseek-ai/dsh-tool-subagent'
  config:
    provider: fork
    toolName: subagent_fork

- id: subagent-controls
  name: '@deepseek-ai/dsh-tool-subagent-control'
  config:
    interrupt: true
```

- `maxDepth` 是递归深度，省略时读取 Host 默认值。`modelSelection: true` 与 `modelDiscovery: true` 可加入支持相应能力的实例。后者新增 `list_subagent_models`，同一作用域只开一次。`agentOptions` 可以为支持的后端配置子级的 `provider`、`model`、`reasoningEffort`、`maxTokens`，显式模型选择仍受路由与会话策略检查。ACP、Codex、Claude Code、DSH SDK 等替代 provider 由 Host 挂载，并各自声明支持的能力。
- 普通委派工具返回 activation 句柄信息，完成结果由后台通知交付。控制插件新增 `send_message`、`list_agents`、`wait_agent`，可选 `interrupt_agent`。在模型需要子 Agent 的可验证 JSON 时，通过宿主代码使用 `ctx.subagents.startActivation()` 并提供 `outputSchema`，读取 `result.structured`，检查 `stopReason` 后再消费结果。
- 程序必须为已发布的 activation 管理清理。`signal` 取消发布前启动，发布后需要以 `dispose()` 结束并等待精确 activation。`delivery: 'caller'` 由调用者消费结果，`'parent'` 交给父 Agent 通知。 [Subagent 功能与生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/subagent/subagent/README.zh.md#L49) · [控制工具](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/subagent/tool-subagent-control/README.zh.md#L33) · [Activation 类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/subagent/subagent/src/types.ts#L28)

在注入 `subagents` 的插件里可用以下结构。`parent` 是当前调用的活跃 Agent，`signal` 来自调用方。

```ts
const child = await ctx.subagents.startActivation({
  provider: 'spawn',
  agentPreset: 'dataset-qc',
  label: 'Check capture manifest',
  prompt: [{ type: 'text', text: '核对当前采集清单，返回通过状态。' }],
  parent,
  signal,
  delivery: 'caller',
  outputSchema: {
    type: 'object',
    additionalProperties: false,
    properties: { passed: { type: 'boolean' } },
    required: ['passed'],
  },
})

let stopping: Promise<void> | undefined
const requestStop = () => {
  stopping ??= child.dispose()
  void stopping.catch(() => {})
}
signal.addEventListener('abort', requestStop, { once: true })
try {
  if (signal.aborted) requestStop()
  const outcome = await child.result
  signal.throwIfAborted()
  if (outcome.stopReason !== 'completed') throw new Error('采集质检未完成')
  return outcome.structured
} finally {
  signal.removeEventListener('abort', requestStop)
  await (stopping ?? child.dispose())
}
```

### Team 的共享任务板与协作

默认 Web Host 有 `dsh-agent-team` 和 `dsh-tool-agent-team`，Team 模式按根 Session 保存，默认关闭。根 Session 可以通过模型菜单开启。程序化入口是 `await ctx.agentTeams.setEnabled(rootAgent, true, signal)`。启用后整个树的后续步骤出现 `team_task_create`、`team_task_get`、`team_task_list` 和 `team_task_update`。普通的启动、发现、联络仍用 `subagent`、`list_agents`、`send_message`。共享任务支持依赖、版本比较更新和分配，任务变更不会唤醒闲置成员，交付新工作时需发送消息。写范围用于提醒协作者。 [Team 模式及宿主配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/team/agent-team/README.zh.md#L26) · [Team 工具注册](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/team/tool-agent-team/src/index.ts#L94)

部署希望默认启用所有新根 Session 时，可以写以下 **Host 补丁**。若只对特定预设开启，由可信入口在选择该预设后对已创建的根 Agent 调用 `setEnabled`。Team 服务和已经挂载的工具由 Host 提供。 [根会话模式 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/agent-team.zh.md#L78) · [官方 defaultEnabled 补丁](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/apps/cli/config/examples/team-mode.yml)

```yaml
- id: agent-team
  config:
    defaultEnabled: true
    maxTasks: 256
```

在注入 `agentTeams` 的可信插件里，下面的例子使用当前任务的版本进行认领。过期版本会由服务拒绝，可重新读取后决定是否重试。同一任务的依赖完成和所有权规则由 Team 服务检查。 [Team API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/team/agent-team/src/index.ts#L103) · [共享任务更新类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/team/agent-team/src/types.ts#L143)

```ts
const task = await ctx.agentTeams.createTask(rootAgent, {
  subject: '质检 office-01',
  description: '核对相机帧、标注和 manifest 是否对齐。',
  writeScopes: ['reports/office-01/'],
}, signal)

await ctx.agentTeams.updateTask(rootAgent, {
  taskId: task.id,
  expectedRevision: task.revision,
  action: 'claim',
}, signal)
```

### 可编程的多 Agent 编排

在预设中将 `workflow-ptc` 与 `tool-workflow` 放进同一 `workflowEngine` 隔离组。底层依赖 Host 的 TypeScript PTC 运行时、沙箱和具名 subagent provider。引擎可设 `provider`、`maxConcurrentAgents`、`maxTotalAgents`、`maxItemsPerCall`、`syncTimeoutMs`。它自己负责脚本和子 Agent 的资源清理，运行显式接受调用方信号。 `tool-workflow` 的 `enableRunInBackground` 还要求 Host Job 服务和该预设的 `tool-jobs` 控制器。 [工作流引擎配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/workflow/workflow-ptc/README.zh.md#L26) · [工作流工具与后台模式](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/workflow/tool-workflow/README.zh.md#L26)

```yaml
- id: dataset-workflow
  name: cordis:group
  group: true
  isolate:
    workflowEngine: true
  config:
    - id: workflow-engine
      name: '@deepseek-ai/dsh-workflow-ptc'
      config:
        provider: spawn
        maxConcurrentAgents: 4
        maxTotalAgents: 40
        maxItemsPerCall: 128
        syncTimeoutMs: 5000
    - id: workflow-tool
      name: '@deepseek-ai/dsh-tool-workflow'
      config:
        toolName: run_dataset_workflow
        maxResultChars: 12000
        enableRunInBackground: true
```

工具参数是 `meta`、`script`、可选 JSON 对象 `args` 和允许时的 `run_in_background`。脚本用纯 JavaScript，其中 `agent()`、`parallel()`、`pipeline()`、`phase()`、`log()` 是运行时提供的入口，支持顶层 `await`。模型传入的 `agent()` 选项支持 `label`、`phase`、`provider`、`model`、对象根 `schema`。确需为每个子任务选独立预设时，用上节的 `startActivation({ agentPreset, ... })` 启动进程内 spawn。子 Agent 普通失败时脚本取得 `null`，协议错误或超出预算时工作流整体报错。 [脚本约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/workflow/workflow/README.zh.md#L30) · [`agent()` 选项校验](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/workflow/workflow-ptc/src/runtime.ts#L237)

```js
phase('质检采集')
const checks = await parallel(args.sceneIds.map(sceneId => () =>
  agent('检查场景 ' + sceneId + ' 的采集产物，并返回摘要。', { label: sceneId })
))
return {
  results: args.sceneIds.map((sceneId, index) => ({
    sceneId,
    check: checks[index],
  })),
}
```

在同一隔离组内，自己的业务插件可以注入 `workflowEngine`，传入已验证的 `args` 和脚本文本。使用者始终在 `finally` 中 `dispose()`。工作流事件 `workflow/start`、`workflow/phase`、`workflow/log`、`workflow/agent-start`、`workflow/agent-end`、`workflow/end` 可作为观察来源，正式训练作业的检查点与重试仍由自己的作业服务记录。 [编程方式运行与事件](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/workflow/workflow/README.zh.md#L49) · [运行句柄定义](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/workflow/workflow/src/runtime-types.ts#L19)

```ts
const run = ctx.workflowEngine.start({
  script,
  meta: { name: 'capture-qc', description: '批量检查采集产物' },
  args: { sceneIds: ['office-01', 'office-02'] },
  parent,
  signal,
  maxTotalAgents: 2,
})
try {
  const result = await run.result
  if (result.stopReason !== 'completed') {
    throw new Error(result.error ?? result.stopReason)
  }
  return result.value
} finally {
  await run.dispose()
}
```

## 官方扩展点的补充写法

### 接收 Agent 生命周期事件

插件可在预设内选择监听 `agent/created`、`agent/status`、`agent/pre-step`、`agent/request`、`agent/request-error`、`agent/turn-stopping`，以及按会话路由的日志事件。下面的监听器观察 Agent 创建和状态变化。要观察已结算的轮次，则订阅持久 `turn/end` 事件。采集模型文本时另监听 `agent/assistant-stream`，用已提交的 Assistant 事件作为最终记录。 [Agent 事件类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent/src/runtime-types.ts#L285) · [Session 广播与作用域](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/session/src/index.ts) · [事件生产者和消费者](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/event-producer-consumer.zh.md)

```ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-agent'

export const name = 'training-agent-status'
export const inject = ['agents', 'logger']

export function apply(ctx: Context): void {
  const logger = ctx.logger(name)
  ctx.on('agent/created', ({ agent }) => {
    logger.info('Created %s', agent.session.id)
    return undefined
  })
  ctx.on('agent/status', ({ agent, status }) => {
    logger.debug('Session %s has status %s', agent.session.id, status)
  })
}
```

事件分两种写法。观察事件只读取负载，waterfall 事件按事件声明返回 `next()` 的结果或合法决策。需要让既有 Agent 开始下一轮时调用 `followup()`，需要在当前轮的下一次请求引导模型时调用 `steer()`。若要实现无人值守循环，给任务定义终止条件和明确的业务状态，使用已提交的轮次事件推进。 [扩展点与 Agent 输入操作](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/extension-cookbook.zh.md#L151)

### Cordis 检查、插件管理和插件市场

`cordis` 创造模式展示了可把 Cordis 检查、插件管理和插件市场 Tool 放进自定义预设。检查 Tool 提供运行时 API 和配置的只读说明。管理 Tool 的实际安装、更新与访问规则由 Host 处理。挪用下面的声明时需要相应的 profile 服务，管理项根据 `profileContext` 启用。

```yaml
- id: tool-cordis
  name: '@deepseek-ai/dsh-tool-cordis'
- id: tool-plugin-manager
  name: '@deepseek-ai/dsh-plugin-manager/tools'
  disabled: !!js "!ctx.get('profileContext')"
- id: tool-plugin-market
  name: '@deepseek-ai/dsh-plugin-market/tools'
  disabled: !!js "!ctx.get('profileContext')"
```

[创造模式完整装配](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/cordis.patch.yml#L124) · [Cordis 检查能力](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/extensions/tool-cordis/README.zh.md)

## 会话状态和业务持久化

### 从现有 Session 日志派生状态

预设插件可以通过 `ctx.sessionProjections` 给会话注册状态折叠。注册表的定义按 `key` 在 Host 共享，状态单元按 Session 分开。`wire` 省略时仅供 Host 使用。下面按已提交的 `tool/call` 事件对示例工具计数。这是**调用数**，成功次数需要匹配对应的 `tool/result`，并检查 `message.isError`。示例使用仅供 Host 查阅的 `artifactUsage`。Web 章节另外给出带 wire 形状的 `artifactCallCount`，同一场景选其中一份注册即可。选择符合业务含义的键，`stateVersion` 随状态形状和折叠语义升级，`apply` 对无关事件直接返回原引用。 [投影 API、生命周期与版本](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/session-projection/README.zh.md#L24-L73) · [工具事件字段](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/session/src/types.ts#L364-L391)

```ts
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-session-projection'
import { z } from 'zod'

export const name = 'artifact-usage-projection'
export const inject = ['sessionProjections']

export async function apply(ctx: Context): Promise<void> {
  await ctx.sessionProjections.register({
    key: 'artifactUsage',
    stateSchema: z.object({ calls: z.number().int().nonnegative() }),
    stateVersion: 1,
    init: () => ({ calls: 0 }),
    apply(state, event) {
      if (event.type !== 'tool/call' || event.data.name !== 'count_artifacts') {
        return state
      }
      return { calls: state.calls + 1 }
    },
  })
}
```

- 需要读取时保留 `await register(...)` 的返回句柄，调用 `handle.stateOf(agent.session)`，或用 `handle.readerFor(session)` 生成会话绑定的读函数。投影注册随插件 fiber 释放，提前释放用 `await handle.dispose()`。
- 需要发到浏览器时，在 `@deepseek-ai/dsh-session-projection/types` 声明合并 `SessionProjectionMap`，并增加 `wire: { viewSchema, view }`。要省略列表摘要里的大字段，用 `SessionProjectionSummaryExcluded<T>` 对齐 `wire.summary: false`。投影是会话读模型，提供给前端的字段应只包含该会话允许读取的业务信息。
- 选择按预设挂载所需的消费方，例如命令与上下文。若工作台跨会话读取该投影，放 Host 唯一的定义更便于保持部署所有会话的可用性。禁止把不同预设参数捕获在同名投影折叠闭包中，同名同版本会共享一个定义。

[投影定义源码](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/session-projection/src/index.ts#L80-L136) · [客户端字段类型约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/session-projection/src/types.ts#L10-L44)

### 单独持久化任务、回执和产物索引

对批次、运行 ID、训练状态、场景验收和检查点，用业务服务保存，再让预设插件读取或更新。这样浏览器、训练 worker 和 Agent 可以基于 `run_id` 读取同一份业务事实。在 DSH 已有的宿主内，可用 `defineDomain()` 定义带 schema 的 KV 域。Web 的 base 已提供 `storageDomain` 和 JSON 后端。下面是一个可放到 Host plugin 行的最小服务，持有每个会话关联的当前运行。完整 job history 可由训练服务按 `run_id` 保存。其他模块声明 `inject: ['sessionRuns']` 后可用 `get(agent.session.id)`，也可把它接到 Remote 或动态上下文。 [Base 存储配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/base/cordis.patch.yml#L176-L190) · [类型化存储及落盘约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/storage/storage-domain/README.zh.md#L24-L74)

```ts
import { Service, type Context } from '@deepseek-ai/cordis'
import { defineDomain, domainTable, type Domain } from '@deepseek-ai/dsh-storage-domain'
import { z } from 'zod'

const runSchema = z.object({
  runId: z.string().min(1),
  datasetVersion: z.string().min(1),
})
type RunBinding = z.infer<typeof runSchema>

const runDomain = defineDomain({
  name: 'session_runs',
  version: 1,
  tables: { bindings: domainTable(runSchema) },
})

declare module '@deepseek-ai/cordis' {
  interface Context {
    sessionRuns: SessionRuns
  }
}

export default class SessionRuns extends Service {
  static inject = ['storageDomain']
  private domain!: Domain<typeof runDomain>

  constructor(ctx: Context) {
    super(ctx, 'sessionRuns')
  }

  protected async [Service.init](): Promise<void> {
    const domain = await this.ctx.storageDomain.open(runDomain)
    this.ctx.effect(() => () => domain.close(), 'session-runs.close')
    this.domain = domain
  }

  get(sessionId: string): RunBinding | undefined {
    return this.domain.table('bindings').get(sessionId)
  }

  async bind(sessionId: string, input: RunBinding): Promise<void> {
    await this.domain.table('bindings').put(sessionId, runSchema.parse(input))
  }
}
```

该服务由 Host 挂一次，数据库域以名称识别，同一域已经打开时会拒绝重复打开。有多个进程或服务共同写入时，使用拥有并发协议的业务后端。`SessionEventMap` 的 TypeScript 声明合并只处理类型，新增必读持久事件还要同步 DSH fork 的事件词表、reader、格式和迁移。外置预设插件可折叠内置事件，或把自己的持久状态写入独立领域。当前 `appendPluginRecord()` 保留给 DSH 自己的实验包。需要等待会话日志写盘时，用 `await ctx.sessions.flush(session)` 作为持久化屏障。 [外部插件持久化规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/practices.md#L17-L22) · [Session 写入与刷新](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/session/README.zh.md#L70-L91) · [持久格式准入](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/persistence.zh.md#L188-L197)

## Web 界面、业务 RPC 与会话状态

对同一个 Web profile，可以交付评测工作台和训练工作台、会话专属按钮和侧栏、工具卡片、实时状态与可回放记录。**预设负责选择会话的 Host 能力，Web Client 读会话的预设 ID 决定渲染。** Web 模块注册表扫描主 Loader 树的已启用行。预设子插件位于独立的内存树，`PresetTree` 构造时恢复主树 owner 原有的 `subtree` 与 `subgroup` 链接。想把一个组件送到浏览器，要在 Web profile 的主树启用它的双面包。 [预设树实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/mount.ts#L8-L23) · [Web 模块扫描](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/modules/src/index.ts#L1118-L1127)

### 声明可安装的页面插件

在自定义 bundle 根目录准备以下四个文件。最小例子为已经注册的 `training-data` 会话显示「训练详情」按钮并打开同会话的右侧标签。

```text
task-workbench/
├── package.json
├── cordis.patch.yml
├── index.js
└── client.js
```

`package.json` 的 `dsh.client.inject` 是浏览器模块图依赖，Client 插件导出的 `inject` 是它需要的 Cordis **服务名**。两处各自声明实际依赖。源码开发可照内置页面的 `tsdown.config.ts` 使用仓库内的 `clientBundle` 生成 `lib/client.js`。下面四文件采用官方模板的 lazy-CJS 格式，适合先验证挂载。 [浏览器包约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/client-modules.zh.md#L92-L100) · [官方最小 manifest](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/templates/decoration/package.json#L1-L21) · [内置页面构建配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-schedule/tsdown.config.ts)

```json
{
  "name": "@local/task-workbench",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./index.js",
    "./client": "./client.js"
  },
  "files": ["index.js", "client.js", "cordis.patch.yml"],
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": {
      "platform": "web",
      "inject": [
        "@deepseek-ai/dsh-client-ui-session",
        "@deepseek-ai/dsh-client-ui-conversation",
        "@deepseek-ai/dsh-client-ui-sidebar-right"
      ]
    }
  }
}
```

`cordis.patch.yml` 在 profile 主树以裸包名插入行。一个 bundle 可同时交付其他 Host 行以及 `@deepseek-ai/dsh-agent-preset` 声明。Client 入口随此根行启停。 [双面包挂载规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-settings-card.zh.md#L56-L68)

```yaml
- insert:
    - id: task-workbench-ui
      name: '@local/task-workbench'
```

`index.js` 的 Host 入口为页面包提供 Loader 生命周期。

```js
export function apply() {}
```

`client.js` 注册会话头按钮和右侧标签。React 从宿主模块表读取。会话槽自带 `useProjection`。当会话投影尚未装载时按钮暂不渲染。 [浏览器模板](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/templates/decoration/client.js) · [会话槽标准 props](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-session/src/client/index.ts#L140-L166) · [右侧标签 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-sidebar-right/README.zh.md#L83-L97)

```js
window.__ModuleLoader__.load({
  id: '@local/task-workbench',
  factory(require) {
    const { createElement: h } = require('react');
    const presetId = 'training-data';
    const tabKind = 'training-details';
    const tabId = '@local/task-workbench';

    function TrainingButton({ useProjection, open }) {
      const selected = useProjection('agentPreset');
      if (selected !== presetId) return null;
      return h('button', { type: 'button', onClick: open }, '训练详情');
    }

    function TrainingTab({ sessionId, useProjection }) {
      const selected = useProjection('agentPreset');
      if (selected !== presetId) return null;
      return h('section', null,
        h('h2', null, '训练详情'),
        h('p', null, '会话 ' + sessionId),
      );
    }

    return {
      inject: ['slots', 'sidebarRight', 'sidebarRightTabs'],
      apply(ctx) {
        ctx.effect(() => ctx.sidebarRightTabs.register({
          id: tabId,
          kind: tabKind,
          title: () => '训练详情',
        }));
        ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({
          name: 'sidebar.right.pane.tab',
          key: tabId,
        }, TrainingTab));
        ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
          name: 'conversation.session.header.actions',
          id: 'training-details-open',
          inject: sessionId => ({
            open: () => ctx.sidebarRight.openTabIn(sessionId, tabKind),
          }),
        }, TrainingButton));
      },
    };
  },
});
```

先创建或安装 DSH Web profile 并准备构建产物，再用相对路径安装本地 bundle。源码分支把下面的 `dsh` 换成 `pnpm dsh`，并从源码工作树执行。Web 插件管理页也可添加本地目录。示例文案直接写在 JS 中便于复制，上产品时用 `ctx.locale.register` 与 slot 的 `locale` 绑定本地化文案。 [安装组合包](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/develop/basic/publish.zh.md#L76-L114) · [UI 本地化与生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/ui-plugin.md#L9-L13)

```powershell
dsh plugin --profile web add ./task-workbench
dsh --profile web --dump-config
dsh web
```

### 前端入口对照与注册范式

| 位置 | 注册接口 | 适用场景 |
|---|---|---|
| 会话标题旁、右端工具区 | `conversation.session.header.actions` / `conversation.session.header.utilities` | 根据预设加「检查产物」「训练详情」「打开回执」。 [会话头槽](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-conversation/src/client/contract/slots.ts#L251-L263) |
| 输入框内的辅助控件 | `conversation.composer.dock` | 选择训练批次、添加数据集引用。会话槽提供会话 ID。 [输入框声明](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-conversation/src/client/apply.ts#L468-L482) |
| 会话正文视图 | `conversation.view` | 打开一次会话的训练状态、运行详情。视图注册表生成一份共享标签清单，组件正文可读预设投影。 [标签清单实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-conversation/src/client/apply.ts#L214-L233) |
| 会话右侧标签与资源预览 | `ctx.sidebarRightTabs.register`、`sidebar.right.pane.tab`、可选 `sidebar.right.pane.tab.title` | 作业详情、日志流、场景预览。按 `kind` 打开，正文和标题按定义 `id` 派发。 [标签注册契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-sidebar-right/src/client/tab-registry.ts#L94-L139) |
| 全局主工作台 | `sidebar.panellist` + `main` | 用同一 ID 注册左侧入口和主页面，显示任务列表并选预设创建会话。 [自动化管理页示例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-schedule/src/client/index.ts#L216-L246) |
| 对话中的工具展示 | `tool.call.toolview` | 按真实 wire 工具名渲染采集回执和质检卡。 [工具卡契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-tool/src/client/contract/slots.ts#L16-L31) |
| 独立业务事件卡 | `ctx.uiConversation.events.register` + `conversation.chat.node` | 把标准会话事件中的业务回执渲染成可回放卡片。 [事件节点编写示例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/conversation.zh.md#L76-L257) |
| 产品设置、插件详情 | `settings.section`、`settings.general.item`、`settings.plugins.tab`、`plugins.detail.actions/badge/section` | 提供默认参数、摘要或连接配置入口。 [设置槽契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-settings/src/client/contract/slots.ts#L27-L87) · [插件详情扩展](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-settings-card.zh.md#L44-L55) |
| 输入命令、引用、快捷键 | `ctx.commandUi`、`ctx.inputTriggers`、`ctx.shortcuts` | 加界面动作、slash 参数选择、`@` 数据集引用或快捷入口。 [命令 UI](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-commands/src/client/contract.ts#L74-L144) · [触发源契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-input-trigger/src/types.ts#L149-L214) · [终端快捷键示例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-sidebar-terminal/src/client/index.ts#L55-L69) |
| 全局浮层、替换与包裹 | `shell.overlay`，以及 owner 声明的 `chain`、`hoc`、`single` | 全局 toast、由选择器命中的替换、已有内容的包裹。使用 owner 声明的槽与 type。 [浮层定义](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-layout/src/client/index.ts#L97-L107) · [槽类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-slots/README.zh.md#L26-L48) |

以下为在 Client `apply(ctx)` 中使用的实现模板。TypeScript 插件从对应 owning package 的 `/client` 引入槽类型，并用 `PropsRuntime<'slot-name'>` 等推导 props。业务回调通过 `inject` 传给组件。表中的共享入口和服务由 profile 加载，`useProjection('agentPreset')` 读取 Host 已提交的会话预设。空白草稿中尚未提交的选择、会话列表摘要和运行中的会话投影有各自的生命周期。用户发起首轮后 Host 锁定该会话的预设。 [框架 props 契约](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-slots/README.zh.md#L36-L48) · [预设投影折叠](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/session.ts#L16-L43) · [锁定检查](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/index.ts#L355-L374)

**主工作台。** `sidebar.panellist` 的 `id` 必须等于 `main` 的 `key`。侧栏 owner 提供选中与导航，图标只渲染 glyph。下面的 `WorkspacePickerPage` 是业务组件，从工作区选择器获得 `WorkspaceId` 后调用注入的动作。Client 注入 `slots` 与 `uiWorkspace`。评测可用同一个工作台启动 `data-evaluation`。 [内置侧栏图标](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-schedule/src/client/TaskManagerIcon.tsx#L1-L17) · [会话创建选项](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-workspace/src/client/navigation.ts#L28-L91)

```tsx
const panelId = 'task-workbench'

ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
  name: 'sidebar.panellist',
  id: panelId,
  order: 15,
  label: () => '评测与训练工作台',
}, WorkbenchIcon))

ctx.slots.inject('main', () => ctx.slots.register({
  name: 'main',
  key: panelId,
  inject: () => ({
    startTraining: (workspaceId: WorkspaceId) =>
      ctx.uiWorkspace.startSession(workspaceId, { agentPreset: 'training-data' }),
    startEvaluation: (workspaceId: WorkspaceId) =>
      ctx.uiWorkspace.startSession(workspaceId, { agentPreset: 'data-evaluation' }),
  }),
}, WorkspacePickerPage))
```

**会话视图。** 读取会话投影并路由正文。需要只有指定预设才出现的入口时，使用会话头按钮和右侧标签。需要由会话日志高效维护自定义视图快照时，另用 `ctx.uiConversation.views.register({ target, create })` 注册 builder，每个会话由 `create` 获得一份 `empty`、`replace({nodes,timeline})`、`apply({upserts,timeline})` 实例。内置 Trajectory 同时实现 view slot 和 target builder。 [view slot 示例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-trajectory/src/client/index.ts#L75-L101) · [builder 接口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-conversation/src/client/contract/conversation.ts#L285-L333)

```tsx
function WorkbenchView({ useProjection }: PropsRuntime<'conversation.view'>) {
  const preset = useProjection('agentPreset')
  if (preset === 'training-data') return <TrainingView />
  if (preset === 'data-evaluation') return <EvaluationView />
  return <p>当前会话暂无评测或训练任务。</p>
}

ctx.slots.inject('conversation.view', () => ctx.slots.register({
  name: 'conversation.view',
  id: 'task-workbench',
  order: 20,
  label: () => '工作台',
}, WorkbenchView))
```

**工具回执卡。** 在 Host Tool 的 `output` 中通过 `presentationMeta(_args, value)` 产出可持久化的 JSON 元数据。示例 Tool 的结果有 `count` 字段时，设 `presentationMeta: (_args, value) => ({ artifactCount: value.count })`。Client 逐项识别 `preparing`、`start`、`result`，旧记录可能缺元数据，失败仍显示真实输出。卡和工具按 wire name 对应，Native 与 PTC 内部工具使用同一 keyed 机制。 [持久展示元数据](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/schema.ts#L484-L503) · [工具展示生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-tool/README.zh.md#L38-L53)

```tsx
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client'

function ArtifactCard(props: ToolCallViewProps) {
  if (props.phase !== 'result') return <p>正在清点产物</p>

  const { block } = props
  const meta = block.meta
  if (!block.isError && meta && typeof meta === 'object'
    && 'artifactCount' in meta && typeof meta.artifactCount === 'number') {
    return <p>已清点 {meta.artifactCount} 项产物</p>
  }

  const text = block.content.flatMap(item => item.type === 'text' ? [item.text] : []).join('\n')
  return <pre>{text || block.error?.reason || '暂无可显示的输出'}</pre>
}

ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({
  name: 'tool.call.toolview',
  key: 'count_artifacts',
}, ArtifactCard))
```

**可回放业务卡。** 在标准 `tool/result` 的 `meta` 携带业务回执。例如 Host 的启动训练 Tool 在结果校验成功后声明 `presentationMeta: (_args, value) => ({ kind: 'training-receipt', runId: value.runId })`。Client 给一条实际结束的调用渲染旁路回执卡，`match` 只检查单条事件，稳定的 `callId` 是卡片身份。`buildViewNode` 返回稳定 key 和持久排序坐标。需要多个阶段时，可扩展 matcher 按稳定业务 ID 配对多条已支持的标准事件。Tool card 与独立节点两处同时渲染时应分别承载业务需要的内容。 [标准工具事件](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/session/src/types.ts#L363-L395) · [事件节点生命周期](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/conversation.zh.md#L252-L268)

```tsx
import type { ConversationNodeDefinition } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { ChatNodeViewProps } from '@deepseek-ai/dsh-client-ui-chat/client'

interface TrainingCardData {
  readonly runId: string
}

declare module '@deepseek-ai/dsh-client-ui-chat/client' {
  interface ChatNodeDataMap {
    'training-run': TrainingCardData
  }
}

function trainingReceipt(meta: unknown): TrainingCardData | null {
  if (meta === null || typeof meta !== 'object'
    || !('kind' in meta) || meta.kind !== 'training-receipt'
    || !('runId' in meta) || typeof meta.runId !== 'string') return null
  return { runId: meta.runId }
}

const definition: ConversationNodeDefinition<TrainingCardData> = {
  kind: 'training-run',
  target: 'chat',
  match: event => {
    if (event.type !== 'tool/result' || event.data.message.isError
      || !trainingReceipt(event.data.meta)) return null
    return { id: String(event.data.message.source.callId), role: 'start' }
  },
  start: (_context, match) => {
    const receipt = match.event.type === 'tool/result'
      ? trainingReceipt(match.event.data.meta)
      : null
    if (!receipt) throw new Error('training-run requires a training receipt')
    return receipt
  },
  update: context => context.state,
  buildViewNode: context => {
    if (!context.state || !context.start) return null
    return {
      key: context.key,
      kind: 'training-run',
      id: context.id,
      target: 'chat',
      anchorSeq: context.start.event.seq,
      location: context.start.location,
      visibility: 'visible',
      data: context.state,
    }
  },
}

function TrainingCard({ node }: ChatNodeViewProps<'training-run'>) {
  return <p>训练作业 {node.data.runId} 已提交</p>
}

ctx.uiConversation.events.register(definition)
ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
  name: 'conversation.chat.node',
  key: 'training-run',
}, TrainingCard))
```

普通插件的会话记录使用 DSH 已注册的持久事件。仅通过 TypeScript 合并 `SessionEventMap` 会留下旧版与已发布构建无法回读的新事件。自行维护 DSH 的 fork 如需新事件，要连同生成的事件目录、持久化 schema、兼容迁移与恢复测试一起维护。`appendPluginRecord()` 保留给 DSH 仓库中的实验包。 [插件事件兼容约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/practices.md#L15-L22) · [实验记录边界](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/session/README.zh.md#L72-L80)

**设置与编辑控件。** 在 `settings.section` 由业务拥有页面，在 `settings.general.item` 追加一行。需要即时保存时，Host Config 建模为 `Volatile<T>`，例如 `endpoint: z.string().volatile()`。下一次操作开始时用 `.get()` 读取实际值。可编辑配置走 Config Editor，表单由 schema 和 revision 管理。密钥字段用 credential 引用或 `role('secret')`。 [配置表单与持久化](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-settings-card.zh.md#L7-L44) · [真实设置页注册](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-settings-models/src/client/index.ts#L132-L145)

```tsx
ctx.slots.inject('settings.section', () => ctx.slots.register({
  name: 'settings.section',
  id: 'task-workbench',
  order: 30,
  label: () => '工作台设置',
  inject: () => ({ loadSettings, saveSettings }),
}, WorkbenchSettings))
```

**用户命令和输入引用。** 用 Host 的 `ctx.commands.register` 注册真正执行的预设命令。Client 用 `ctx.commandUi.decorate` 为已存在的 Host 命令加选择弹窗，或用 `ctx.commandUi.register` 注册只在浏览器运行的命令。Client 表面的 `available` 接收会话身份，再用 `ctx.sessions.binding(sessionId)` 取已装载投影。引用来源用 `ctx.inputTriggers.registerSource`，遵循候选加载的 AbortSignal，`onPick` 返回插入文字或结构化引用。 [Host 命令注册](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/interaction/commands/README.zh.md#L30-L56) · [Client 命令贡献和装饰](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-commands/src/client/contract.ts#L85-L144) · [触发源接口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-input-trigger/src/client/contract.ts#L11-L25)

```ts
import type { ClientSessionContext } from '@deepseek-ai/dsh-client-ui-input-trigger/client'

const trainingAvailable = ({ sessionId }: ClientSessionContext) =>
  ctx.sessions.binding(sessionId)?.session.projections.faceOf('agentPreset').getSnapshot()
    === 'training-data'

ctx.effect(() => ctx.commandUi.register({
  name: 'training-panel',
  label: () => '训练面板',
  available: trainingAvailable,
  ui: {
    kind: 'action',
    run: ({ sessionId }) => ctx.sidebarRight.openTabIn(sessionId, 'training-details'),
  },
}))

ctx.effect(() => ctx.inputTriggers.registerSource({
  trigger: '@',
  name: '训练数据集',
  async candidates(session, { query, signal }) {
    if (!trainingAvailable(session)) return []
    const matches = await listDatasets({ query, signal })
    return matches.map(item => ({ name: item.id, label: item.title }))
  },
  onPick: ({ candidate }) => ({ text: candidate.name }),
}))
```

这些代码依赖相应的 Web 组件已由 profile 装配。加新槽时，owner 先声明 slot 的 kind 与 scope，外部插件在对应命名空间贡献。需要按条件替换的 owner 可声明 `chain`，注册项用 `select` 返回匹配数据或 `null`。需要多层包裹时用 `hoc` 并透传 `children`。`single` 和 `keyed` 避免重复注册。快捷键注册遵照 `ctx.shortcuts.register({ id, label, regions, modals, resolve, defaults })` 的权限与焦点判定，`resolve` 在会话不存在时返回 `blocked`。 [槽注册纪律与 chain](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-slots/README.zh.md#L46-L70) · [真实快捷键注册](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-sidebar-terminal/src/client/index.ts#L55-L69)

### UI 状态、RPC 与资源预览

| 状态归属 | 编写方式 |
|---|---|
| 当前用户展开了哪个标签、表单草稿 | Client 本地状态或 slot store。跨标签/跨会话时以业务 ID 或会话 ID 隔离。 |
| Session 日志已有的工具调用、回执和进度摘要 | `ctx.sessionProjections` 从标准事件派生投影，Client 用 `useProjection` 读取。 |
| 跨会话的运行号、队列、产物版本、指标历史 | 由 Host 业务服务或数据库持久化。工作台通过 Gateway Remote 查询，以明确的业务身份定位数据。 |
| 大文件、相机图、生成日志或高频指标 | Host 持有资源，Client 以受控 URL、资源 provider 或流式 Remote 读取。队列、运行号和可回放摘要保留在业务记录里。 |

**会话投影。** 把类型放在 Client-safe 的类型导出中。举例定义 `artifactCallCount`，从标准 `tool/call` 统计当前会话里模型请求清点产物的次数。它统计调用请求，成功次数要根据结算事件和工具身份另行计算。状态结构或回放语义变化时更新 `stateVersion`。Host 用 retained handle 同步读取，Client 用 `useProjection('artifactCallCount')`。 [投影定义和注册](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/session-projection/README.zh.md#L33-L73) · [标准工具事件](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/session/src/types.ts#L363-L395)

```ts
// shared/projection-types.ts，Host 和 Client 均以类型方式导入
declare module '@deepseek-ai/dsh-session-projection/types' {
  interface SessionProjectionMap {
    artifactCallCount: number
  }
}
export {}
```

```ts
// Host 领域包
import { z } from 'zod'
import type { Context } from '@deepseek-ai/cordis'
import type { ProjectionDefinition } from '@deepseek-ai/dsh-session-projection'
import type {} from './shared/projection-types.js'

export const inject = ['sessionProjections']
const countSchema = z.number().int().nonnegative()

const artifactCalls = {
  key: 'artifactCallCount',
  stateVersion: 1,
  stateSchema: countSchema,
  init: () => 0,
  apply: (count, event) => event.type === 'tool/call' && event.data.name === 'count_artifacts'
    ? count + 1
    : count,
  wire: { viewSchema: countSchema, view: value => value },
} satisfies ProjectionDefinition<'artifactCallCount', number>

export async function apply(ctx: Context): Promise<void> {
  await ctx.sessionProjections.register(artifactCalls)
}
```

投影的 fold 保持同步，忽略无关事件时返回原引用。需要从 Host 读取时，保存注册返回的 handle，用 `handle.stateOf(session)`。注册表是 Host 共享实例，注册应由领域包拥有。需要避免状态进入每条会话摘要时，在共享类型使用 `SessionProjectionSummaryExcluded<T>`，同时声明 `wire.summary: false`。 [投影摘要语义](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/session-projection/README.zh.md#L96-L107)

**业务状态和类型化 RPC。** 把运行记录存进业务服务。下面的 Host 根服务用 DSH 的 `storageDomain` 保存每个会话最新一次训练状态，适合把数据留在同一 DSH 实例。要支持一条会话多次运行时，表按 `runId` 建键并保存 `sessionId`、`workspaceId` 等归属。生产 Agent 的预设插件可依赖这个 Host 服务。对 Client 开放的方法用 `@Remote`，内置的 `Agent` lookup 令 wire 参数为 `agentId`，Gateway 在 Host 解析后再交给方法。另有 `@RemoteScope('agent', 'method')`，它先解析会话作用域，再在对应 Context 查找服务。预设内通过 Cordis `isolate` 注册的私有服务，需要由同 realm 消费方处理，或由 Host 通过 `agentPresets.serviceFor` 明确访问。 [领域存储 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/storage/storage-domain/README.zh.md#L26-L69) · [Remote 编程模型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/api-gateway.zh.md#L9-L65) · [预设私有服务的访问规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/README.zh.md#L54-L60)

```ts
import { Service, type Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import { defineDomain, domainTable, type Domain } from '@deepseek-ai/dsh-storage-domain'
import { Remote, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'
import { z } from 'zod'

export interface TrainingState {
  readonly runId: string
  readonly phase: 'queued' | 'running' | 'completed' | 'failed'
  readonly completed: number
}

const runSchema = z.object({
  runId: z.string(),
  phase: z.enum(['queued', 'running', 'completed', 'failed']),
  completed: z.number().int().nonnegative(),
})

const runsSpec = defineDomain({
  name: 'training_status',
  version: 1,
  tables: { runs: domainTable(runSchema) },
})

export default class TrainingStatus extends TypertRemoteService {
  static inject = ['storageDomain']

  private domain!: Domain<typeof runsSpec>

  constructor(ctx: Context) {
    super(ctx, 'trainingStatus')
  }

  protected async [Service.init](): Promise<void> {
    const domain = await this.ctx.storageDomain.open(runsSpec)
    this.ctx.effect(() => () => domain.close(), 'training-status.close')
    this.domain = domain
  }

  async record(sessionId: SessionId, state: TrainingState): Promise<void> {
    await this.domain.table('runs').put(sessionId, state)
  }

  @Remote('status')
  status(agent: Agent, signal: AbortSignal): TrainingState | null {
    signal.throwIfAborted()
    return this.domain.table('runs').get(agent.session.id) ?? null
  }
}
```

发布时把领域包纳入 Host TypeScript project references，按照生成器要求导出 `./typert` 与 `./remote`，并把产物纳入 `files`。标准仓库由 `pnpm run build` 触发生成及两侧构建。把该包生成的 `/remote` contribution 加入 Client 组合的 `api-remotes` 挂载表。业务 Client 声明 `inject: ['remote', 'remote.trainingStatus']`，调用 `ctx.remote.trainingStatus.status(sessionId, signal)`。UI 按预设控制入口可见性，读写权限由 Host Gateway 和领域服务校验。 [构建与 Remote 导出](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/api-gateway.zh.md#L102-L122) · [内置 Client 贡献挂载](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/remotes/src/client/index.ts#L190-L219) · [Gateway 访问检查](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/api-gateway.zh.md#L126-L138)

**流式 RPC 与文件路由。** 训练日志尾随可以用 `@Remote({ name: 'follow', mode: 'stream' })`，Host 方法返回 `AsyncIterable<TrainingFrame>` 并响应最后一个 `AbortSignal`，Client 用生成的 handle 迭代、取消和释放。普通 JSON 查询走 unary Remote。需要字节响应时，Host 可以注册精确 Fetch 路由 `ctx.connection.fetch.register`，或在 Web 宿主注册 `ctx.webServer.register` 的 `GET/HEAD` resource。下面用固定信息演示 resource 签名。真实产物接口还要把经过验证的运行身份、文件身份和读取者权限传给业务服务。 [流式 Remote 约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/api-gateway.zh.md#L58-L65) · [Connection 字节路由](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/file-upload/src/index.ts#L73-L87) · [Web resource 路由](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/host/webserver/README.zh.md#L59-L71)

```ts
export const inject = ['webServer']

export function apply(ctx: Context): void {
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: '/task-workbench/version',
    auth: 'required',
    resource: async () => Response.json({ apiVersion: 1 }),
  }))
}
```

**资源 viewer。** 需要由面板、引用和预览共同读取时，用 `dsh-resource://<type>/…` 表示资源。在 Client 注册协议提供方，`open(address, {signal})` 产出初值和更新帧，订阅结束即取消。资源权限由实际 Host 读取接口处理。资源标签定义设置 `patterns` 认领地址，正文接收 `useTabInfo()`，通过 `useResource<'training-artifact'>(tab.navigation.address)` 订阅。代码里的 `readArtifact` 是接上节 Gateway 的读取函数，返回该 API 的 `RemoteResult<ArtifactView>`。 [资源插件 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/resources/README.zh.md#L27-L69) · [标签资源匹配与打开](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-sidebar-right/README.zh.md#L83-L97)

```tsx
declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface ResourceProtocolMap {
    'training-artifact': ArtifactView
  }
}

ctx.effect(() => ctx.resources.register<'training-artifact'>({
  protocol: 'training-artifact',
  async *open(address, { signal }) {
    yield await readArtifact(address, signal)
  },
}))

ctx.effect(() => ctx.sidebarRightTabs.register({
  id: 'training-artifact-preview',
  kind: 'training-artifact',
  patterns: ['dsh-resource://training-artifact/**'],
  title: () => '训练产物',
}))

function ArtifactPreview({
  useTabInfo, useResource,
}: PropsRuntime<'sidebar.right.pane.tab'>) {
  const { tab } = useTabInfo()
  const resource = useResource<'training-artifact'>(tab.navigation.address)
  if (resource.status === 'failed') return <p>读取产物失败</p>
  if (resource.status !== 'live') return <p>等待产物数据</p>
  return <pre>{JSON.stringify(resource.value, null, 2)}</pre>
}

ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({
  name: 'sidebar.right.pane.tab',
  key: 'training-artifact-preview',
}, ArtifactPreview))
// 业务组件调用 ctx.sidebarRight.openResource(authorizedAddress)
```

### 在两个预设上做界面验收

- 用内置标准模式和 `training-data` 各开启一条会话，检查只有训练会话显示入口，刷新和切换会话后仍按所选会话显示。预设在空白会话中的切换与首轮后的锁定分别验证。
- 工作台从用户选定的 workspace 打开目标预设。右栏打开后，确认 tab 的 `sessionId`、业务的 `runId` 和后端查询使用同一条记录。
- 工具卡覆盖准备、执行、完成、失败及缺少 metadata 的旧记录。会话业务卡测试关闭、刷新、分页回填后仍能展示正确状态。
- 使用不同连接身份验证查询和动作的后端授权。流式页面关闭时取消订阅。重载或卸载 UI bundle 后检查 slot、resource provider 与远程调用监听的 disposer。

## Host 入口与共享基础设施

同一个 bundle 可以同时插入 Host 插件和 Agent 预设声明。把需要被多个预设、Gateway、前端或外部调用者共享的能力注册在 Host 树中。以下写法使用 Host 已挂载的服务。若部署自行搭建精简 profile，先补齐这些服务，再启用相应的消费插件。 [组合归属规则](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/compositions.md#L71) · [构建 profile 的分层机制](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/architecture.zh.md#L15)

| 基础设施 | 实现入口和写法 |
|---|---|
| LLM 接入和部署默认模型 | 用 Host 插件调用 `ctx.llm.registerAdapter(['route-id'], adapter)`。配置 `dsh-agent-default-model` 的 `provider`、`model` 和可选 `reasoningEffort`。会话用 `agent.model.select(selection)` 或 `session.selectModel`，在请求准备前设置。 [适配器指南](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-an-llm-adapter.zh.md) · [默认模型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent-default-model/README.zh.md#L28) |
| Agent 创建、轮次循环与会话存储 | 使用 Host 的 `ctx.agents.create()` / `resume()` 或 Session Controller。定制存储实现 `SessionPersistence` 的 `create/open/stat/list/export` 等约定。 [Agent 创建与恢复](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/subsystems/core.zh.md#L45) · [存储约定](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/session-persistence/README.zh.md) |
| 沙箱、文件和审批 | Host 装配 `ctx.sandbox`、`ctx.fs`、审批及权限服务。文件操作有 `fs/write-intent`、`fs/edit-intent`、`fs/delete-intent`、`fs/observed`。其作用范围看提供方和事件分派。预设级业务门禁可以用 `ctx.tools.guard()`。 [文件策略事件](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/fs/fs/README.zh.md#L67) · [权限服务](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/interaction/permission-presets/README.zh.md#L62) |
| Shell、PTC 和委派提供方 | Host 装配实际的执行及沙箱提供方，预设消费它们。独立的持久终端或工作流引擎可用 `isolate` 分组。自行实现 Shell 时参考 `ShellExecutor`，持久终端后端用 `ctx.terminals.registerBackend()`。 [Shell seam](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/shell/shell/README.zh.md) · [终端后台注册](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/terminal/terminal/src/index.ts#L100) |
| 会话标题 | 调 `ctx.sessionTitle.rename()` 可显式更新业务会话的标题。自动标题插件在 Host 注册 `ctx.sessionTitle.register(provider)`，同一时间一个提供方。 [标题接口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/session-title/README.zh.md#L27) |
| 对外协议和 Web 模块 | Gateway 负责 Remote 调用和鉴权。Web Server 负责页面和传输，Web Client 加载浏览器模块。SDK 和 ACP 使用自己的 stdio 协议入口。 [启动与 profile](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/architecture.zh.md#L44) · [Gateway](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/api-gateway.zh.md) |
| 插件管理、诊断、热重载 | profile 挂载插件管理器和 HMR，工具入口按预设暴露。验证时检查有效的配置和运行中的插件状态。 [插件管理器](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/boot/plugin-manager/README.zh.md) · [热重载](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/boot/hmr/README.zh.md#L24) |

### 让业务入口指定预设

Web 组件通过 `ctx.uiWorkspace.startSession(workspaceId, { agentPreset: 'training-data' })` 创建或进入匹配的空会话。服务端 API 的创建请求可显式传 `workspaceId` 或 `cwd`，以及 `agentPreset`。创建后使用返回的 `sessionId` 关联任务。`session.selectModel` 记录会话选择，同时会在后台保存为 profile 默认值。如果业务需要为一次生产或训练运行固定模型且避免修改部署默认值，使用可信入口的 `agentOptions` 或 `agent.model.select()`，并提前核验选定的模型路由。 [会话创建输入](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/session-controller/src/types.ts#L268) · [模型选择及保存行为](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/session-controller/src/commands.ts#L160)

如果你自己实现 Agent 创建入口，Registry 可以在发布前的 `setup` 中把 Agent 绑定到预设。以下片段展示**新建**顺序，其中 `sessionId` 是已分配的 `SessionId`。需要工作区归档、权限默认值、恢复和并发创建控制时，沿用正常 Session Controller。记录初始模型、预设和权限由各自的公开接口完成。 [Web Agent 创建实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/api/session-controller/src/agent.ts#L437) · [注册表 mount 实现](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/src/index.ts#L290)

```ts
const presetId = 'training-data'

await ctx.agents.create({
  sessionId,
  meta: { cwd: workspacePath, agentPreset: presetId },
  agentOptions: { provider, model },
  setup: async (agentCtx) => {
    await ctx.agentPresets.mount(agentCtx, presetId)
  },
})
```

随附 SDK 的 `createSession()` 直接用 Host 工具组合创建 Agent，headless 入口也有独立创建/恢复逻辑，并明确拦截带预设的会话恢复。用 Python 或 CLI 跑训练任务时，有两条可执行路径：调用已装配 Web Host 的会话 API，并把 job id 和 `sessionId` 记录到训练系统。或者在专用 profile 直接装配共享工具能力，自行扩展 SDK/runner 的创建和恢复路径后再支持命名预设。单加一行 Registry 或一份 Web overlay 无法接通 SDK 的 `setup`。 [SDK 创建路径](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/sdk/server/src/server.ts#L562) · [headless 恢复限制](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/headless/src/index.ts#L200)

### 定时和外部事件启动指定预设

通过 Host 的 `ctx.schedule.create()` 可保存定时投递。示例中的 `kind: 'new'` 每次新建会话，`create.agentPreset` 指定预设，`create.cwd` 指定工作空间对应的目录。改为 `new_once` 可让后续投递复用首次创建的会话。预设可通过 `dsh-tool-schedule` 提供模型入口。 [定时任务 API](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/schedule/schedule/README.zh.md#L44) · [调用类型](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/schedule/schedule/src/types.ts#L344)

```ts
await ctx.schedule.create({
  title: '训练产物巡检',
  prompt: '检查新生成的训练数据批次，并记录质检回执。',
  timing: {
    kind: 'cron',
    cron: { expression: '0 2 * * *', time_zone: 'Asia/Shanghai' },
  },
  target: {
    kind: 'new',
    create: { cwd: '/absolute/path/to/project', agentPreset: 'training-data' },
  },
})
```

Webhook 路径需要 Host 装配可信事件适配器和 `webhookRuntime`。规则通过 `ctx.webhookRuntime.register(rule)` 注册，`run(delivery, signal)` 返回 `null` 或包含 `workspacePath`、`title`、`prompt`、`agentPreset`、`permissionPreset` 的请求。当前实现每次投递执行规则，任务系统如果要求幂等，以经过校验的 delivery id 或业务幂等键记录已接受的投递。GitHub 评审示例展示了完整注册与部署。 [Webhook 规则与请求](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/experimental/webhook/README.zh.md#L24) · [完整配置和规则示例](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/guide/github-review.zh.md)

## 评测与训练预设的组合示例

在一个 bundle 内提供 `data-evaluation` 和 `training-data` 两个声明。每个声明拥有自己的 Persona、Skill 来源、命令及业务工具。两个预设都能消费 Host 的任务服务、制品存储和同一套 Web Client：

| 组件 | 评测预设 | 训练预设 |
|---|---|---|
| 运行指令 | 评测协议、评分与报告证据 | 训练数据协议、版本记录、生产和失败分类 |
| 作用域工具 | 场景、标注、题目、运行评测、查询和导出报告 | 数据生产、校验、训练提交和状态查询 |
| 每轮上下文 | 评测 run、数据版本、组合和评分协议 | 批次 ID、切分、采集配置、训练模型和前一轮回执 |
| 业务校验 | 服务端校验评测配置和数据集版本，保存基准结果 | 服务端按可信记录查分区与校验结果，用幂等键提交训练任务 |
| Web 工作台 | 启动 `data-evaluation` 会话，显示评测阶段和报告 | 启动 `training-data` 会话，显示数据批次、训练作业和回归指标 |

仿真器 gRPC 连接可归共享 Host 业务服务，由预设的各个 Tool 调用。给 Tool 返回小型结构化回执，按业务 run ID 读取图像、日志和模型产物。Agent 的会话日志与训练服务的任务状态分别持久化，用 `sessionId`、`runId`、数据版本和模型版本关联。数据生产、训练和回归评测可以据此重放。 [Tool 运行规范](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/cookbook/adding-a-tool.zh.md) · [会话事件与运行时状态](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/architecture.zh.md#L69)

### 从同一份配置启动评测和训练

下面是一份本地 overlay。它复用本手册的 `count_artifacts` 工具模块与 Skill 文件，并用不同的扫描根为两种任务提供工作流程。把示例里的 `C:/path/to/deepseek-harness/` 改成实际 DSH 源码根目录。两个 Skill 根分别创建自己的 `<skill-name>/SKILL.md`。完整的 Web 工作台包沿用「Web 界面、业务 RPC 与会话状态」中的 manifest，和这两个预设声明可以装在同一份 bundle 的 patch 里。

```yaml
- insert:
    - id: preset-data-evaluation
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: data-evaluation
        name: 数据评测
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config:
              prefix: 你负责数据评测。汇报引用评测协议、数据分区和结果回执。
          - id: artifact-tools
            name: 'file:///C:/path/to/deepseek-harness/examples/training-preset/artifact-tools.ts'
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config:
              includeDefaultRoots: false
              customSkillDirs:
                - 'C:/path/to/deepseek-harness/examples/training-preset/skills/eval'
          - id: tool-skill
            name: '@deepseek-ai/dsh-tool-skill'

    - id: preset-training-data
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: training-data
        name: 训练数据生产
        plugins:
          - id: persona
            name: '@deepseek-ai/dsh-persona'
            config:
              prefix: 你负责训练数据生产。汇报引用数据版本、验证结果和产物 ID。
          - id: artifact-tools
            name: 'file:///C:/path/to/deepseek-harness/examples/training-preset/artifact-tools.ts'
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config:
              includeDefaultRoots: false
              customSkillDirs:
                - 'C:/path/to/deepseek-harness/examples/training-preset/skills/train'
          - id: tool-skill
            name: '@deepseek-ai/dsh-tool-skill'
```

将「Tool 编写、可见性与执行策略」首个 TypeScript 例子保存为 `artifact-tools.ts`。训练目录的 Skill 中可写一条明确指令：从输入提取清单并调用 `count_artifacts({ items })`，按工具返回的 `count` 汇报。新建训练会话后，用该 Skill 检查 RGB、深度和分割掩码三项。验收工具结果 `{"count":3}`，并检查评测会话的 Skill 列表没有扫描训练目录。实际评测和训练操作替换为各自的业务工具行。 [声明参考](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/README.zh.md#L25) · [Skill 发现和作用域](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/skill/skill-filesystem/README.zh.md#L34)

## 验收步骤

1. **检查声明。** `--dump-config` 中有预设声明，`config.id` 唯一，使用的行都有正确的包名和配置。Web 预设列表能显示名字。用故意缺失依赖的副本确认诊断能定位到失败行。
2. **检查作用域。** 新建标准、评测、训练会话，各发一条消息。检查可见工具、Skill、命令和系统提示词是否符合期望。将同一预设开两个会话，检查它们的业务状态互不串用。
3. **检查调用和取消。** 验证成功、错误参数、业务拒绝、服务失败以及运行中取消的结果。PTC 组合还要检查 `run_code` 内的调用经过同样的门禁。
4. **检查生命周期。** 切换空会话的预设，再开始首轮。修改定义后用新会话验证。在测试环境重启并恢复旧会话，观察当前定义和历史业务记录是否符合预期。
5. **检查界面。** 按不同预设打开会话，确认专属按钮与面板、切换会话、刷新和会话恢复。直接调用业务 API 时也必须按会话和工作区校验资源访问。
6. **检查并行和重试。** 提交同一个训练业务请求两次。再次尝试在 UI 和 Agent 分别提交时，训练服务应依据业务键去重。取消、恢复、批次失败需能从记录中读出归属和结果。

[预设注册表测试](https://github.com/deepseek-ai/deepseek-harness/tree/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset-registry/tests) · [Web 预设选择测试](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/apps/web/tests/agent-preset-selection.e2e.ts) · [工具链测试](https://github.com/deepseek-ai/deepseek-harness/tree/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/tests)

## 按包和接口查证

- [四个内置预设的原始配置](https://github.com/deepseek-ai/deepseek-harness/tree/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets)提供能照抄的插件装配、分组和依赖关系。
- [全量插件包目录](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/preset/agent-preset/skills/dsh-doc/references/packages.md)列出仓库内 Cordis 插件、版本内路径、是否接收 Config 与职责。将目录中的包放进预设前，根据它的依赖和注册范围核对能否由预设挂载。
- [配置字段目录](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/config-catalog.zh.md)是具体插件的字段、默认值与范围的查找入口。[模型工具目录](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/tool-catalog.zh.md)涵盖工具名、参数 schema、依赖和副作用。
- 筛选现成插件时，先读它的 `README.zh.md`，再看入口的 `Config`、`inject`、实际 `apply` 注册点或类服务名。对于 `experimental` 下的实现，按选用版本的声明和测试验证其 API、加载范围、事件写入和客户端配套。通用 Codex/Claude Code hooks 桥接器也位于该分组，进程级 `configPath` 在加载时读取。 [Codex hooks 配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/experimental/hooks-codex/src/index.ts#L48) · [Claude Code hooks 配置](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/experimental/hooks-claude-code/src/index.ts#L47)

## 四套内置预设的全部装配行

表里是固定提交中四份 YAML 的全部子条目，遍历了各显式 group。共 **35 个不同的模块名或 Loader 内建名**。单元格是声明里的行 ID。配置字段列只列 YAML 实际覆盖过的字段，字段类型与默认值见配置目录。打开对应源文件可以直接取得含平台条件、隔离结构和完整配置的可复制 YAML。 [standard](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/standard.patch.yml) · [ptc](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/ptc.patch.yml) · [minimal](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/minimal.patch.yml) · [cordis](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/bundle/web-app/presets/cordis.patch.yml)

| 插件名，省略 `@deepseek-ai/` 包前缀 | standard | ptc | minimal | cordis | 预设中实际覆盖的配置字段 |
|---|---|---|---|---|---|
| `dsh-agent-instructions` | `agent-instructions` | `agent-instructions` | — | `agent-instructions` | `maxBytes` |
| `dsh-command-compact` | `command-compact` | `command-compact` | `command-compact` | `command-compact` | — |
| `dsh-command-goal` | `command-goal` | `command-goal` | — | `command-goal` | — |
| `dsh-compaction-basic` | `compaction-basic` | `compaction-basic` | `compaction-basic` | `compaction-basic` | — |
| `dsh-compaction-tool-result-pruner` | `tool-result-pruner` | `tool-result-pruner` | — | `tool-result-pruner` | `thresholdChars`、`headChars`、`tailChars` |
| `dsh-persona` | `persona` | `persona` | `persona` | `persona` | `prefix`、`complete`、`includeRuntimeContext` |
| `dsh-plan-mode` | `plan-mode` | `plan-mode` | — | `plan-mode` | `section` |
| `dsh-plugin-manager/tools` | `tool-plugin-manager`（有条件） | `tool-plugin-manager`（禁用） | — | `tool-plugin-manager`（有条件） | — |
| `dsh-plugin-market/tools` | `tool-plugin-market`（禁用） | `tool-plugin-market`（禁用） | — | `tool-plugin-market`（有条件） | — |
| `dsh-skill-filesystem` | `skill-filesystem` | `skill-filesystem` | — | `skill-filesystem` | `customSkillDirs` |
| `dsh-terminal` | — | — | `pty` | — | — |
| `dsh-terminal-bash` | — | — | `terminal-bash`（有条件）、`terminal-pwsh`（有条件） | — | `timeoutMs`、`shellDialect` |
| `dsh-time-context` | `time-context` | `time-context` | — | `time-context` | — |
| `dsh-tool-ask-user` | `tool-ask-user` | `tool-ask-user` | — | `tool-ask-user` | — |
| `dsh-tool-bash` | `tool-bash`（有条件） | `tool-bash`（有条件） | — | `tool-bash`（有条件） | — |
| `dsh-tool-bash-persistent` | — | — | `persistent-bash`（有条件） | — | `timeoutMs`、`description` |
| `dsh-tool-cordis` | — | — | — | `tool-cordis` | — |
| `dsh-tool-executor-ptc` | — | `tool-executor-ptc` | — | — | — |
| `dsh-tool-fs` | `tool-fs` | `tool-fs` | `tool-fs` | `tool-fs` | `applyPatch`、`read`、`readImage`、`write`、`edit` |
| `dsh-tool-fs-search` | `tool-fs-search` | `tool-fs-search` | — | `tool-fs-search` | `sampleOverCapGlobResults` |
| `dsh-tool-goal` | `tool-goal` | `tool-goal` | — | `tool-goal` | — |
| `dsh-tool-jobs` | `tool-jobs` | `tool-jobs` | — | `tool-jobs` | — |
| `dsh-tool-office` | `tool-office` | `tool-office` | — | — | — |
| `dsh-tool-present` | `present` | `present` | — | `present` | — |
| `dsh-tool-pwsh` | `tool-pwsh`（有条件） | `tool-pwsh`（有条件） | — | `tool-pwsh`（有条件） | — |
| `dsh-tool-pwsh-persistent` | — | — | `persistent-pwsh`（有条件） | — | `timeoutMs`、`description` |
| `dsh-tool-schedule` | `tool-schedule` | `tool-schedule` | — | `tool-schedule` | — |
| `dsh-tool-skill` | `tool-skill` | `tool-skill` | — | `tool-skill` | — |
| `dsh-tool-subagent` | `tool-subagent`、`tool-subagent-fork` | `tool-subagent`、`tool-subagent-fork` | — | `tool-subagent`、`tool-subagent-fork` | `provider`、`toolName`、`modelSelection`、`modelDiscovery` |
| `dsh-tool-subagent-control` | `tool-subagent-control` | `tool-subagent-control` | — | `tool-subagent-control` | `interrupt` |
| `dsh-tool-todo` | `tool-todo` | `tool-todo` | — | `tool-todo` | `allowParallelInProgress` |
| `dsh-tool-web` | `tool-web` | `tool-web` | — | `tool-web` | `fetch`、`searchTimeoutMs` |
| `dsh-tool-workflow` | `tool-workflow` | `tool-workflow`（禁用） | — | `tool-workflow` | — |
| `dsh-workflow-ptc` | `workflow-ptc` | `workflow-ptc`（禁用） | — | `workflow-ptc` | `provider` |
| `cordis:group` | `planning`、`compaction`、`delegation` | `planning`、`compaction`、`delegation` | `compaction`、`persistent-shell` | `planning`、`compaction`、`delegation` | — |
