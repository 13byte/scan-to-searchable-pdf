resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

resource "aws_ecs_task_definition" "skew_corrector" {
  family                   = "${var.project_name}-skew-corrector"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"   # 50% 리소스 절감
  memory                   = "1024"  # 50% 메모리 절감 
  execution_role_arn       = aws_iam_role.lambda_fargate_base_role.arn
  task_role_arn            = aws_iam_role.lambda_fargate_base_role.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"  # 비용 효율적인 ARM64 유지
  }

  container_definitions = jsonencode([
    {
      name      = "skew-corrector"
      image     = "${aws_ecr_repository.fargate_processor.repository_url}:${var.fargate_image_tag}"
      essential = true
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.fargate_logs.name,
          "awslogs-region"        = var.aws_region,
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_cloudwatch_log_group" "fargate_logs" {
  name              = "/ecs/${var.project_name}-skew-corrector"
  retention_in_days = 7
}
