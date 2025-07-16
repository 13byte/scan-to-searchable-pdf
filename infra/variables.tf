variable "project_name" {
  description = "프로젝트 이름 (리소스 명명에 사용)."
  type        = string
  default     = "book-scan-performance"
}

variable "environment" {
  description = "환경 이름 (예: production, staging)."
  type        = string
  default     = "production"
}

variable "fargate_image_tag" {
  description = "Fargate Docker 이미지 태그."
  type        = string
  default     = "latest"
}

variable "vision_lambda_image_tag" {
  description = "Google Vision Lambda 컨테이너 이미지 태그."
  type        = string
  default     = "latest"
}

variable "detect_skew_lambda_image_tag" {
  description = "Detect Skew Lambda 컨테이너 이미지 태그."
  type        = string
  default     = "latest"
}

variable "process_ocr_lambda_image_tag" {
  description = "Process OCR Lambda 컨테이너 이미지 태그."
  type        = string
  default     = "latest"
}

variable "trigger_pipeline_lambda_image_tag" {
  description = "Trigger Pipeline Lambda 컨테이너 이미지 태그."
  type        = string
  default     = "latest"
}

variable "pdf_generator_lambda_image_tag" {
  description = "PDF Generator Lambda 컨테이너 이미지 태그."
  type        = string
  default     = "latest"
}

variable "sagemaker_image_tag" {
  description = "SageMaker Docker 이미지 태그."
  type        = string
  default     = "latest"
}

variable "sns_topic_arn" {
  description = "실패 알림용 SNS 토픽 ARN."
  type        = string
  default     = ""
}

variable "aws_region" {
  description = "리소스를 배포할 AWS 리전."
  type        = string
  default     = "ap-northeast-2"
}

variable "input_bucket_name" {
  description = "입력 이미지 S3 버킷 이름."
  type        = string
  default     = ""
}

variable "temp_bucket_name" {
  description = "임시 저장용 S3 버킷 이름."
  type        = string
  default     = ""
}

variable "output_bucket_name" {
  description = "최종 결과물 S3 버킷 이름."
  type        = string
  default     = ""
}

variable "max_batch_size" {
  description = "동적 배치 크기의 최대값."
  type        = number
  default     = 50
}

variable "min_batch_size" {
  description = "동적 배치 크기의 최소값."
  type        = number
  default     = 5
}
