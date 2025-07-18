# Docker 이미지 빌드 및 푸시를 위한 최적화된 null_resource
# BuildKit 및 병렬 처리로 성능 대폭 개선

data "aws_caller_identity" "current_build" {}
data "aws_region" "current_build" {}

locals {
  account_id = data.aws_caller_identity.current_build.account_id
  region     = data.aws_region.current_build.id
}

# ECR 로그인 및 이미지 빌드/푸시를 위한 최적화된 null_resource
resource "null_resource" "docker_images" {
  # ECR 리포지토리가 생성된 후에만 실행
  depends_on = [
    aws_ecr_repository.fargate_processor,
    aws_ecr_repository.sagemaker_realesrgan,
    aws_ecr_repository.detect_skew_lambda,
    aws_ecr_repository.process_ocr_lambda,
    aws_ecr_repository.pdf_generator_lambda,
    aws_ecr_repository.orchestrator_lambda
  ]

  # 트리거: Dockerfile이나 소스 코드 변경 시 재빌드
  triggers = {
    # Dockerfile 변경 감지
    fargate_dockerfile      = filesha256("${path.module}/../workers/2_image_processing/skew_corrector/Dockerfile")
    detect_skew_dockerfile  = filesha256("${path.module}/../docker/detect-skew/Dockerfile")
    process_ocr_dockerfile  = filesha256("${path.module}/../docker/process-ocr/Dockerfile")
    pdf_gen_dockerfile      = filesha256("${path.module}/../docker/pdf-generator/Dockerfile")
    orchestrator_dockerfile = filesha256("${path.module}/../docker/orchestrator/Dockerfile")
    sagemaker_dockerfile    = filesha256("${path.module}/../sagemaker/Dockerfile")
    
    # 빌드 스크립트 변경 감지
    build_script_hash = filesha256("${path.module}/../scripts/commands.sh")
    
    # ECR 리포지토리 변경 감지
    ecr_repos = join(",", [
      aws_ecr_repository.fargate_processor.repository_url,
      aws_ecr_repository.sagemaker_realesrgan.repository_url,
      aws_ecr_repository.detect_skew_lambda.repository_url,
      aws_ecr_repository.process_ocr_lambda.repository_url,
      aws_ecr_repository.pdf_generator_lambda.repository_url,
      aws_ecr_repository.orchestrator_lambda.repository_url
    ])
  }

  # 최적화된 이미지 빌드 및 푸시 실행
  provisioner "local-exec" {
    command = <<-EOF
      set -e
      echo "🚀 [최적화] BuildKit 기반 병렬 Docker 빌드 시작..."
      
      # BuildKit 활성화 및 최적화 설정
      export DOCKER_BUILDKIT=1
      export BUILDKIT_PROGRESS=plain
      
      # ECR 로그인
      aws ecr get-login-password --region ${local.region} | docker login --username AWS --password-stdin ${local.account_id}.dkr.ecr.${local.region}.amazonaws.com
      
      # 빌드 디렉토리로 이동
      cd "${path.module}/.."
      
      # 병렬 빌드를 위한 백그라운드 프로세스 배열
      declare -a build_pids=()
      
      # Lambda 함수들 병렬 빌드 (ARM64)
      echo "⚡ [병렬] detect-skew Lambda 빌드 중..."
      (
        docker buildx build --platform linux/arm64 \
          --push \
          -t ${aws_ecr_repository.detect_skew_lambda.repository_url}:latest \
          -f docker/detect-skew/Dockerfile .
        echo "✅ detect-skew 완료"
      ) &
      build_pids+=($!)
      
      echo "⚡ [병렬] process-ocr Lambda 빌드 중..."
      (
        docker buildx build --platform linux/arm64 \
          --push \
          -t ${aws_ecr_repository.process_ocr_lambda.repository_url}:latest \
          -f docker/process-ocr/Dockerfile .
        echo "✅ process-ocr 완료"
      ) &
      build_pids+=($!)
      
      echo "⚡ [병렬] orchestrator Lambda 빌드 중..."
      (
        docker buildx build --platform linux/arm64 \
          --push \
          -t ${aws_ecr_repository.orchestrator_lambda.repository_url}:latest \
          -f docker/orchestrator/Dockerfile .
        echo "✅ orchestrator 완료"
      ) &
      build_pids+=($!)
      
      echo "⚡ [병렬] PDF generator Lambda 빌드 중..."
      (
        docker buildx build --platform linux/arm64 \
          --push \
          -t ${aws_ecr_repository.pdf_generator_lambda.repository_url}:latest \
          -f docker/pdf-generator/Dockerfile .
        echo "✅ PDF generator 완료"
      ) &
      build_pids+=($!)
      
      # Fargate 프로세서 빌드 (별도 ARM64)
      echo "⚡ [병렬] Fargate processor 빌드 중..."
      (
        docker buildx build --platform linux/arm64 \
          --push \
          -t ${aws_ecr_repository.fargate_processor.repository_url}:latest \
          -f workers/2_image_processing/skew_corrector/Dockerfile .
        echo "✅ Fargate processor 완료"
      ) &
      build_pids+=($!)
      
      # SageMaker 빌드 (AMD64) - AWS Support 공식 해결책 적용
      echo "⚡ [별도] SageMaker Real-ESRGAN 빌드 중..."
      (
        # AWS Support 권장: --provenance=false + --output type=docker
        docker buildx build --platform linux/amd64 \
          --provenance=false \
          --output type=docker \
          -t ${aws_ecr_repository.sagemaker_realesrgan.repository_url}:latest \
          -f sagemaker/Dockerfile . && \
        
        # ECR에 푸시 (Docker v2 형식으로 빌드됨)
        docker push ${aws_ecr_repository.sagemaker_realesrgan.repository_url}:latest
        
        echo "✅ SageMaker Real-ESRGAN 완료 (Docker v2 형식)"
      ) &
      build_pids+=($!)
      
      # 모든 병렬 빌드 완료 대기
      echo "⏳ [대기] 병렬 빌드 완료 중..."
      for pid in "$${build_pids[@]}"; do
        wait $pid || {
          echo "❌ [오류] 빌드 프로세스 $pid 실패"
          exit 1
        }
      done
      
      echo "🎉 [성공] 모든 Docker 이미지 빌드 및 푸시 완료!"
      echo "📊 [성능] BuildKit + 병렬 처리로 대폭 속도 향상!"
    EOF
    
    working_dir = path.module
  }
}

# 이미지 태그 확인을 위한 data source
data "aws_ecr_image" "fargate_image" {
  depends_on      = [null_resource.docker_images]
  repository_name = aws_ecr_repository.fargate_processor.name
  image_tag       = "latest"
}

data "aws_ecr_image" "detect_skew_image" {
  depends_on      = [null_resource.docker_images]
  repository_name = aws_ecr_repository.detect_skew_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "process_ocr_image" {
  depends_on      = [null_resource.docker_images]
  repository_name = aws_ecr_repository.process_ocr_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "pdf_generator_image" {
  depends_on      = [null_resource.docker_images]
  repository_name = aws_ecr_repository.pdf_generator_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "orchestrator_image" {
  depends_on      = [null_resource.docker_images]
  repository_name = aws_ecr_repository.orchestrator_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "sagemaker_image" {
  depends_on      = [null_resource.docker_images]
  repository_name = aws_ecr_repository.sagemaker_realesrgan.name
  image_tag       = "latest"
}