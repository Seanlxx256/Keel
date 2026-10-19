"""Isolated installed-Serena symbol retrieval; reads query-only input, never labels."""
import argparse
import json
from importlib import metadata
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.launch_serena import prepare
from keel.experience import ExperienceStore
from keel.tool_recovery import symbol_queries


def query_identifiers(query):
    # Fixed transparent adapter, not an LLM or a semantic-search implementation.
    raw = re.findall(r'[A-Za-z_]\w*', query)
    strong = [s for s in raw if '_' in s or s[0].isupper()]
    dotted = re.findall(r'\b\w+\.([A-Za-z_]\w*)', query)
    result = []
    for term in [*dotted, *strong]:
        if len(term) < 3 or term in result:
            continue
        result.append(term)
        if len(result) == 8:
            break
    return result


def retrieve(config):
    repo = Path(config['repo']).resolve(strict=True)
    prepare(repo, Path(config['state']))
    from serena.config.serena_config import SerenaConfig
    from serena.agent import SerenaAgent
    from serena.tools.symbol_tools import FindSymbolTool
    settings = SerenaConfig.from_config_file()
    settings.web_dashboard = False
    settings.gui_log_window = False
    if config.get('pyright_command'):
        settings.ls_specific_settings = {'python': {'ls_base_cmd': config['pyright_command']}}
    agent = SerenaAgent(project=str(repo), serena_config=settings)
    candidates, observations, seen = [], [], set()
    try:
        tool = agent.get_tool(FindSymbolTool)
        def invoke(term, substring, timeout):
            value = agent.execute_task(lambda: tool.apply(name_path_pattern=term, substring_matching=substring,
                               include_body=False, max_matches=100, max_answer_chars=100000),
                               name='benchmark_symbol_query', timeout=timeout)
            return json.loads(value)
        store = ExperienceStore(config['experience_store']) if config.get('experience_store') else None
        measured = symbol_queries(invoke, query_identifiers(config['query']),
            version=metadata.version('serena-agent'), store=store)
        observations = measured['observations']
        for row in measured['symbols']:
            # File/package entries are navigation containers, not code
            # definitions; some LSPs report virtual EOF lines for them.
            if row.get('kind') in ('File', 'Package', 'Module'):
                continue
            path = row.get('relative_path')
            location = row.get('body_location') or {}
            start, end = location.get('start_line'), location.get('end_line')
            if not isinstance(path, str) or type(start) is not int or type(end) is not int:
                continue
            target = (repo/path).resolve(strict=True)
            if not target.is_relative_to(repo):
                raise ValueError('Serena returned a path outside the snapshot')
            # Language servers also return package-directory symbols. These
            # have no file lines and cannot enter the line-budget metric.
            if not target.is_file():
                continue
            # Installed Serena body locations are 0-based line numbers.
            item = {'path': target.relative_to(repo).as_posix(), 'start_line': start+1, 'end_line': end+1}
            key = (item['path'], item['start_line'], item['end_line'])
            if key not in seen:
                seen.add(key)
                candidates.append(item)
        return {'status': 'ok', 'candidates': candidates[:100], 'observations': observations,
            'recovery': measured['recovery'], 'tool_calls': measured['tool_calls'], 'max_tool_calls': 8,
            'unqueried_terms': measured['unqueried_terms'],
            'version': metadata.version('serena-agent'),
            'adapter': 'Issue-only identifiers, max 8 calls including relative/root exact-query recovery; not a full Serena Agent.'}
    finally:
        # shutdown() sends SIGTERM to its own process in installed Serena 2.0.
        # Use its cleanup hook so the worker can persist the measured result.
        agent.on_shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = retrieve(json.loads(args.input.read_text(encoding='utf-8')))
    except Exception as error:
        result = {'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)[:1000]}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
