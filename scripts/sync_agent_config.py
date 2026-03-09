#!/usr/bin/env python3
"""
同步 openclaw.json 中的 agent 配置 → data/agent_config.json
三智能体架构：鸽鸽、狗头、黑奴
"""
import json
import pathlib
import datetime
import logging
from file_lock import atomic_json_write

log = logging.getLogger('sync_agent_config')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# Auto-detect project root (parent of scripts/)
BASE = pathlib.Path(__file__).resolve().parent.parent
DATA = BASE / 'data'
OPENCLAW_CFG = pathlib.Path.home() / '.openclaw' / 'openclaw.json'

# 三智能体定义
ID_LABEL = {
    'gege':    {'label': '鸽鸽',   'role': '日常秘书', 'duty': '消息分拣与沟通',   'emoji': '🕊️'},
    'goutou':   {'label': '狗头',   'role': '项目经理',   'duty': '任务规划与派发',   'emoji': '🐕'},
    'heinu':    {'label': '黑奴',   'role': '资深开发',   'duty': '全栈任务执行',   'emoji': '👨‍💻'},
}

KNOWN_MODELS = [
    {'id': 'anthropic/claude-sonnet-4-6', 'label': 'Claude Sonnet 4.6', 'provider': 'Anthropic'},
    {'id': 'anthropic/claude-opus-4-5',   'label': 'Claude Opus 4.5',   'provider': 'Anthropic'},
    {'id': 'anthropic/claude-haiku-3-5', 'label': 'Claude Haiku 3.5', 'provider': 'Anthropic'},
    {'id': 'openai/gpt-4o',               'label': 'GPT-4o',            'provider': 'OpenAI'},
    {'id': 'openai/gpt-4o-mini',          'label': 'GPT-4o Mini',       'provider': 'OpenAI'},
    {'id': 'openai-codex/gpt-5.3-codex', 'label': 'GPT-5.3 Codex',    'provider': 'OpenAI Codex'},
    {'id': 'google/gemini-2.0-flash',     'label': 'Gemini 2.0 Flash',  'provider': 'Google'},
    {'id': 'google/gemini-2.5-pro',       'label': 'Gemini 2.5 Pro',    'provider': 'Google'},
    {'id': 'copilot/claude-sonnet-4',     'label': 'Claude Sonnet 4',   'provider': 'Copilot'},
    {'id': 'copilot/claude-opus-4.5',     'label': 'Claude Opus 4.5',   'provider': 'Copilot'},
    {'id': 'github-copilot/claude-opus-4.6', 'label': 'Claude Opus 4.6', 'provider': 'GitHub Copilot'},
    {'id': 'copilot/gpt-4o',              'label': 'GPT-4o',            'provider': 'Copilot'},
    {'id': 'copilot/gemini-2.5-pro',      'label': 'Gemini 2.5 Pro',    'provider': 'Copilot'},
    {'id': 'copilot/o3-mini',             'label': 'o3-mini',           'provider': 'Copilot'},
]


def normalize_model(model_value, fallback='unknown'):
    if isinstance(model_value, str) and model_value:
        return model_value
    if isinstance(model_value, dict):
        return model_value.get('primary') or model_value.get('id') or fallback
    return fallback


def get_skills(workspace: str):
    """获取指定 workspace 下的 skills 列表"""
    skills_dir = pathlib.Path(workspace) / 'skills'
    skills = []
    try:
        if skills_dir.exists():
            for d in sorted(skills_dir.iterdir()):
                if d.is_dir():
                    md = d / 'SKILL.md'
                    desc = ''
                    if md.exists():
                        try:
                            for line in md.read_text(encoding='utf-8', errors='ignore').splitlines():
                                line = line.strip()
                                if line and not line.startswith('#') and not line.startswith('---'):
                                    desc = line[:100]
                                    break
                        except Exception:
                            desc = '(读取失败)'
                    skills.append({'name': d.name, 'path': str(md), 'exists': md.exists(), 'description': desc})
    except PermissionError as e:
        log.warning(f'kills 目录访问受限: {e}')
    return skills


def main():
    # 读取 openclaw.json 配置
    cfg = {}
    try:
        cfg = json.loads(OPENCLAW_CFG.read_text())
    except Exception as e:
        log.warning(f'cannot read openclaw.json: {e}')
        return

    agents_cfg = cfg.get('agents', default={})
    default_model = normalize_model(agents_cfg.get('defaults', {}).get('model', {}), 'unknown')
    agents_list = agents_cfg.get('list', [])

    result = []
    seen_ids = set()

    # 处理 openclaw.json 中的 agents
    for ag in agents_list:
        ag_id = ag.get('id', '')
        if ag_id not in ID_LABEL:
            continue  # 只处理三智能体
        meta = ID_LABEL[ag_id]
        workspace = ag.get('workspace', str(pathlib.Path.home() / f'.openclaw/workspace-{ag_id}'))
        result.append({
            'id': ag_id,
            'label': meta['label'],
            'role': meta['role'],
            'duty': meta['duty'],
            'emoji': meta['emoji'],
            'model': normalize_model(ag.get('model', default_model), default_model),
            'defaultModel': default_model,
            'workspace': workspace,
            'skills': get_skills(workspace),
            'allowAgents': ag.get('subagents', {}).get('allowAgents', []),
        })
        seen_ids.add(ag_id)

    # 补充不在 openclaw.json 中的 agent
    EXTRA_AGENTS = {
        'gege':    {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-gege'),
                       'allowAgents': ['goutou']},
        'goutou':  {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-goutou'),
                       'allowAgents': ['heinu']},
        'heinu':   {'model': default_model, 'workspace': str(pathlib.Path.home() / '.openclaw/workspace-heinu'),
                       'allowAgents': []},
    }
    for ag_id, extra in EXTRA_AGENTS.items():
        if ag_id not in seen_ids and ag_id not in ID_LABEL:
            meta = ID_LABEL.get(ag_id)
            if meta:
                result.append({
                    'id': ag_id,
                    'label': meta['label'],
                    'role': meta['role'],
                    'duty': meta['duty'],
                    'emoji': meta['emoji'],
                    'model': extra['model'],
                    'defaultModel': default_model,
                    'workspace': extra['workspace'],
                    'skills': get_skills(extra['workspace']),
                    'allowAgents': extra['allowAgents'],
                    'isDefaultModel': True,
                })
            seen_ids.add(ag_id)

    payload = {
        'generatedAt': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'defaultModel': default_model,
        'knownModels': KNOWN_MODELS,
        'agents': result,
    }

    DATA.mkdir(exist_ok=True)
    atomic_json_write(DATA / 'agent_config.json', payload)
    log.info(f'{len(result)} agents synced to {DATA / "agent_config.json"}')


if __name__ == '__main__':
    main()
