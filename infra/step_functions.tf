resource "aws_sfn_state_machine" "book_scan_workflow" {
  name     = "${var.project_name}-main-workflow"
  role_arn = aws_iam_role.step_functions_role.arn
  definition = templatefile("${path.module}/../step-functions/main-workflow.json", {
    trigger_pipeline_lambda_arn = aws_lambda_function.trigger_pipeline.arn
    initialize_state_lambda_arn = aws_lambda_function.initialize_state.arn
    orchestrator_lambda_arn     = aws_lambda_function.orchestrator.arn

    detect_skew_lambda_arn   = aws_lambda_function.detect_skew.arn
    process_ocr_lambda_arn   = aws_lambda_function.process_ocr.arn
    upscale_image_lambda_arn = aws_lambda_function.upscaler.arn
    fargate_task_arn         = aws_ecs_task_definition.skew_corrector.arn

    generate_pdf_lambda_arn         = aws_lambda_function.pdf_generator.arn
    generate_run_summary_lambda_arn = aws_lambda_function.summary_generator.arn

    ecs_cluster_arn     = aws_ecs_cluster.main.arn
    subnet_id           = aws_subnet.private[0].id
    security_group_id   = aws_security_group.main.id
    dynamodb_table_name = aws_dynamodb_table.state_tracking.name
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_logs.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  depends_on = [
    aws_iam_role.step_functions_role,
    aws_lambda_function.trigger_pipeline,
    aws_lambda_function.initialize_state,
    aws_lambda_function.orchestrator,
    aws_lambda_function.detect_skew,
    aws_lambda_function.process_ocr,
    aws_lambda_function.upscaler,
    aws_lambda_function.pdf_generator,
    aws_lambda_function.summary_generator,
    aws_ecs_task_definition.skew_corrector,
    aws_sagemaker_endpoint.realesrgan,
    aws_dynamodb_table.state_tracking
  ]
}

resource "aws_cloudwatch_log_group" "sfn_logs" {
  name              = "/aws/vendedlogs/states/${var.project_name}-main-workflow"
  retention_in_days = 7
}