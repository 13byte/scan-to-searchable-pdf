#!/bin/bash

# Lambda 함수 빌드 스크립트 - Google Cloud Vision API 의존성 포함
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
LAMBDAS_DIR="$PROJECT_ROOT/lambdas"

# 빌드할 Lambda 함수 목록 (Google Vision API 사용 - Layer 전용)
LAMBDA_FUNCTIONS_WITH_LAYER=("trigger_pipeline" "detect_skew" "process_ocr")

# Google 라이브러리가 없는 함수들 (기존 방식)
LAMBDA_FUNCTIONS_STANDARD=("copy_cover_files" "generate_pdf" "final_cleanup" "handle_failure" "generate_run_summary" "upscale_image")

# 기존 dist 디렉토리 정리
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "Lambda 함수 빌드 시작..."

# Google Vision Layer 사용 함수들 (의존성 제외 빌드)
for func in "${LAMBDA_FUNCTIONS_WITH_LAYER[@]}"; do
    echo "빌드 중 (Layer용): $func"
    
    FUNC_DIR="$LAMBDAS_DIR/$func"
    BUILD_DIR="/tmp/lambda_build_$func"
    
    # 임시 빌드 디렉토리 생성
    rm -rf "$BUILD_DIR"
    mkdir -p "$BUILD_DIR"
    
    # 함수 코드만 복사 (requirements.txt 제외)
    cp "$FUNC_DIR/index.py" "$BUILD_DIR/" 2>/dev/null || true
    cp "$FUNC_DIR"/*.py "$BUILD_DIR/" 2>/dev/null || true
    
    # ZIP 파일 생성 (의존성 없이)
    cd "$BUILD_DIR"
    zip -r "$DIST_DIR/${func}.zip" . -x "*.pyc" "*__pycache__*" "requirements.txt"
    
    echo "  완료: $DIST_DIR/${func}.zip"
done

# 표준 함수들 (기존 방식으로 빌드)
for func in "${LAMBDA_FUNCTIONS_STANDARD[@]}"; do
    if [ -d "$LAMBDAS_DIR/$func" ]; then
        echo "압축 중: $func"
        cd "$LAMBDAS_DIR/$func"
        zip -r "$DIST_DIR/${func}.zip" . -x "*.pyc" "*__pycache__*"
        echo "  완료: $DIST_DIR/${func}.zip"
    fi
done

echo "모든 Lambda 함수 빌드 완료"
