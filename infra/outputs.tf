output "s3_input_bucket_name" {
  description = "입력 이미지용 S3 버킷 이름."
  value       = aws_s3_bucket.input.id
}

output "s3_temp_bucket_name" {
  description = "임시 파일용 S3 버킷 ��름."
  value       = aws_s3_bucket.temp.id
}

output "s3_output_bucket_name" {
  description = "최종 PDF 출력용 S3 버킷 이름."
  value       = aws_s3_bucket.output.id
}

output "state_machine_arn" {
  description = "Step Functions 상태 머신의 ARN."
  value       = aws_sfn_state_machine.book_scan_workflow.arn
}

output "fargate_task_definition_arn" {
  description = "Fargate 작업 정의의 ARN."
  value       = aws_ecs_task_definition.skew_corrector.arn
}

output "dynamodb_state_table_name" {
  description = "DynamoDB 상태 추적 테이블의 이름."
  value       = aws_dynamodb_table.state_tracking.name
}

output "sagemaker_endpoint_name" {
  description = "SageMaker Real-ESRGAN 엔드포인트 이름."
  value       = try(aws_sagemaker_endpoint.realesrgan.name, "not-deployed")
}

output "sagemaker_endpoint_status" {
  description = "SageMaker 엔드포인트 배포 상태."
  value       = try("deployed", "not-deployed")
}