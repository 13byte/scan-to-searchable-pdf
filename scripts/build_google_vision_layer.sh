#!/bin/bash

# Google Cloud Vision Lambda Layer 빌드 스크립트
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAYER_DIR="$PROJECT_ROOT/build/google-vision-layer"
PYTHON_DIR="$LAYER_DIR/python"

echo "Google Cloud Vision Lambda Layer 빌드 시작..."

# 기존 빌드 디렉토리 정리
rm -rf "$LAYER_DIR"
mkdir -p "$PYTHON_DIR"

# Google Cloud Vision 및 관련 의존성 설치 (x86_64 아키텍처로 변경)
cd "$PYTHON_DIR"
pip3 install \
    --platform manylinux2014_x86_64 \
    --target . \
    --python-version 3.12 \
    --only-binary=:all: \
    --no-deps \
    google-cloud-vision==3.10.2 \
    google-auth==2.29.0 \
    google-api-core==2.19.0 \
    grpcio==1.62.2 \
    grpcio-status==1.62.2 \
    googleapis-common-protos==1.63.0 \
    protobuf==4.25.3 \
    requests==2.31.0 \
    urllib3==2.2.1 \
    certifi==2024.2.2 \
    charset-normalizer==3.3.2 \
    idna==3.7 \
    cachetools==5.3.3 \
    pyasn1==0.6.0 \
    pyasn1-modules==0.4.0 \
    rsa==4.9 \
    six==1.16.0

# Layer ZIP 파일 생성
cd "$LAYER_DIR"
zip -r "$PROJECT_ROOT/build/google-vision-layer.zip" python/

echo "Google Cloud Vision Layer 생성 완료: $PROJECT_ROOT/build/google-vision-layer.zip"

# 크기 확인 및 최적화 검증
LAYER_SIZE=$(stat -f%z "$PROJECT_ROOT/build/google-vision-layer.zip" 2>/dev/null || stat -c%s "$PROJECT_ROOT/build/google-vision-layer.zip" 2>/dev/null)
echo "Layer 크기: $(($LAYER_SIZE / 1024 / 1024))MB"

# 의존성 호환성 검증
if [ $LAYER_SIZE -gt 268435456 ]; then
    echo "경고: Layer 크기가 256MB를 초과합니다. 의존성을 검토하세요."
    exit 1
fi

echo "Google Cloud Vision Layer 빌드 성공적으로 완료"
