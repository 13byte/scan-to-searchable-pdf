resource "aws_sqs_queue" "failure_dlq" {
  name                      = "${var.project_name}-failure-dlq"
  message_retention_seconds = 1209600
  visibility_timeout_seconds = 300

  tags = {
    Name = "${var.project_name}-failure-dlq"
  }
}

output "failure_dlq_url" {
  description = "실패용 SQS 데드 레터 큐의 URL."
  value       = aws_sqs_queue.failure_dlq.id
}

output "failure_dlq_arn" {
  description = "실패용 SQS 데드 레터 큐의 ARN."
  value       = aws_sqs_queue.failure_dlq.arn
}
