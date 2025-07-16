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

# --- Docker 이미지 빌드 및 푸시 함수 ---
build_and_push() {
  local dockerfile_path=$1
  local ecr_repo_uri=$2
  local context_path=$3
  local platform_arg=$4
  # Terraform과 일치하도록 latest 태그 고정 사용
  local image_tag="latest"

  log_info "Building and pushing image to '${ecr_repo_uri}:${image_tag}'..."
  aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" >&2
  
  # SageMaker/Lambda 호환성을 위한 Direct Registry Push
  DOCKER_BUILDKIT=1 docker buildx build \
    --platform ${platform_arg#--platform } \
    --provenance=false \
    --output type=image,push=true,oci-mediatypes=false \
    -t "${ecr_repo_uri}:${image_tag}" \
    -f "${dockerfile_path}" \
    "${context_path}" >&2
    
  log_success "Image push complete: ${ecr_repo_uri}:${image_tag}"
  echo "$image_tag"
}

# --- 명령어 처리 ---
case "$COMMAND" in
deploy)
  log_info "Starting infrastructure deployment..."

  log_info "Initializing Terraform and creating ECR repositories first..."
  (cd infra && terraform init)
  (cd infra && terraform apply -auto-approve -target=aws_ecr_repository.fargate_processor -target=aws_ecr_repository.sagemaker_realesrgan -target=aws_ecr_repository.detect_skew_lambda -target=aws_ecr_repository.process_ocr_lambda -target=aws_ecr_repository.trigger_pipeline_lambda)

  log_info "Building and pushing Docker images..."
  FARGATE_ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/skew-corrector"
  DETECT_SKEW_LAMBDA_ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/detect-skew"
  PROCESS_OCR_LAMBDA_ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/process-ocr"
  TRIGGER_PIPELINE_LAMBDA_ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/trigger-pipeline"
  SAGEMAKER_ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT_NAME}/sagemaker-realesrgan"

  FARGATE_IMAGE_TAG=$(build_and_push "workers/2_image_processing/skew_corrector/Dockerfile" "$FARGATE_ECR_REPO" "." "--platform linux/arm64")
  DETECT_SKEW_LAMBDA_IMAGE_TAG=$(build_and_push "docker/detect-skew/Dockerfile" "$DETECT_SKEW_LAMBDA_ECR_REPO" "." "--platform linux/arm64")
  PROCESS_OCR_LAMBDA_IMAGE_TAG=$(build_and_push "docker/process-ocr/Dockerfile" "$PROCESS_OCR_LAMBDA_ECR_REPO" "." "--platform linux/arm64")
  TRIGGER_PIPELINE_LAMBDA_IMAGE_TAG=$(build_and_push "docker/trigger-pipeline/Dockerfile" "$TRIGGER_PIPELINE_LAMBDA_ECR_REPO" "." "--platform linux/arm64")
  SAGEMAKER_IMAGE_TAG=$(build_and_push "sagemaker/Dockerfile" "$SAGEMAKER_ECR_REPO" "." "--platform linux/amd64")

  log_info "Deploying the rest of the AWS resources..."
  (cd infra && terraform apply -auto-approve \
    -var="fargate_image_tag=${FARGATE_IMAGE_TAG}" \
    -var="detect_skew_lambda_image_tag=${DETECT_SKEW_LAMBDA_IMAGE_TAG}" \
    -var="process_ocr_lambda_image_tag=${PROCESS_OCR_LAMBDA_IMAGE_TAG}" \
    -var="trigger_pipeline_lambda_image_tag=${TRIGGER_PIPELINE_LAMBDA_IMAGE_TAG}" \
    -var="sagemaker_image_tag=${SAGEMAKER_IMAGE_TAG}")

  log_success "Infrastructure deployment completed successfully."
  log_info "Please check 'config/.env' and update the Google API key in AWS Secrets Manager if needed."
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
