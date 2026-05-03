import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.runner import AgentResult, AgentRunner


@pytest.fixture
def runner():
    return AgentRunner(timeout_seconds=5)


async def test_run_returns_result_on_success(runner):
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"agent thinking...\n", b""))
    fake_proc.returncode = 0

    with patch("agent.runner.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        result = await runner.run("test prompt")
    assert isinstance(result, AgentResult)
    assert result.exit_code == 0
    assert "agent thinking" in result.stdout
    assert result.stderr == ""


async def test_run_records_nonzero_exit_code(runner):
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b"oops"))
    fake_proc.returncode = 1
    with patch("agent.runner.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        result = await runner.run("test prompt")
    assert result.exit_code == 1
    assert result.stderr == "oops"


async def test_run_kills_on_timeout():
    runner = AgentRunner(timeout_seconds=0.1)

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(10)
        return (b"", b"")

    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(side_effect=hang)
    fake_proc.kill = MagicMock()
    fake_proc.returncode = None

    with patch("agent.runner.asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)):
        result = await runner.run("test prompt")
    assert result.timed_out is True
    fake_proc.kill.assert_called_once()


async def test_run_passes_prompt_via_stdin():
    runner = AgentRunner(timeout_seconds=5)
    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    fake_proc.returncode = 0
    create = AsyncMock(return_value=fake_proc)
    with patch("agent.runner.asyncio.create_subprocess_exec", create):
        await runner.run("hello prompt")
    create.assert_called_once()
    args, _kwargs = create.call_args
    assert args[0] == "claude"
    assert "--print" in args
    fake_proc.communicate.assert_awaited_once_with(input=b"hello prompt")
