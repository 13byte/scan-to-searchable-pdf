# Layer 인프라 완전 제거 - 모든 함수가 기본 런타임 또는 컨테이너 사용

data "archive_file" "initialize_state" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/1_orchestration/initialize_state"
  output_path = "${path.module}/../dist/initialize_state.zip"
}
data "archive_file" "upscaler" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/2_image_processing/upscaler"
  output_path = "${path.module}/../dist/upscaler.zip"
}
data "archive_file" "summary_generator" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/3_finalization/summary_generator"
  output_path = "${path.module}/../dist/summary_generator.zip"
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  for_each = {
    initialize_state  = "initialize_state"
    orchestrator      = "orchestrator"
    upscaler          = "upscaler"
    pdf_generator     = "pdf_generator"
    summary_generator = "summary_generator"
    detect_skew       = "detect_skew"
    process_ocr       = "process_ocr"
    trigger_pipeline  = "trigger_pipeline"
  }
  name              = "/aws/lambda/${var.project_name}-${each.value}"
  retention_in_days = 7
}


resource "aws_lambda_function" "initialize_state" {
  function_name    = "${var.project_name}-initialize-state"
  role             = aws_iam_role.lambda_fargate_base_role.arn
  handler          = "main.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 120
  memory_size      = 256
  filename         = data.archive_file.initialize_state.output_path
  source_code_hash = data.archive_file.initialize_state.output_base64sha256
  environment {
    variables = {
      DYNAMODB_STATE_TABLE = aws_dynamodb_table.state_tracking.name
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda_logs["initialize_state"]]
}

resource "aws_lambda_function" "orchestrator" {
  function_name    = "${var.project_name}-orchestrator"
  role             = aws_iam_role.lambda_fargate_base_role.arn
  package_type     = "Image"
  image_uri        = "${aws_ecr_repository.orchestrator_lambda.repository_url}:${var.orchestrator_lambda_image_tag}"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 256
  environment {
    variables = {
      DYNAMODB_STATE_TABLE = aws_dynamodb_table.state_tracking.name
      EVENT_BUS_NAME       = aws_cloudwatch_event_bus.main.name
      MAX_BATCH_SIZE       = var.max_batch_size
      MIN_BATCH_SIZE       = var.min_batch_size
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda_logs["orchestrator"]]
}

resource "aws_lambda_function" "upscaler" {
  function_name                  = "${var.project_name}-upscaler"
  role                           = aws_iam_role.lambda_fargate_base_role.arn
  handler                        = "main.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 300
  memory_size                    = 1024
  reserved_concurrent_executions = 25
  filename                       = data.archive_file.upscaler.output_path
  source_code_hash               = data.archive_file.upscaler.output_base64sha256

  environment {
    variables = {
      DYNAMODB_STATE_TABLE    = aws_dynamodb_table.state_tracking.name
      SAGEMAKER_ENDPOINT_NAME = aws_sagemaker_endpoint.realesrgan.name
      LOG_LEVEL               = "INFO"
      POWERTOOLS_SERVICE_NAME = "upscaler"
    }
  }

  tracing_config {
    mode = "Active"
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  depends_on = [aws_cloudwatch_log_group.lambda_logs["upscaler"],
    aws_sagemaker_endpoint.realesrgan # 명시적 의존성 추가
  ]
}

resource "aws_lambda_function" "pdf_generator" {
  function_name    = "${var.project_name}-pdf-generator"
  role             = aws_iam_role.lambda_fargate_base_role.arn
  package_type     = "Image"
  image_uri        = "${aws_ecr_repository.pdf_generator_lambda.repository_url}:${var.pdf_generator_lambda_image_tag}"
  architectures    = ["arm64"]
  timeout          = 300
  memory_size      = 1536

  environment {
    variables = {
      DYNAMODB_STATE_TABLE    = aws_dynamodb_table.state_tracking.name
      OUTPUT_BUCKET           = aws_s3_bucket.output.id
      TEMP_BUCKET             = aws_s3_bucket.temp.id
      LOG_LEVEL               = "INFO"
      POWERTOOLS_SERVICE_NAME = "pdf-generator"
    }
  }

  tracing_config {
    mode = "Active"
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  depends_on = [aws_cloudwatch_log_group.lambda_logs["pdf_generator"]]
}

resource "aws_lambda_function" "summary_generator" {
  function_name    = "${var.project_name}-summary-generator"
  role             = aws_iam_role.lambda_fargate_base_role.arn
  handler          = "main.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 256
  filename         = data.archive_file.summary_generator.output_path
  source_code_hash = data.archive_file.summary_generator.output_base64sha256
  environment {
    variables = {
      OUTPUT_BUCKET        = aws_s3_bucket.output.id
      DYNAMODB_STATE_TABLE = aws_dynamodb_table.state_tracking.name
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda_logs["summary_generator"]]
}

resource "aws_lambda_function" "detect_skew" {
  function_name                  = "${var.project_name}-detect-skew"
  role                           = aws_iam_role.lambda_fargate_base_role.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.detect_skew_lambda.repository_url}:${var.detect_skew_lambda_image_tag}"
  architectures                  = ["arm64"]
  timeout                        = 30
  memory_size                    = 512
  reserved_concurrent_executions = 50

  environment {
    variables = {
      DYNAMODB_STATE_TABLE    = aws_dynamodb_table.state_tracking.name
      GOOGLE_SECRET_NAME      = aws_secretsmanager_secret.google_credentials.name
      LOG_LEVEL               = "INFO"
      POWERTOOLS_SERVICE_NAME = "detect-skew"
    }
  }

  tracing_config {
    mode = "Active"
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  depends_on = [aws_cloudwatch_log_group.lambda_logs["detect_skew"],
    aws_sagemaker_endpoint.realesrgan # 명시적 의존성 추가
  ]
}

resource "aws_lambda_function" "process_ocr" {
  function_name                  = "${var.project_name}-process-ocr"
  role                           = aws_iam_role.lambda_fargate_base_role.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.process_ocr_lambda.repository_url}:${var.process_ocr_lambda_image_tag}"
  architectures                  = ["arm64"]
  timeout                        = 60
  memory_size                    = 1024
  reserved_concurrent_executions = 30

  environment {
    variables = {
      DYNAMODB_STATE_TABLE    = aws_dynamodb_table.state_tracking.name
      GOOGLE_SECRET_NAME      = aws_secretsmanager_secret.google_credentials.name
      LOG_LEVEL               = "INFO"
      POWERTOOLS_SERVICE_NAME = "process-ocr"
    }
  }

  tracing_config {
    mode = "Active"
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.dlq.arn
  }

  depends_on = [aws_cloudwatch_log_group.lambda_logs["process_ocr"],
    aws_sagemaker_endpoint.realesrgan # 명시적 의존성 추가
  ]
}

resource "aws_lambda_function" "trigger_pipeline" {
  function_name = "${var.project_name}-trigger-pipeline"
  role          = aws_iam_role.lambda_fargate_base_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.trigger_pipeline_lambda.repository_url}:${var.trigger_pipeline_lambda_image_tag}"
  architectures = ["arm64"]
  timeout       = 60
  memory_size   = 256

  environment {
    variables = {
      TEMP_BUCKET = aws_s3_bucket.temp.id
    }
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [aws_cloudwatch_log_group.lambda_logs["trigger_pipeline"]]
}
