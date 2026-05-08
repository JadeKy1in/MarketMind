"""
test_chat_panel.py —— Sprint 2 ChatPanel 测试
"""

from __future__ import annotations
import time
import pytest
import customtkinter as ctk
from projects.command_center.gateway.task_queue import TaskQueue
from projects.command_center.ui.dashboard_panel import DashboardPanel
from projects.command_center.ui.intake_bar import IntakeBar
from projects.command_center.ui.chat_panel import ChatPanel


@pytest.fixture(scope="module")
def tk_root():
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def dash(tk_root):
    p = DashboardPanel(tk_root)
    p.pack(fill="both", expand=True)
    tk_root.update_idletasks()
    yield p
    p.destroy()


@pytest.fixture
def ibar(tk_root):
    b = IntakeBar(tk_root)
    b.pack(fill="x")
    tk_root.update_idletasks()
    yield b
    b.destroy()


@pytest.fixture
def tq():
    q = TaskQueue.create_default(auto_start=True)
    yield q
    q.shutdown(wait=True, timeout=2.0)


@pytest.fixture
def cp(tk_root, tq):
    p = ChatPanel(tk_root, task_queue=tq)
    p.pack(fill="both", expand=True)
    tk_root.update_idletasks()
    yield p
    p.shutdown()
    p.destroy()


class TestDashboardPanel:
    def test_tabs_exist(self, dash):
        assert dash.tab_positions is not None
        assert dash.tab_beliefs is not None
        assert dash.tab_shadows is not None


class TestIntakeBar:
    def test_empty_ignored(self, ibar):
        calls = []
        ibar.set_on_submit(lambda t, f: calls.append((t, f)))
        ibar._do_submit()
        assert len(calls) == 0

    def test_submit_works(self, ibar):
        calls = []
        ibar.set_on_submit(lambda t, f: calls.append((t, f)))
        ibar.entry.insert(0, "测试")
        ibar._do_submit()
        assert len(calls) == 1
        text, files = calls[0]
        assert "测试" in text
        assert files == []

    def test_clear_after(self, ibar):
        ibar.set_on_submit(lambda t, f: None)
        ibar.entry.insert(0, "x")
        ibar._do_submit()
        assert ibar.entry.get() == ""

    def test_enable_disable(self, ibar):
        ibar.disable()
        assert ibar.entry.cget("state") == "disabled"
        ibar.enable()
        assert ibar.entry.cget("state") == "normal"


class TestChatPanel:
    def test_components(self, cp):
        assert cp.intake_bar is not None
        assert cp.task_queue is not None
        assert cp.task_queue.is_running

    def test_submit_poll(self, tk_root, cp, tq):
        tid = tq.submit_from_text(text="测试")
        assert tid is not None
        deadline = time.time() + 10
        found = False
        while time.time() < deadline:
            for r in tq.drain_callbacks(10):
                if r.task_id == tid:
                    assert len(r.output) > 0
                    assert "mock" in r.model_used.lower()
                    found = True
                    break
            if found:
                break
            time.sleep(0.1)
            tk_root.update_idletasks()
        assert found, f"Task {tid} timeout"

    def test_append_user(self, tk_root, cp):
        cp.append_user_message("用户消息")
        tk_root.update_idletasks()
        assert "用户消息" in cp._disp.get("1.0", "end")

    def test_append_system(self, tk_root, cp):
        cp.append_system_message("系统回复", model="mock_pro")
        tk_root.update_idletasks()
        c = cp._disp.get("1.0", "end")
        assert "系统回复" in c
        assert "mock_pro" in c

    def test_append_error(self, tk_root, cp):
        cp.append_error_message("出错")
        tk_root.update_idletasks()
        assert "出错" in cp._disp.get("1.0", "end")

    def test_welcome(self, tk_root, cp):
        c = cp._disp.get("1.0", "end")
        assert "Command Center" in c
        assert "四象限" in c

    def test_shutdown(self, cp, tq):
        assert tq.is_running
        cp.shutdown()
