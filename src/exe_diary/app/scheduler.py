from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from exe_diary.config import normalize_daily_time


TASK_NAME = "exe_diary_daily_auto_run"


@dataclass(frozen=True)
class SchedulerResult:
    success: bool
    message: str


def install_daily_start_task(
    run_time: str,
    *,
    launcher_dir: Path | None = None,
) -> SchedulerResult:
    if os.name != "nt":
        return SchedulerResult(False, "当前仅支持在 Windows 上自动创建系统计划任务。")

    normalized_time = normalize_daily_time(run_time)
    task_dir = launcher_dir or (_app_dir() / "data")
    launcher_path = _write_launcher(task_dir)
    hidden_launcher_path = _write_hidden_launcher(task_dir, launcher_path)
    task_xml_path = _write_task_xml(task_dir, normalized_time, hidden_launcher_path)
    command = [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/XML",
        str(task_xml_path),
        "/F",
    ]
    return _run_schtasks(command, f"计划任务已设置：每天 {normalized_time} 自动启动 exe_diary")


def remove_daily_start_task() -> SchedulerResult:
    if os.name != "nt":
        return SchedulerResult(False, "当前仅支持在 Windows 上自动删除系统计划任务。")

    command = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    result = _run_schtasks(command, "计划任务已删除")
    if not result.success and "找不到" in result.message:
        return SchedulerResult(True, "计划任务不存在，无需删除")
    return result


def _run_schtasks(command: list[str], success_message: str) -> SchedulerResult:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return SchedulerResult(False, output or f"schtasks 退出码：{completed.returncode}")
    return SchedulerResult(True, success_message)


def _write_launcher(directory: Path) -> Path:
    project_dir = _app_dir()
    python_executable = _python_executable()
    directory.mkdir(parents=True, exist_ok=True)
    launcher_path = directory / "exe_diary_scheduled_run.cmd"
    log_path = directory / "exe_diary_scheduled_run.log"
    launcher_path.write_text(
        "\n".join(
            [
                "@echo off",
                f'cd /d "{project_dir}"',
                f'echo [%date% %time%] scheduled-run start >> "{log_path}"',
                f'set "PYTHONPATH={project_dir / "src"};%PYTHONPATH%"',
                f'"{python_executable}" -m exe_diary.main scheduled-run >> "{log_path}" 2>&1',
                "set EXE_DIARY_EXIT_CODE=%errorlevel%",
                f'echo [%date% %time%] scheduled-run exit %EXE_DIARY_EXIT_CODE% >> "{log_path}"',
                "exit /b %EXE_DIARY_EXIT_CODE%",
            ]
        )
        + "\n",
        encoding="mbcs" if os.name == "nt" else "utf-8",
    )
    return launcher_path


def _write_hidden_launcher(directory: Path, launcher_path: Path) -> Path:
    hidden_launcher_path = directory / "exe_diary_scheduled_run.vbs"
    hidden_launcher_path.write_text(
        "\n".join(
            [
                'Set shell = CreateObject("WScript.Shell")',
                f'shell.CurrentDirectory = "{_escape_vbs_string(str(_app_dir()))}"',
                f'exitCode = shell.Run("cmd.exe /c ""{_escape_vbs_string(str(launcher_path))}""", 0, True)',
                "WScript.Quit exitCode",
            ]
        )
        + "\n",
        encoding="utf-16",
    )
    return hidden_launcher_path


def _write_task_xml(directory: Path, run_time: str, launcher_path: Path) -> Path:
    start_boundary = f"{date.today().isoformat()}T{run_time}:00"
    user_id = _current_user_id()
    principal = (
        f"""
    <Principal id="Author">
      <UserId>{escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>"""
        if user_id
        else """
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>"""
    )
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{escape(user_id or os.getenv("USERNAME") or "exe_diary")}</Author>
    <Description>每天自动启动 exe_diary，先同步活动数据，再弹出主观记录问卷。</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>{principal}
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT72H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(_wscript_executable()))}</Command>
      <Arguments>//B "{escape(str(launcher_path))}"</Arguments>
    </Exec>
  </Actions>
</Task>
"""
    task_xml_path = directory / "exe_diary_daily_auto_run.xml"
    task_xml_path.write_text(xml, encoding="utf-16")
    return task_xml_path


def _current_user_id() -> str:
    domain = os.getenv("USERDOMAIN")
    username = os.getenv("USERNAME")
    if domain and username:
        return f"{domain}\\{username}"
    return username or ""


def _wscript_executable() -> Path:
    system_root = os.getenv("SystemRoot", r"C:\Windows")
    return Path(system_root) / "System32" / "wscript.exe"


def _escape_vbs_string(value: str) -> str:
    return value.replace('"', '""')


def _python_executable() -> Path:
    executable = Path(sys.executable)
    candidates = [
        executable.parent.parent / "bin" / "python.exe",
        executable.with_name("python.exe"),
        executable,
    ]

    for name in ("python.exe", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return executable


def _app_dir() -> Path:
    package_dir = Path(__file__).resolve().parent
    if package_dir.parent.parent.name == "src":
        return package_dir.parent.parent.parent
    return package_dir.parent.parent
