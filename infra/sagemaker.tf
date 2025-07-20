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
    aws_ecr_repository_policy.sagemaker_realesrgan_policy,
    null_resource.docker_images
  ]
}

resource "aws_sagemaker_endpoint_configuration" "realesrgan" {
  name = "${var.project_name}-realesrgan-ep-config"

  production_variants {
    variant_name           = "AllTraffic"
    model_name            = aws_sagemaker_model.realesrgan.name
    initial_instance_count = 1
    instance_type         = "ml.g6.2xlarge"  # NVIDIA L4 Tensor Core GPU, 8 vCPUs, 32 GiB
    initial_variant_weight = 1
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

# Auto Scaling 설정으로 비용 최적화 (ml.g6.2xlarge 최적화)
resource "aws_appautoscaling_target" "sagemaker_target" {
  max_capacity       = 3  # 최대 3개 인스턴스
  min_capacity       = 0  # 비사용시 0개로 스케일다운
  resource_id        = "endpoint/${aws_sagemaker_endpoint.realesrgan.name}/variant/AllTraffic"
  scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
  service_namespace  = "sagemaker"

  depends_on = [aws_sagemaker_endpoint.realesrgan]
}

resource "aws_appautoscaling_policy" "sagemaker_scaling_policy" {
  name               = "${var.project_name}-realesrgan-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.sagemaker_target.resource_id
  scalable_dimension = aws_appautoscaling_target.sagemaker_target.scalable_dimension
  service_namespace  = aws_appautoscaling_target.sagemaker_target.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "SageMakerVariantInvocationsPerInstance"
    }
    target_value       = 75.0  # ml.g6.2xlarge 최적화: 인스턴스당 75 요청/분 목표
    scale_in_cooldown  = 300   # 스케일 인 대기시간 5분
    scale_out_cooldown = 300   # 스케일 아웃 대기시간 5분
  }
}
