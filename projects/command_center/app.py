"""
app.py —— SignalFoundry Terminal 入口点

启动流程:
  1. 尝试加载 .env（python-dotenv，失败静默）
  2. 初始化 SettingsManager（config.json 优先）
  3. 创建 TaskQueue（从 SettingsManager 读取 API Key）
  4. 启动 UI（MainWindow + DashboardPanel + ChatPanel）

环境变量可选依赖:
  python-dotenv==1.0.1  (非必须，缺失时静默跳过)
"""

from __future__ import annotations
import logging
import sys
from pathlib import Path


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting SignalFoundry Terminal")

    # Step 0: 尝试加载 .env（可选依赖，失败静默降级）
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            import os
            ak = os.environ.get("DEEPSEEK_API_KEY", "")
            logger.info(".env loaded from %s (DEEPSEEK_API_KEY length=%d)", env_path, len(ak))
        else:
            logger.warning(".env not found at %s; using environment variables only", env_path)
    except ImportError:
        logger.warning("python-dotenv not installed; .env file will be ignored. Install with: pip install python-dotenv")

    # Step 1: 初始化 SettingsManager（config.json 优先，.env 后备）
    from projects.command_center.config.settings_manager import SettingsManager
    settings = SettingsManager()

    # Step 2: 创建 TaskQueue（适配器从 SettingsManager 读取配置）
    from projects.command_center.gateway.task_queue import TaskQueue
    from projects.command_center.gateway.pro_adapter import (
        ProAdapter, ProAdapterConfig,
    )
    from projects.command_center.gateway.flash_adapter import (
        FlashAdapter, FlashAdapterConfig,
    )
    from projects.command_center.gateway.router import LLMRouter

    pro_config = ProAdapterConfig.from_settings(settings)
    flash_config = FlashAdapterConfig.from_settings(settings)
    router = LLMRouter.create_default()

    pro_adapter = ProAdapter(config=pro_config)
    flash_adapter = FlashAdapter(config=flash_config)

    task_queue = TaskQueue(
        pro_adapter=pro_adapter,
        flash_adapter=flash_adapter,
        router=router,
    )
    task_queue.start()

    # 记录 Mock 状态
    logger.info(
        "API Key: %s | Pro=%s | Flash=%s",
        "SET" if settings.get_api_key() else "NOT SET",
        "MOCK" if not pro_config.api_key else "REAL",
        "MOCK" if not flash_config.api_key else "REAL",
    )

    # Step 3: 设置 UI 外观
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
    except ImportError:
        pass

    # Step 4: 启动 UI (注入 adapter 状态查询)
    try:
        from projects.command_center.ui.main_window import MainWindow
        app = MainWindow(task_queue=task_queue, settings=settings)
        logger.info("MainWindow displayed")

        # 注入 adapter 状态到 ChatPanel 欢迎消息
        pro_label = pro_adapter.status_label
        flash_label = flash_adapter.status_label
        app.chat_panel.update_adapter_status(pro_label, flash_label)
        logger.info("Adapter status injected: Pro=%s, Flash=%s", pro_label, flash_label)

        app.mainloop()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except Exception as e:
        logger.error("Fatal: %s", e, exc_info=True)
        sys.exit(1)

    # 关闭
    task_queue.shutdown()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()