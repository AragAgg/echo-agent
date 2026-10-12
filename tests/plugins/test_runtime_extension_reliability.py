import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from echo_agent.agent.loop import AgentLoop
from echo_agent.agent.tools.registry import ToolRegistry
from echo_agent.bus.events import InboundEvent
from echo_agent.bus.queue import MessageBus
from echo_agent.channels.base import SendResult
from echo_agent.config.schema import Config, MCPServerConfig
from echo_agent.mcp.manager import MCPManager
from echo_agent.plugins.hooks import HookRegistry
from echo_agent.plugins.runtime import RuntimeExtension, RuntimeExtensionError
from echo_agent.security.tool_policy import is_tool_allowed
from echo_agent.models.provider import LLMProvider, LLMResponse, ToolCallRequest
from echo_agent.tools import Tool, ToolResult


class ReplyProvider(LLMProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        self.calls += 1
        return LLMResponse(content="完成", finish_reason="stop")

    async def chat_stream(self, messages, tools=None, **kwargs):
        return await self.chat(messages, tools, **kwargs)

    def get_default_model(self):
        return "stub"


def make_loop(tmp_path, extension, *, streaming=False):
    config = Config(workspace=str(tmp_path), memory={"enabled": False}, observability={"otel_enabled": False})
    config.channels.stream_channels = ["test"] if streaming else []
    bus, provider = MessageBus(), ReplyProvider()
    loop = AgentLoop(bus=bus, config=config, provider=provider, workspace=tmp_path)
    loop.set_plugin_manager(SimpleNamespace(runtime_extension=extension, hooks=HookRegistry(), shutdown=AsyncMock()))
    loop._running = True
    return loop, bus, provider


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_every_final_delivery_notifies_the_extension_once(tmp_path, streaming):
    class Receipts(RuntimeExtension):
        def __init__(self):
            self.results = []
        async def record_delivery(self, event, result):
            self.results.append(result)
    extension = Receipts()
    loop, bus, _ = make_loop(tmp_path, extension, streaming=streaming)
    sent = []
    async def receive(event):
        sent.append(event)
        return SendResult(success=True, message_id="receipt")
    bus.subscribe_outbound("test", receive)
    await loop._on_inbound(InboundEvent.text_message("test", "u", "u", "hello"))
    assert len(extension.results) == 1 and extension.results[0].ok
    assert sum(event.is_final for event in sent) == 1


@pytest.mark.asyncio
async def test_binding_failure_blocks_later_native_and_model_paths(tmp_path):
    class BrokenBinding(RuntimeExtension):
        def bind_mcp_manager(self, manager):
            raise RuntimeError("cannot bind policy")
    loop, _, provider = make_loop(tmp_path, BrokenBinding())
    loop.config.execution.network_policy = "allow"
    loop.config.tools.mcp_servers = {"catalog": MCPServerConfig(url="http://127.0.0.1:1/mcp")}
    with pytest.raises(RuntimeExtensionError):
        await loop._start_mcp_background()
    with pytest.raises(RuntimeExtensionError):
        await loop._process_event(InboundEvent.text_message("test", "u", "u", "execute"), "trace")
    assert provider.calls == 0


async def connected_manager(tmp_path, extension, registry):
    manager = MCPManager(tmp_path, extension=extension)
    client = MagicMock(is_connected=True)
    client.list_tools = AsyncMock(return_value=[{"name": "first"}, {"name": "second"}])
    client.disconnect = AsyncMock()
    manager._clients["catalog"] = client
    manager._configs["catalog"] = MCPServerConfig(url="http://project/mcp")
    await manager.discover_tools(registry)
    return manager


@pytest.mark.asyncio
async def test_invalid_adapter_directory_leaves_no_partial_or_untracked_tools(tmp_path):
    class Policy(RuntimeExtension):
        broken = False
        def build_mcp_adapter(self, **kwargs):
            adapter = super().build_mcp_adapter(**kwargs)
            if self.broken and kwargs["mcp_tool"]["name"] == "second":
                adapter.name = "existing"
            return adapter
    class Existing(Tool):
        name = "existing"
        parameters = {"type": "object", "properties": {}}
        async def execute(self, params, ctx=None):
            return ToolResult(output="ok")
    policy, registry = Policy(), ToolRegistry()
    existing = Existing()
    registry.register(existing)
    manager = await connected_manager(tmp_path, policy, registry)
    policy.broken = True
    with pytest.raises(RuntimeExtensionError):
        await manager.refresh_tools("catalog")
    assert registry.get("existing") is existing
    assert not any(name.startswith("mcp_catalog_") for name in registry.tool_names)
    with pytest.raises(RuntimeExtensionError):
        manager.get_client("catalog")
    policy.broken = False
    assert await manager.refresh_tools("catalog")
    assert manager.get_client("catalog") is not None
    assert registry.has("mcp_catalog_first") and registry.has("mcp_catalog_second")
    await manager.stop_all()
    assert registry.tool_names == ["existing"]


@pytest.mark.asyncio
async def test_policy_failure_during_inference_prevents_a_later_write(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []
    class Policy(RuntimeExtension):
        allowed_tool_patterns = ("native_write", "mcp_catalog_*")
        broken = False
        def build_mcp_adapter(self, **kwargs):
            if self.broken:
                raise RuntimeError("policy rejected")
            return super().build_mcp_adapter(**kwargs)
    class Write(Tool):
        name = "native_write"
        parameters = {"type": "object", "properties": {}}
        async def execute(self, params, ctx=None):
            writes.append("unsafe")
            return ToolResult(output="done")
    class Delayed(ReplyProvider):
        async def chat(self, messages, tools=None, **kwargs):
            entered.set()
            await release.wait()
            return LLMResponse(tool_calls=[ToolCallRequest(id="write", name="native_write", arguments={})], finish_reason="tool_calls")
    policy = Policy()
    loop, _, _ = make_loop(tmp_path, policy)
    loop._inference_stage._provider = Delayed()
    loop.tools.register(Write())
    manager = await connected_manager(tmp_path, policy, loop.tools)
    loop.mcp_manager = manager
    processing = asyncio.create_task(loop._process_event(InboundEvent.text_message("test", "u", "u", "write"), "trace"))
    await asyncio.wait_for(entered.wait(), 5)
    policy.broken = True
    with pytest.raises(RuntimeExtensionError):
        await manager.refresh_tools("catalog")
    release.set()
    with pytest.raises(RuntimeExtensionError):
        await asyncio.wait_for(processing, 5)
    assert writes == []


def test_runtime_allowlist_cannot_disable_operator_security_controls():
    config = Config(security={"profile": "public_gateway"}, execution={"network_policy": "deny"})
    extension = RuntimeExtension()
    extension.allowed_tool_patterns = ("*",)
    config._runtime_extension = extension
    assert not is_tool_allowed(config, "exec")
    assert not is_tool_allowed(config, "web_fetch")
    config.tools.deny = ["read_file"]
    assert not is_tool_allowed(config, "read_file")
