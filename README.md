# exe_diary

一个面向跑步训练的本地桌面日记工具。当前版本可以从 Garmin Connect 同步跑步 FIT 文件，解析并写入本地 SQLite 数据库，再收集用户的主观训练反馈。

## 当前能力

- 同步今天、指定日期范围或最近若干条 Garmin 跑步活动。
- 下载并保留原始 FIT 文件。
- 解析 FIT 与 Garmin 活动摘要，写入 SQLite。
- 查询尚未填写主观记录的活动。
- 通过桌面弹窗补填疲劳、酸痛、睡眠、RPE、心情和备注。
- 提供桌面主界面，用于执行同步、查看最近活动、查看待补填活动和查看同步记录。

## 数据流程

```text
Garmin Connect
  -> 获取活动列表
  -> 过滤 running 类型
  -> 下载 FIT 文件
  -> 保存原始 FIT
  -> 解析运动摘要
  -> 写入 SQLite
  -> 查询未填写主观记录的活动
  -> 弹窗收集用户反馈
  -> 保存 activity_notes
```

## 本地配置

复制 `.env.example` 为 `.env`，然后填写 Garmin 账号信息。敏感信息不要提交到 Git。

```text
GARMIN_EMAIL=
GARMIN_PASSWORD=
GARMIN_IS_CN_ACCOUNT=true

EXE_DIARY_DATA_DIR=data
EXE_DIARY_DB_PATH=data/exe_diary.sqlite
EXE_DIARY_LOG_DIR=logs

EXE_DIARY_AUTO_RUN_ENABLED=false
EXE_DIARY_AUTO_RUN_TIME=20:30
```

相对路径会按项目目录解析。例如上面的配置会把数据库写到 `D:\Project\exe_diary\data\exe_diary.sqlite`。
`EXE_DIARY_AUTO_RUN_TIME` 使用 24 小时制 `HH:MM` 格式。桌面界面保存“每日自动运行”设置时，会同步写入 `.env` 并创建或删除 Windows 计划任务。到点后软件会自动启动并执行“同步今天 -> 补填问卷”，问卷结束后会把主界面弹到前台。外部调度器也可以直接调用 `exe-diary scheduled-run`，用于立刻执行同一流程。

## 安装

基础安装：

```bash
pip install -e .
```

安装 FIT 解析依赖：

```bash
pip install -e .[fit]
```

## 桌面界面入口

安装后可以直接打开桌面界面：

```bash
exe-diary-gui
```

也可以通过现有命令行入口打开：

```bash
exe-diary gui
python -m exe_diary.main gui
```

桌面界面包含：

- 初始化数据库。
- 同步今天、最近活动或指定日期范围。
- 同步今天并继续弹窗补填主观记录。
- 每日自动运行设置，可保存到 `.env`，也可直接通过环境变量外部配置。
- 查看最近活动、待补填活动和同步记录。

## 命令行入口

```bash
exe-diary init-db
exe-diary run
exe-diary run --limit 1
exe-diary sync-today
exe-diary sync-today --limit 1
exe-diary sync-range --from-date 2026-06-01 --to-date 2026-06-02
exe-diary sync-range --from-date 2026-06-01 --to-date 2026-06-02 --limit 2
exe-diary sync-latest --limit 2
exe-diary pending-notes
exe-diary prompt-notes
exe-diary gui
exe-diary scheduled-run
exe-diary install-daily-schedule --time 20:30
exe-diary remove-daily-schedule
```

开发阶段也可以使用：

```bash
python -m exe_diary.main init-db
python -m exe_diary.main run
python -m exe_diary.gui
```

## 项目结构

```text
src/exe_diary/
  main.py                 # 命令行入口
  gui.py                  # 桌面界面入口
  config.py               # 环境变量和路径配置

  garmin/
    client.py             # Garmin 登录、活动列表、FIT 下载
    sync.py               # 自动/手动同步流程

  fit/
    parser.py             # FIT 摘要解析
    models.py             # 运动摘要数据结构

  db/
    database.py           # SQLite 连接和初始化
    schema.sql            # 数据库表结构
    repositories.py       # 数据读写接口

  app/
    workflow.py           # 应用流程编排

  ui/
    app.py                # 桌面主界面
    prompt.py             # 主观记录弹窗
```

## 数据库表

- `activities`：运动客观信息，包括 Garmin ID、本地 ID、FIT 路径、距离、时长、心率、步频等。
- `activity_notes`：用户主观记录，包括疲劳、酸痛、睡眠、RPE、疼痛备注和总结。
- `sync_runs`：同步任务记录，用于排查自动同步是否成功。
