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

# Lambda 레이어를 사용하는 함수들의 requirements.txt 파일 목록
REQUIREMENTS_FILES=(
  "$PROJECT_ROOT/workers/1_orchestration/initialize_state/requirements.txt"
  "$PROJECT_ROOT/workers/1_orchestration/orchestrator/requirements.txt"
  "$PROJECT_ROOT/workers/3_finalization/pdf_generator/requirements.txt"
  "$PROJECT_ROOT/workers/2_image_processing/upscaler/requirements.txt"
  "$PROJECT_ROOT/workers/3_finalization/summary_generator/requirements.txt"
)

# 각 requirements.txt 파일에서 의존성 설치
for req_file in "${REQUIREMENTS_FILES[@]}"; do
  if [ -f "$req_file" ]; then
    echo "Installing dependencies from $req_file..."
    pip3 install --platform manylinux2014_aarch64 --target "$PYTHON_DIR" --python-version 3.12 --only-binary=:all: -r "$req_file"
  else
    echo "Warning: $req_file not found, skipping."
  fi
done

# 추가적으로 필요한 라이브러리 (예: 폰트)
cp "$PROJECT_ROOT/config/NotoSansKR-Regular.ttf" "$PYTHON_DIR/NotoSansKR-Regular.ttf"

# Layer ZIP 파일 생성
cd "$LAYER_DIR"
zip -r "$PROJECT_ROOT/build/pdf-dependencies-layer.zip" python/

echo "Lambda Layer 생성 완료: $PROJECT_ROOT/build/pdf-dependencies-layer.zip"
