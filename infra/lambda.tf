resource "null_resource" "build_pdf_layer" {
  triggers = {
    requirements_hash = filemd5("${path.module}/../workers/3_finalization/pdf_generator/requirements.txt")
    font_hash         = filemd5("${path.module}/../config/NotoSansKR-Regular.ttf")
  }
  provisioner "local-exec" {
    command = "pip install -r ${path.module}/../workers/3_finalization/pdf_generator/requirements.txt -t ${path.module}/../build/lambda-layer/python && cp ${path.module}/../config/NotoSansKR-Regular.ttf ${path.module}/../build/lambda-layer/python/NotoSansKR-Regular.ttf && zip -r ${path.module}/../build/pdf-dependencies-layer.zip ${path.module}/../build/lambda-layer"
  }
}

resource "aws_lambda_layer_version" "pdf_dependencies" {
  filename   = "${path.module}/../build/pdf-dependencies-layer.zip"
  layer_name = "${var.project_name}-pdf-dependencies"
  compatible_runtimes = ["python3.12"]
  compatible_architectures = ["arm64"]
  depends_on = [null_resource.build_pdf_layer]
}

data "archive_file" "initialize_state" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/1_orchestration/initialize_state"
  output_path = "${path.module}/../dist/initialize_state.zip"
}
data "archive_file" "orchestrator" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/1_orchestration/orchestrator"
  output_path = "${path.module}/../dist/orchestrator.zip"
}
data "archive_file" "upscaler" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/2_image_processing/upscaler"
  output_path = "${path.module}/../dist/upscaler.zip"
}
data "archive_file" "pdf_generator" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/3_finalization/pdf_generator"
  output_path = "${path.module}/../dist/pdf_generator.zip"
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
    detect_skew        = "detect_skew"
    process_ocr        = "process_ocr"
  }
  name              = "/aws/lambda/${var.project_name}-${each.value}"
  retention_in_days = 7
}

resource "aws_lambda_function" "vision_api_handler" {
  function_name = "${var.project_name}-vision-api-handler"
  role          = aws_iam_role.lambda_fargate_base_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.vision_api_handler_lambda.repository_url}:${var.vision_lambda_image_tag}"
  architectures = ["x86_64"]
  timeout       = 120
  memory_size   = 512  # 최적화: 1024→512MB, Google Vision API는 네트워크 호출 위주
  environment {
    variables = {
      DYNAMODB_STATE_TABLE = aws_dynamodb_table.state_tracking.name
      GOOGLE_SECRET_NAME   = aws_secretsmanager_secret.google_credentials.name
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda_logs["vision_api_handler"]]
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
  handler          = "main.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 256
  filename         = data.archive_file.orchestrator.output_path
  source_code_hash = data.archive_file.orchestrator.output_base64sha256
  environment {
    variables = {
      DYNAMODB_STATE_TABLE = aws_dynamodb_table.state_tracking.name
      MAX_BATCH_SIZE       = "50"
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda_logs["orchestrator"]]
}

resource "aws_lambda_function" "upscaler" {
  function_name    = "${var.project_name}-upscaler"
  role             = aws_iam_role.lambda_fargate_base_role.arn
  handler          = "main.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 300
  memory_size      = 768  # 최적화: 1024→768MB, SageMaker 호출과 최소한의 이미지 처리
  filename         = data.archive_file.upscaler.output_path
  source_code_hash = data.archive_file.upscaler.output_base64sha256
  environment {
    variables = {
      DYNAMODB_STATE_TABLE    = aws_dynamodb_table.state_tracking.name
      SAGEMAKER_ENDPOINT_NAME = aws_sagemaker_endpoint.realesrgan.name
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda_logs["upscaler"]]
}

resource "aws_lambda_function" "pdf_generator" {
  function_name    = "${var.project_name}-pdf-generator"
  role             = aws_iam_role.lambda_fargate_base_role.arn
  handler          = "main.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 300
  memory_size      = 1536  # 25% 메모리 절감 (2048→1536)
  filename         = data.archive_file.pdf_generator.output_path
  source_code_hash = data.archive_file.pdf_generator.output_base64sha256
  layers           = [aws_lambda_layer_version.pdf_dependencies.arn]
  environment {
    variables = {
      DYNAMODB_STATE_TABLE = aws_dynamodb_table.state_tracking.name
      OUTPUT_BUCKET        = aws_s3_bucket.output.id
      TEMP_BUCKET          = aws_s3_bucket.temp.id
    }
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
      OUTPUT_BUCKET = aws_s3_bucket.output.id
      DYNAMODB_STATE_TABLE = aws_dynamodb_table.state_tracking.name
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda_logs["summary_generator"]]
}
