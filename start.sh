#!/bin/bash
# 三智能体 · 一键启动脚本
# 同时启动数据刷新循环和看板服务器

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

banner() {
  echo ""
  echo -e.e "${BLUE}╔════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║  🚀  三智能体 · 一键启动脚本           ║${NC}"
  echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
  echo ""
}

log()   { echo -e "${GREEN}✅ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }
info()  { echo -e "${BLUE}ℹ️  $1${NC}"; }

# ── 检查依赖 ──────────────────────────────────
check_deps() {
  info "检查依赖..."

  if ! command -v python3 &>/dev/null; then
    error "未找到 python3"
    exit 1
  fi
  log "Python3: $(python3 --version)"
}

# ── 清理旧进程 ──────────────────────────────────
cleanup() {
  echo ""
  info "清理旧进程和文件..."

  # 停止旧的刷新循环
  if [ -f /tmp/agents_refresh.pid ]; then
    OLD_PID=$(cat /tmp/agents_refresh.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
      log "已停止旧刷新循环 (PID=$OLD_PID)"
    fi
    rm -f /tmp/agents_refresh.pid
  fi

  # 停止旧的看板服务器
  if [ -f /tmp/edict_server.pid ]; then
    OLD_PID=$(cat /tmp/edict_server.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
      log "已停止旧服务器 (PID=$OLD_PID)"
    fi
    rm -f /tmp/edict_server.pid
  fi

  # 清理临时日志
  if [ -f /tmp/agents_refresh.log ]; then
    rm /tmp/agents_refresh.log
  fi
}

# ── 启动数据刷新循环 ──────────────────────────
start_refresh_loop() {
  info "启动数据刷新循环..."
  cd "$REPO_DIR"

  # 将刷新循环后台运行，输出重定向到日志
  nohup bash scripts/run_loop.sh > /tmp/agents_refresh.log 2>&1 &
  REFRESH_PID=$!

  # 等待一下确保进程启动成功
  sleep 2

  # 检查进程是否还在运行
  if ! kill -0 $REFRESH_PID 2>/dev/null; then
    error "刷新循环启动失败"
    return 1
  fi

  echo $REFRESH_PID > /tmp/agents_refresh.pid
  log "数据刷新循环已启动 (PID=$REFRESH_PID)"
  return 0
}

# ── 启动看板服务器 ──────────────────────────
start_dashboard() {
  info "启动看板服务器..."
  cd "$REPO_DIR"

  # 将看板服务器后台运行
  nohup python3 dashboard/server.py > /tmp/edict_server.log 2>&1 &
  SERVER_PID=$!

  # 等待一下确保进程启动成功
  sleep 2

  # 检查进程是否还在运行
  if ! kill -0 $SERVER_PID 2>/dev/null; then
    error "看板服务器启动失败"
    return 1
  fi

  echo $SERVER_PID > /tmp/edict_server.pid
  log "看板服务器已启动 (PID=$SERVER_PID)"

  # 等待服务器启动
  sleep 3

  # 检查端口是否可访问
  if command -v curl &>/dev/null; then
    if curl -s http://127.0.0.1:7891 > /dev/null 2>&1; then
      log "看板服务已就绪：http://127.0.0.1:7891"
    else
      warn "看板服务可能还在启动中..."
    fi
  fi

  return 0
}

# ── 显示状态 ──────────────────────────────────
show_status() {
  echo ""
  echo -e "${BLUE}┌────────────────────────────────────────────────┐${NC}"
  echo -e "${BLUE}│ 系统状态                                   │${NC}"
  echo -e "${BLUE}├────────────────────────────────────────────────┤${NC}"
  echo ""

  # 刷新循环状态
  if [ -f /tmp/agents_refresh.pid ]; then
    REFRESH_PID=$(cat /tmp/agents_refresh.pid 2>/dev/null)
    if [ -n "$REFRESH_PID" ] && kill -0 "$REFRESH_PID" 2>/dev/null; then
      echo -e "  数据刷新循环: ${GREEN}运行中${NC} (PID: $REFRESH_PID)"
      # 显示最后几行日志
      echo -e "  最近日志:"
      tail -5 /tmp/agents_refresh.log 2>/dev/null | sed 's/^/    /'
    else
      echo -e "  数据刷新循环: ${RED}已停止${NC}"
    fi
  else
    echo -e "  数据刷新循环: ${YELLOW}未启动${NC}"
  fi

  echo ""

  # 看板服务器状态
  if [ -f /tmp/edict_server.pid ]; then
    SERVER_PID=$(cat /tmp/edict_server.pid 2>/dev/null)
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
      echo -e "  看板服务器:   ${GREEN}运行中${NC} (PID: $SERVER_PID)"
      echo -e "  访问地址:     ${BLUE}http://127.0.0.1:7891${NC}"
      if command -v curl &>/dev/null; then
        if curl -s http://127.0.0.1:7891 > /dev/null 2>&1; then
          echo -e "  状态:         ${GREEN}✅ 可访问${NC}"
        else
          echo -e "  状态:         ${YELLOW}🔄 启动中...${NC}"
        fi
      fi
    else
      echo -e "  看板服务器:   ${RED}已停止${NC}"
    fi
  else
    echo -e "  看板服务器:   ${YELLOW}未启动${NC}"
  fi

  echo ""
  echo -e "${BLUE}└────────────────────────────────────────────────┘${NC}"
  echo ""
  echo -e "${BLUE}💡 使用以下命令控制服务:${NC}"
  echo -e "${BLUE}   ./stop.sh     - 停止所有服务${NC}"
  echo -e "${BLUE}   tail -f /tmp/agents_refresh.log   - 查看刷新日志${NC}"
  echo -e "${BLUE}   tail -f /tmp/edict_server.log     - 查看服务器日志${NC}"
  echo ""
}

# ── 创建停止脚本 ──────────────────────────────────
create_stop_script() {
  cat > "$REPO_DIR/stop.sh" << 'STOP_EOF'
#!/bin/bash
echo "停止三智能体服务..."

# 停止刷新循环
if [ -f /tmp/agents_refresh.pid ]; then
  PID=$(cat /tmp/agents_refresh.pid)
  if [ -n "\$PID" ] && kill -0 "\$PID" 2>/dev/null; then
    echo "已停止刷新循环 (PID=\$PID)"
    rm -f /tmp/agents_refresh.pid
  fi
fi

# 停止看板服务器
if [ -f /tmp/edict_server.pid ]; then
  PID=$(cat /tmp/edict_server.pid)
  if [ -n "\$PID" ] && kill -0 "\$PID" 2>/dev/null; then
    echo "已停止看板服务器 (PID=\$PID)"
    rm -f /tmp/edict_server.pid
  fi
fi

echo ""
echo "所有服务已停止"
STOP_EOF

  chmod +x "$REPO_DIR/stop.sh"
  log "已创建 stop.sh 脚本"
}

# ── 处理退出信号 ──────────────────────────────────
on_exit() {
  echo ""
  echo -e "${YELLOW}收到退出信号，停止所有服务...${NC}"

  # 停止刷新循环
  if [ -f /tmp/agents_refresh.pid ]; then
    REFRESH_PID=$(cat /tmp/agents_refresh.pid 2>/dev/null)
    kill -0 "$REFRESH_PID" 2>/dev/null
    rm -f /tmp/agents_refresh.pid
  fi

  # 停止看板服务器
  if [ -f /tmp/edict_server.pid ]; then
    SERVER_PID=$(cat /tmp/edict_server.pid 2>/dev/null)
    kill -0 "$SERVER_PID" 2>/dev/null
    rm -f /tmp/edict_server.pid
  fi

  log "所有服务已停止"
  exit 0
}

# 注册退出信号处理
trap on_exit SIGINT SIGTERM

# ── 主流程 ──────────────────────────────────
main() {
  banner
  check_deps
  cleanup

  echo ""
  info "开始启动服务..."
  echo ""

  # 启动服务
  start_refresh_loop
  start_dashboard

  echo ""
  show_status

  log "启动完成！按 Ctrl+C 停止服务，或运行 ./stop.sh"
  echo ""
}

# 运行主流程
main
