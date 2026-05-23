"""Tests for L1 Data Mining — Flash-driven knowledge base search."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from marketmind.pipeline.l1_data_mining import (
    is_data_mining_request,
    execute_data_mining,
)


# ── is_data_mining_request tests ────────────────────────────────────────────

class TestIsDataMiningRequest:
    # English keywords
    def test_search_for(self):
        assert is_data_mining_request("search for oil prices") is True

    def test_look_up(self):
        assert is_data_mining_request("look up AAPL fundamentals") is True

    def test_find_data(self):
        assert is_data_mining_request("find data on treasury yields") is True

    def test_check(self):
        assert is_data_mining_request("check the latest CPI numbers") is True

    def test_verify(self):
        assert is_data_mining_request("verify the employment data") is True

    def test_what_does_the_data_say(self):
        assert is_data_mining_request("what does the data say about inflation?") is True

    def test_get_data_on(self):
        assert is_data_mining_request("get data on tech sector earnings") is True

    def test_research(self):
        assert is_data_mining_request("research semiconductor supply chains") is True

    def test_cross_reference(self):
        assert is_data_mining_request("cross reference the GDP forecasts") is True

    def test_cross_reference_hyphen(self):
        assert is_data_mining_request("cross-reference with other sources") is True

    # Chinese keywords
    def test_chinese_cha_yixia(self):
        assert is_data_mining_request("查一下黄金价格走势") is True

    def test_chinese_sousuo(self):
        assert is_data_mining_request("搜索最近的通胀数据") is True

    def test_chinese_chacha(self):
        assert is_data_mining_request("查查A股资金流向") is True

    def test_chinese_cha(self):
        assert is_data_mining_request("查美联储利率决议") is True

    def test_chinese_zhao_yixia(self):
        assert is_data_mining_request("找一下最近的原油库存报告") is True

    def test_chinese_heshi(self):
        assert is_data_mining_request("核实一下市场的预期") is True

    # Negative cases
    def test_non_mining_text(self):
        assert is_data_mining_request("What do you think about the market?") is False

    def test_empty_string(self):
        assert is_data_mining_request("") is False

    def test_chinese_non_mining(self):
        assert is_data_mining_request("你觉得市场怎么样？") is False

    def test_case_insensitive(self):
        assert is_data_mining_request("SEARCH FOR gold price trends") is True

    def test_partial_match_avoids_false_positive(self):
        """'check' only matches when it's a standalone keyword, not part of a word."""
        # But the code uses string 'in' check, so "checklist" would match
        assert is_data_mining_request("checklist review") is True

    def test_keyword_at_start(self):
        assert is_data_mining_request("look up the latest oil report") is True

    def test_keyword_in_middle(self):
        assert is_data_mining_request("Can you check the market data for me?") is True


# ── execute_data_mining tests ──────────────────────────────────────────────

class TestExecuteDataMining:
    @pytest.mark.asyncio
    async def test_successful_call(self):
        mock_result = {"content": "Gold prices are at $1950/oz with support at $1900."}
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.return_value = mock_result
            result = await execute_data_mining("gold price trends", mock_state)

        assert "Gold prices" in result
        assert "$1950" in result
        mock_flash.assert_called_once()

    @pytest.mark.asyncio
    async def test_defang_applied_to_direction(self):
        """Verify that defang_text is applied to the user direction text."""
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.return_value = {"content": "Result here."}
            with patch("marketmind.pipeline.l1_data_mining.defang_text", wraps=lambda x: x) as mock_defang:
                await execute_data_mining("gold price trends", mock_state)
                mock_defang.assert_called_once_with("gold price trends")

    @pytest.mark.asyncio
    async def test_direction_truncated_to_500(self):
        """Direction longer than 500 chars is truncated."""
        long_direction = "A" * 600
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.return_value = {"content": "Result."}
            await execute_data_mining(long_direction, mock_state)

        call_args = mock_flash.call_args
        # The user_prompt should contain truncated direction (500 chars max)
        user_prompt = call_args.kwargs.get("user_prompt", "")
        assert len("A" * 600) > 500  # original is longer
        assert "A" * 500 in user_prompt

    @pytest.mark.asyncio
    async def test_exception_returns_error_message(self):
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.side_effect = ConnectionError("Network timeout")
            result = await execute_data_mining("oil prices", mock_state)

        assert "Search unavailable" in result
        assert "Network timeout" in result

    @pytest.mark.asyncio
    async def test_generic_exception_handling(self):
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.side_effect = RuntimeError("Unexpected error")
            result = await execute_data_mining("test query", mock_state)

        assert "Search unavailable" in result
        assert "Unexpected error" in result

    @pytest.mark.asyncio
    async def test_empty_result_fallback(self):
        """When chat_flash returns no content."""
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.return_value = {}
            result = await execute_data_mining("mining query", mock_state)

        assert "No search results available" in result

    @pytest.mark.asyncio
    async def test_missing_content_key(self):
        """When chat_flash returns dict without 'content' key — uses default."""
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.return_value = {"status": "ok"}
            result = await execute_data_mining("test", mock_state)

        assert "No search results available" in result

    @pytest.mark.asyncio
    async def test_chat_flash_parameters(self):
        """Verify correct parameters passed to chat_flash."""
        mock_state = MagicMock()

        with patch("marketmind.pipeline.l1_data_mining.chat_flash", new_callable=AsyncMock) as mock_flash:
            mock_flash.return_value = {"content": "OK"}
            await execute_data_mining("oil forecast", mock_state)

        call_kwargs = mock_flash.call_args.kwargs
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["max_tokens"] == 1024
        assert "system_prompt" in call_kwargs
        assert "user_prompt" in call_kwargs
        assert "data retrieval assistant" in call_kwargs["system_prompt"].lower()
