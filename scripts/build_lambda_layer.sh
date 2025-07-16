#!/bin/bash

# Lambda Layer 의존성 빌드 스크립트
set -e

# 스크립트 위치를 기준으로 절대 경로 계산
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAYER_DIR="$PROJECT_ROOT/build/lambda-layer"
PYTHON_DIR="$LAYER_DIR/python"

# 기존 빌드 디렉토리 정리
rm -rf "$LAYER_DIR"
mkdir -p "$PYTHON_DIR"

# requirements.txt에서 의존성 설치
cd "$PYTHON_DIR"
pip3 install --platform manylinux2014_aarch64 --target . --python-version 3.12 --only-binary=:all: reportlab Pillow aws-lambda-powertools

# Layer ZIP 파일 생성
cd "$LAYER_DIR"
zip -r "$PROJECT_ROOT/build/pdf-dependencies-layer.zip" python/

echo "Lambda Layer 생성 완료: $PROJECT_ROOT/build/pdf-dependencies-layer.zip"
