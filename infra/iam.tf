resource "aws_iam_role" "lambda_fargate_base_role" {
  name = "${var.project_name}-base-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = [
            "lambda.amazonaws.com",
            "ecs-tasks.amazonaws.com"
          ]
        }
      }
    ]
  })
}

resource "aws_iam_policy" "lambda_fargate_sagemaker_invoke_policy" {
  name        = "${var.project_name}-lambda-fargate-sagemaker-invoke-policy"
  description = "Lambda 및 Fargate가 SageMaker 엔드포인트를 호출하기 위한 최소 권한 정책"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "sagemaker:InvokeEndpoint"
        ],
        Resource = "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:endpoint/${var.project_name}-*"
      },
      {
        Effect = "Allow",
        Action = [
          "secretsmanager:GetSecretValue"
        ],
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}-*"
      }
    ]
  })
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
        Resource = aws_sagemaker_endpoint.realesrgan.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_fargate_sagemaker_invoke_attach" {
  role       = aws_iam_role.lambda_fargate_base_role.name
  policy_arn = aws_iam_policy.lambda_fargate_sagemaker_invoke_policy.arn
}

resource "aws_iam_policy" "base_policy" {
  name        = "${var.project_name}-base-policy"
  description = "S3, CloudWatch Logs, Secrets Manager 액세스를 위한 기본 정책."

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:PutLifecycleConfiguration",
          "s3:DeleteLifecycleConfiguration",
          "sagemaker:DeleteEndpoint",
          "sagemaker:DeleteEndpointConfig",
          "ecs:DeleteService",
          "ecs:UpdateService",
          "ecs:DeregisterTaskDefinition",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ],
        Resource = [
          aws_s3_bucket.input.arn,
          "${aws_s3_bucket.input.arn}/*",
          aws_s3_bucket.temp.arn,
          "${aws_s3_bucket.temp.arn}/*",
          aws_s3_bucket.output.arn,
          "${aws_s3_bucket.output.arn}/*",
          aws_sagemaker_endpoint.realesrgan.arn,
          aws_sagemaker_endpoint_configuration.realesrgan.arn,
          aws_ecs_cluster.main.arn,
          "${aws_ecs_cluster.main.arn}/*",
          aws_dynamodb_table.state_tracking.arn,
          "${aws_dynamodb_table.state_tracking.arn}/*",
          "${aws_dynamodb_table.state_tracking.arn}/index/*"
        ]
      },
      {
        Effect = "Allow",
        Action = [
          "secretsmanager:GetSecretValue"
        ],
        Resource = aws_secretsmanager_secret.google_credentials.arn
      },
      {
        Effect = "Allow",
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "sqs:SendMessage"
        ],
        Resource = aws_sqs_queue.dlq.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "base_attach" {
  role       = aws_iam_role.lambda_fargate_base_role.name
  policy_arn = aws_iam_policy.base_policy.arn
}

resource "aws_iam_role" "sagemaker_role" {
  name = "${var.project_name}-sagemaker-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "sagemaker.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "sagemaker_attach_base" {
  role       = aws_iam_role.sagemaker_role.name
  policy_arn = aws_iam_policy.base_policy.arn
}

resource "aws_iam_role_policy_attachment" "sagemaker_attach_ecr" {
  role       = aws_iam_role.sagemaker_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role" "step_functions_role" {
  name = "${var.project_name}-step-functions-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "step_functions_policy" {
  name        = "${var.project_name}-step-functions-policy"
  description = "Step Functions가 Lambda, Fargate, SageMaker를 호출하기 위한 정책."

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "lambda:InvokeFunction"
        ],
        Resource = [
          aws_lambda_function.initialize_state.arn,
          aws_lambda_function.orchestrator.arn,
          aws_lambda_function.detect_skew.arn,
          aws_lambda_function.process_ocr.arn,
          aws_lambda_function.upscaler.arn,
          aws_lambda_function.pdf_generator.arn,
          aws_lambda_function.summary_generator.arn,
          aws_lambda_function.trigger_pipeline.arn
        ]
      },
      {
        Effect = "Allow",
        Action = [
          "ecs:RunTask"
        ],
        Resource = [
          aws_ecs_task_definition.skew_corrector.arn
        ]
      },
      {
        Effect = "Allow",
        Action = [
            "ecs:StopTask",
            "ecs:DescribeTasks"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "iam:PassRole"
        ],
        Resource = [
          aws_iam_role.lambda_fargate_base_role.arn
        ]
      },
      {
        Effect = "Allow",
        Action = [
          "sagemaker:InvokeEndpoint"
        ],
        Resource = aws_sagemaker_endpoint.realesrgan.arn
      },
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ],
        Resource = [
          "${aws_s3_bucket.temp.arn}/*",
          "${aws_s3_bucket.input.arn}/*",
          "${aws_s3_bucket.output.arn}/*"
        ]
      },
      {
        Effect = "Allow",
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:DescribeRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:PutEvents"
        ],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "cloudwatch:PutMetricData"
        ],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "step_functions_attach" {
  role       = aws_iam_role.step_functions_role.name
  policy_arn = aws_iam_policy.step_functions_policy.arn
}
