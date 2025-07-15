resource "aws_secretsmanager_secret" "google_credentials" {
  name = "${var.project_name}-google-vision-credentials"
  description = "Google Cloud Vision API JSON 자격 증명을 저장합니다."
}

resource "aws_secretsmanager_secret_version" "google_credentials" {
  secret_id     = aws_secretsmanager_secret.google_credentials.id
  secret_string = jsonencode({
    "type": "service_account",
    "project_id": "your-gcp-project-id",
    "private_key_id": "your-private-key-id",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
    "client_email": "your-service-account-email",
    "client_id": "your-client-id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "..."
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
