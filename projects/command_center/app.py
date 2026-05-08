"""
app.py —— Cline OS Command Center V2.0 入口点

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
    logger.info("Starting Cline OS Command Center V2.0")

    # Step 0: 尝试加载 .env（可选依赖，失败静默降级）
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(".env loaded from %s", env_path)
    except ImportError:
        pass  # python-dotenv 未安装，跳过

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

    task_queue = TaskQueue(
        pro_adapter=ProAdapter(config=pro_config),
        flash_adapter=FlashAdapter(config=flash_config),
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

    # Step 3: 启动 UI
    try:
        from projects.command_center.ui.main_window import MainWindow
        app = MainWindow(task_queue=task_queue, settings=settings)
        logger.info("MainWindow displayed")
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