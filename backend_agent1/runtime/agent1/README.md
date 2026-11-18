# agent1 运行时依赖

"
        "发布包不包含 Codex CLI、Java、Python 虚拟环境或任何密钥。安装时请准备：

"
        "- Python 3.11+；
- Java 21（需有 `java.exe` 和 `javac.exe`）；
"
        "- 与 agent1 兼容的 Codex CLI 可执行文件；
"
        "- MinerU API key 和下游模型 API key。

"
        "运行 `install.ps1` 会生成 `app/config/runtime.json`，把本机路径写入正式配置。
"
        "不要把运行时二进制、`.env` 或生成的任务目录提交到 GitLab。
