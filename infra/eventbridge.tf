resource "aws_cloudwatch_event_bus" "main" {
  name = "${var.project_name}-event-bus"

  tags = {
    Name = "${var.project_name}-event-bus"
  }
}

resource "aws_cloudwatch_event_rule" "orchestration_trigger" {
  name           = "${var.project_name}-orchestration-trigger"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  description    = "오케스트레이션 트리거 규칙"

  event_pattern = jsonencode({
    source        = ["book-scan.orchestration"]
    detail-type   = ["Batch Processing Complete"]
    detail = {
      status = ["COMPLETED"]
    }
  })

  tags = {
    Name = "${var.project_name}-orchestration-trigger"
  }
}

resource "aws_cloudwatch_event_target" "orchestration_target" {
  rule           = aws_cloudwatch_event_rule.orchestration_trigger.name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  arn            = aws_lambda_function.orchestrator.arn
  target_id      = "OrchestratorTarget"

  input_transformer {
    input_paths = {
      "run_id" = "$.detail.run_id"
    }
    input_template = jsonencode({
      "run_id"        = "<run_id>"
      "input_bucket"  = var.input_bucket_name
      "temp_bucket"   = var.temp_bucket_name
      "output_bucket" = var.output_bucket_name
    })
  }
}

resource "aws_lambda_permission" "orchestration_event_invoke" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orchestrator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.orchestration_trigger.arn
}

resource "aws_cloudwatch_event_rule" "batch_completion" {
  name           = "${var.project_name}-batch-completion"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  description    = "배치 완료 감지 규칙"

  event_pattern = jsonencode({
    source        = ["book-scan.processing"]
    detail-type   = ["Image Processing Complete"]
    detail = {
      batch_complete = [true]
    }
  })

  tags = {
    Name = "${var.project_name}-batch-completion"
  }
}

resource "aws_cloudwatch_event_target" "batch_completion_target" {
  rule           = aws_cloudwatch_event_rule.batch_completion.name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  arn            = aws_sfn_state_machine.book_scan_workflow.arn
  target_id      = "WorkflowTarget"
  role_arn       = aws_iam_role.eventbridge_sfn_role.arn

  input_transformer {
    input_paths = {
      "run_id" = "$.detail.run_id"
    }
    input_template = jsonencode({
      "input" = {
        "orchestrator_output" = {
          "Payload" = {
            "is_work_done" = true
          }
        }
        "Execution" = {
          "Name" = "<run_id>"
        }
      }
    })
  }
}

resource "aws_iam_role" "eventbridge_sfn_role" {
  name = "${var.project_name}-eventbridge-sfn-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-eventbridge-sfn-role"
  }
}

resource "aws_iam_role_policy" "eventbridge_sfn_policy" {
  name = "${var.project_name}-eventbridge-sfn-policy"
  role = aws_iam_role.eventbridge_sfn_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution"
        ]
        Resource = aws_sfn_state_machine.book_scan_workflow.arn
      }
    ]
  })
}
