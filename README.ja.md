# open-primeagent

[English](README.md) · [한국어](README.ko.md) · [简体中文](README.zh-CN.md) · **日本語**

<sub>英語版 README の最初の画面だけを訳したものです。全体と最新の内容は[英語版 README](README.md) にあります。</sub>

**Claude Code が時間をかけてリポジトリを覚えました。ところが同僚が同じリポジトリを Codex で開くと、
Codex はそのどれも知りません。**

いまのエージェントはそれぞれ自分で覚えます。ただし自分のためだけに。Claude Code は `~/.claude` に、
Codex は `~/.codex` に、それも書いたマシンの上にだけ残します。open-primeagent は、エージェントが学んだことを
リポジトリの `AGENTS.md` と `CLAUDE.md` の中の、目印で囲んだブロック 1 つに書きます。だからコードと一緒に
コミットされ、Claude Code も Codex も opencode も同じものを読みます。

![見つけ直しにくいルールのある新しいクローンで素の Claude Code を 2 セッション比較：前のエージェントが残した AGENTS.md がある方がターン数 51% 減、時間 51% 減](docs/assets/portable-demo.gif)

<sub>[実測データ](bench/results/portable-deep-sonnet.json)（Sonnet、各 n=6、平均）を再生したもので、演出ではありません。見つけ直しやすいルールでは効果はおよそ半分です：[26%](bench/README.md#p-a-rule-learned-by-one-agent-used-by-the-next-one-without-us---wins-more-when-the-rule-is-hard)。[`bench/demo_portable.py`](bench/demo_portable.py) で作り直せます。</sub>

いま使っているエージェント（3 つのどれでも）に MCP サーバーを 1 つ足すだけです。

- **リポジトリと一緒に移るルール。** open-primeagent をつないだ Claude Code が、1 回のセッションで
  リポジトリの隠れたルールを見つけて記録しました。そこからできた `AGENTS.md` だけを入れた新しいクローンを、
  open-primeagent をまったく使わない素の Claude Code で開くと、見つけ直しにくいルールではターン数と時間が
  51% 減、見つけ直しやすいルールでは 26% 減で同じタスクを終えました。ブロックは `opa_bootstrap(remove=True)` でそのまま取り除けます。
- **エージェントをまたぐサブエージェント。** Claude Code から Codex のサブエージェントを残しておき、
  あとで追加の質問を送れます。Claude Code、Codex、opencode はどれも自分のサブエージェントは再開できますが、
  互いのものには届きません。（Codex の子は実際の CLI で手作業で確認済み。CI はスタブを使います。）
- **呼び出しの合間も生きている Python プロセス。** コンテキストウィンドウに置きたくない状態をしまっておけます。
  ただ、役に立つことはまだ示せていません。ベンチマークの 120 ターンで、エージェントは一度も呼びませんでした。

```bash
claude mcp add opa -- uvx open-primeagent
# Codex と opencode は英語版 README の Install を参照。Claude Code のプラグインとしても入れられます：
# /plugin install open-primeagent --marketplace softkleenex/open-primeagent
```

### 負けたベンチマーク

| 実験 | 結果 | |
|---|---|---|
| open-primeagent で学んだルールを、それを持たない新しいエージェントが `AGENTS.md` だけで読む（おとりスクリプト 3 つがもっともらしい誤った出力を出す） | ターン数 51% 減、時間 51% 減 | 勝ち |
| 同じ実験で、見つけ直しやすいルール | ターン数 26% 減、時間 26% 減 | 小さく勝ち |
| 同じ実験の最初の版：エージェントがルールをメモリとして保存し、他のエージェントにはタイトルしか見えなかった | 肝心の事実が届いたのは 6 回中 4 回 | 負け、修正後 6 回中 6 回 |
| 16 個のおとりスクリプトに埋もれた知識をルールとして記録（8 月） | かかった時間 57% 減、ばらつきも縮小 | 勝ち |
| 同じルールで、答えがすぐ目に入る場合 | ターン数 26% 増 | 負け |
| 新しく立ち上げず、コードを読み終えたサブエージェントに頼み直す | コスト 81% 減 | 勝ち、ただし今は各エージェントが標準で対応 |
| 新しいサブエージェント 4 つに分担 | コスト 777% 増 | 負け |
| 分担が勝つように作った 444 ファイルのコードベースで分担 | かかった時間 127% 増 | 負け |
| 永続カーネルを 120 ターンつないだまま | 呼び出し 0 回 | 効果なし |

負けた結果も消しません。勝った結果を信じられるものにしているのは負けた結果で、
なぜ負けたかのほうが数字より役に立ちます。[生データと測定方法](bench/README.md)

自分たちにも同じ基準を当てています。この README は以前「セッションが終わっても残るサブエージェント」を
看板にしていました。各エージェントと比べてみたところ、Claude Code、Codex、opencode が今年そろって標準機能にしていたので、
もう最初の一文には置いていません。「ブロックの外は 1 文字も変えない」という約束も、外部レビューで破れる入力が見つかり、
[経緯は開発ログにあります](docs/journal.md#an-outside-review-breaks-the-headline-promise-2026-11-25)。
いまは安全装置すべてに[ミューテーションテスト](scripts/mutate_guards.py)をかけています。わざと壊して、テストが落ちることを確かめます。

**[残りのドキュメント（英語）→](README.md#install)**
