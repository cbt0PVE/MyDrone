# Git 速查（本项目专用）

> 目标：一个人两台机器，不搞分支，只在 `main` 上直来直去。

## 一、日常只有三条

```bash
git pull                                  # 开工：拉别人的改动
git add -A && git commit -m "说明"        # 收工：暂存 + 提交
git push                                  # 收工：推到 GitHub
```

`git status` 随时可以看现在是什么状态，不改变任何东西，随便敲。

## 二、每条命令在说什么

### `git pull` = fetch + merge

成功时会看到 `Fast-forward`，意思是"没冲突，直接把指针往前挪"。
如果看到 `Already up to date.`，就是远端没新东西，正常。

**前提：工作区必须是干净的**（没有改了一半的文件）。不干净就 `git pull` 会报：

```
error: Your local changes to the following files would be overwritten by merge
```

处理：先提交（哪怕是临时的 `wip`），再 pull。

### `git add -A` = 把所有改动放进"待提交"

**敲之前先 `git status` 看一眼列表**。确认没有：
- `*.pt` / `*.mp4` / `*.onnx`（大文件，`.gitignore` 已挡，但新类型可能漏网）
- `.env`、密钥、密码
- 调试输出、临时截图

只想提交部分文件时，用 `git add 文件名` 逐个来。

### `git commit -m "..."` = 存一个快照

`-m` 后面写一句人话。项目约定写"改了什么、为什么"，不用很正式：

```bash
git commit -m "docs: 补充 Mac 端环境信息"
git commit -m "fix: takeoff.py 去掉 finally 里的 kill"
```

### `git push` = 推到 GitHub

成功会看到 `xxxx..yyyy  main -> main`。第一次在新机器上可能要加 `-u`：

```bash
git push -u origin main     # 只需第一次
```

## 三、报错怎么办

| 报错 | 意思 | 解决 |
| --- | --- | --- |
| `Your local changes ... would be overwritten` | 有未提交改动，pull 会覆盖 | 先 `git commit` 或 `git stash` |
| `! [rejected] ... (fetch first)` | 远端比你新，先拉 | `git pull` 再 `git push` |
| `fatal: not a git repository` | 不在仓库目录里 | `cd` 到项目目录 |
| `Permission denied (publickey)` | SSH 密钥没配好 | 检查 `ssh -T git@github.com` |
| `CONFLICT (content): Merge conflict in xxx` | 两台机器改了同一行 | 打开文件找 `<<<<<<<`，手动选保留哪段，删掉标记，再 `git add` + `git commit` |
| `nothing to commit, working tree clean` | 没有改动，不用提交 | 正常，直接结束 |

**冲突并不可怕**：冲突只发生在"两台机器改了同一个文件的同一段"。所以有个好习惯——收工必提交、开工必拉取，冲突概率会低很多。

## 四、建议先设一次（每台机器设一次）

```bash
git config --global pull.rebase true      # pull 用 rebase，历史更干净
git config --global rebase.autoStash true # pull 时自动暂存改动，少一类报错
git config --global init.defaultBranch main
```

## 五、后悔药

```bash
git status                          # 先看清楚，永远安全
git restore 文件名                   # 丢弃某个文件的未提交改动（不可恢复！）
git reset --soft HEAD~1             # 撤销上一次 commit，改动还留在工作区
git log --oneline -5                # 看最近 5 条提交
git diff                            # 看还没暂存的具体改动
```

**不要用** `git push --force`，也不要 `git reset --hard` 去"修"问题——这个仓库是两台机器共用的，强推会把另一台的提交抹掉。

## 六、让 AI 代劳时怎么说

可以直接说：

> **开工**：「先 `git pull`，然后告诉我这次拉下来改了什么。」
> **收工**：「提交并推送。commit message 你写，先把要提交的文件列给我确认。」

第二条里的"先列给我确认"是关键——让 AI 把 `git status` 的结果摆出来，你扫一眼有没有大文件或不该进库的东西，再让它提交。比你自己敲命令省事，又不会失控。
