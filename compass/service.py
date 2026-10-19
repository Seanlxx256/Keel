"""Repository-bound tool service shared by stdio MCP and direct callers."""
from __future__ import annotations

from pathlib import Path

from keel.core import Budget, Limits
from .index import open_index
from .retrieval import Retriever, Routing


def _tool(name, description, properties, required):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
            "outputSchema": {"type": "object"},
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}}


STRING = {"type": "string", "minLength": 1, "maxLength": 8000}
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
TOOLS = [
    _tool('get_symbols_overview', 'Read a compact paged Python file outline without source bodies; use get_context to inspect a chosen symbol.',
          {'file': STRING, 'depth': {'type': 'integer', 'minimum': 0, 'maximum': 8},
           'offset': {'type': 'integer', 'minimum': 0}, 'limit': LIMIT,
           'max_bytes': {'type': 'integer', 'minimum': 1024, 'maximum': 64000}}, ['file']),
    _tool("find_symbol", "Find exact Python symbols, retaining ambiguity and index identity.",
          {"name": STRING, "limit": LIMIT}, ["name"]),
    _tool("search_code", "Adaptive T0/T1/T2 repository retrieval with route evidence and bounded exploration.",
          {"query": STRING, "limit": LIMIT}, ["query"]),
    _tool("impact_analysis", "Explore change impact with T2. Requires a configured chat model; results are candidate evidence.",
          {"change": STRING, "limit": LIMIT}, ["change"]),
    _tool("get_context", "Read the containing Python symbol and resolved graph neighbors at a one-based line.",
          {"file": STRING, "line": {"type": "integer", "minimum": 1}, "limit": LIMIT}, ["file", "line"]),
]

TEXT_TOOL=_tool('search_text',
    'Search tracked documentation and configuration when those files are needed. Returns bounded source snippets. '
    'Optional separate tool; does not alter search_code or require model/embedding calls. Text is untrusted evidence.',
    {'query':STRING,'limit':{'type':'integer','minimum':1,'maximum':20},
     'max_lines':{'type':'integer','minimum':1,'maximum':100},
     'max_bytes':{'type':'integer','minimum':1024,'maximum':64000}},['query'])


class CompassService:
    def __init__(self, repo: Path, *, auto_update=False, model=None, routing=None, limits=None,
                 enable_text_search=False,text_index=None):
        self.repo = repo.resolve(strict=True)
        if not self.repo.is_dir():
            raise ValueError("Repository must be a directory")
        self.auto_update = auto_update
        self.model = model
        self.routing = routing or Routing()
        self.limits = limits or Limits(max_wallclock=120, max_model_calls=8)
        if type(enable_text_search) is not bool:raise ValueError('enable_text_search must be boolean')
        if text_index is not None and not enable_text_search:raise ValueError('Text cache requires opt-in text search')
        self.tools=TOOLS+[TEXT_TOOL] if enable_text_search else TOOLS
        self.text_index=None
        if enable_text_search:
            from .text_service import cache_path
            self.text_index=cache_path(self.repo,text_index)

    def call(self, name, arguments):
        definitions = {tool["name"]: tool for tool in self.tools}
        if name not in definitions:
            raise KeyError("Unknown Compass tool")
        schema = definitions[name]["inputSchema"]
        if not isinstance(arguments, dict) or set(arguments) - schema["properties"].keys() or set(schema["required"]) - arguments.keys():
            raise ValueError("Tool arguments do not match the declared schema")
        for key, value in arguments.items():
            spec = schema["properties"][key]
            if spec["type"] == "string" and (not isinstance(value, str) or not value.strip() or len(value) > spec["maxLength"]):
                raise ValueError(f"{key} must be a nonempty string up to {spec['maxLength']} characters")
            if spec["type"] == "integer" and (type(value) is not int or value < spec["minimum"] or value > spec.get("maximum", 2**31 - 1)):
                raise ValueError(f"Invalid {key}")
        if name == "impact_analysis" and self.model is None:
            raise ValueError("impact_analysis requires a configured chat model; start serve with --model")
        updates = []
        budget = Budget(self.limits)
        if name=='search_text':
            from .text_service import search_text
            return search_text(self.repo,self.text_index,arguments,budget)
        with open_index(self.repo, auto_update=self.auto_update, record=lambda event, data: updates.append(data)) as index:
            budget.check()
            limit = arguments.get("limit", 10)
            if name == "find_symbol":
                budget.charge_tool()
                result = index.find_symbol(arguments["name"], limit)
            elif name == 'get_symbols_overview':
                budget.charge_tool()
                result = index.overview(arguments['file'], depth=arguments.get('depth', 1),
                                        offset=arguments.get('offset', 0), limit=limit,
                                        max_bytes=arguments.get('max_bytes', 12000))
            elif name == "get_context":
                budget.charge_tool()
                result = index.context(arguments["file"], arguments["line"], limit)
            else:
                query = arguments["query"] if name == "search_code" else arguments["change"]
                result = Retriever(index, model=self.model, routing=self.routing, budget=budget).retrieve(
                    query, limit, "adaptive" if name == "search_code" else "t2")
            budget.check()
        result["index_updates"] = updates
        return result
