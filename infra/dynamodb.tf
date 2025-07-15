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

  global_secondary_index {
    name            = "status-index"
    hash_key        = "run_id"
    range_key       = "job_status"
    projection_type = "INCLUDE"
    non_key_attributes = ["image_key"]
  }

  tags = {
    Project = var.project_name
    Purpose = "Book Scan Workflow State Tracking"
  }
}
