
# 🔗 Git 远程仓库提交

  - **概述**: 当用户说「帮我把代码提交到远程仓库」「push 一下」「同步 GitLab / GitHub」等时，按本 Skill 执行：**先检查与确认，再校验连通性与 Token，最后提交**。
  - **日期**: 2026-07-08

## 1 触发场景与原则

  - **触发词**: 提交远程、push、同步 GitLab、同步 GitHub。
  - **认证方式**: 统一 **HTTP/HTTPS** + Token；`credential.helper=store` 缓存于 `~/.git-credentials`。
  - **remote 命名**: `github`（个人）、`gitlab`（团队）；`<仓库标识>` 是 `git remote` 别名，不是分支名。
  - **凭据安全（强制）**:
    - **禁止**在对话中向用户索要 Token，**禁止**接受用户在聊天里粘贴的 Token。
    - **禁止**将 Token 写入 shell 命令、`echo`、日志或任何 Agent 可回显的输出。
    - 新仓库 / 目标平台无缓存凭据时，**停止 push**，仅指引用户**在本机终端自行**配置（见 §2.2），配置完成后再继续。
  - **注意**: 未经用户明确同意，不得 `git push --force`；受保护分支被拒绝时，改用 `pull --allow-unrelated-histories` 合并。

## 2 检查 remote 与凭据

  - 在项目根目录执行以下命令：

    ```bash
    git rev-parse --is-inside-work-tree
    git config user.name
    git config user.email
    git config --global credential.helper
    git remote -v
    test -f ~/.git-credentials && echo "credentials: yes" || echo "credentials: no"
    # 按目标平台检查是否已有缓存（仅判断有无，禁止读取或输出凭据内容）
    grep -q 'github.com' ~/.git-credentials 2>/dev/null && echo "github cred: yes" || echo "github cred: no"
    grep -q '<gitlab-host>' ~/.git-credentials 2>/dev/null && echo "gitlab cred: yes" || echo "gitlab cred: no"
    git status -sb
    ```

  - `<gitlab-host>` 取自 `git remote get-url gitlab` 的域名（如 `doc.geoai.com`）。

### 2.1 缺少 remote 时

  - 指引用户新建链接：

    ```bash
    git remote add <仓库标识> <远程仓库URL>
    # 例：git remote add gitlab http://doc.geoai.com:5002/geoai/ai/yoloe.git
    ```

### 2.2 缺少凭据时（用户自行写入）

  - 触发条件：目标 `<仓库标识>` 对应主机在 `~/.git-credentials` 中**无记录**，或 push 报 `could not read Username` / 认证失败。
  - **立即停止**，不得继续 push；向用户说明「该平台凭据未缓存」，并给出以下指引（**对话中不出现 Token 字样以外的敏感信息，不索要 Token**）：

    **步骤 1 — 在平台创建访问凭据**

    | 平台 | 创建路径 | 所需权限 |
    | ---- | -------- | -------- |
    | GitHub | Settings → Developer settings → Personal access tokens | `repo` |
    | GitLab | Settings → Access Tokens | `write_repository` |

    **步骤 2 — 用户在本机终端自行写入**（Agent **不得代写**）

    ```bash
    git config --global credential.helper store

    # 将 <平台用户名> 与 <访问凭据> 替换为实际值后，在本机终端执行：
    # 注意：必须是 https://（两个斜杠），写成 https: 会导致认证失败
    echo "https://<平台用户名>:<访问凭据>@github.com" >> ~/.git-credentials

    # GitHub 示例（请替换为你自己的用户名与 PAT，切勿把真实 Token 写入仓库）：
    # echo "https://Yulin-CC:ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx@github.com" >> ~/.git-credentials

    # GitLab 占位符：
    # echo "https://<平台用户名>:<访问凭据>@doc.geoai.com:5002" >> ~/.git-credentials
    ```

    **步骤 3 — 用户回复「已配置」后**，Agent 执行 §3.3 连通性与 Token 校验；通过后再进入 §3 收集远程信息。

  - **注意**:
    - 缺少 remote 或凭据时**停止**，等用户自行补全并确认后再进入 §3。
    - 凭据行格式必须为 `https://用户名:凭据@主机`；`https:`（少一个 `/`）会导致 `could not read Username`。
    - 若用户在聊天中误发凭据，**不要**写入文件或回显；提醒其立即在平台撤销并重新生成。

## 3 打印现状并与用户确认

### 3.1 收集远程信息

  - 先 fetch，再对比本地与远程差异：

    ```bash
    git fetch --all
    git branch -a
    git log --oneline HEAD..<仓库标识>/<分支>   # 远程有、本地无
    git log --oneline <仓库标识>/<分支>..HEAD   # 本地有、远程无
    ```

  - 向用户打印（凭据仅说明「已缓存 / 未缓存」，禁止输出明文、禁止索要）：

    - `user.name` / `user.email`
    - 各 `<仓库标识>` → URL
    - 本地当前分支、候选远程分支
    - `git status` 摘要
    - 远程是否领先（需 pull）

### 3.2 必须逐项确认

  - 使用 AskQuestion 或对话，拿到以下确认前**不得 push**：

    - **a.** 提交到哪个 `<仓库标识>`、哪个 `<分支>`？是否 `git checkout -b <新分支>`？
    - **b.** 远程该分支有更新时，先 **pull** 还是覆盖（覆盖需明确授权 force push）？
    - **c.** 是否修改 `user.name` / `user.email`？
    - **d.** 读 `README.md`「更新日志」与 `git diff --stat`，拟定 commit message 并请用户确认。

  - commit message 拟定规则：

    - 优先对照 `README.md` 更新日志
    - 无对应条目时，根据 `git diff --stat` 一句话概括
    - 示例：`docs: 更新 README 开集训练说明`、`feat: 新增 data/create_data.py`

### 3.3 推送前连通性与 Token 校验

  - **时机**: 用户 §3.2 确认目标 `<仓库标识>` / `<分支>` 后、§4 执行 `add` / `commit` / `push` **之前**；凭据刚配置完（§2.2 步骤 3）亦执行本节。
  - **目的**: 提前发现「凭据格式错误 / Token 失效 / 无写权限 / 网络不通」，避免 commit 完成后才 push 失败。
  - **原则**: 全程 `GIT_TERMINAL_PROMPT=0`（禁止交互式索要凭据）；**禁止** `cat` / 输出 `~/.git-credentials` 明文；`git credential fill` 的 stdout **必须**重定向到 `/dev/null`。

  - 在项目根目录**顺序执行**（将 `<仓库标识>`、`<分支>` 替换为用户确认值）：

    ```bash
    export GIT_TERMINAL_PROMPT=0
    url=$(git remote get-url <仓库标识>)
    host=$(echo "$url" | sed -E 's#https?://([^/@]+@)?([^/]+).*#\2#')

    # A. 凭据是否已缓存
    grep -q "$host" ~/.git-credentials || { echo "FAIL: 凭据未缓存 ($host)"; exit 1; }

    # B. 凭据行格式（常见错误：写成 https: 而非 https://）
    grep "$host" ~/.git-credentials | grep -qE '^https?://' || { echo "FAIL: 凭据格式错误，须为 https://用户名:凭据@主机"; exit 1; }

    # C. git 能否读取凭据（仅看 exit code，不回显）
    printf 'url=%s\n' "$url" | git credential fill >/dev/null || { echo "FAIL: git 无法读取凭据"; exit 1; }

    # D. 仓库可达 + Token 读权限
    git fetch <仓库标识> || { echo "FAIL: fetch 失败（网络或 Token 读权限）"; exit 1; }

    # E. Token 写权限（dry-run，不实际上传对象）
    git push --dry-run <仓库标识> <分支> || { echo "FAIL: push dry-run 失败（Token 无效或无写权限）"; exit 1; }

    echo "OK: 连通性与 Token 校验通过"
    ```

  - **失败处理**（停止 §4，不得继续 push）：

    | 现象 | 可能原因 | 处理 |
    | ---- | -------- | ---- |
    | `FAIL: 凭据未缓存` | `~/.git-credentials` 无对应主机 | → §2.2 |
    | `FAIL: 凭据格式错误` | `https:` 少 `/` 或缺少协议头 | → §2.2，强调 `https://` |
    | `FAIL: git 无法读取凭据` | `credential.helper` 未配置或格式损坏 | → §2.2 |
    | `could not read Username` | 同上，多为格式错误或 helper 未生效 | → §2.2 |
    | `Authentication failed` / `403` / `Invalid username or token` | Token 过期或权限不足 | → §2.2，提示重新生成并检查 `repo` / `write_repository` |
    | `fetch` 超时 | 网络问题 | → §4.1 网络超时配置后重试 §3.3 |

  - **向用户汇报**（仅说明通过 / 失败原因，禁止输出凭据）：
    - 目标 `<仓库标识>` / URL / `<分支>`
    - 各项检查结果：`凭据缓存` / `凭据格式` / `credential fill` / `fetch` / `push --dry-run`
    - 全部通过后方可进入 §4

## 4 后台执行提交

  - **前置条件**: §3.3 校验已通过。
  - 用户确认后，在项目根目录**顺序执行**：

    ```bash
    git config --global user.name "<用户名>"
    git config --global user.email "<用户邮箱>"

    git checkout "<分支>"
    # 新建分支：git checkout -b "<分支>"

    git fetch <仓库标识>
    git pull <仓库标识> <分支> --no-rebase

    git add .
    git commit -m "<message>"

    git push -u <仓库标识> <分支>
    ```

  - **注意**: 若用户 §3.2 **c** 确认不修改身份，跳过 `git config` 两行；若 §3.2 **b** 选择暂不 pull，跳过 `git pull`；无 staged 改动时跳过 `git commit`，直接 push。

### 4.1 异常处理

  - **`rejected (fetch first)`**（远程有 Initial commit）：

    ```bash
    git pull <仓库标识> <分支> --allow-unrelated-histories --no-rebase --no-edit
    git checkout --ours README.md && git add README.md
    git commit -m "Merge remote initial commit"
    git push -u <仓库标识> <分支>
    ```

  - **protected branch 拒绝 force push**：仅 pull 合并，不要 force。

  - **认证失败**（`could not read Username`、`Authentication failed`、`403`）：

    - 若 §3.3 已执行仍失败（极少见，如 Token 中途失效）：回到 §2.2，指引用户自行写入凭据；**不得**在对话中索要或接收凭据后重试。

  - **网络超时**（`HTTP 408`、`RPC failed`）：可调大缓冲后重试，**不涉及凭据**：

    ```bash
    git config --global http.postBuffer 524288000
    git config --global http.lowSpeedLimit 0
    git config --global http.lowSpeedTime 999999
    git config --global http.version HTTP/1.1
    ```

## 5 回报结果

  - 执行完毕后向用户报告：

    - 目标 `<仓库标识>` / `<分支>` / commit hash
    - push 是否成功
    - 若同步多个 remote，分别说明

    ```bash
    git log -1 --oneline
    git status -sb
    git branch -vv
    ```

## 6 双仓库维护（可选）

  - 同时维护 GitLab + GitHub 时：

    - **pull**：只从 `gitlab` 拉团队更新
    - **push**：按用户确认，依次 push 各 remote

    ```bash
    git pull gitlab main --no-rebase
    git push gitlab main
    git push github main
    ```

  - **注意**: 需求原文见 `.cursor/skills/tools-git_remote_repo/requi.md`。
