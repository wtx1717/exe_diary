# exe_diary

一个面向跑步训练的桌面端笔记记录软件。项目目标是每天定时获取 Garmin Connect 上的跑步 FIT 文件，解析后写入本地 SQLite 数据库，并通过弹窗收集用户的主观训练反馈。

## 第一版目标

- 自动同步当天 Garmin 跑步活动。
- 保留手动同步日期范围的入口，用于补同步错过的活动。
- 下载并保留原始 FIT 文件。
- 解析 FIT 和 Garmin 活动摘要，写入 SQLite。
- 查询尚未填写主观记录的运动，后续用于弹窗问卷。
- 优先跑通本地数据闭环，再扩展统计面板和训练建议。

## 数据流程

```text
Garmin Connect
  -> 获取当天活动列表
  -> 过滤 running 类型
  -> 下载 FIT 文件
  -> 保存原始 FIT
  -> 解析运动摘要
  -> 写入 SQLite
  -> 查询未填写主观记录的活动
  -> 弹窗收集用户反馈
  -> 保存 activity_notes
```

## 同步策略

- 自动同步：默认只同步当天活动，适合电脑每天开机后定时运行。
- 手动同步：支持指定日期范围，防止电脑未开机或漏掉某次活动。
- 去重策略：保留 Garmin 原始 `activityId`，同时生成包含日期的本地 `local_id`。
- FIT 文件名：使用 `{YYYYMMDD}_{activityId}.fit`，并按年月目录保存。

## 当前项目结构

```text
src/exe_diary/
  main.py                 # 命令行入口
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
    prompt.py             # 后续弹窗问卷入口
```

## 本地配置

复制 `.env.example` 后填写 Garmin 账号信息。敏感信息不要提交到 Git。

```text
GARMIN_EMAIL=
GARMIN_PASSWORD=
GARMIN_IS_CN_ACCOUNT=true

EXE_DIARY_DATA_DIR=data
EXE_DIARY_DB_PATH=data/exe_diary.sqlite
EXE_DIARY_LOG_DIR=logs
```

## 命令入口

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
```

开发阶段也可以使用：

```bash
python -m exe_diary.main init-db
python -m exe_diary.main run
```

## 当前阶段使用方式

1. 安装项目和依赖：

```bash
pip install -e .[fit]
```

2. 复制 `.env.example` 为 `.env`，填写 Garmin 账号。

3. 初始化数据库：

```bash
exe-diary init-db
```

4. 运行完整流程：

```bash
exe-diary run
```

`run` 会先同步当天跑步活动，再对尚未填写主观记录的活动弹出窗口。若只想补填已入库但未填写的记录，使用：

```bash
exe-diary prompt-notes
```

## 数据库表

- `activities`：运动客观信息，包括 Garmin ID、本地 ID、FIT 路径、hash、距离、时长、心率、步频等。
- `activity_notes`：用户主观记录，包括疲劳、酸痛、睡眠、RPE、疼痛备注和总结。
- `sync_runs`：同步任务记录，用于排查自动同步是否成功。

## 后续开发重点

1. 接入已有 Garmin 抓取脚本的有效逻辑。
2. 完善 FIT 解析字段。
3. 实现弹窗问卷 UI。
4. 配置 Windows 计划任务。
5. 增加历史记录和基础统计视图。
