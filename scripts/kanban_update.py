#!/usr/bin/env python3
"""
看板任务更新工具 - 供三个智能体调用
支持三智能体架构：鸽鸽(gege)、狗头(goutou)、黑奴(heinu)
"""
import json, pathlib, datetime, sys, subprocess, logging, os, re, argparse
from file_lock import atomic_json_read, atomic_json_write

BASE = pathlib.Path(__file__).resolve().parent.parent
TASKS_FILE = BASE / 'data' / 'tasks_source.json'
REFRESH_SCRIPT = BASE / 'scripts' / 'refresh_live_data.py'

log = logging.getLogger('kanban_update')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')

# 三智能体状态到智能体ID的映射
STATE_AGENT_MAP = {
    'Created': 'gege',
    'Planning': 'goutou',
    'Assigned': 'goutou',
    'Executing': 'heinu',
    'Review': 'goutou',
    'Done': None,
}

# 组织名到智能体ID的映射
ORG_AGENT_MAP = {
    '鸽鸽': 'gege',
    '狗头': 'goutou',
    '黑奴': 'heinu',
}

# 智能体到组织的映射
STATE_ORG_MAP = {
    'Created': '鸽鸽',
    'Planning': '狗头',
    'Assigned': '狗头',
    'Executing': '黑奴',
    'Review': '狗头',
    'Done': '完成',
    'Blocked': '阻塞',
    'Cancelled': '已取消',
}

# 三智能体显示信息
AGENTS = {
    'gege': {
        'label': '鸽鸽',
        'emoji': '🕊️',
        'role': '日常秘书',
        'rank': '一级',
    },
    'goutou': {
        'label': '狗头',
        'emoji': '🐕',
        'role': '项目经理',
        'rank': '一级',
    },
    'heinu': {
        'label': '黑奴',
        'emoji': '👨‍💻',
        'role': '资深开发',
        'rank': '一级',
    },
}

_MAX_PROGRESS_LOG = 100

def load():
    return atomic_json_read(TASKS_FILE, [])

def save(tasks):
    atomic_json_write(TASKS_FILE, tasks)

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')

def _find_task(tasks, task_id):
    return next((t for t in tasks if t.get('id') == task_id), None)

def _is_valid_task_title(title):
    if not title:
        return False, '标题为空'
    if len(title) < 6:
        return False, f'标题过短（{len(title)}字）'
    if len(title) > 100:
        return False, f'标题过长（{len(title)}字）'
    return True, ''

def _get_agent_id(task=None, task_id=None, state=None):
    """推断当前执行该命令的Agent ID"""
    # 优先从任务ID或状态推断
    if task_id:
        # JJC任务主要是狗头处理
        if task_id.startswith('JJC-'):
            return 'goutou'
        # OC任务：从ID推断智能体（通常是第二个部分）
        # 例如：OC-gege-xxx123 → gege, OC-goutou-xxx → goutou, OC-heinu-xxx → heinu
        elif task_id.startswith('OC-'):
            parts = task_id.split('-')
            if len(parts) >= 2:
                last_part = parts[1]  # 第一部分是OC前缀，第二部分可能是智能体ID
                if last_part in AGENTS:
                    return last_part
            else:
                log.warning(f'无法从任务ID推断智能体：{task_id}')
                return 'goutou'

    # 从状态推断
    if state:
        agent = STATE_AGENT_MAP.get(state)
        if agent:
            return agent

    # 从任务对象推断
    if task:
        org = task.get('org', '')
        if org:
            return ORG_AGENT_MAP.get(org)

    # 默认返回狗头
    return 'goutou'

def _get_task_for_dispatch(task_id):
    """获取任务用于派发的数据（可能需要克隆）"""
    task = _find_task(load(), task_id)
    if not task:
        log.error(f'任务 {task_id} 不存在')
        return None
    return task

def trigger_refresh():
    try:
        subprocess.Popen(
            [sys.executable, str(REFRESH_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

def cmd_create(task_id, title, state='Created', org='鸽鸽', official='鸽鸽', remark=''):
    """创建新任务"""
    tasks = load()
    if _find_task(tasks, task_id):
        log.error(f'任务 {task_id} 已存在')
        return False

    valid, msg = _is_valid_task_title(title)
    if not valid:
        log.error(f'无效的标题：{msg}')
        return False

    tasks.append({
        'id': task_id,
        'title': title,
        'state': state,
        'org': org,
        'official': official,
        'now': f'已接收旨意，等待{org}处理',
        'eta': '-',
        'block': '无',
        'output': '',
        'flow_log': [
            {'at': now_iso(), 'from': '用户', 'to': org, 'remark': remark},
        ],
        'createdAt': now_iso(),
        'updatedAt': now_iso(),
    })

    save(tasks)
    trigger_refresh()
    log.info(f'✅ 创建 {task_id} | {title[:30]} | state={state}')
    return True

def cmd_state(task_id, new_state, remark=''):
    """更新任务状态"""
    tasks = load()
    task = _find_task(tasks, task_id)
    if not task:
        log.error(f'任务 {task_id} 不存在')
        return False

    old_state = task.get('state', '')

    # 验证状态流转是否合法
    valid_transitions = {
        'Created': ['Planning', 'Cancelled'],
        'Planning': ['Assigned', 'Blocked', 'Cancelled'],
        'Assigned': ['Executing', 'Cancelled'],
        'Executing': ['Done', 'Blocked', 'Cancelled'],
        'Review': ['Done', 'Executing', 'Cancelled'],
        'Blocked': ['Planning', 'Executing'],
        'Cancelled': [],
        'Done': [],
    }

    if new_state not in valid_transitions.get(old_state, []):
        log.error(f'无效的状态流转：{old_state} → {new_state}')
        return False

    # 更新状态
    task['state'] = new_state
    task['updatedAt'] = now_iso()

    # 如果状态改变，可能需要更新组织和官员
    if new_state != old_state:
        new_org = STATE_ORG_MAP.get(new_state, '')
        if new_org:
            task['org'] = new_org
            # 通过状态找到agent_id，再从AGENTS获取label
            agent_id = STATE_AGENT_MAP.get(new_state)
            task['official'] = AGENTS.get(agent_id, {}).get('label', new_org)

    save(tasks)
    trigger_refresh()
    log.info(f'✅ {task_id} 状态更新：{old_state} → {new_state}')
    return True

def cmd_flow(task_id, from_dept, to_dept, remark=''):
    """添加流转记录"""
    tasks = load()
    task = _find_task(tasks, task_id)
    if not task:
        log.error(f'任务 {task_id} 不存在')
        return False

    task.setdefault('flow_log', [])
    task['flow_log'].append({
        'at': now_iso(),
        'from': from_dept,
        'to': to_dept,
        'remark': remark,
    })
    task['updatedAt'] = now_iso()

    save(tasks)
    trigger_refresh()
    log.info(f'✅ {task_id} 流转：{from_dept} → {to_dept}')
    return True

def cmd_done(task_id, output, summary=''):
    """标记任务完成"""
    tasks = load()
    task = _find_task(tasks, task_id)
    if not task:
        log.error(f'任务 {task_id} 不存在')
        return False

    task['state'] = 'Done'
    task['org'] = '完成'
    task['now'] = f'任务已完成：{summary[:100] if summary else "任务已完成"}'
    task['output'] = output
    task['updatedAt'] = now_iso()

    task.setdefault('flow_log', [])
    task['flow_log'].append({
        'at': now_iso(),
        'from': task.get('org', ''),
        'to': '完成',
        'remark': summary or '任务已完成',
    })

    save(tasks)
    trigger_refresh()
    log.info(f'✅ {task_id} 已完成 | {summary[:50]}')
    return True

def cmd_block(task_id, reason):
    """标记任务阻塞"""
    return cmd_state(task_id, 'Blocked', reason)

def cmd_progress(task_id, now_text='', todos_pipe='', tokens=0, cost=0.0, elapsed=0):
    """上报进度（不改变状态，只更新now和todos）"""
    tasks = load()
    task = _find_task(tasks, task_id)
    if not task:
        log.error(f'任务 {task_id} 不存在')
        return False

    # 更新当前进展
    task['now'] = now_text
    task['updatedAt'] = now_iso()

    # 解析todos_pipe（可选）
    if todos_pipe:
        task['todos'] = []
        for item in todos_pipe.split('|'):
            item = item.strip()
            if not item:
                continue

            if item.endswith('✅'):
                status = 'completed'
                title = item[:-1].strip()
            elif item.endswith('🔄'):
                status = 'in-progress'
                title = item[:-1].strip()
            else:
                status = 'not-started'
                title = item.strip()

            task['todos'].append({
                'id': str(len(task['todos']) + 1),
                'title': title,
                'status': status,
            })

    # 添加进度日志
    progress_entry = {
        'at': now_iso(),
        'agent': _get_agent_id(task=task, task_id=task_id),
        'agentLabel': AGENTS.get(_get_agent_id(task=task, task_id=task_id), {}).get('label', ''),
        'text': now_text,
        'todos': task.get('todos', []),
        'state': task.get('state', ''),
        'org': task.get('org', ''),
    }

    task.setdefault('progress_log', [])

    # 限制 progress_log 大小，防止无限增长
    if len(task['progress_log']) > _MAX_PROGRESS_LOG:
        task['progress_log'] = task['progress_log'][-_MAX_PROGRESS_LOG:]

    task['progress_log'].append(progress_entry)

    save(tasks)
    trigger_refresh()
    log.info(f'📊 {task_id} 进展: {now_text[:40]}')

def cmd_todo(task_id, todo_id, title, status='not-started', detail=''):
    """添加或更新子任务"""
    tasks = load()
    task = _find_task(tasks, task_id)
    if not task:
        log.error(f'任务 {task_id} 不存在')
        return False

    task.setdefault('todos', [])

    # 查找或创建TODO项
    existing = None
    for i, td in enumerate(task['todos']):
        if str(td.get('id')) == todo_id:
            existing = td
            break

    if existing:
        # 更新
        existing['title'] = title
        existing['status'] = status
        existing['detail'] = detail
        task['updatedAt'] = now_iso()
    else:
        new_id = len(task['todos']) + 1
        task['todos'].append({
            'id': new_id,
            'title': title,
            'status': status,
            'detail': detail,
        })

    save(tasks)
    trigger_refresh()
    log.info(f'✅ {task_id} TODO {todo_id}: {title[:30]} | {status}')

def _get_agent_name(agent_id):
    """获取智能体显示名称"""
    return AGENTS.get(agent_id, {}).get('label', agent_id)


def main():
    parser = argparse.ArgumentParser(description='三智能体看板任务更新工具')

    # 子命令
    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # create 命令
    create_parser = subparsers.add_parser('create', help='创建新任务')
    create_parser.add_argument('task_id', help='任务ID')
    create_parser.add_argument('title', help='任务标题')
    create_parser.add_argument('--state', default='Created', help='初始状态')
    create_parser.add_argument('--org', default='鸽鸽', help='组织')
    create_parser.add_argument('--official', default='鸽鸽', help='官员')
    create_parser.add_argument('--remark', default='', help='备注')

    # state 命令
    state_parser = subparsers.add_parser('state', help='更新任务状态')
    state_parser.add_argument('task_id', help='任务ID')
    state_parser.add_argument('new_state', help='新状态')
    state_parser.add_argument('--remark', default='', help='备注')

    # flow 命令
    flow_parser = subparsers.add_parser('flow', help='添加流转记录')
    flow_parser.add_argument('task_id', help='任务ID')
    flow_parser.add_argument('from_dept', help='来源部门')
    flow_parser.add_argument('to_dept', help='目标部门')
    flow_parser.add_argument('remark', default='', help='备注')

    # done 命令
    done_parser = subparsers.add_parser('done', help='标记任务完成')
    done_parser.add_argument('task_id', help='任务ID')
    done_parser.add_argument('output', default='', help='输出路径')
    done_parser.add_argument('--summary', default='', help='完成摘要')

    # block 命令
    block_parser = subparsers.add_parser('block', help='标记任务阻塞')
    block_parser.add_argument('task_id', help='任务ID')
    block_parser.add_argument('reason', help='阻塞原因')

    # progress 命令
    progress_parser = subparsers.add_parser('progress', help='上报进度')
    progress_parser.add_argument('task_id', help='任务ID')
    progress_parser.add_argument('now_text', help='当前进展')
    progress_parser.add_argument('--todos', default='', help='TODO列表(用|分隔)')
    progress_parser.add_argument('--tokens', type=float, default=0, help='消耗tokens')
    progress_parser.add_argument('--cost', type=float, default=0.0, help='成本(美元)')
    progress_parser.add_argument('--elapsed', type=int, default=0, help='耗时(秒)')

    # todo 命令
    todo_parser = subparsers.add_parser('todo', help='添加/更新TODO')
    todo_parser.add_argument('task_id', help='任务ID')
    todo_parser.add_argument('todo_id', help='TODO ID')
    todo_parser.add_argument('title', help='TODO标题')
    todo_parser.add_argument('--status', default='not-started', help='TODO状态')
    todo_parser.add_argument('--detail', default='', help='TODO详情')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 处理各种命令
    if args.command == 'create':
        cmd_create(args.task_id, args.title, args.state, args.org, args.official, args.remark)

    elif args.command == 'state':
        if not args.new_state:
            parser.error('state 命令需要 new_state 参数')
        cmd_state(args.task_id, args.new_state, args.remark)

    elif args.command == 'flow':
        cmd_flow(args.task_id, args.from_dept, args.to_dept, args.remark)

    elif args.command == 'done':
        cmd_done(args.task_id, args.output, args.summary)

    elif args.command == 'block':
        cmd_block(args.task_id, args.reason)

    elif args.command == 'progress':
        cmd_progress(args.task_id, args.now_text, args.todos, args.tokens, args.cost, args.elapsed)

    elif args.command == 'todo':
        cmd_todo(args.task_id, args.todo_id, args.title, args.status, args.detail)

if __name__ == '__main__':
    main()
