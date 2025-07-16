resource "aws_sqs_queue" "dlq" {
  name                       = "${var.project_name}-dlq"
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 300

  tags = {
    Name        = "${var.project_name}-dlq"
    Environment = var.environment
    Purpose     = "Dead Letter Queue for failed processing"
  }
}

resource "aws_sqs_queue" "retry_queue" {
  name                       = "${var.project_name}-retry-queue"
  visibility_timeout_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name        = "${var.project_name}-retry-queue"
    Environment = var.environment
    Purpose     = "Retry queue for transient failures"
  }
}

data "archive_file" "dlq_processor" {
  type        = "zip"
  source_dir  = "${path.module}/../workers/dlq_processor"
  output_path = "${path.module}/../dist/dlq_processor.zip"
}

resource "aws_lambda_function" "dlq_processor" {
  function_name    = "${var.project_name}-dlq-processor"
  role             = aws_iam_role.lambda_fargate_base_role.arn
  handler          = "main.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 60
  memory_size      = 256
  filename         = data.archive_file.dlq_processor.output_path
  source_code_hash = data.archive_file.dlq_processor.output_base64sha256

  environment {
    variables = {
      SNS_TOPIC_ARN = var.sns_topic_arn
      LOG_LEVEL     = "INFO"
    }
  }

  tags = {
    Name        = "${var.project_name}-dlq-processor"
    Environment = var.environment
  }
}

resource "aws_lambda_event_source_mapping" "dlq_trigger" {
  event_source_arn = aws_sqs_queue.dlq.arn
  function_name    = aws_lambda_function.dlq_processor.arn
  batch_size       = 10
}

output "dlq_url" {
  description = "DLQ URL"
  value       = aws_sqs_queue.dlq.id
}

output "dlq_arn" {
  description = "DLQ ARN"
  value       = aws_sqs_queue.dlq.arn
}

resource "aws_sqs_queue_policy" "dlq_policy" {
  queue_url = aws_sqs_queue.dlq.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "lambda.amazonaws.com"
        },
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage" # 이벤트 소스 매핑을 위해 추가
        ],
        Resource = aws_sqs_queue.dlq.arn
      }
    ]
  })
}
