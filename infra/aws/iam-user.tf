# A dedicated, project-scoped IAM user for day-to-day Terraform/CLI work on
# this project, instead of using the AWS account root user. The access key
# itself is deliberately NOT a Terraform resource here (storing a secret
# access key in state — even encrypted-at-rest state — is bad practice);
# generate it once via `aws iam create-access-key --user-name vithana-deployer`
# after this applies, and store it in a separate AWS CLI profile.

resource "aws_iam_user" "deployer" {
  name = "vithana-deployer"
  tags = { Project = var.project }
}

# Scoped to what this Terraform config actually creates/manages — not
# AdministratorAccess. A few EC2/logs actions don't support resource-level
# restriction in IAM at all (a real limitation, not an oversight here), so
# those are allowed account-wide; everything else is scoped by ARN/prefix.
#
# A managed policy, not inline on the user — inline user policies are
# capped at 2,048 characters, too small for this; managed policies allow
# 6,144.
resource "aws_iam_policy" "deployer" {
  name = "${var.project}-deployer-scope"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRFull"
        Effect = "Allow"
        Action = ["ecr:*"]
        Resource = [
          "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/${var.project}-*"
        ]
      },
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"] # this specific action has no resource-level permission support
      },
      {
        Sid    = "ECSFull"
        Effect = "Allow"
        Action = ["ecs:*"]
        Resource = [
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/${var.project}-*",
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/${var.project}-*/*",
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/${var.project}-*:*",
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task/${var.project}-*/*",
          "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:capacity-provider/*"
        ]
      },
      {
        Sid      = "ECSDescribeList"
        Effect   = "Allow"
        Action   = ["ecs:Describe*", "ecs:List*"]
        Resource = ["*"] # describe/list calls generally require resource "*"
      },
      {
        Sid      = "AppRunnerFull"
        Effect   = "Allow"
        Action   = ["apprunner:*"]
        Resource = ["*"] # App Runner ARNs are only known after create; scoping further isn't practical here
      },
      {
        Sid    = "S3Bucket"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          "arn:aws:s3:::${var.project}-*",
          "arn:aws:s3:::${var.project}-*/*"
        ]
      },
      {
        Sid      = "SecretsManager"
        Effect   = "Allow"
        Action   = ["secretsmanager:*"]
        Resource = ["arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project}/*"]
      },
      {
        Sid      = "EFS"
        Effect   = "Allow"
        Action   = ["elasticfilesystem:*"]
        Resource = ["*"] # EFS resource-level permissions are inconsistent across actions; scoped by tag would need a separate condition, kept simple here
      },
      {
        Sid    = "EC2Network"
        Effect = "Allow"
        Action = [
          "ec2:DescribeSecurityGroups", "ec2:DescribeSubnets", "ec2:DescribeVpcs",
          "ec2:DescribeNetworkInterfaces", "ec2:DescribeAddresses",
          "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
          "ec2:CreateTags", "ec2:DeleteTags",
          "ec2:AllocateAddress", "ec2:ReleaseAddress", "ec2:AssociateAddress", "ec2:DisassociateAddress"
        ]
        Resource = ["*"] # EC2 network actions largely don't support resource-level ARNs
      },
      {
        Sid    = "IAMProjectRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:PassRole",
          "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies", "iam:TagRole", "iam:UntagRole"
        ]
        Resource = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project}-*"]
      },
      {
        Sid    = "LogsFull"
        Effect = "Allow"
        Action = ["logs:*"]
        Resource = [
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/${var.project}/*",
          "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/apprunner/${var.project}-*"
        ]
      },
      {
        Sid      = "ServiceDiscoveryLegacyCleanup"
        Effect   = "Allow"
        Action   = ["servicediscovery:*"]
        Resource = ["*"] # kept in case Cloud Map is reintroduced; harmless if unused
      },
      {
        Sid      = "STSIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = ["*"]
      },
      {
        Sid      = "Budgets"
        Effect   = "Allow"
        Action   = ["budgets:*"]
        Resource = ["*"] # AWS Budgets ARNs aren't known until after create; scoping further isn't practical here
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "deployer" {
  user       = aws_iam_user.deployer.name
  policy_arn = aws_iam_policy.deployer.arn
}
