#!/bin/bash
# Monitor and optimize OCR pipeline operations using RTK + Headroom

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RTK="${PROJECT_ROOT}/rtk.exe"

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  OCR Pipeline Optimization Monitor (RTK + Headroom)       ║"
echo "╚═══════════════════════════════════════════════════════════╝"

# Function: Monitor Docker services
monitor_docker() {
  echo -e "\n📦 Docker Services (optimized output):"
  $RTK docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}

# Function: Monitor service logs
monitor_logs() {
  local service=$1
  local lines=${2:-20}
  echo -e "\n📝 Logs for $service (last $lines lines):"
  docker logs "$service" --tail "$lines" 2>&1 | $RTK log | head -30
}

# Function: Check disk usage
monitor_disk() {
  echo -e "\n💾 Model & Data Storage:"
  du -sh models/ 2>/dev/null | $RTK wc --lines
  du -sh .venv/ 2>/dev/null | $RTK wc --lines || true
}

# Function: Git status
monitor_git() {
  echo -e "\n📌 Git Status:"
  $RTK git status --short
}

# Function: Test execution
monitor_tests() {
  echo -e "\n🧪 Recent Test Results:"
  if [ -f "pytest.log" ]; then
    $RTK test pytest.log | tail -20
  else
    echo "No test results found"
  fi
}

# Function: Token savings
show_savings() {
  echo -e "\n📊 Token Optimization Savings:"
  echo "RTK Savings:"
  $RTK gain 2>/dev/null || echo "No gains recorded yet"

  echo -e "\nHeadroom Savings:"
  headroom savings 2>/dev/null || echo "Headroom not tracking yet"
}

# Main monitoring loop
main() {
  case "${1:-all}" in
    docker)
      monitor_docker
      ;;
    logs)
      monitor_logs "${2:-postgres}" "${3:-20}"
      ;;
    disk)
      monitor_disk
      ;;
    git)
      monitor_git
      ;;
    tests)
      monitor_tests
      ;;
    savings)
      show_savings
      ;;
    all)
      monitor_docker
      monitor_disk
      monitor_git
      show_savings
      ;;
    *)
      echo "Usage: $0 {docker|logs|disk|git|tests|savings|all}"
      exit 1
      ;;
  esac
}

main "$@"
