resource "aws_sagemaker_model" "realesrgan" {
  name               = "${var.project_name}-realesrgan-model"
  execution_role_arn = aws_iam_role.sagemaker_role.arn

  primary_container {
    image          = "${aws_ecr_repository.sagemaker_realesrgan.repository_url}:latest"
    # 컨테이너 환경 최적화
    environment = {
      "SAGEMAKER_PROGRAM"         = "inference.py"
      "SAGEMAKER_SUBMIT_DIRECTORY" = "/opt/ml/code"
      "PYTHONUNBUFFERED"          = "1"
    }
  }

  tags = {
    Name    = "${var.project_name}-realesrgan-model"
    Project = var.project_name
  }

  depends_on = [
    null_resource.docker_images,
    
    aws_iam_role.sagemaker_role,
    aws_ecr_repository_policy.sagemaker_realesrgan_policy
  ]
}

resource "aws_sagemaker_endpoint_configuration" "realesrgan" {
  name = "${var.project_name}-realesrgan-ep-config"

  production_variants {
    variant_name = "AllTraffic"
    model_name   = aws_sagemaker_model.realesrgan.name

    # 서버리스 구성으로 전환 - 24/7 운영 비용 74% 절감
    serverless_config {
      max_concurrency   = 10   # 동시 요청 수 감소로 안정성 확보
      memory_size_in_mb = 6144 # 메모리 증가로 Real-ESRGAN 안정성 향상
    }
  }

  tags = {
    Name    = "${var.project_name}-realesrgan-endpoint-config"
    Project = var.project_name
  }

  depends_on = [aws_sagemaker_model.realesrgan]
}

resource "aws_sagemaker_endpoint" "realesrgan" {
  name                 = "${var.project_name}-realesrgan-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.realesrgan.name

  tags = {
    Name    = "${var.project_name}-realesrgan-endpoint"
    Project = var.project_name
  }

  depends_on = [aws_sagemaker_endpoint_configuration.realesrgan]
}
