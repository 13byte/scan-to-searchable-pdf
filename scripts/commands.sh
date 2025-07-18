#!/bin/bash
set -e

# --- 로깅 및 색상 정의 ---
log_info() { echo -e "\033[34m[정보]\033[0m $1" >&2; }
log_success() { echo -e "\033[32m[성공]\033[0m $1" >&2; }
log_error() {
  echo -e "\033[31m[오류]\033[0m $1" >&2
  exit 1
}
log_warn() { echo -e "\033[33m[경고]\033[0m $1" >&2; }

# --- 환경 변수 및 공통 설정 ---
COMMAND=$1

if [ -z "$AWS_REGION" ] || [ -z "$PROJECT_NAME" ]; then
  log_error "AWS_REGION and PROJECT_NAME must be set in the environment."
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# --- 명령어 처리 ---
case "$COMMAND" in
deploy)
  log_info "🚀 최적화된 인프라 배포 시작 (SageMaker 단계적 배포)..."

  # Docker Buildx 초기화 및 최적화
  log_info "⚡ Docker BuildKit 최적화 설정 중..."
  export DOCKER_BUILDKIT=1
  export BUILDKIT_PROGRESS=plain
  
  # Docker buildx 빌더 확인/생성
  if ! docker buildx inspect multiarch-builder >/dev/null 2>&1; then
    log_info "📦 다중 아키텍처 빌더 생성 중..."
    docker buildx create --name multiarch-builder --driver docker-container --use || true
    docker buildx inspect multiarch-builder --bootstrap
  else
    docker buildx use multiarch-builder
  fi

  log_info "🔧 Terraform 초기화 중..."
  (cd infra && terraform init)
  
  log_info "📦 ECR 리포지토리 생성 중..."
  (cd infra && terraform apply -auto-approve \
    -target=aws_ecr_repository.fargate_processor \
    -target=aws_ecr_repository.sagemaker_realesrgan \
    -target=aws_ecr_repository.detect_skew_lambda \
    -target=aws_ecr_repository.process_ocr_lambda \
    -target=aws_ecr_repository.pdf_generator_lambda \
    -target=aws_ecr_repository.orchestrator_lambda)

  log_info "⚡ Docker 이미지 병렬 빌드 시작 (BuildKit + Multi-stage)..."
  (cd infra && terraform apply -auto-approve \
    -target=null_resource.docker_images)

  log_info "🏗️ 메인 AWS 리소스 배포 중..."
  (cd infra && terraform apply -auto-approve \
    $(terraform state list | grep -v 'aws_sagemaker' | sed 's/^/-target=/' | tr '\n' ' '))

  log_info "🤖 SageMaker Real-ESRGAN 모델 배포 중... (15분 소요 예상)"
  (cd infra && terraform apply -auto-approve \
    -target=aws_sagemaker_model.realesrgan \
    -target=aws_sagemaker_endpoint_configuration.realesrgan \
    -target=aws_sagemaker_endpoint.realesrgan)

  log_success "🎉 전체 인프라 배포 완료! (SageMaker 포함)"
  log_info "📊 확인: DynamoDB, Lambda 함수, SageMaker 엔드포인트가 AWS 콘솔에서 활성화됨"
  ;;
start)
  log_info "Starting the image processing pipeline..."

  INPUT_BUCKET=$(cd infra && terraform output -raw s3_input_bucket_name)
  TEMP_BUCKET=$(cd infra && terraform output -raw s3_temp_bucket_name)
  OUTPUT_BUCKET=$(cd infra && terraform output -raw s3_output_bucket_name)
  STATE_MACHINE_ARN=$(cd infra && terraform output -raw state_machine_arn)

  if [ -z "$INPUT_BUCKET" ] || [ -z "$TEMP_BUCKET" ] || [ -z "$OUTPUT_BUCKET" ] || [ -z "$STATE_MACHINE_ARN" ]; then
    log_error "Could not retrieve necessary outputs from Terraform. Please run 'deploy' first."
  fi

  log_info "Uploading images from 'scan_images/' to 's3://${INPUT_BUCKET}/scan_images/'..."
  aws s3 sync "scan_images/" "s3://${INPUT_BUCKET}/scan_images/" --exclude ".*" --quiet

  SFN_INPUT=$(cat <<-JSON
{
  "input_bucket": "${INPUT_BUCKET}",
  "input_prefix": "scan_images/",
  "output_bucket": "${OUTPUT_BUCKET}",
  "temp_bucket": "${TEMP_BUCKET}"
}
JSON
)

  log_info "Starting Step Functions workflow..."
  EXECUTION_ARN=$(aws stepfunctions start-execution \
    --state-machine-arn "$STATE_MACHINE_ARN" \
    --input "$SFN_INPUT" \
    --query "executionArn" --output text)

  log_success "Pipeline started! Execution ARN:"
  log_info "$EXECUTION_ARN"
  log_info "You can monitor the progress in the AWS Step Functions console."
  ;;
*)
  log_error "Unknown command: '$COMMAND'. Available commands: deploy, start"
  ;;
esac
