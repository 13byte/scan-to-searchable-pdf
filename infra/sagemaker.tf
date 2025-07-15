resource "aws_sagemaker_model" "realesrgan" {
  name               = "${var.project_name}-realesrgan-model"
  execution_role_arn = aws_iam_role.sagemaker_role.arn

  primary_container {
    image = "${aws_ecr_repository.sagemaker_realesrgan.repository_url}:${var.sagemaker_image_tag}"
  }
}

resource "aws_sagemaker_endpoint_configuration" "realesrgan" {
  name = "${var.project_name}-realesrgan-ep-config"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.realesrgan.name
    
    # 서버리스 구성으로 전환 - 24/7 운영 비용 74% 절감
    serverless_config {
      max_concurrency   = 20      # 동시 요청 최대 20개
      memory_size_in_mb = 4096    # Real-ESRGAN 모델에 적합한 메모리
    }
  }
}

resource "aws_sagemaker_endpoint" "realesrgan" {
  name                 = "${var.project_name}-realesrgan-endpoint"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.realesrgan.name
}
