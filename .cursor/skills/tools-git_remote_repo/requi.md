用户说，帮我把代码提交一下远程仓库吧，那么此时Agent需要做的事情：

1. 查看机器中的远程仓库地址和已缓存凭据（按平台检查 `~/.git-credentials` 是否有对应主机记录）。如果没有，请指引用户新建仓库链接，并**在本机终端自行写入凭据**；**禁止在对话中索要或接收 Token**。

2. 如果有，打印当前的 [user.name]，[user.email]，[仓库标识和URL], [远程仓库分支]

   a. 跟用户确认提交到哪个仓库，哪个分支(是否要新建分支)
   b. 查询项目正常连接到仓库以及 token 是否有效
   b. 查询远程仓库该分支是否有更新，跟用户确认是否先拉取还是覆盖
   c. 跟用户确认是否需要更改 [user.name]，[user.email]
   d. 查询 README.md 更新信息，跟用户确认 commit [message]

3. 拿到关键信息后，后台帮助用户提交

    ```bash
    git config --global user.name "<用户名>"
    git config --global user.email "<用户邮箱>"

    git checkout "<branch>"   # 若新建分支则 git checkout -b "<branch>"
    git pull ""

    git add .
    git commit -m "<message>"
    
    git push -u ""
    ```

    



   