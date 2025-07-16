#!/bin/bash
set -e

# 설정
PROJECT_NAME="book-scan-performance"
AWS_REGION="ap-northeast-2"
IMAGE_TAG="${1:-latest}"

# 로깅 함수
log_info() { echo "[INFO] $1"; }
log_success() { echo "[SUCCESS] $1"; }
log_error() { echo "[ERROR] $1"; exit 1; }

# AWS CLI 및 Docker 확인
command -v aws >/dev/null 2>&1 || log_error "AWS CLI 필요"
command -v docker >/dev/null 2>&1 || log_error "Docker 필요"

# ECR 로그인
log_info "ECR 로그인 중..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $(aws sts get-caller-identity --query Account --output text).dkr.ecr.$AWS_REGION.amazonaws.com

# ECR 리포지토리 URI 가져오기
ECR_REPO_URI=$(aws ecr describe-repositories --repository-names "${PROJECT_NAME}/pdf-generator" --region $AWS_REGION --query 'repositories[0].repositoryUri' --output text)

if [ "$ECR_REPO_URI" = "None" ]; then
    log_error "ECR 리포지토리 없음: ${PROJECT_NAME}/pdf-generator"
fi

log_info "PDF 생성기 컨테이너 빌드 시작..."

# 빌드 컨텍스트로 이동
cd $(dirname $0)/..

# Docker build
docker build \
    --platform linux/arm64 \
    -t ${PROJECT_NAME}/pdf-generator:${IMAGE_TAG} \
    -f docker/pdf-generator/Dockerfile \
    .

# ECR 태그 및 푸시
docker tag ${PROJECT_NAME}/pdf-generator:${IMAGE_TAG} ${ECR_REPO_URI}:${IMAGE_TAG}

log_info "이미지 푸시 중..."
docker push ${ECR_REPO_URI}:${IMAGE_TAG}

log_success "PDF 생성기 컨테이너 빌드 완료: ${ECR_REPO_URI}:${IMAGE_TAG}"
