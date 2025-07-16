resource "aws_dynamodb_table" "state_tracking" {
  name         = "${var.project_name}-state-tracking"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "image_key"

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "image_key"
    type = "S"
  }

  attribute {
    name = "job_status"
    type = "S"
  }

  attribute {
    name = "priority"
    type = "N"
  }

  attribute {
    name = "shard_id"
    type = "S"
  }

  global_secondary_index {
    name            = "shard-status-index"
    hash_key        = "shard_id"
    range_key       = "job_status"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "status-priority-index"
    hash_key        = "job_status"
    range_key       = "priority"
    projection_type = "KEYS_ONLY"
  }

  global_secondary_index {
    name            = "run-status-index"
    hash_key        = "run_id"
    range_key       = "job_status"
    projection_type = "KEYS_ONLY"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Name        = "${var.project_name}-state-tracking"
    Environment = var.environment
    Project     = var.project_name
    Purpose     = "Book Scan Workflow State Tracking"
  }
}
