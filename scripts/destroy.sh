#!/bin/bash

# 인프라 정리 스크립트

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 사용법
usage() {
    echo "사용법: $0 [OPTIONS]"
    echo ""
    echo "옵션:"
    echo "  --keep-data           S3 버킷 데이터 보존 (버킷만 비우기)"
    echo "  --force               확인 없이 강제 삭제"
    echo "  --partial             일부 리소스만 정리"
    echo "  --dry-run             실제 삭제 없이 계획만 표시"
    echo "  -h, --help            이 도움말 출력"
    echo ""
    echo "경고: 이 스크립트는 모든 인프라를 삭제합니다."
    echo "데이터 손실이 발생할 수 있으므로 신중하게 사용하세요."
}

# 환경 변수 로드
load_environment() {
    if [ -f "config/.env" ]; then
        export $(cat config/.env | grep -v '^#' | xargs)
    else
        log_error "config/.env 파일을 찾을 수 없습니다."
        exit 1
    fi
}

# 실행 중인 워크플로우 확인
check_running_workflows() {
    log_info "실행 중인 워크플로우 확인..."
    
    local state_machine_arn
    if command -v terraform &> /dev/null && [ -d "terraform" ]; then
        state_machine_arn=$(terraform -chdir=terraform output -raw state_machine_arn 2>/dev/null || echo "")
    fi
    
    if [ -n "$state_machine_arn" ]; then
        local running_executions=$(aws stepfunctions list-executions \
            --state-machine-arn "$state_machine_arn" \
            --status-filter RUNNING \
            --query 'executions[*].executionArn' \
            --output text)
        
        if [ -n "$running_executions" ]; then
            log_warn "다음 워크플로우가 실행 중입니다:"
            echo "$running_executions"
            
            read -p "실행 중인 워크플로우를 중단하시겠습니까? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                for arn in $running_executions; do
                    aws stepfunctions stop-execution --execution-arn "$arn" --cause "Infrastructure cleanup"
                    log_info "워크플로우 중단: $arn"
                done
                
                log_info "워크플로우 중단 완료까지 대기 중..."
                sleep 30
            else
                log_error "실행 중인 워크플로우가 있으면 인프라를 안전하게 삭제할 수 없습니다."
                exit 1
            fi
        fi
    fi
}

# S3 버킷 비우기
empty_s3_buckets() {
    local keep_data="$1"
    
    log_info "S3 버킷 정리 중..."
    
    local buckets=("$INPUT_BUCKET_NAME" "$OUTPUT_BUCKET_NAME" "$TEMP_BUCKET_NAME")
    
    for bucket in "${buckets[@]}"; do
        if aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
            log_info "S3 버킷 '$bucket' 정리 중..."
            
            # 버킷 버전 확인
            local versioning=$(aws s3api get-bucket-versioning --bucket "$bucket" --query 'Status' --output text 2>/dev/null || echo "")
            
            if [ "$versioning" = "Enabled" ]; then
                # 버전이 활성화된 경우 모든 버전 삭제
                aws s3api delete-objects --bucket "$bucket" \
                    --delete "$(aws s3api list-object-versions --bucket "$bucket" \
                    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
                    --output json)" 2>/dev/null || true
                
                # 삭제 마커도 제거
                aws s3api delete-objects --bucket "$bucket" \
                    --delete "$(aws s3api list-object-versions --bucket "$bucket" \
                    --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
                    --output json)" 2>/dev/null || true
            else
                # 일반 객체 삭제
                aws s3 rm s3://"$bucket" --recursive 2>/dev/null || true
            fi
            
            log_success "S3 버킷 '$bucket' 비우기 완료"
        else
            log_warn "S3 버킷 '$bucket'을 찾을 수 없습니다."
        fi
    done
}

# ECR 이미지 정리
cleanup_ecr_images() {
    log_info "ECR 이미지 정리 중..."
    
    local repositories=("${PROJECT_NAME}-opencv" "${PROJECT_NAME}-realesrgan")
    
    for repo in "${repositories[@]}"; do
        if aws ecr describe-repositories --repository-names "$repo" 2>/dev/null; then
            log_info "ECR 리포지토리 '$repo' 이미지 삭제 중..."
            
            # 모든 이미지 삭제
            local image_digests=$(aws ecr list-images --repository-name "$repo" \
                --query 'imageIds[*].imageDigest' --output text)
            
            if [ -n "$image_digests" ]; then
                aws ecr batch-delete-image --repository-name "$repo" \
                    --image-ids "$(aws ecr list-images --repository-name "$repo" \
                    --query 'imageIds' --output json)"
                
                log_success "ECR 리포지토리 '$repo' 이미지 삭제 완료"
            else
                log_info "ECR 리포지토리 '$repo'에 삭제할 이미지가 없습니다."
            fi
        else
            log_warn "ECR 리포지토리 '$repo'을 찾을 수 없습니다."
        fi
    done
}

# Lambda 함수 삭제
cleanup_lambda_functions() {
    log_info "Lambda 함수 정리 중..."
    
    local lambda_functions=("detect-skew" "perform-ocr" "upscale-image" "generate-pdf" "cleanup")
    
    for func in "${lambda_functions[@]}"; do
        local func_name="${PROJECT_NAME}-${func}"
        
        if aws lambda get-function --function-name "$func_name" 2>/dev/null; then
            aws lambda delete-function --function-name "$func_name"
            log_success "Lambda 함수 '$func_name' 삭제 완료"
        else
            log_warn "Lambda 함수 '$func_name'을 찾을 수 없습니다."
        fi
    done
}

# SageMaker 엔드포인트 정리
cleanup_sagemaker_endpoint() {
    log_info "SageMaker 엔드포인트 정리 중..."
    
    local endpoint_name="${PROJECT_NAME}-realesrgan-endpoint"
    
    if aws sagemaker describe-endpoint --endpoint-name "$endpoint_name" 2>/dev/null; then
        log_info "SageMaker 엔드포인트 '$endpoint_name' 삭제 중..."
        aws sagemaker delete-endpoint --endpoint-name "$endpoint_name"
        
        # 엔드포인트 삭제 완료 대기
        log_info "엔드포인트 삭제 완료 대기 중..."
        aws sagemaker wait endpoint-deleted --endpoint-name "$endpoint_name" || true
        
        log_success "SageMaker 엔드포인트 삭제 완료"
    else
        log_warn "SageMaker 엔드포인트 '$endpoint_name'을 찾을 수 없습니다."
    fi
}

# ECS 태스크 중지
stop_ecs_tasks() {
    log_info "실행 중인 ECS 태스크 중지 중..."
    
    local cluster_name="${PROJECT_NAME}-cluster"
    
    if aws ecs describe-clusters --clusters "$cluster_name" 2>/dev/null; then
        local running_tasks=$(aws ecs list-tasks --cluster "$cluster_name" \
            --desired-status RUNNING --query 'taskArns[*]' --output text)
        
        if [ -n "$running_tasks" ]; then
            for task in $running_tasks; do
                aws ecs stop-task --cluster "$cluster_name" --task "$task" \
                    --reason "Infrastructure cleanup"
                log_info "ECS 태스크 중지: $task"
            done
            
            log_info "ECS 태스크 중지 완료 대기 중..."
            sleep 30
        else
            log_info "중지할 ECS 태스크가 없습니다."
        fi
    else
        log_warn "ECS 클러스터 '$cluster_name'을 찾을 수 없습니다."
    fi
}

# CloudWatch 로그 그룹 정리
cleanup_cloudwatch_logs() {
    log_info "CloudWatch 로그 그룹 정리 중..."
    
    local log_groups=(
        "/aws/lambda/${PROJECT_NAME}-detect-skew"
        "/aws/lambda/${PROJECT_NAME}-perform-ocr"
        "/aws/lambda/${PROJECT_NAME}-upscale-image"
        "/aws/lambda/${PROJECT_NAME}-generate-pdf"
        "/aws/lambda/${PROJECT_NAME}-cleanup"
        "/ecs/${PROJECT_NAME}-fargate"
    )
    
    for log_group in "${log_groups[@]}"; do
        if aws logs describe-log-groups --log-group-name-prefix "$log_group" \
           --query 'logGroups[0].logGroupName' --output text 2>/dev/null | grep -q "$log_group"; then
            aws logs delete-log-group --log-group-name "$log_group"
            log_success "CloudWatch 로그 그룹 삭제: $log_group"
        else
            log_warn "CloudWatch 로그 그룹을 찾을 수 없습니다: $log_group"
        fi
    done
}

# Google Cloud 시크릿 정리
cleanup_secrets() {
    log_info "AWS Secrets Manager 시크릿 정리 중..."
    
    local secret_name="google-vision-credentials"
    
    if aws secretsmanager describe-secret --secret-id "$secret_name" 2>/dev/null; then
        aws secretsmanager delete-secret --secret-id "$secret_name" --force-delete-without-recovery
        log_success "시크릿 삭제 완료: $secret_name"
    else
        log_warn "시크릿을 찾을 수 없습니다: $secret_name"
    fi
}

# Terraform 인프라 삭제
destroy_terraform_infrastructure() {
    local dry_run="$1"
    
    if [ ! -d "terraform" ]; then
        log_error "terraform 디렉토리를 찾을 수 없습니다."
        return 1
    fi
    
    cd terraform
    
    log_info "Terraform 인프라 삭제 계획 생성 중..."
    
    if [ "$dry_run" = true ]; then
        terraform plan -destroy \
            -var="aws_account_id=${AWS_ACCOUNT_ID}" \
            -var="google_cloud_project_id=${GOOGLE_CLOUD_PROJECT_ID}"
    else
        terraform plan -destroy \
            -var="aws_account_id=${AWS_ACCOUNT_ID}" \
            -var="google_cloud_project_id=${GOOGLE_CLOUD_PROJECT_ID}" \
            -out=destroy.tfplan
        
        log_warn "다음 리소스들이 삭제됩니다:"
        terraform show destroy.tfplan
        
        echo
        read -p "모든 인프라를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다. (yes/no): " -r
        
        if [ "$REPLY" = "yes" ]; then
            terraform apply destroy.tfplan
            log_success "Terraform 인프라 삭제 완료"
        else
            log_warn "인프라 삭제가 취소되었습니다."
            rm -f destroy.tfplan
            cd ..
            return 1
        fi
    fi
    
    cd ..
}

# 완전 정리
full_cleanup() {
    local keep_data="$1"
    local force="$2"
    local dry_run="$3"
    
    if [ "$force" != true ] && [ "$dry_run" != true ]; then
        echo
        log_warn "경고: 이 작업은 모든 인프라와 데이터를 삭제합니다!"
        log_warn "삭제될 리소스:"
        echo "  - S3 버킷 및 모든 데이터"
        echo "  - Lambda 함수"
        echo "  - ECS 클러스터 및 태스크"
        echo "  - SageMaker 엔드포인트"
        echo "  - Step Functions 상태 머신"
        echo "  - ECR 리포지토리 및 이미지"
        echo "  - IAM 역할 및 정책"
        echo "  - VPC 및 네트워킹 리소스"
        echo "  - CloudWatch 로그"
        echo "  - Secrets Manager 시크릿"
        echo
        
        read -p "정말로 계속하시겠습니까? 'DELETE'를 입력하세요: " -r
        
        if [ "$REPLY" != "DELETE" ]; then
            log_info "정리 작업이 취소되었습니다."
            return 0
        fi
    fi
    
    if [ "$dry_run" = true ]; then
        log_info "DRY RUN: 실제 삭제 없이 계획만 표시합니다."
        destroy_terraform_infrastructure true
        return 0
    fi
    
    log_info "=========================================="
    log_info "인프라 정리 시작"
    log_info "=========================================="
    
    # 1. 실행 중인 워크플로우 확인 및 중지
    check_running_workflows
    
    # 2. 실행 중인 리소스 중지
    stop_ecs_tasks
    cleanup_sagemaker_endpoint
    
    # 3. 데이터 정리
    if [ "$keep_data" != true ]; then
        empty_s3_buckets false
    else
        log_info "데이터 보존 옵션으로 S3 버킷 데이터를 유지합니다."
    fi
    
    # 4. 컨테이너 이미지 정리
    cleanup_ecr_images
    
    # 5. Lambda 함수 정리 (Terraform 외부에서 생성된 경우)
    cleanup_lambda_functions
    
    # 6. CloudWatch 로그 정리
    cleanup_cloudwatch_logs
    
    # 7. 시크릿 정리
    cleanup_secrets
    
    # 8. Terraform 인프라 삭제
    destroy_terraform_infrastructure false
    
    log_success "=========================================="
    log_success "인프라 정리 완료!"
    log_success "=========================================="
}

# 부분 정리
partial_cleanup() {
    log_info "부분 정리 옵션을 선택하세요:"
    echo "1) S3 버킷 비우기만"
    echo "2) 실행 중인 리소스만 중지"
    echo "3) CloudWatch 로그만 삭제"
    echo "4) ECR 이미지만 삭제"
    echo "5) Lambda 함수만 삭제"
    echo "6) 취소"
    
    read -p "선택 (1-6): " -n 1 -r
    echo
    
    case $REPLY in
        1)
            empty_s3_buckets false
            ;;
        2)
            stop_ecs_tasks
            cleanup_sagemaker_endpoint
            ;;
        3)
            cleanup_cloudwatch_logs
            ;;
        4)
            cleanup_ecr_images
            ;;
        5)
            cleanup_lambda_functions
            ;;
        6)
            log_info "정리 작업이 취소되었습니다."
            ;;
        *)
            log_error "잘못된 선택입니다."
            ;;
    esac
}

# 메인 함수
main() {
    local keep_data=false
    local force=false
    local partial=false
    local dry_run=false
    
    # 명령행 인수 파싱
    while [[ $# -gt 0 ]]; do
        case $1 in
            --keep-data)
                keep_data=true
                shift
                ;;
            --force)
                force=true
                shift
                ;;
            --partial)
                partial=true
                shift
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "알 수 없는 옵션: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    load_environment
    
    if [ "$partial" = true ]; then
        partial_cleanup
    else
        full_cleanup "$keep_data" "$force" "$dry_run"
    fi
}

# 필수 도구 확인
check_requirements() {
    local missing_tools=()
    
    for tool in "terraform" "aws"; do
        if ! command -v $tool &> /dev/null; then
            missing_tools+=($tool)
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        log_error "다음 도구들이 필요합니다: ${missing_tools[*]}"
        exit 1
    fi
}

check_requirements
main "$@"
