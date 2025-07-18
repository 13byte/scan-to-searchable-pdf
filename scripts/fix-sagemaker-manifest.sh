#!/bin/bash
# SageMaker ECR OCI Manifest 문제 해결 스크립트 (skopeo 사용)
set -e

# 색상 출력 함수
log_info() { echo -e "\033[34m[정보]\033[0m $1"; }
log_success() { echo -e "\033[32m[성공]\033[0m $1"; }
log_error() { echo -e "\033[31m[오류]\033[0m $1"; exit 1; }
log_warn() { echo -e "\033[33m[경고]\033[0m $1"; }

# 프로젝트 디렉토리로 이동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
log_info "프로젝트 디렉토리로 이동: $(pwd)"

# 환경 변수 로드
if [ -f "config/.env" ]; then
    log_info "환경 변수 로딩 중..."
    export $(grep -v '^#' config/.env | xargs)
else
    log_error "환경 설정 파일을 찾을 수 없습니다: config/.env"
fi

# 필수 변수 확인
PROJECT_NAME="${PROJECT_NAME:-book-scan-performance}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || \
    log_error "AWS 인증 실패. 'aws configure' 실행 필요"

ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/sagemaker-realesrgan"
DOCKER_IMAGE="sagemaker-realesrgan-temp:latest"

log_info "설정 정보:"
log_info "  PROJECT_NAME: $PROJECT_NAME"
log_info "  AWS_REGION: $AWS_REGION"
log_info "  AWS_ACCOUNT_ID: $AWS_ACCOUNT_ID"
log_info "  ECR_REPO: $ECR_REPO"

# skopeo 설치 확인
log_info "skopeo 설치 확인 중..."
if ! command -v skopeo &> /dev/null; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        log_info "skopeo 설치 중... (Homebrew 필요)"
        if ! command -v brew &> /dev/null; then
            log_error "Homebrew가 설치되지 않았습니다. https://brew.sh 참조"
        fi
        brew install skopeo
    else
        log_error "skopeo 수동 설치 필요: https://github.com/containers/skopeo/blob/main/install.md"
    fi
fi
log_success "skopeo 설치 확인됨: $(skopeo --version)"

# Dockerfile 존재 확인
if [ ! -f "sagemaker/Dockerfile" ]; then
    log_error "SageMaker Dockerfile을 찾을 수 없습니다: sagemaker/Dockerfile"
fi

# ECR 리포지토리 존재 확인
log_info "ECR 리포지토리 확인 중..."
if ! aws ecr describe-repositories \
    --repository-names "${PROJECT_NAME}/sagemaker-realesrgan" \
    --region "$AWS_REGION" &>/dev/null; then
    log_error "ECR 리포지토리가 존재하지 않습니다. Terraform으로 먼저 생성하세요."
fi

# 기존 이미지 정리
log_info "ECR에서 기존 latest 이미지 삭제 중..."
aws ecr batch-delete-image \
    --repository-name "${PROJECT_NAME}/sagemaker-realesrgan" \
    --image-ids imageTag=latest \
    --region "$AWS_REGION" 2>/dev/null || log_warn "삭제할 이미지가 없습니다"

# 로컬 이미지 정리
log_info "로컬에서 기존 이미지 삭제 중..."
docker rmi "$DOCKER_IMAGE" 2>/dev/null || log_warn "삭제할 로컬 이미지가 없습니다"

# Docker 이미지 빌드
log_info "SageMaker Docker 이미지 빌드 중..."
docker build \
    --platform linux/amd64 \
    --no-cache \
    -t "$DOCKER_IMAGE" \
    -f sagemaker/Dockerfile .

# 빌드 결과 확인
log_info "빌드된 이미지 확인 중..."
if ! docker images "$DOCKER_IMAGE" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}" | tail -n +2; then
    log_error "이미지 빌드 실패"
fi

# skopeo ECR 로그인
log_info "skopeo ECR 로그인 중..."
aws ecr get-login-password --region "$AWS_REGION" | \
    skopeo login --username AWS --password-stdin "$ECR_REPO" || \
    log_error "skopeo ECR 로그인 실패"

# skopeo로 Docker v2s2 형식 변환 후 푸시
log_info "skopeo로 Docker v2 schema 2 형식 변환 후 ECR 푸시 중..."
skopeo copy \
    --format v2s2 \
    --dest-compress \
    docker-daemon:"$DOCKER_IMAGE" \
    docker://"$ECR_REPO":latest || \
    log_error "skopeo 복사 실패"

# 결과 검증
log_info "ECR 이미지 manifest 형식 확인 중..."
IMAGE_DETAILS=$(aws ecr describe-images \
    --repository-name "${PROJECT_NAME}/sagemaker-realesrgan" \
    --region "$AWS_REGION" \
    --query 'imageDetails[0].[imagePushedAt,imageSizeInBytes,imageManifestMediaType]' \
    --output text)

if [[ $IMAGE_DETAILS == *"application/vnd.docker.distribution.manifest.v2+json"* ]]; then
    log_success "✅ SageMaker 호환 Docker v2 schema 2 형식으로 성공적으로 변환됨!"
    log_info "이미지 정보: $IMAGE_DETAILS"
else
    log_error "❌ manifest 형식 변환 실패: $IMAGE_DETAILS"
fi

# 정리
log_info "로컬 이미지 정리 중..."
docker rmi "$DOCKER_IMAGE" 2>/dev/null || true

log_success "🎉 SageMaker ECR 이미지 준비 완료!"
log_info "💡 다음 단계: cd infra && terraform apply -target=aws_sagemaker_model.realesrgan"
