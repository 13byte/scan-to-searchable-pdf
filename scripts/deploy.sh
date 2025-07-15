#!/bin/bash
set -e

# ==============================================================================
# 책 스캔 자동화 시스템 배포 스크립트 (경로 문제 해결 버전)
# ==============================================================================

# --- 스크립트의 실제 위치를 기준으로 프로젝트 루트 디렉토리로 이동 ---
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
PROJECT_ROOT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_ROOT_DIR"

# --- 설정 및 로그 함수 ---
BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- 변수 설정 ---
TF_VARS_FILE="terraform/variables.tf"
PROJECT_NAME=$(grep -A 2 'variable "project_name"' "$TF_VARS_FILE" | grep 'default' | awk -F'"' '{print $2}')
PROJECT_NAME=${PROJECT_NAME:-"book-scan-pipe"}

AWS_REGION=$(grep -A 2 'variable "aws_region"' "$TF_VARS_FILE" | grep 'default' | awk -F'"' '{print $2}')
AWS_REGION=${AWS_REGION:-"ap-northeast-2"}

# --- 1. 필수 도구 확인 ---
log_info "필수 도구(aws, docker, terraform)를 확인합니다..."
for tool in aws docker terraform; do
    if ! command -v $tool &> /dev/null; then
        log_error "'$tool'이 설치되어 있지 않습니다. 설치 후 다시 시도하세요."
    fi
done
log_success "모든 필수 도구가 준비되었습니다."

# --- 2. Terraform으로 인프라 배포 (ECR 리포지토리 먼저 생성) ---
log_info "Terraform으로 모든 클라우드 인프라를 배포합니다..."

# .env 파일에서 변수 가져오기 (이제 올바른 경로에서 찾음)
if [ ! -f "config/.env" ]; then
    log_error "'config/.env' 파일이 없습니다. 'config/.env.example'을 복사하여 생성하고 필요한 값들을 설정하세요."
fi
GCP_PROJECT_ID=$(grep 'GCP_PROJECT_ID' config/.env | cut -d '=' -f2)
GOOGLE_CREDENTIALS_PATH=$(grep 'GOOGLE_CREDENTIALS_PATH' config/.env | cut -d '=' -f2)

if [ -z "$GCP_PROJECT_ID" ] || [ -z "$GOOGLE_CREDENTIALS_PATH" ]; then
    log_error "'config/.env' 파일에 'GCP_PROJECT_ID' 또는 'GOOGLE_CREDENTIALS_PATH'가 설정되지 않았습니다."
fi

# Terraform 디렉토리로 이동하여 실행
cd terraform
terraform init -upgrade
terraform apply -auto-approve \
    -var="gcp_project_id=${GCP_PROJECT_ID}" \
    -var="google_credentials_path=${GOOGLE_CREDENTIALS_PATH}"
cd ..

log_success "인프라 배포가 성공적으로 완료되었습니다!"

# --- 3. AWS 인증 및 ECR 로그인 ---
log_info "AWS 계정을 확인하고 ECR에 로그인합니다..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    log_error "AWS 인증에 실패했습니다. 'aws configure'를 실행하여 자격 증명을 설정하세요."
fi
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
log_success "ECR 로그인 완료 (계정 ID: ${AWS_ACCOUNT_ID})."

# --- 4. Docker 이미지 빌드 및 푸시 ---
build_and_push() {
    local context_path=$1
    local repo_name=$2
    local ecr_repo_url="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${repo_name}:latest"
    
    log_info ">> '${repo_name}' 이미지 빌드 및 푸시를 시작합니다..."
    
    # SageMaker 호환성을 위한 Direct Registry Push
    docker buildx build \
        --platform linux/amd64 \
        --provenance=false \
        --output type=image,push=true,oci-mediatypes=false \
        --tag "$ecr_repo_url" \
        "$context_path"
    
    log_success ">> '${repo_name}' 이미지 푸시가 완료되었습니다."
}

build_and_push "fargate" "${PROJECT_NAME}-fargate-processor"
build_and_push "sagemaker" "${PROJECT_NAME}-sagemaker-upscaler"
build_and_push "workers/2_image_processing/vision_api_handler" "${PROJECT_NAME}/vision-api-handler"

log_success "모든 Docker 이미지를 ECR에 성공적으로 푸시했습니다."

# --- 5. 배포 결과 출력 ---
echo
log_info "=================================================="
log_info "배포된 주요 리소스 정보:"
log_info "=================================================="
terraform -chdir=terraform output
log_info "=================================================="
