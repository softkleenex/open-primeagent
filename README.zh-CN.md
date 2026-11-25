# open-primeagent

[English](README.md) · [한국어](README.ko.md) · **简体中文** · [日本語](README.ja.md)

<sub>本文只翻译了英文 README 的首屏。完整文档和最新内容请看[英文 README](README.md)。</sub>

**Claude Code 雇了一个子代理。子代理读了你半个仓库。
然后 Claude Code 把它开除了，下次再雇一个新的，从头再读一遍。**

![同一个追问，分别交给新建的子代理和已经读过代码的子代理：成本降低 81%，token 减少 91%](docs/assets/reuse-demo.gif)

<sub>回放的是[实测数据](bench/results/warm-sonnet.json)（Sonnet，n=4，取平均），不是摆拍。可以用 [`bench/demo.py`](bench/demo.py) 重新生成。</sub>

open-primeagent 会把子代理留下来。之后你再追问，它还记得代码。
它只是一个 MCP 服务器，加到你正在用的代理（Claude Code、Codex 或 opencode）上就行，做三件事：

- **会话结束后还在的子代理。** 让已经读过代码的子代理接着干活，成本比新建一个低 81%。
- **不会被忘掉的项目规则。** 代理学到的东西会写进它本来就会读的 `CLAUDE.md` 或 `AGENTS.md`，
  只写在一个带标记的区块里，`opa_bootstrap(remove=True)` 可以原样移除。
  在规则很难重新找到的任务上，耗时减少了 57%。
- **在调用之间一直活着的 Python 进程**，用来放你不想塞进上下文窗口的状态。
  它有没有用，我们还没证明：基准测试的 120 轮里，代理一次也没调用过它。

```bash
claude mcp add opa -- uvx open-primeagent
# 或者作为带技能的 Claude Code 插件安装：
# /plugin install open-primeagent --marketplace softkleenex/open-primeagent
```

### 我们输掉的基准测试

| 实验 | 结果 | |
|---|---|---|
| 不新建，而是让已经读过代码的子代理接着干 | 成本降低 81% | 赢 |
| 把藏在 16 个干扰脚本里的知识记成规则 | 耗时减少 57%，波动也变小 | 赢 |
| 同一条规则，但答案一眼就能看到 | 轮数增加 26% | 输 |
| 分给 4 个新的子代理 | 成本增加 777% | 输 |
| 在专门为分派设计的 444 个文件的代码库上分派 | 耗时增加 127% | 输 |
| 持久内核挂了 120 轮 | 调用 0 次 | 没效果 |

输掉的结果我们不删。正是它们让赢的结果可信，而且"为什么输"比数字更有用。[原始数据和方法](bench/README.md)

代码也守同样的规矩。这份 README 曾经承诺：区块外的内容一个字都不会改。
一次外部审查找到了能打破这个承诺的输入，[经过写在开发日志里](docs/journal.md#an-outside-review-breaks-the-headline-promise-2026-11-25)。
现在每个安全防护都做了[变异测试](scripts/mutate_guards.py)：故意把它弄坏，确认有测试会失败。

**[其余文档（英文）→](README.md#install)**
