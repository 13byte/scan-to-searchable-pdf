# Docker 이미지 빌드 및 푸시를 위한 null_resource
# 이미지 존재를 보장하여 Lambda/SageMaker 배포 전 의존성 해결

data "aws_caller_identity" "current_build" {}
data "aws_region" "current_build" {}

locals {
  account_id = data.aws_caller_identity.current_build.account_id
  region     = data.aws_region.current_build.id
}

# ECR 로그인 및 이미지 빌드/푸시를 위한 null_resource
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
    fargate_dockerfile     = filesha256("${path.module}/../workers/2_image_processing/skew_corrector/Dockerfile")
    detect_skew_dockerfile = filesha256("${path.module}/../docker/detect-skew/Dockerfile")
    process_ocr_dockerfile = filesha256("${path.module}/../docker/process-ocr/Dockerfile")
    pdf_gen_dockerfile     = filesha256("${path.module}/../docker/pdf-generator/Dockerfile")
    orchestrator_dockerfile = filesha256("${path.module}/../docker/orchestrator/Dockerfile")
    sagemaker_dockerfile   = filesha256("${path.module}/../sagemaker/Dockerfile")
    
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

  # 이미지 빌드 및 푸시 실행
  provisioner "local-exec" {
    command = <<-EOF
      set -e
      echo "[INFO] Starting Docker image builds..."
      
      # ECR 로그인
      aws ecr get-login-password --region ${local.region} | docker login --username AWS --password-stdin ${local.account_id}.dkr.ecr.${local.region}.amazonaws.com
      
      # 빌드 디렉토리로 이동
      cd "${path.module}/.."
      
      # 각 이미지 빌드 및 푸시 (병렬 처리 안함 - 안정성 우선)
      echo "[INFO] Building Fargate processor..."
      DOCKER_BUILDKIT=0 docker build --platform linux/arm64 \
        -t ${aws_ecr_repository.fargate_processor.repository_url}:latest \
        -f workers/2_image_processing/skew_corrector/Dockerfile .
      docker push ${aws_ecr_repository.fargate_processor.repository_url}:latest
      
      echo "[INFO] Building detect-skew Lambda..."
      DOCKER_BUILDKIT=0 docker build --platform linux/arm64 \
        -t ${aws_ecr_repository.detect_skew_lambda.repository_url}:latest \
        -f docker/detect-skew/Dockerfile .
      docker push ${aws_ecr_repository.detect_skew_lambda.repository_url}:latest
      
      echo "[INFO] Building process-ocr Lambda..."
      DOCKER_BUILDKIT=0 docker build --platform linux/arm64 \
        -t ${aws_ecr_repository.process_ocr_lambda.repository_url}:latest \
        -f docker/process-ocr/Dockerfile .
      docker push ${aws_ecr_repository.process_ocr_lambda.repository_url}:latest
      
      echo "[INFO] Building PDF generator Lambda..."
      DOCKER_BUILDKIT=0 docker build --platform linux/arm64 \
        -t ${aws_ecr_repository.pdf_generator_lambda.repository_url}:latest \
        -f docker/pdf-generator/Dockerfile .
      docker push ${aws_ecr_repository.pdf_generator_lambda.repository_url}:latest
      
      echo "[INFO] Building orchestrator Lambda..."
      DOCKER_BUILDKIT=0 docker build --platform linux/arm64 \
        -t ${aws_ecr_repository.orchestrator_lambda.repository_url}:latest \
        -f docker/orchestrator/Dockerfile .
      docker push ${aws_ecr_repository.orchestrator_lambda.repository_url}:latest
      
      echo "[INFO] Building SageMaker Real-ESRGAN..."
      DOCKER_BUILDKIT=0 docker build --platform linux/amd64 \
        -t ${aws_ecr_repository.sagemaker_realesrgan.repository_url}:latest \
        -f sagemaker/Dockerfile .
      docker push ${aws_ecr_repository.sagemaker_realesrgan.repository_url}:latest
      
      echo "[SUCCESS] All Docker images built and pushed successfully!"
    EOF
    
    working_dir = path.module
  }
}

# 이미지 태그 확인을 위한 data source
data "aws_ecr_image" "fargate_image" {
  depends_on = [null_resource.docker_images]
  repository_name = aws_ecr_repository.fargate_processor.name
  image_tag       = "latest"
}

data "aws_ecr_image" "detect_skew_image" {
  depends_on = [null_resource.docker_images]
  repository_name = aws_ecr_repository.detect_skew_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "process_ocr_image" {
  depends_on = [null_resource.docker_images]
  repository_name = aws_ecr_repository.process_ocr_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "pdf_generator_image" {
  depends_on = [null_resource.docker_images]
  repository_name = aws_ecr_repository.pdf_generator_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "orchestrator_image" {
  depends_on = [null_resource.docker_images]
  repository_name = aws_ecr_repository.orchestrator_lambda.name
  image_tag       = "latest"
}

data "aws_ecr_image" "sagemaker_image" {
  depends_on = [null_resource.docker_images]
  repository_name = aws_ecr_repository.sagemaker_realesrgan.name
  image_tag       = "latest"
}
