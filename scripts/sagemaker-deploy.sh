#!/bin/bash
set -e

# 로깅 함수
log_info() { echo -e "\033[34m[정보]\033[0m $1" >&2; }
log_success() { echo -e "\033[32m[성공]\033[0m $1" >&2; }
log_error() { echo -e "\033[31m[오류]\033[0m $1" >&2; exit 1; }
log_warn() { echo -e "\033[33m[경고]\033[0m $1" >&2; }

COMMAND=$1

case "$COMMAND" in
    deploy-sagemaker)
        log_info "🤖 SageMaker Real-ESRGAN 모델 배포 시작..."
        
        cd infra
        
        # SageMaker 리소스만 배포
        log_info "📦 SageMaker 모델 생성 중... (15분 소요 예상)"
        terraform apply -auto-approve \
            -target=aws_sagemaker_model.realesrgan \
            -target=aws_sagemaker_endpoint_configuration.realesrgan \
            -target=aws_sagemaker_endpoint.realesrgan
        
        cd ..
        log_success "🎉 SageMaker 엔드포인트 배포 완료!"
        log_info "📊 엔드포인트 상태: AWS 콘솔에서 확인 가능"
        ;;
    
    check-sagemaker)
        log_info "🔍 SageMaker 엔드포인트 상태 확인 중..."
        
        ENDPOINT_NAME=$(cd infra && terraform output -raw sagemaker_endpoint_name 2>/dev/null || echo "")
        
        if [ -z "$ENDPOINT_NAME" ]; then
            log_warn "SageMaker 엔드포인트가 아직 생성되지 않았습니다."
            exit 1
        fi
        
        aws sagemaker describe-endpoint \
            --endpoint-name "$ENDPOINT_NAME" \
            --query 'EndpointStatus' \
            --output text
        ;;
    
    deploy-without-sagemaker)
        log_info "🚀 SageMaker 제외 인프라 배포 시작..."
        
        cd infra
        
        # SageMaker 제외한 모든 리소스 배포
        terraform apply -auto-approve \
            -target=aws_ecr_repository.fargate_processor \
            -target=aws_ecr_repository.detect_skew_lambda \
            -target=aws_ecr_repository.process_ocr_lambda \
            -target=aws_ecr_repository.pdf_generator_lambda \
            -target=aws_ecr_repository.orchestrator_lambda \
            -target=null_resource.docker_images
        
        # Lambda 및 기타 리소스 배포
        terraform apply -auto-approve \
            --exclude='aws_sagemaker_*'
        
        cd ..
        log_success "🎉 메인 인프라 배포 완료! (SageMaker 제외)"
        ;;
    
    *)
        log_error "알 수 없는 명령어: '$COMMAND'"
        echo "사용 가능한 명령어:"
        echo "  deploy-without-sagemaker  - SageMaker 제외 배포"
        echo "  deploy-sagemaker         - SageMaker만 별도 배포"
        echo "  check-sagemaker          - SageMaker 상태 확인"
        ;;
esac