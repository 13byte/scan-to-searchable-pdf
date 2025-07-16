# -*- coding: utf-8 -*-
# infra/monitoring.tf
resource "aws_cloudwatch_metric_alarm" "processing_latency_alarm" {
  alarm_name          = "${var.project_name}-processing-latency-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ProcessingLatency"
  namespace           = "BookScan/Processing"
  period              = "300"
  statistic           = "Average"
  threshold           = "60000" # 60초
  alarm_description   = "이미지 처리 지연시간 임계값 초과"
  alarm_actions       = [var.sns_topic_arn]

  dimensions = {
    RunId = "ALL"
  }
}

resource "aws_cloudwatch_metric_alarm" "secrets_cache_miss_rate" {
  alarm_name          = "${var.project_name}-secrets-cache-miss-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "3"
  metric_name         = "SecretsCacheMissRate"
  namespace           = "BookScan/Security"
  period              = "300"
  statistic           = "Average"
  threshold           = "15" # 15% 미스율
  alarm_description   = "Secrets 캐시 미스율 높음"
  alarm_actions       = [var.sns_topic_arn]
}

resource "aws_cloudwatch_log_metric_filter" "vision_api_quota_exceeded" {
  name           = "${var.project_name}-vision-api-quota"
  log_group_name = aws_cloudwatch_log_group.lambda_logs["detect_skew"].name
  pattern        = "[timestamp, request_id, level=\"ERROR\", message=\"*quota*\"]"

  metric_transformation {
    name      = "VisionAPIQuotaExceeded"
    namespace = "BookScan/Errors"
    value     = "1"
  }

  depends_on = [aws_cloudwatch_log_group.lambda_logs]
}

resource "aws_cloudwatch_metric_alarm" "vision_api_quota_exceeded_alarm" {
  alarm_name          = "${var.project_name}-vision-api-quota-exceeded"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "VisionAPIQuotaExceeded"
  namespace           = "BookScan/Errors"
  period              = "60"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "Google Vision API 할당량 초과 오류 발생"
  alarm_actions       = [var.sns_topic_arn]
  treat_missing_data  = "notBreaching"
}
