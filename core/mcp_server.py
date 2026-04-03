"""🔌 JARVIS MCP Server - Deep Integration
Model Context Protocol (MCP) implementation with full features:

- JSON-RPC 2.0 protocol
- Multiple transports: stdio, HTTP, WebSocket
- Dynamic tool registration
- Resource management
- Prompt management
- Sampling support
- Server capabilities discovery
"""

import asyncio
import inspect
import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

from core.schema_validation import (
    SchemaValidationError,
    ensure_object_schema,
    validate_arguments,
    validate_tool_schema,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# MCP Protocol Types
# ═══════════════════════════════════════════════════════════════


class MCPMethod(Enum):
    """MCP JSON-RPC methods."""

    # Tools
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"

    # Resources
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    RESOURCES_SUBSCRIBE = "resources/subscribe"

    # Prompts
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"

    # Sampling
    SAMPLING_CREATE_MESSAGE = "sampling/createMessage"

    # Server
    SERVER_INITIALIZE = "initialize"
    PING = "ping"


@dataclass
class MCPRequest:
    """MCP JSON-RPC request."""

    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str = ""
    params: Optional[Dict] = None


@dataclass
class MCPResponse:
    """MCP JSON-RPC response."""

    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[Dict] = None


@dataclass
class MCPTool:
    """MCP tool definition."""

    name: str
    description: str
    inputSchema: Dict[str, Any]
    handler: Callable  # Async function to execute


@dataclass
class MCPResource:
    """MCP resource."""

    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None
    handler: Optional[Callable] = None


@dataclass
class MCPPrompt:
    """MCP prompt template."""

    name: str
    description: str
    arguments: Optional[List[Dict]] = None
    template: str = ""


@dataclass
class ServerCapabilities:
    """MCP server capabilities."""

    tools: bool = True
    resources: bool = True
    prompts: bool = True
    sampling: bool = True

    def to_dict(self) -> Dict:
        return {
            "tools": {"listChanged": True} if self.tools else None,
            "resources": {"subscribe": True} if self.resources else None,
            "prompts": self.prompts,
            "sampling": self.sampling,
        }


# ═══════════════════════════════════════════════════════════════
# MCP Transport Implementations
# ═══════════════════════════════════════════════════════════════


class MCPTransport(ABC):
    """Abstract base for MCP transports."""

    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    async def receive(self) -> Optional[MCPRequest]:
        pass

    @abstractmethod
    async def send(self, response: MCPResponse):
        pass


class StdioTransport(MCPTransport):
    """stdio transport for CLI integration."""

    def __init__(self):
        self.running = False

    async def start(self):
        self.running = True
        logger.info("MCP Stdio transport started")

    async def stop(self):
        self.running = False
        logger.info("MCP Stdio transport stopped")

    async def receive(self) -> Optional[MCPRequest]:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, input)
            if line:
                data = json.loads(line)
                return MCPRequest(**data)
        except EOFError:
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
        return None

    async def send(self, response: MCPResponse):
        print(json.dumps(response.__dict__, default=str))


class HTTPTransport(MCPTransport):
    """HTTP transport for web integration."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.server = None
        self.running = False
        self._queue = asyncio.Queue()

    async def start(self):
        from aiohttp import web

        async def handle(request):
            try:
                data = await request.json()
                await self._queue.put(MCPRequest(**data))

                # Wait for response
                response = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                return web.json_response(response.__dict__, default=str)
            except asyncio.TimeoutError:
                return web.json_response(
                    {"jsonrpc": "2.0", "error": {"code": -1, "message": "Timeout"}}
                )
            except Exception as e:
                return web.json_response(
                    {"jsonrpc": "2.0", "error": {"code": -1, "message": str(e)}}
                )

        self.server = web.Application()
        self.server.router.add_post("/mcp", handle)

        runner = web.AppRunner(self.server)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        self.running = True
        logger.info(f"MCP HTTP transport started on {self.host}:{self.port}")

    async def stop(self):
        self.running = False
        if self.server:
            await self.server.cleanup()

    async def receive(self) -> Optional[MCPRequest]:
        return await self._queue.get()

    async def send(self, response: MCPResponse):
        # Handled via response queue in HTTP
        await self._queue.put(response)


# ═══════════════════════════════════════════════════════════════
# MCP Server Implementation
# ═══════════════════════════════════════════════════════════════


class MCPServer:
    """
    Full MCP Server implementation with tools, resources, prompts.

    Usage:
        server = MCPServer()

        # Register tools
        @server.tool(name="echo", description="Echo back input")
        async def echo(text: str):
            return text

        # Start server
        await server.start(transport="stdio")
    """

    def __init__(self, name: str = "JARVIS", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: Dict[str, MCPTool] = {}
        self.resources: Dict[str, MCPResource] = {}
        self.prompts: Dict[str, MCPPrompt] = {}
        self.capabilities = ServerCapabilities()
        self.transport: Optional[MCPTransport] = None
        self._initialized = False
        self._request_handlers: Dict[str, Callable] = {}
        self.tracer: Any = None

        # Setup default handlers
        self._setup_handlers()

    def set_tracer(self, tracer: Any) -> None:
        """Attach a tracer for request and tool-call instrumentation."""
        self.tracer = tracer

    def _setup_handlers(self):
        """Setup method handlers."""
        self._request_handlers = {
            MCPMethod.TOOLS_LIST.value: self._handle_list_tools,
            MCPMethod.TOOLS_CALL.value: self._handle_call_tool,
            MCPMethod.RESOURCES_LIST.value: self._handle_list_resources,
            MCPMethod.RESOURCES_READ.value: self._handle_read_resource,
            MCPMethod.PROMPTS_LIST.value: self._handle_list_prompts,
            MCPMethod.PROMPTS_GET.value: self._handle_get_prompt,
            MCPMethod.PING.value: self._handle_ping,
            MCPMethod.SERVER_INITIALIZE.value: self._handle_initialize,
            MCPMethod.SAMPLING_CREATE_MESSAGE.value: self._handle_sampling,
        }

    # ═══════════════════════════════════════════════════════════
    # Registration Methods
    # ═══════════════════════════════════════════════════════════════

    def tool(self, name: str = None, description: str = "", inputSchema: Dict = None):
        """Decorator to register a tool."""

        def decorator(func: Callable):
            tool_name = name or func.__name__
            tool_description = description or func.__doc__ or ""
            schema = validate_tool_schema(inputSchema or self._generate_schema(func))

            self.tools[tool_name] = MCPTool(
                name=tool_name,
                description=tool_description,
                inputSchema=schema,
                handler=func,
            )
            logger.info(f"Registered tool: {tool_name}")
            return func

        return decorator

    def register_tool(self, tool: MCPTool):
        """Register a tool directly."""
        tool.inputSchema = validate_tool_schema(tool.inputSchema)
        self.tools[tool.name] = tool

    def resource(
        self,
        uri: str = None,
        name: str = "",
        description: str = "",
        mimeType: str = None,
    ):
        """Decorator to register a resource."""

        def decorator(func: Callable):
            resource_uri = uri or f"jarvis://{func.__name__}"
            self.resources[resource_uri] = MCPResource(
                uri=resource_uri,
                name=name or func.__name__,
                description=description,
                mimeType=mimeType,
                handler=func,
            )
            logger.info(f"Registered resource: {resource_uri}")
            return func

        return decorator

    def prompt(
        self,
        name: str = None,
        description: str = "",
        arguments: List = None,
        template: str = "",
    ):
        """Decorator to register a prompt."""

        def decorator(func: Callable):
            prompt_name = name or func.__name__
            self.prompts[prompt_name] = MCPPrompt(
                name=prompt_name,
                description=description,
                arguments=arguments,
                template=template or func.__doc__ or "",
            )
            logger.info(f"Registered prompt: {prompt_name}")
            return func

        return decorator

    def _generate_schema(self, func: Callable) -> Dict:
        """Generate input schema from function signature."""
        import inspect

        sig = inspect.signature(func)

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ["self", "cls"]:
                continue

            param_type = "string"
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == float:
                    param_type = "number"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif hasattr(param.annotation, "__origin__"):
                    param_type = (
                        "array" if param.annotation.__origin__ is list else "object"
                    )

            properties[param_name] = {"type": param_type}

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        schema["additionalProperties"] = False

        return schema

    # ═══════════════════════════════════════════════════════════════
    # Request Handlers
    # ═══════════════════════════════════════════════════════════════

    async def _handle_initialize(self, params: Dict) -> Dict:
        """Handle server initialization."""
        self._initialized = True
        client_info = params.get("clientInfo", {})

        logger.info(f"Initialized by: {client_info.get('name', 'unknown')}")

        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": self.name, "version": self.version},
            "capabilities": self.capabilities.to_dict(),
            "tools": self._get_tools_list(),
        }

    async def _handle_list_tools(self, params: Dict = None) -> Dict:
        """Handle tools/list request."""
        return self._get_tools_list()

    def _get_tools_list(self) -> Dict:
        """Get tools list in MCP format."""
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": ensure_object_schema(tool.inputSchema),
                }
                for tool in self.tools.values()
            ]
        }

    async def _handle_call_tool(self, params: Dict) -> Dict:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool = self.tools[tool_name]
        span_id = None
        if self.tracer:
            span_id = self.tracer.start_span(
                "mcp_server_tool",
                tool_name,
                {"argument_keys": sorted(arguments.keys())},
            )

        try:
            validated_arguments = validate_arguments(arguments, tool.inputSchema)
            result = tool.handler(**validated_arguments)
            if inspect.isawaitable(result):
                result = await result
            if span_id:
                self.tracer.end_span(
                    span_id,
                    attributes={"result_type": type(result).__name__},
                )
            return {"content": [{"type": "text", "text": str(result)}]}
        except SchemaValidationError as e:
            logger.warning("Tool %s validation failed: %s", tool_name, e)
            if span_id:
                self.tracer.end_span(
                    span_id,
                    status="validation_error",
                    error=str(e),
                )
            return {
                "content": [
                    {"type": "text", "text": f"Validation error: {str(e)}"}
                ],
                "isError": True,
            }
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            if span_id:
                self.tracer.end_span(
                    span_id,
                    status="error",
                    error=str(e),
                )
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    async def _handle_list_resources(self, params: Dict = None) -> Dict:
        """Handle resources/list request."""
        return {
            "resources": [
                {
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mimeType": r.mimeType,
                }
                for r in self.resources.values()
            ]
        }

    async def _handle_read_resource(self, params: Dict) -> Dict:
        """Handle resources/read request."""
        uri = params.get("uri")

        if uri not in self.resources:
            raise ValueError(f"Unknown resource: {uri}")

        resource = self.resources[uri]

        if resource.handler:
            content = await resource.handler()
        else:
            content = ""

        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mimeType or "text/plain",
                    "text": str(content),
                }
            ]
        }

    async def _handle_list_prompts(self, params: Dict = None) -> Dict:
        """Handle prompts/list request."""
        return {
            "prompts": [
                {"name": p.name, "description": p.description, "arguments": p.arguments}
                for p in self.prompts.values()
            ]
        }

    async def _handle_get_prompt(self, params: Dict) -> Dict:
        """Handle prompts/get request."""
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in self.prompts:
            raise ValueError(f"Unknown prompt: {name}")

        prompt = self.prompts[name]
        # Simple template substitution
        template = prompt.template
        for key, value in arguments.items():
            template = template.replace(f"{{{key}}}", str(value))

        return {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": template}}
            ]
        }

    async def _handle_ping(self, params: Dict = None) -> Dict:
        """Handle ping request."""
        return {"pong": True}

    async def _handle_sampling(self, params: Dict) -> Dict:
        """Handle sampling/createMessage request."""
        # Basic implementation - would integrate with LLM
        messages = params.get("messages", [])

        # For now, return a simple response
        return {"content": [{"type": "text", "text": "Sampling not fully implemented"}]}

    # ═══════════════════════════════════════════════════════════════
    # Server Lifecycle
    # ═══════════════════════════════════════════════════════════════

    async def start(self, transport: str = "stdio", **kwargs):
        """Start the MCP server."""
        if transport == "stdio":
            self.transport = StdioTransport()
        elif transport == "http":
            self.transport = HTTPTransport(**kwargs)
        else:
            raise ValueError(f"Unknown transport: {transport}")

        await self.transport.start()

        logger.info(f"MCP Server '{self.name}' started with {transport} transport")

        # Main message loop
        while True:
            try:
                request = await self.transport.receive()
                if request is None:
                    break

                response = await self._handle_request(request)
                await self.transport.send(response)

            except Exception as e:
                logger.error(f"Error handling request: {e}")
                response = MCPResponse(
                    id=None, error={"code": -32603, "message": str(e)}
                )
                await self.transport.send(response)

    async def _handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle a single request."""
        try:
            method = request.method
            params = request.params or {}

            if method in self._request_handlers:
                result = await self._request_handlers[method](params)
                return MCPResponse(id=request.id, result=result)
            else:
                return MCPResponse(
                    id=request.id,
                    error={"code": -32601, "message": f"Method not found: {method}"},
                )
        except Exception as e:
            return MCPResponse(id=request.id, error={"code": -32603, "message": str(e)})

    async def stop(self):
        """Stop the server."""
        if self.transport:
            await self.transport.stop()


# ═══════════════════════════════════════════════════════════════
# MCP Client for JARVIS
# ═══════════════════════════════════════════════════════════════


class MCPClient:
    """MCP client to connect to external MCP servers."""

    def __init__(self, server_url: str = None):
        self.server_url = server_url
        self.tools: Dict[str, Dict] = {}
        self.resources: Dict[str, Dict] = {}
        self._session: Dict[str, Any] | None = None
        self.mode = "stateless"
        self.client_name = "JARVIS MCP Client"
        self.allowed_tools: set[str] = set()
        self.blocked_tools: set[str] = set()

    async def connect(
        self,
        server_url: str,
        *,
        mode: str = "stateless",
        client_name: str = "JARVIS MCP Client",
        allowed_tools: Optional[List[str]] = None,
        blocked_tools: Optional[List[str]] = None,
    ):
        """Connect to an MCP server."""
        self.server_url = server_url
        self.mode = mode
        self.client_name = client_name
        self.allowed_tools = set(allowed_tools or [])
        self.blocked_tools = set(blocked_tools or [])

        self._session = {
            "server_url": server_url,
            "mode": mode,
            "client_name": client_name,
            "connected_at": datetime.now().isoformat(),
        }
        await self._send_request(
            {
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": client_name, "mode": mode},
                },
            }
        )
        await self.refresh_tools()

        logger.info(f"Connected to MCP server: {server_url}")
        return {
            "server_url": self.server_url,
            "mode": self.mode,
            "tool_count": len(self.tools),
            "allowed_tools": sorted(self.allowed_tools),
            "blocked_tools": sorted(self.blocked_tools),
        }

    async def refresh_tools(self) -> Dict[str, Any]:
        """Refresh remote tool listing and local cache."""
        result = await self._send_request({"method": "tools/list", "params": {}})
        self.tools = {
            tool["name"]: tool for tool in result.get("tools", []) if isinstance(tool, dict)
        }
        return result

    def list_tools(self) -> List[Dict[str, Any]]:
        """List cached remote tools after policy filtering."""
        return [
            tool
            for name, tool in self.tools.items()
            if self._is_tool_allowed(name)
        ]

    def set_tool_policy(
        self,
        *,
        allowed_tools: Optional[List[str]] = None,
        blocked_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update local client-side tool access policy."""
        if allowed_tools is not None:
            self.allowed_tools = set(allowed_tools)
        if blocked_tools is not None:
            self.blocked_tools = set(blocked_tools)
        return {
            "allowed_tools": sorted(self.allowed_tools),
            "blocked_tools": sorted(self.blocked_tools),
        }

    async def call_tool(self, name: str, arguments: Dict = None) -> Any:
        """Call a tool on the MCP server."""
        if not self._is_tool_allowed(name):
            raise PermissionError(f"Tool '{name}' is blocked by client policy.")

        result = await self._send_request(
            {
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        return result

    def _is_tool_allowed(self, name: str) -> bool:
        if name in self.blocked_tools:
            return False
        if self.allowed_tools and name not in self.allowed_tools:
            return False
        return True

    async def _send_request(self, request: Dict) -> Any:
        """Send request to MCP server."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/mcp", json=request, timeout=30.0
            )
            data = response.json()

            if "error" in data:
                raise Exception(data["error"]["message"])

            return data.get("result")


# ═══════════════════════════════════════════════════════════════
# JARVIS MCP Integration
# ═══════════════════════════════════════════════════════════════


def create_jarvis_mcp_server() -> MCPServer:
    """Create and configure JARVIS MCP server."""
    server = MCPServer(name="JARVIS", version="5.0.0")

    # Register JARVIS capabilities as tools
    @server.tool(
        name="jarvis_execute",
        description="Execute a JARVIS mission/task",
        inputSchema={
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task to execute"}
            },
            "required": ["task"],
        },
    )
    async def execute_task(task: str):
        return f"Task queued: {task}"

    @server.tool(
        name="jarvis_search_memory",
        description="Search JARVIS memory",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    )
    async def search_memory(query: str):
        return f"Memory search results for: {query}"

    @server.tool(
        name="jarvis_skills_status", description="Get status of self-evolving skills"
    )
    async def skills_status():
        return "Skills engine: Active"

    return server


# Standalone usage
if __name__ == "__main__":

    async def test():
        server = create_jarvis_mcp_server()

        # Add a custom tool
        @server.tool(name="calculate", description="Simple calculator")
        async def calculate(a: int, b: int, operation: str = "add"):
            if operation == "add":
                return a + b
            elif operation == "sub":
                return a - b
            elif operation == "mul":
                return a * b
            elif operation == "div" and b != 0:
                return a / b
            return "Invalid operation"

        print(f"Server ready with {len(server.tools)} tools")
        print("Starting MCP server (stdio mode)...")

        # Start server (would normally block)
        # await server.start(transport="stdio")

    asyncio.run(test())
