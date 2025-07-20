#!/bin/bash

# 가상환경 활성화
source /opt/venv/bin/activate

if [[ "$1" == "serve" ]]; then
    echo "Uvicorn 서버 시작 중..."
    # CPU 코어 수에 기반하여 워커 수 설정 (예: CPU 코어 수 * 2 + 1)
    # ml.g6e 인스턴스의 CPU 코어 수를 최대한 활용하여 동시 처리량 증대
    WORKERS=$(expr $(nproc) \* 2 + 1)
    echo "Uvicorn 워커 수: ${WORKERS}"
    exec /opt/venv/bin/uvicorn inference:app --host 0.0.0.0 --port 8080 --workers ${WORKERS} --log-level info
else
    exec "$@"
fi