#!/bin/bash

# 가상환경 활성화
source /opt/venv/bin/activate

if [[ "$1" == "serve" ]]; then
    echo "Uvicorn 서버 시작 중..."
    exec /opt/venv/bin/uvicorn inference:app --host 0.0.0.0 --port 8080 --workers 1 --log-level info
else
    exec "$@"
fi
