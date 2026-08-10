# PolymerLit 双仓库同步与自动部署流程

## 1. 两个仓库分别负责什么

| 仓库 | 角色 | 主要内容 |
|---|---|---|
| `leexh2333-jpg/polymer_paper_extraction` | 开发上游 | 文献抽取代码、提示词、数据结构、测试、前后端通用功能、`batch_results` 和 `source_pdfs` |
| `zqk-7k/polymer_paper_extraction` | 集成与生产 | 自动合并上游，并额外维护 CI/CD、Docker、服务器发布配置和生产页面 |

开发者继续向 `leexh2333-jpg/main` 提交。生产服务器只部署通过 `zqk-7k/main` 完整测试的提交，不直接从开发仓库拉取代码。

## 2. 总流程

```text
开发者 push 到 leexh2333-jpg/main
              |
              v
zqk-7k 的 Sync development upstream
每小时第 17 分钟检查，或在 Actions 页面手动运行
              |
              v
GitHub Runner 临时拉取 development/main，并 merge 到 zqk-7k/main
              |
       +------+------+
       |             |
    有冲突          无冲突
    停止同步         push 生产 main
                     |
                     v
Python/前端测试 -> 两个 Docker 镜像构建检查
                     |
                全部通过后
                     v
读取服务器当前 SHA -> 生成增量 Git Bundle -> SSH 上传
                     |
                     v
服务器导入精确提交，按变化同步批处理数据，构建不可变版本
                     |
                     v
切换 /srv/polymerlit/current -> 重建容器 -> 健康检查
                     |
                     v
             https://122.51.104.121:18120
```

## 3. 如何手动拉取上游

手动同步不在服务器终端执行，也不需要在本地执行 `git pull`。

1. 打开 `https://github.com/zqk-7k/polymer_paper_extraction/actions`。
2. 左侧选择 **Sync development upstream**。
3. 点击右上角 **Run workflow**。
4. Branch 选择 `main`，再次点击绿色 **Run workflow**。

工作流运行在 GitHub 临时创建的 Ubuntu Runner 中。实际执行的核心命令是：

```bash
git remote add development https://github.com/leexh2333-jpg/polymer_paper_extraction.git
git fetch development main
git merge --no-edit development/main
git push origin HEAD:main
```

这里的 `development` 只是 Runner 中的临时 Git remote。执行结束后 Runner 会被销毁，生产服务器不会直接连接开发仓库。

定时同步由 `.github/workflows/sync-upstream.yml` 控制，cron 为 `17 * * * *`。GitHub 的定时任务可能因平台排队延迟几分钟，不保证在整点第 17 分钟精确启动。

## 4. 同步后为什么会自动部署

当同步工作流成功合并上游后，它会把新提交推送到 `zqk-7k/main`，并显式启动 `ci-cd.yml`。之所以显式启动，是因为 GitHub 为避免工作流递归，通常不会让使用内置 `GITHUB_TOKEN` 的一次自动 push 再无限触发其他工作流。

也可以只重新部署当前生产仓库的 `main`：

1. 在 Actions 中选择 **CI and production deployment**。
2. 点击 **Run workflow**，选择 `main`。

这不会再次拉取上游，只会测试并部署 `zqk-7k/main` 当前已有内容。

## 5. CI 检查了什么

只有以下步骤全部通过，部署任务才会开始：

| 阶段 | 内容 |
|---|---|
| Python 测试 | 抽取、OCR、候选结果发布、批处理集合选择 |
| 前端测试 | `npm ci`、lint 和组件测试 |
| 容器验证 | 分别构建 FastAPI/抽取服务和前端镜像 |
| 发布条件 | 仅 `main` push 或手动运行，且 `PRODUCTION_DEPLOY_ENABLED=true` |

Pull Request 只执行测试，不会部署生产服务器。

## 6. 自动部署的内容

### 6.1 应用代码

- 文献抽取各 Stage、OCR、Preview 和候选结果发布逻辑；
- 提示词、Schema、标准化和校验规则；
- FastAPI 后端及网页前端；
- Docker、Caddy 和生产发布脚本；
- 构建和运行这些模块所需的配置文件。

### 6.2 批处理展示数据

- `batch_results/`：随 Git 提交同步到服务器 `/srv/polymerlit/data/batch_results`；
- `source_pdfs/`：随 Git 提交同步到服务器 `/srv/polymerlit/data/source_pdfs`；
- 只有 Git 判断目录内容发生变化时才更新，未变化时不会重复复制；
- 更新采用暂存目录和目录替换，随后重建 API 容器。

API 启动时会扫描 `batch_results/` 下所有带 `RESULT_INDEX.json` 的集合，按 `result_date`、`generated_at` 和目录名选择最新集合。因此：

- 修改现有批次中的 `candidate.json`，部署后页面会显示新内容；
- 增加日期更晚的新批次，部署后页面会自动切到新批次；
- 删除或修改文件但没有提交、没有同步到 `zqk-7k/main`，页面不会变化；
- 若生产环境设置 `BATCH_RESULTS_COLLECTION`，页面会固定使用该目录，而不自动选最新集合。

可访问 `/api/health` 查看当前实际使用的 `batch_collection` 和 `batch_result_date`。

### 6.3 不随 Git 自动覆盖的数据

| 数据 | 保存位置与原因 |
|---|---|
| 网页上传任务及抽取结果 | `/srv/polymerlit/runtime`，持久化保存，发布新版本不会删除 |
| PoLyInfo 本地对照数据 | 服务器 `/srv/polymerlit/polyinfo`，不来自公开仓库，不随代码部署覆盖 |
| API Key、MinerU Key | 用户请求时临时传给任务进程，不写入 Git、镜像或任务记录 |
| GitHub Secrets | 仅 GitHub Actions 部署步骤读取，不进入发布包 |

## 7. 服务器如何发布

1. CI 读取 `/srv/polymerlit/current` 指向的当前 Git SHA。
2. 从当前 SHA 到新 SHA 生成增量 Git Bundle，只传输新增 Git 对象。
3. 服务器将 Bundle 导入 `/srv/polymerlit/app` 并验证目标提交存在。
4. 比较新旧提交中的 `batch_results/` 和 `source_pdfs/`；变化时才准备新数据目录。
5. 代码通过 `git archive` 生成精简发布包，数据目录不放进 Docker 构建上下文。
6. 在 `/srv/polymerlit/releases/<sha>` 构建 API 和前端镜像。
7. 原子更新 `/srv/polymerlit/current`，重建 API、前端和 Caddy 容器。
8. 最多等待约 90 秒访问 `/api/health`；成功后清理无用镜像，失败则工作流报错。

每个发布目录以完整提交 SHA 命名，因此可以定位线上代码版本，也为人工回滚保留基础。

## 8. 失败时会发生什么

| 失败点 | 结果 |
|---|---|
| 上游 merge 冲突 | 同步工作流失败，`zqk-7k/main` 和线上版本保持不变，需要人工解决冲突 |
| 任一测试失败 | 不构建、不部署 |
| Docker 构建失败 | 不部署 |
| SSH 或上传失败 | 线上容器继续运行旧版本 |
| 新容器健康检查失败 | 工作流失败，需要查看服务器容器日志；当前脚本不会把失败版本标为成功 |

## 9. 日常操作速查

| 目的 | 操作 |
|---|---|
| 立刻同步开发者最新提交 | Actions -> Sync development upstream -> Run workflow |
| 仅重跑当前版本的测试和部署 | Actions -> CI and production deployment -> Run workflow |
| 查看同步是否成功 | 查看 Sync workflow 的 merge 和 push 步骤 |
| 查看部署是否成功 | CI workflow 中 `test`、`container-build`、`deploy` 全部为绿色 |
| 确认线上版本和批次 | 访问 `/api/health` |
| 检查批处理页面为何未更新 | 确认文件已 commit、已同步到生产 main、CI 部署成功、索引日期有效且未被环境变量固定 |

## 10. HTTPS 与密钥安全

公开地址为 `https://122.51.104.121:18120`，使用 Let's Encrypt 的短期 IP 证书，不强制购买域名。证书约 6 天有效，`polymerlit-cert-renew.timer` 每天检查两次，续期成功后自动热加载 Caddy。生产 API 仍拒绝通过明文 HTTP 提交用户 API Key。服务器密码、SSH 私钥和 API Key 不得提交到任一仓库。
