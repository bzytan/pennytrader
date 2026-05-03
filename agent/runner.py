import asyncio
from dataclasses import dataclass
from time import monotonic


@dataclass
class AgentResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool


class AgentRunner:
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout = timeout_seconds

    async def run(self, prompt: str) -> AgentResult:
        start = monotonic()
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=self._timeout,
            )
            return AgentResult(
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                duration_seconds=monotonic() - start,
                timed_out=False,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return AgentResult(
                exit_code=-1, stdout="", stderr="agent invocation timed out",
                duration_seconds=monotonic() - start, timed_out=True,
            )
