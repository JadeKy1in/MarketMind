"""Tests for chat handler — session management and endpoint validation."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from marketmind.api.routes import app
from marketmind.api.chat_handler import ChatManager, ChatSession, get_chat_manager


class TestChatManager:
    def test_get_or_create_new_session(self):
        mgr = ChatManager()
        sess = mgr.get_or_create("abc123")
        assert sess.session_id == "abc123"
        assert len(sess.messages) == 0

    def test_get_or_create_reuses_session(self):
        mgr = ChatManager()
        s1 = mgr.get_or_create("abc")
        s1.add_message("user", "hello")
        s2 = mgr.get_or_create("abc")
        assert s2 is s1
        assert len(s2.messages) == 1

    def test_get_history_empty(self):
        mgr = ChatManager()
        assert mgr.get_history("nonexistent") == []

    def test_clear_session(self):
        mgr = ChatManager()
        mgr.get_or_create("abc").add_message("user", "test")
        mgr.clear("abc")
        assert mgr.get_history("abc") == []

    def test_max_history_truncation(self):
        from marketmind.api.chat_handler import MAX_HISTORY
        mgr = ChatManager()
        sess = mgr.get_or_create("abc")
        for i in range(MAX_HISTORY + 10):
            sess.add_message("user", f"msg {i}")
        assert len(sess.messages) == MAX_HISTORY


class TestChatEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app, base_url="http://127.0.0.1:8520")

    def test_chat_empty_message_returns_400(self, client):
        r = client.post("/api/chat", json={"message": "", "session_id": "test"})
        assert r.status_code == 400

    def test_chat_missing_message_returns_400(self, client):
        r = client.post("/api/chat", json={"session_id": "test"})
        assert r.status_code == 400

    def test_chat_history_returns_messages(self, client):
        r = client.get("/api/chat/history?session_id=test_history")
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == "test_history"
        assert "messages" in data

    def test_chat_history_clear(self, client):
        r = client.delete("/api/chat/history?session_id=test_clear")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestChatIntegration:
    """Test end-to-end chat with mocked AI gateway."""

    @pytest.fixture
    def client(self):
        return TestClient(app, base_url="http://127.0.0.1:8520")

    @patch("marketmind.gateway.async_client.chat_pro", new_callable=AsyncMock)
    def test_chat_returns_ai_response(self, mock_chat_pro, client):
        mock_chat_pro.return_value = {"content": "这是 AI 的回复。"}
        r = client.post("/api/chat", json={
            "message": "今天市场怎么样？",
            "session_id": "test_ai",
        })
        assert r.status_code == 200
        data = r.json()
        assert "response" in data
        assert data["session_id"] == "test_ai"
        assert "AI 的回复" in data["response"]

    @patch("marketmind.gateway.async_client.chat_pro", new_callable=AsyncMock)
    def test_chat_adds_to_history(self, mock_chat_pro, client):
        mock_chat_pro.return_value = {"content": "回复1"}
        client.post("/api/chat", json={
            "message": "msg1", "session_id": "test_history2",
        })
        r = client.get("/api/chat/history?session_id=test_history2")
        data = r.json()
        # Should have user message + assistant response
        assert len(data["messages"]) >= 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "msg1"
        assert data["messages"][1]["role"] == "assistant"
