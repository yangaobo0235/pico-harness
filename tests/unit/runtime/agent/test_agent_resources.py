"""Agent shutdown must release native skill watchers, including on failure."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pico.integrations.llm.contracts import LLMProvider
from pico.runtime.agent import AgentLoop


@pytest.mark.parametrize("mcp_failure", [False, True])
async def test_close_stops_owned_skill_watcher(tmp_path, monkeypatch, mcp_failure):
    (tmp_path / "skills").mkdir()
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "fake/model"
    agent = AgentLoop(provider=provider, workspace=tmp_path)
    watcher = agent.context.skills._file_watcher
    assert watcher is not None
    thread = watcher._thread
    assert thread is not None and thread.is_alive()
    if mcp_failure:
        monkeypatch.setattr(agent, "close_mcp", AsyncMock(side_effect=RuntimeError("MCP close failed")))
    try:
        if mcp_failure:
            with pytest.raises(RuntimeError, match="MCP close failed"):
                await agent.close()
        else:
            await agent.close()
            await agent.close()
        assert not thread.is_alive()
        assert agent.context.skills._file_watcher is None
    finally:
        watcher.stop()
