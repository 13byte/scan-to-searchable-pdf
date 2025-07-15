resource "aws_ecr_repository" "fargate_processor" {
  name                 = "${var.project_name}/skew-corrector"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = { Project = var.project_name }
}

resource "aws_ecr_repository" "sagemaker_realesrgan" {
  name                 = "${var.project_name}/sagemaker-realesrgan"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = { Project = var.project_name }
}

resource "aws_ecr_repository" "detect_skew_lambda" {
  name                 = "${var.project_name}/detect-skew"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = { Project = var.project_name }
}

resource "aws_ecr_repository" "process_ocr_lambda" {
  name                 = "${var.project_name}/process-ocr"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = { Project = var.project_name }
}

resource "aws_ecr_repository" "trigger_pipeline_lambda" {
  name                 = "${var.project_name}/trigger-pipeline"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = { Project = var.project_name }
}

resource "aws_ecr_lifecycle_policy" "default_policy" {
  for_each = {
    fargate   = aws_ecr_repository.fargate_processor.name
    sagemaker = aws_ecr_repository.sagemaker_realesrgan.name
    detect_skew = aws_ecr_repository.detect_skew_lambda.name
    process_ocr = aws_ecr_repository.process_ocr_lambda.name
    trigger_pipeline = aws_ecr_repository.trigger_pipeline_lambda.name
  }
  repository = each.value

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1,
        description  = "최근 3개의 태그된 이미지 ��지",
        selection = {
          tagStatus     = "tagged",
          tagPrefixList = ["v"],
          countType     = "imageCountMoreThan",
          countNumber   = 3
        },
        action = { type = "expire" }
      },
      {
        rulePriority = 2,
        description  = "7일 후 태그되지 않은 이미지 만료",
        selection = {
          tagStatus   = "untagged",
          countType   = "sinceImagePushed",
          countUnit   = "days",
          countNumber = 7
        },
        action = { type = "expire" }
      }
    ]
  })
}