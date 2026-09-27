#!/usr/bin/env bash
# Подготовка локального git-репозитория (без push).
# Если `git init` падает из‑за Xcode license: sudo xcodebuild -license
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
  if grep -qE 'sk-|API_KEY=.+[A-Za-z0-9]{20}' .env 2>/dev/null; then
    echo "OK: .env на месте (в git не попадёт — см. .gitignore)"
  fi
fi

git init -b main
git add -A
git status
echo
echo "Дальше (когда будете готовы):"
echo "  git commit -m \"Initial: Цифровой Ординатор (Agentic/RAG СППР АГ)\""
echo "  gh repo create ... --source=. --private --push"
echo "или: скажите ассистенту «закоммить и запушь на GitHub»"
