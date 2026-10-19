# UTCPToolBox

`UTCPToolBox` (`ovos_tool_adapters/utcp.py`)

`UTCPToolBox` connects UTCP (Universal Tool Calling Protocol) tools to the OVOS agentic loop. A UTCP server publishes a manual: a JSON document that lists its tools and tells the client how to call each one. The toolbox reads the manuals you name, and the agent then calls the tools directly over HTTP. No proxy runs between them.

The toolbox uses the UTCP 1.x client. The `utcp` extra installs `utcp` and `utcp-http`:

```bash
pip install "ovos-tool-adapters[utcp]"
```

## Config reference

| Key | Type | Default | Description |
|---|---|---|---|
| `utcp_config` | dict | `{}` | **Required.** Passed to `UtcpClientConfig(**utcp_config)`. Put one entry per manual in `manual_call_templates`. |
| `timeout` | int | `30` | Seconds to wait per tool call or connection attempt |

Each entry in `manual_call_templates` is a UTCP call template that fetches a manual:

| Key | Value |
|---|---|
| `name` | A name for the manual. The client puts it in front of each tool name, for example `ovos_translate.translate`. |
| `call_template_type` | `"http"` for a manual served over HTTP |
| `url` | The full URL of the manual, for example `http://localhost:9686/utcp` |
| `http_method` | `"GET"` |

The UTCP client supports other call template types, such as `cli`, `sse`, `websocket` and `mcp`. Each one needs its own plugin package, for example `utcp-cli`. If the plugin is not installed, the toolbox skips that template and logs an ERROR with `Invalid call template type`. When the type is `http` and `utcp-http` is missing, the ERROR tells you to install it.

## Persona config examples

### An OVOS server

The OVOS TTS, STT and translate servers serve a UTCP manual at `GET /utcp`. This persona config loads the tools of a local [ovos-translate-server](https://github.com/OpenVoiceOS/ovos-translate-server):

```json
{
  "toolboxes": ["ovos-utcp-toolbox"],
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "manual_call_templates": [
        {
          "name": "ovos_translate",
          "call_template_type": "http",
          "url": "http://localhost:9686/utcp",
          "http_method": "GET"
        }
      ]
    },
    "timeout": 30
  }
}
```

The toolbox then has these tools:

```
ovos_translate.classify_language
ovos_translate.detect_language
ovos_translate.supported_languages
ovos_translate.translate
ovos_translate.translate_with_source
```

A call to `ovos_translate.translate_with_source` with `{"src_lang": "en", "tgt_lang": "pt", "utterance": "good morning"}` returns the translated text in `content`.

### Several servers

```json
{
  "ovos-utcp-toolbox": {
    "utcp_config": {
      "manual_call_templates": [
        {
          "name": "ovos_translate",
          "call_template_type": "http",
          "url": "http://localhost:9686/utcp",
          "http_method": "GET"
        },
        {
          "name": "ovos_tts",
          "call_template_type": "http",
          "url": "http://localhost:9666/utcp",
          "http_method": "GET"
        }
      ]
    }
  }
}
```

## Errors in the config

The toolbox checks `utcp_config` before it connects. If the check fails, the toolbox logs one ERROR and loads no tools:

| Config | Error |
|---|---|
| A `tool_providers` or `providers` key | `'utcp_config.tool_providers' is not a UTCP 1.x key; list each manual in 'manual_call_templates' instead` |
| A template without `call_template_type`, or an `http` template without `url` | `manual_call_templates[1] ('tx') is missing the required key 'url'` |
| `manual_call_templates` is not a list, or an entry is not an object | The error names the wrong type |

To convert a `tool_providers` or `providers` entry, rename `provider_type` to `call_template_type`, keep `name` and `url`, and add `"http_method": "GET"`.

Two more failures affect one manual only. The toolbox logs an ERROR that names the manual and the reason, and the other manuals still load:

| Failure | Example ERROR |
|---|---|
| The UTCP client rejects the template, for example an uninstalled plugin type or a wrong field value | `manual_call_templates[0] ('bad-method') skipped: http_method: Input should be 'GET', 'POST', 'PUT', 'DELETE' or 'PATCH'.` |
| The manual cannot be fetched, for example the server returns 401 or does not answer | `manual 'locked' loaded no tools: Error connecting to HTTP provider 'locked': 401, ...` |

A `${VAR}` variable that is not set is different: the UTCP client stops the whole registration, so every manual in the config loads no tools. Set each variable that a template uses before the toolbox starts. The client reads the variable under a name made from the manual name, `_`, and the variable name. In the manual name, each character that is not a letter, digit or `_` becomes `_`, and then each `_` is doubled. So `${API_KEY}` in the manual `keyed` reads `keyed_API_KEY`, and `${API_KEY}` in the manual `my_api` or `my-api` reads `my__api_API_KEY`. The warning names the exact variable.

## How tools are exposed

`UTCPToolBox.discover_tools` does the following:

1. Checks the `utcp_config` shape, then validates each template in `manual_call_templates` and skips a template that the UTCP client rejects.
2. Creates a new client with `UtcpClient.create(config=...)` without the templates, and registers the valid ones with `client.register_manuals(...)`. A manual that cannot be fetched does not stop the others.
3. Replaces the previous client with the new one, then closes the previous one. Tool calls made during a rediscovery use the previous client until the new one has its manuals.
4. Reads all tools from the client's tool repository.
5. Converts each tool's `inputs` JSON Schema into a Pydantic `ToolArguments` model with `_schema_to_pydantic`, so the LLM sees the real argument schema.
6. Wraps `client.call_tool(name, args)` in `_call_utcp_tool`.

## Tool output

All UTCP tool calls return `AdapterToolOutput`:

| Field | Type | Description |
|---|---|---|
| `content` | str | Normalised text from the response |
| `is_error` | bool | `True` if the response contained `is_error: true` |
| `raw` | list[dict] | Original response block(s) |

`_call_utcp_tool` normalises the response:

- A `str` response gives `content = str` and `raw = [{"type": "text", "text": str}]`.
- A `dict` response gives `content = dict["text"] or dict["content"] or str(dict)`.
- Any other response gives `content = str(result)` and `raw = [{"type": "raw", ...}]`.

## Lifecycle

```
UTCPToolBox.__init__()
  → _AsyncRunner started
  → super().__init__() → discover_tools()
      → _runner.run(_connect_and_list())
          → CallTemplateSerializer().validate_dict(template)   # each template
          → UtcpClient.create(config=UtcpClientConfig(...))     # no templates
          → client.register_manuals(valid_templates)
          → previous client closed, new client in use
          → client.config.tool_repository.get_tools()
      → AgentTools registered

call_tool("ovos_translate.translate", {"tgt_lang": "pt", "utterance": "..."})
  → _call_utcp_tool(name, args)
      → _runner.run(client.call_tool(...))
      → AdapterToolOutput returned

UTCPToolBox.close()
  → _runner.run(client.close())   # skipped at interpreter shutdown
  → _runner.close()
```

---
[← MCPToolBox](mcp.md) · [Home](index.md) · [Configuration →](configuration.md)
