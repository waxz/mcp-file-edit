import asyncio
from fastmcp import Client

client = Client("http://localhost:8000/mcp")

async def call_tool(name: str):
    async with client:
        result = await client.call_tool("greet", {"name": name})
        print(result)
        result = await client.call_tool("bye", {"name": name})
        print(result)
        result = await client.call_tool("read_file", {"path": "./README.md"})
        print(result)
        # result = await client.call_tool("read_file", {"path": "../README.md"})
        # print(result)
        result = await client.call_tool("set_project_directory", {"path": "."})

        result = await client.call_tool("git_status", {"path": "."})

        # result = await client.call_tool("set_project_directory", {"path": "/workspaces/mcp-file-edit/src"})
        
        result = await client.call_tool("list_files", {"path": "."})
        result = await client.call_tool("git_add", {"files": ["./README.md"]})

        result = await client.call_tool("git_commit", {"message": "commit by mcp"})

        print(result)

        # result = await client.call_tool("git_status", {"path": "/workspaces/mcp-file-edit"})
        # print(result)
        
asyncio.run(call_tool("Ford"))